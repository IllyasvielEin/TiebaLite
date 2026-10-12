#!/usr/bin/env python3
"""Inspect both *packaged* APKs with official aapt2, before adb is allowed to install either."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

APPLICATION_ID = "io.github.illyasvielein.tiebalite"
HOST = "com.huanchengfly.tieba.post.smoke.SmokeActivity"
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"


def parse_manifest_dump(text):
    """Parse official aapt2's indented XML tree; bind attributes to their actual element."""
    roots, stack = [], []
    namespaces = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        namespace = re.fullmatch(r"\s*N: ([A-Za-z_][A-Za-z0-9_.-]*)=(\S+)(?: \(line=\d+\))?", line)
        if namespace:
            prefix, uri = namespace[1], namespace[2]
            if ((prefix == "android" and uri != ANDROID_NAMESPACE) or
                    (prefix in namespaces and namespaces[prefix] != uri)):
                raise ValueError("Unexpected or rebound packaged manifest namespace")
            namespaces[prefix] = uri
            continue
        element = re.fullmatch(r"( *)E: ([A-Za-z_][A-Za-z0-9_.:-]*)(?: \(line=\d+\))?", line)
        if element:
            indent = len(element[1])
            while stack and stack[-1][0] >= indent:
                stack.pop()
            node = {"tag": element[2], "attrs": {}, "children": []}
            (stack[-1][1]["children"] if stack else roots).append(node)
            stack.append((indent, node))
            continue
        attribute = re.fullmatch(r"( *)A: ([^\s()=]+)(?:\(0x[0-9a-fA-F]+\))?=(.+)", line)
        if not attribute or not stack or len(attribute[1]) <= stack[-1][0]:
            raise ValueError("Malformed aapt2 manifest tree")
        key, value = attribute[2], attribute[3]
        if ":" in key:
            namespace, local = key.rsplit(":", 1)
            # aapt2 36 emits expanded URI names; older dumps can use a declared prefix.
            # Normalize only the exact Android URI, never any key merely ending in :name.
            if (namespace != ANDROID_NAMESPACE and
                    namespaces.get(namespace) != ANDROID_NAMESPACE):
                raise ValueError("Unexpected packaged manifest attribute namespace")
            key = "android:" + local
        else:
            local = key
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", local):
            raise ValueError("Malformed packaged manifest attribute name")
        attrs = stack[-1][1]["attrs"]
        if key in attrs:
            raise ValueError("Duplicate packaged manifest attribute")
        if key in {"package", "android:name", "android:authorities", "android:targetPackage"}:
            string = re.fullmatch(r'"([^"\\]*)"(?: \(Raw: "[^"\\]*"\))?', value)
            if not string:
                raise ValueError("Expected literal packaged manifest identity")
            value = string[1]
        attrs[key] = value
    if len(roots) != 1 or roots[0]["tag"] != "manifest":
        raise ValueError("Missing or ambiguous packaged manifest")
    return roots[0]


def verify_dumps(role, permissions, badging, manifest):
    if role not in {"target", "test"}:
        raise ValueError("Unknown APK role")
    expected = APPLICATION_ID + (".test" if role == "test" else "")
    if not re.search(r"^package: name='" + re.escape(expected) + r"'", badging, re.M):
        raise ValueError(f"Unexpected {role} application ID")
    if "android.permission.INTERNET" in permissions or "android.permission.INTERNET" in manifest:
        raise ValueError(f"{role} APK has INTERNET permission")
    if not re.search(r"^package: " + re.escape(expected) + r"\s*$", permissions, re.M):
        raise ValueError("Missing or mismatched aapt2 permissions output")
    root = parse_manifest_dump(manifest)
    if root["attrs"].get("package") != expected:
        raise ValueError("Packaged manifest identity does not match badging")
    if role == "target":
        applications = [node for node in root["children"] if node["tag"] == "application"]
        if len(applications) != 1 or applications[0]["attrs"].get("android:name") != "android.app.Application":
            raise ValueError("Exact inert smoke Application is missing")
        components = [node for node in applications[0]["children"] if node["tag"] in
                      {"activity", "activity-alias", "service", "receiver", "provider"}]
        if sorted(node["tag"] for node in components) != ["activity", "provider"]:
            raise ValueError("Unexpected startup/production component in smoke APK")
        host = next(node for node in components if node["tag"] == "activity")
        provider = next(node for node in components if node["tag"] == "provider")
        if host["attrs"].get("android:name") != HOST:
            raise ValueError("Exact smoke Activity is missing")
        if (provider["attrs"].get("android:name") != "androidx.core.content.FileProvider" or
                provider["attrs"].get("android:authorities") != APPLICATION_ID + ".smoke-fixtures"):
            raise ValueError("Exact synthetic-only provider is missing")
        if (re.findall(r"(?m)^(?:minSdkVersion|sdkVersion):'([^']+)'", badging) != ['35'] or
                re.findall(r"(?m)^targetSdkVersion:'([^']+)'", badging) != ['37']):
            raise ValueError("Smoke SDK bounds changed")
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aapt2", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--test", required=True, type=Path)
    parser.add_argument("--reports", required=True, type=Path)
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)
    inspected = []
    for role, apk in (("target", args.target), ("test", args.test)):
        dumps = {}
        for name, command in (("permissions", ["permissions"]), ("badging", ["badging"]),
                              ("manifest", ["xmltree", "--file", "AndroidManifest.xml"])):
            dumps[name] = subprocess.run([str(args.aapt2), "dump", *command, str(apk)],
                                         check=True, capture_output=True, text=True, timeout=30).stdout
            (args.reports / f"{role}-{name}.txt").write_text(dumps[name])
        inspected.append((role, apk, dumps))
    # Retain both diagnostic trees even if one APK fails the subsequent safety gate.
    # No APK is installed here; the caller may continue only after all checks succeed.
    records = []
    for role, apk, dumps in inspected:
        package = verify_dumps(role, **dumps)
        records.append({"role": role, "package": package, "internet_permission": False,
                        "sha256": hashlib.sha256(apk.read_bytes()).hexdigest()})
    (args.reports / "apk-verification.json").write_text(json.dumps(records, indent=2) + "\n")
    print("Both actual APKs verified offline; only these hashes may now be installed.")


if __name__ == "__main__":
    main()
