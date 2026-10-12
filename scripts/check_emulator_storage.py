#!/usr/bin/env python3
"""Read-only capacity gates for the disposable smoke emulator; never override Android storage policy."""
import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

MIB = 1024 * 1024
PARTITION_MIB = 6144
RESERVE_BYTES = 1024 * MIB
MAX_REPORT_BYTES = 4096
MAX_PROBE_TEXT_CHARS = 128
MAX_MOUNT_PATH_CHARS = 192


class StorageError(ValueError):
    pass


def apk_budget(directory):
    apks = []
    for role in ("target", "test"):
        path = directory / f"{role}.apk"
        if path.is_symlink() or not path.is_file():
            raise StorageError("Expected verified regular target/test APK files")
        size = path.stat().st_size
        with zipfile.ZipFile(path) as archive:
            expanded = sum(item.file_size for item in archive.infolist())
        if size <= 0 or expanded <= 0:
            raise StorageError("Empty APK storage metadata")
        apks.append({"role": role, "apk_bytes": size, "uncompressed_entry_bytes": expanded})
    compressed = sum(item["apk_bytes"] for item in apks)
    expanded = sum(item["uncompressed_entry_bytes"] for item in apks)
    # Conservative planning allowance, not PackageInstaller's exact allocation calculation:
    # a staging copy + installed APK copies, all ZIP contents, and one GiB for dex/runtime
    # growth and Android's own low-space reserve. Android still makes the final decision.
    return {"apks": apks, "apk_total_bytes": compressed,
            "uncompressed_total_bytes": expanded, "reserve_bytes": RESERVE_BYTES,
            "required_guest_available_bytes": 2 * compressed + expanded + RESERVE_BYTES}


def parse_statfs(text):
    if len(text) > 4096 or not re.fullmatch(r"\d{1,20},\d{1,20},\d{1,20},\d{1,20}\s*", text):
        raise StorageError("Unexpected guest /data statfs output")
    block, total, free, available = map(int, text.strip().split(","))
    if not (0 < block <= MIB and 0 <= available <= free <= total and total > 0):
        raise StorageError("Invalid guest /data block accounting")
    return {"block_bytes": block, "total_blocks": total, "free_blocks": free,
            "available_blocks": available, "total_bytes": total * block,
            "free_bytes": free * block, "available_bytes": available * block}


def parse_df(text):
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if (len(text) > 4096 or len(lines) != 2 or len(lines[0]) != 7 or
            lines[0][0] != "Filesystem" or lines[0][1] not in {"1024-blocks", "1K-blocks"} or
            lines[0][2:4] != ["Used", "Available"] or lines[0][4] not in {"Use%", "Capacity"} or
            lines[0][5:] != ["Mounted", "on"] or len(lines[1]) != 6):
        raise StorageError("Unexpected guest /data df output")
    row = lines[1]
    if not all(re.fullmatch(r"\d{1,20}", value) for value in row[1:4]):
        raise StorageError("Non-numeric guest /data df accounting")
    total, used, available = map(int, row[1:4])
    if (not (total > 0 and 0 <= used <= total and 0 <= available <= total and used + available <= total) or
            not re.fullmatch(r"(?:100|[0-9]{1,2})%", row[4])):
        raise StorageError("Invalid guest /data df accounting")
    mount = row[-1]
    # adb shell joins arguments for a guest shell. A reported path is never passed back to
    # it unless it contains only these bounded safe characters and canonical components.
    if (len(mount) > MAX_MOUNT_PATH_CHARS or not re.fullmatch(r"/[A-Za-z0-9_./-]+", mount) or
            any(component in {"", ".", ".."} for component in mount[1:].split("/"))):
        raise StorageError("Unsafe or unsupported guest df mount path")
    return {"total_bytes": total * 1024, "used_bytes": used * 1024,
            "available_bytes": available * 1024, "reported_mount": mount}


def parse_mount_identity(text):
    match = re.fullmatch(r"([1-9][0-9]{0,19})\r?\n([1-9][0-9]{0,19})(?:\r?\n)?", text)
    if match is None:
        raise StorageError("Unexpected guest df mount identity output")
    data_device, mount_device = map(int, match.groups())
    if data_device != mount_device:
        raise StorageError("Guest df mount does not share /data device identity")
    return {"data_device": data_device, "reported_mount_device": mount_device}


def probe_text(value):
    # Fixed /data probes only, never an application/filesystem dump. Replace control/non-ASCII
    # characters so previews stay printable and JSON escaping has a bounded expansion.
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = value or ""
    preview = "".join(character if " " <= character <= "~" or character in "\r\n\t" else "?"
                      for character in text[:MAX_PROBE_TEXT_CHARS])
    return preview, len(text), len(text) > MAX_PROBE_TEXT_CHARS


def guest_storage(adb, serial, evidence=None):
    guest = {} if evidence is None else evidence
    guest["probes"] = {}

    def capture(probe, stdout, stderr):
        for name, value in (("stdout", stdout), ("stderr", stderr)):
            preview, length, truncated = probe_text(value)
            probe[name + "_preview"] = preview
            probe[name + "_characters"] = length
            probe[name + "_truncated"] = truncated

    def read(name, command):
        guest["stage"] = name + "_command"
        probe = {"command": command}
        guest["probes"][name] = probe
        try:
            result = subprocess.run([str(adb), "-s", serial, "shell", *command],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    check=False, timeout=15)
        except subprocess.TimeoutExpired as failure:
            capture(probe, failure.stdout, failure.stderr)
            probe["status"] = "timeout"
            raise StorageError(f"Guest /data {name} command timed out") from failure
        except (OSError, subprocess.SubprocessError) as failure:
            probe["status"] = "failed"
            probe["failure_type"] = type(failure).__name__
            raise
        capture(probe, result.stdout, result.stderr)
        probe["exit_code"] = result.returncode
        probe["status"] = "completed" if result.returncode == 0 else "failed"
        if result.returncode != 0:
            raise StorageError(f"Guest /data {name} command failed")
        guest["stage"] = name + "_parse"
        probe["parse_status"] = "blocked"
        return result.stdout

    # Fixed read-only commands, explicit disposable serial, no root or settings changes.
    stat = parse_statfs(read("statfs", ["stat", "-f", "-c", "%S,%b,%f,%a", "/data"]))
    guest["statfs"] = stat
    guest["probes"]["statfs"]["parse_status"] = "passed"
    df = parse_df(read("df", ["df", "-Pk", "/data"]))
    guest["df"] = df
    guest["probes"]["df"]["parse_status"] = "passed"
    if df["reported_mount"] != "/data":
        # Toybox selects a mount with the requested path's st_dev, which can name a bind
        # mount alias. Independently verify that identity before trusting its capacity.
        identity = parse_mount_identity(read("mount_identity", [
            "stat", "-L", "-c", "%d", "/data", df["reported_mount"]
        ]))
        guest["df_mount_identity"] = identity
        guest["probes"]["mount_identity"]["parse_status"] = "passed"
        df["mount_validation"] = "same_device"
    else:
        df["mount_validation"] = "literal_data"
    guest["available_bytes_for_gate"] = min(stat["available_bytes"], df["available_bytes"])
    guest["stage"] = "complete"
    return guest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("host", "guest"))
    parser.add_argument("--apks", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--adb", type=Path)
    parser.add_argument("--serial", default="emulator-5554", choices=("emulator-5554",))
    args = parser.parse_args()
    report = {"phase": args.phase, "status": "blocked", "configured_partition_mib": PARTITION_MIB}
    error = None
    stage = "apk_budget"
    try:
        report.update(apk_budget(args.apks))
        if args.phase == "host":
            stage = "host_capacity"
            host = shutil.disk_usage(args.apks.parent)
            # Allow the complete configured data image plus the same installation headroom.
            required = PARTITION_MIB * MIB + report["required_guest_available_bytes"]
            report.update(host_total_bytes=host.total, host_available_bytes=host.free,
                          required_host_available_bytes=required)
            if host.free < required:
                raise StorageError("Host temporary disk lacks room for the disposable data image and reserve")
        else:
            stage = "guest_probe"
            if args.adb is None:
                raise StorageError("Guest storage check requires the official adb path")
            # Populate this report in-place before probing, preserving earlier measurements
            # and bounded diagnostics if a later command or parse fails.
            report["guest"] = {}
            guest_storage(args.adb, args.serial, report["guest"])
            stage = "guest_capacity"
            if report["guest"]["available_bytes_for_gate"] < report["required_guest_available_bytes"]:
                raise StorageError("Guest /data lacks measured space for both APKs and the installation reserve")
        report["status"] = "passed"
    except (StorageError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as failure:
        error = str(failure) if isinstance(failure, StorageError) else f"Storage probe failed ({type(failure).__name__})"
        report["error"] = error
        report["failure_stage"] = report.get("guest", {}).get("stage", stage) if stage == "guest_probe" else stage
    encoded = json.dumps(report, indent=2) + "\n"
    # Preserve accounting/stages even if escaped previews plus a later error exhaust the
    # total report budget. Trim previews only; never truncate values used by the gate.
    for preview_limit in (MAX_PROBE_TEXT_CHARS // 2, 0):
        if len(encoded.encode()) <= MAX_REPORT_BYTES:
            break
        for probe in report.get("guest", {}).get("probes", {}).values():
            for stream in ("stdout", "stderr"):
                key = stream + "_preview"
                if len(probe.get(key, "")) > preview_limit:
                    probe[key] = probe[key][:preview_limit]
                    probe[stream + "_truncated"] = True
        encoded = json.dumps(report, indent=2) + "\n"
    if len(encoded.encode()) > MAX_REPORT_BYTES:
        raise SystemExit("Storage report exceeded its fixed diagnostic limit")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(encoded)
    if error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print(f"{args.phase.capitalize()} storage preflight passed; measured capacity saved in {args.report.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
