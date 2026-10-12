#!/usr/bin/env python3
"""Gate the disposable emulator's package service, then install each verified APK once."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SERIAL = "emulator-5554"
READINESS_SECONDS = 60
PROBE_SECONDS = 5
SAMPLE_INTERVAL_SECONDS = 2
INSTALL_SECONDS = 90
SNAPSHOT_SECONDS = 15
# The workflow grants five minutes. Stop commands at 270 seconds, leaving at least
# 30 seconds for the bounded report to be encoded/written before workflow cancellation.
STEP_SECONDS = 270
MAX_REPORT_BYTES = 4096
MAX_PREVIEW_CHARACTERS = 128
MAX_PARSE_BYTES = 4096
PROBES = (
    ("boot_completed", ("getprop", "sys.boot_completed")),
    ("system_server", ("pidof", "system_server")),
    ("package_path", ("cmd", "package", "path", "android")),
)


class InstallError(ValueError):
    pass


def plain_path(path):
    """Do not follow symlinks in the caller's input or report paths."""
    path = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise InstallError("symlink_path")
    return path


def verified_apks(directory):
    directory = plain_path(directory)
    if not directory.is_dir():
        raise InstallError("apk_directory_missing")
    entries = {entry.name for entry in directory.iterdir()}
    if not {"target.apk", "test.apk"} <= entries or entries - {"target.apk", "test.apk", "SHA256SUMS"}:
        raise InstallError("unexpected_apk_directory_entries")
    for name in entries:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise InstallError("apk_directory_requires_plain_regular_files")
        if path.stat().st_size <= 0:
            raise InstallError("empty_apk_directory_file")
    # The caller owns manifest/signature/hash verification. This helper neither changes
    # these bytes nor claims that regular files alone establish APK isolation.
    return directory


def prepare_report_path(path, directory):
    path = plain_path(path)
    if path.name != "install-diagnostics.json" or path.is_relative_to(directory):
        raise InstallError("report_requires_fixed_name_outside_apk_directory")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise InstallError("report_requires_plain_regular_file")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def milliseconds(seconds):
    return max(0, round(seconds * 1000))


def output_bytes(value):
    if isinstance(value, bytes):
        return value
    return (value or "").encode("utf-8", errors="replace")


def capture(record, stdout=None, stderr=None):
    for stream, value in (("stdout", stdout), ("stderr", stderr)):
        raw = output_bytes(value)
        decoded = raw.decode("utf-8", errors="replace")
        # One replacement per decoded character keeps counts exact. No terminal control
        # sequences, raw exception/command details, environment, or logcat are collected.
        preview = "".join(character if " " <= character <= "~" else "?"
                          for character in decoded[:MAX_PREVIEW_CHARACTERS])
        record[stream + "_preview"] = preview
        record[stream + "_bytes"] = len(raw)
        record[stream + "_characters"] = len(decoded)
        record[stream + "_omitted_characters"] = len(decoded) - len(preview)


def command(adb, arguments, seconds, deadline):
    started = time.monotonic()
    timeout = min(seconds, max(0, deadline - started))
    record = {"elapsed_ms": 0, "timeout_ms": milliseconds(timeout)}
    stdout = b""
    if timeout <= 0:
        record["status"] = "deadline"
        capture(record)
        return record, stdout
    try:
        result = subprocess.run([str(adb), "-s", SERIAL, *arguments],
                                capture_output=True, check=False, timeout=timeout)
        stdout = output_bytes(result.stdout)
        capture(record, stdout, result.stderr)
        record.update(status="exit", exit_code=result.returncode)
    except subprocess.TimeoutExpired as failure:
        stdout = output_bytes(failure.stdout)
        capture(record, stdout, failure.stderr)
        record["status"] = "timeout"
    except (OSError, subprocess.SubprocessError) as failure:
        capture(record)
        record.update(status="error", failure_type=type(failure).__name__)
    record["elapsed_ms"] = milliseconds(time.monotonic() - started)
    return record, stdout


def parse_probe(name, raw):
    if len(raw) > MAX_PARSE_BYTES:
        raise InstallError("oversized_probe_output")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as failure:
        raise InstallError("invalid_probe_utf8") from failure
    if name == "boot_completed":
        if not re.fullmatch(r"[01](?:\r?\n)?", text):
            raise InstallError("malformed_boot_completed")
        return {"boot_completed": text[0] == "1"}, text[0] == "1"
    if name == "system_server":
        match = re.fullmatch(r"([1-9][0-9]{0,9})(?:\r?\n)?", text)
        if match is None or int(match[1]) > 2_147_483_647:
            raise InstallError("missing_or_ambiguous_system_server_pid")
        return {"pid": int(match[1])}, True
    # Package paths are evidence only, never interpolated into a later shell command.
    if "\r" in text.replace("\r\n", ""):
        raise InstallError("missing_or_malformed_package_path")
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or len(lines) > 16:
        raise InstallError("missing_or_malformed_package_path")
    for line in lines:
        match = re.fullmatch(r"package:(/[A-Za-z0-9_./+-]+\.apk)", line)
        if match is None or any(part in {"", ".", ".."} for part in match[1][1:].split("/")):
            raise InstallError("missing_or_malformed_package_path")
    return {"package_paths": len(lines)}, True


def sample(adb, deadline):
    started = time.monotonic()
    observation = {"ready": False, "probes": {}}
    ready = True
    for name, arguments in PROBES:
        record, stdout = command(adb, ["shell", *arguments], PROBE_SECONDS, deadline)
        observation["probes"][name] = record
        record["parse_status"] = "unknown"
        if record["status"] != "exit" or record["exit_code"] != 0:
            ready = False
            continue
        try:
            values, passed = parse_probe(name, stdout)
            record["parse_status"] = "ready" if passed else "not_ready"
            observation.update(values)
            ready = ready and passed
        except InstallError as failure:
            record["parse_error"] = str(failure)
            ready = False
    observation["ready"] = ready and time.monotonic() < deadline
    observation["elapsed_ms"] = milliseconds(time.monotonic() - started)
    return observation


def wait_for_readiness(adb, step_deadline, evidence):
    started = time.monotonic()
    deadline = min(started + READINESS_SECONDS, step_deadline)
    evidence.update(role="emulator", stage="readiness", status="blocked", samples=0, successful_samples=0, failed_samples=0,
                    pid_changes=0, probe_counts={name: {} for name, _ in PROBES})
    candidate_pid = None
    candidate_completed_at = None
    previous_pid = None
    while time.monotonic() < deadline:
        observation = sample(adb, deadline)
        now = time.monotonic()
        evidence["last_sample"] = observation
        evidence["samples"] += 1
        for name, record in observation["probes"].items():
            counts = evidence["probe_counts"][name]
            status = record["status"]
            if status == "exit":
                status = "exit_zero" if record["exit_code"] == 0 else "exit_nonzero"
            counts[status] = counts.get(status, 0) + 1
            status = record["parse_status"]
            counts[status] = counts.get(status, 0) + 1
        pid = observation.get("pid")
        if pid is not None:
            if previous_pid is not None and pid != previous_pid:
                evidence["pid_changes"] += 1
            previous_pid = pid
        if observation["ready"]:
            evidence["successful_samples"] += 1
            if candidate_pid == pid and now - candidate_completed_at >= SAMPLE_INTERVAL_SECONDS:
                evidence.update(status="passed", stable_pid=pid,
                                stable_sample_elapsed_ms=[milliseconds(candidate_completed_at - started),
                                                          milliseconds(now - started)])
                evidence["elapsed_ms"] = milliseconds(now - started)
                return
            candidate_pid = pid
            candidate_completed_at = now
        else:
            evidence["failed_samples"] += 1
            candidate_pid = None
            candidate_completed_at = None
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(SAMPLE_INTERVAL_SECONDS, remaining))
    evidence["elapsed_ms"] = milliseconds(time.monotonic() - started)
    raise InstallError("readiness_deadline")


def install(adb, apk, role, step_deadline):
    record, stdout = command(adb, ["install", "-t", str(apk)], INSTALL_SECONDS, step_deadline)
    record.update(role=role, stage="install")
    # A zero exit code alone is insufficient. Match the whole unmodified line, never a
    # substring or a whitespace-stripped diagnostic. Keep default adb install transport.
    record["success_lines"] = sum(line == b"Success" for line in stdout.splitlines())
    record["passed"] = (record["status"] == "exit" and record["exit_code"] == 0 and
                        record["success_lines"] == 1 and len(stdout) <= MAX_PARSE_BYTES)
    return record


def records(report):
    yield from report.get("readiness", {}).get("last_sample", {}).get("probes", {}).values()
    yield from report.get("installs", [])
    yield from report.get("snapshot", {}).get("probes", {}).values()


def encode_report(report):
    # Keep every captured numeric/status field. Only previews may be shortened; original
    # byte/character counts stay unchanged and omitted-character counts remain exact.
    diagnostic_records = list(report.get("readiness", {}).get("last_sample", {}).get("probes", {}).values())
    diagnostic_records += list(report.get("snapshot", {}).get("probes", {}).values())
    # Sacrifice repeated readiness/postmortem previews before the original install
    # failure's preview; no status or count is discarded in either group.
    reductions = [(diagnostic_records, limit) for limit in (MAX_PREVIEW_CHARACTERS, 64, 32, 16, 0)]
    reductions += [(report.get("installs", []), limit) for limit in (64, 32, 16, 0)]
    for group, limit in reductions:
        for record in group:
            for stream in ("stdout", "stderr"):
                key = stream + "_preview"
                if len(record.get(key, "")) > limit:
                    record[key] = record[key][:limit]
                    record[stream + "_omitted_characters"] = record[stream + "_characters"] - limit
        encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n"
        if len(encoded.encode("utf-8")) <= MAX_REPORT_BYTES:
            return encoded
    raise InstallError("report_exceeded_fixed_limit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apks", type=Path, required=True)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", choices=(SERIAL,), default=SERIAL)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    step_deadline = started + STEP_SECONDS
    report = {"schema": 1, "serial": SERIAL, "status": "blocked", "stage": "inputs",
              "readiness": {}, "installs": []}
    # Prepare the safe report destination even when input validation fails, so the
    # caller gets a bounded failure report without ever probing/installing unsafe input.
    try:
        directory = plain_path(args.apks)
        report_path = prepare_report_path(args.report, directory)
    except (InstallError, OSError) as failure:
        print(f"::error::Install report path rejected ({type(failure).__name__})", file=sys.stderr)
        return 1
    inputs_valid = False
    try:
        directory = verified_apks(directory)
        inputs_valid = True
        report["stage"] = "readiness"
        wait_for_readiness(args.adb, step_deadline, report["readiness"])
        for role in ("target", "test"):
            report["stage"] = role + "_install"
            record = install(args.adb, directory / f"{role}.apk", role, step_deadline)
            report["installs"].append(record)
            if not record["passed"]:
                raise InstallError(role + "_install_failed")
        report.update(status="passed", stage="complete")
    except (InstallError, OSError) as failure:
        report["error"] = str(failure) if isinstance(failure, InstallError) else type(failure).__name__
    finally:
        if inputs_valid:
            snapshot_deadline = min(time.monotonic() + SNAPSHOT_SECONDS, step_deadline)
            report["snapshot"] = sample(args.adb, snapshot_deadline)
            report["snapshot"].update(role="emulator", stage="post_success" if report["status"] == "passed" else "post_failure")
            if report["status"] == "passed" and not report["snapshot"]["ready"]:
                report.update(status="blocked", stage="post_install_health", error="post_install_health_failed")
        report["elapsed_ms"] = milliseconds(time.monotonic() - started)
    try:
        report_path.write_text(encode_report(report), encoding="utf-8")
    except (InstallError, OSError) as failure:
        print(f"::error::Install diagnostics could not be saved ({type(failure).__name__})", file=sys.stderr)
        return 1
    if report["status"] != "passed":
        print(f"::error::{report['stage']}: {report['error']}; see {report_path.name}", file=sys.stderr)
        return 1
    print(f"Both verified APKs installed once and post-install health passed; see {report_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
