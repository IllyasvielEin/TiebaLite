#!/usr/bin/env python3
"""Failure-only, fixed-field system-process signatures; raw log data stays in capped memory."""
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time

SERIAL = "emulator-5554"
METADATA_SECONDS = 2
LOG_SECONDS = 5
MAX_STDOUT_BYTES = 65536
MAX_STDERR_BYTES = 1024
MAX_REPORT_BYTES = 4096
MAX_WINDOW_NS = 210 * 1_000_000_000
MAX_PID = 2_147_483_647
MAX_LINE_BYTES = 4096
EXCEPTIONS = {"java.lang." + name: name for name in
              ("OutOfMemoryError", "NullPointerException", "IllegalStateException", "SecurityException")}
HEADER = re.compile(r" {0,16}([1-9][0-9]{0,9})\.([0-9]{6}) {1,16}([1-9][0-9]{0,9}) {1,16}([1-9][0-9]{0,9}) ([VDIWEF]) ([A-Za-z][A-Za-z0-9_]{0,31}) {0,8}: (.*)")
LIBC_SIGNAL = re.compile(r"Fatal signal ([1-9][0-9]?) \(SIG[A-Z0-9_+ -]{1,24}\), code -?[0-9]{1,10} \([^()\r\n]{1,128}\)(?:, (?:fault addr (?:0x[0-9A-Fa-f]{1,16}|\(nil\))|syscall [0-9]{1,10}))? in tid ([1-9][0-9]{0,9}) \([^()\r\n]{1,64}\)(?:, pid ([1-9][0-9]{0,9}) \([^()\r\n]{1,64}\))?")
EVIDENCE_FIELDS = ("zygote_termination_seen", "zygote_exit_status", "zygote_signal",
                   "java_fatal_seen", "java_exception", "libc_signal")


def ms(seconds):
    return max(0, round(seconds * 1000))


def unknown_evidence():
    return {**{name: None for name in EVIDENCE_FIELDS}, "ambiguous": False}


def read_capped(arguments, seconds, deadline, stdout_limit=MAX_STDOUT_BYTES):
    """Drain both pipes without communicate(), files, previews, or unbounded buffers."""
    started = time.monotonic()
    end = min(started + seconds, deadline)
    result = {"collection_status": "unavailable", "reason": "no_budget", "exit_code": None,
              "elapsed_ms": 0, "stdout_bytes_seen": 0, "stderr_bytes_seen": 0}
    if end - started < 0.05:
        return result, b""
    # Reserve cleanup time inside the same deadline, including on cap/timeout paths.
    read_end = end - min(0.25, (end - started) / 4)
    process = None
    selector = None
    raw = bytearray()
    try:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, close_fds=True)
        selector = selectors.DefaultSelector()
        for stream, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, stream)
        result.update(collection_status="complete", reason=None)
        while selector.get_map():
            remaining = read_end - time.monotonic()
            if remaining <= 0:
                result.update(collection_status="timeout", reason="timeout")
                break
            for key, _ in selector.select(remaining):
                stream = key.data
                limit = stdout_limit if stream == "stdout" else MAX_STDERR_BYTES
                seen_key = stream + "_bytes_seen"
                chunk = os.read(key.fileobj.fileno(), min(4096, limit - result[seen_key]))
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                result[seen_key] += len(chunk)
                if stream == "stdout":
                    raw.extend(chunk)
                # Stderr content is discarded immediately, including warnings/secrets.
                if result[seen_key] >= limit:
                    result.update(collection_status="byte_limit", reason="output_limit")
                    break
            if result["collection_status"] != "complete":
                break
        if result["collection_status"] == "complete":
            try:
                process.wait(timeout=max(0, read_end - time.monotonic()))
            except subprocess.TimeoutExpired:
                result.update(collection_status="timeout", reason="timeout")
    except (OSError, ValueError, subprocess.SubprocessError):
        result.update(collection_status="command_error", reason="io_error")
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    result.update(collection_status="command_error", reason="io_error")
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            try:
                process.wait(timeout=max(0, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                result.update(collection_status="timeout", reason="timeout")
            result["exit_code"] = process.poll()
        result["elapsed_ms"] = ms(time.monotonic() - started)
    if result["collection_status"] == "complete":
        if result["exit_code"] != 0:
            result.update(collection_status="command_error", reason="command_failed")
        elif result["stderr_bytes_seen"]:
            result.update(collection_status="command_error", reason="stderr_present")
    return result, bytes(raw)


def positive_pid(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_PID


def parse_zygotes(raw):
    match = re.fullmatch(rb"([1-9][0-9]{0,9})(?: +([1-9][0-9]{0,9}))?(?:\r?\n)?", raw)
    if match is None:
        raise ValueError("invalid_metadata")
    values = [int(value) for value in match.groups() if value is not None]
    if not all(positive_pid(value) for value in values) or len(set(values)) != len(values):
        raise ValueError("invalid_metadata")
    return values


def parse_epoch(raw):
    match = re.fullmatch(rb"([1-9][0-9]{0,9})\.([0-9]{9})(?:\r?\n)?", raw)
    if match is None:
        raise ValueError("invalid_metadata")
    return int(match[1]) * 1_000_000_000 + int(match[2])


def unavailable_metadata(pid=None, reason="metadata_unavailable"):
    return {"system_server_pid": pid if positive_pid(pid) else None, "zygote_pids": [],
            "start_epoch_ns": None, "reason": reason}


def metadata_read(adb, command, deadline):
    result, raw = read_capped([str(adb), "-s", SERIAL, "shell", *command], METADATA_SECONDS,
                              deadline, stdout_limit=128)
    return raw if result["collection_status"] == "complete" else None


def start_metadata(adb, pid, deadline):
    metadata = unavailable_metadata(pid)
    if not positive_pid(pid):
        metadata["reason"] = "invalid_metadata"
        return metadata
    if deadline - time.monotonic() < 0.05:
        metadata["reason"] = "no_budget"
        return metadata
    raw = metadata_read(adb, ("pidof", "zygote64", "zygote"), deadline)
    if raw is None:
        return metadata
    try:
        metadata["zygote_pids"] = parse_zygotes(raw)
        raw = metadata_read(adb, ("date", "+%s.%N"), deadline)
        if raw is None:
            return metadata
        metadata["start_epoch_ns"] = parse_epoch(raw)
        metadata["reason"] = None
    except ValueError:
        metadata["reason"] = "invalid_metadata"
    return metadata


def base_report(role, metadata):
    if role not in {"target", "test"}:
        raise ValueError("invalid_metadata")
    metadata = metadata or unavailable_metadata()
    pid = metadata.get("system_server_pid")
    zygotes = metadata.get("zygote_pids", [])
    if not isinstance(zygotes, list) or not 1 <= len(zygotes) <= 2 or not all(positive_pid(pid) for pid in zygotes) or len(set(zygotes)) != len(zygotes):
        zygotes = []
    return {"schema": 1, "role": role, "window_scope": "install_sequence",
            "system_server_pid": pid if positive_pid(pid) else None, "zygote_pids": zygotes,
            "window_duration_ms": None, "collection_status": "unavailable", "reason": "metadata_unavailable",
            "exit_code": None, "elapsed_ms": 0, "stdout_bytes_seen": 0, "stderr_bytes_seen": 0,
            "parsed_records": 0, "ignored_records": 0, "evidence": unknown_evidence()}


def parse_records(raw, pid, zygotes, start_ns, end_ns):
    """Source-derived exact headers/markers, never emit free-form log or throwable text."""
    evidence = {**unknown_evidence(), "zygote_termination_seen": False, "java_fatal_seen": False}
    parsed, ignored = 0, 0
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        return "invalid_utf8", parsed, ignored, unknown_evidence()
    if raw and not raw.endswith(b"\n"):
        return "truncated_record", parsed, ignored, unknown_evidence()
    if "\r" in text.replace("\r\n", "") or any(not char.isprintable() and char not in "\r\n" for char in text):
        return "invalid_header", parsed, ignored, unknown_evidence()
    pending_fatal = {}
    conflicted = set()
    observed_fields = set()
    fact_identities = {}

    def fact(name, value, identity=None):
        observed_fields.add(name)
        if name in conflicted:
            return
        identity = value if identity is None else identity
        if name in fact_identities and fact_identities[name] != identity:
            evidence["ambiguous"] = True
            evidence[name] = None
            conflicted.add(name)
        else:
            evidence[name] = value
            fact_identities[name] = identity

    for line in text.replace("\r\n", "\n").split("\n")[:-1]:
        if re.fullmatch(r"--------- (?:beginning of|switch to) (?:main|system|crash)", line):
            ignored += 1
            continue
        match = HEADER.fullmatch(line) if len(line.encode("utf-8")) <= MAX_LINE_BYTES else None
        if match is None:
            return "invalid_header", parsed, ignored, unknown_evidence()
        seconds, micros, sender, tid = map(int, match.groups()[:4])
        priority, tag, message = match.groups()[4:]
        if not positive_pid(sender) or not positive_pid(tid):
            return "invalid_header", parsed, ignored, unknown_evidence()
        timestamp = seconds * 1_000_000 + micros
        parsed += 1
        if not start_ns // 1000 <= timestamp <= end_ns // 1000:
            ignored += 1
            continue
        matched = False
        if tag == "Zygote" and sender in zygotes:
            terminated = re.fullmatch(r"Exit zygote because system server \(pid ([1-9][0-9]{0,9})\) has terminated", message)
            clean = re.fullmatch(r"Process ([1-9][0-9]{0,9}) exited cleanly \(([0-9]{1,3})\)", message)
            signal = re.fullmatch(r"Process ([1-9][0-9]{0,9}) exited due to signal ([1-9][0-9]?) \([A-Za-z][A-Za-z0-9 _-]{0,63}\)(?:; core dumped)?", message)
            if terminated and priority == "E" and int(terminated[1]) == pid:
                evidence["zygote_termination_seen"] = True
                matched = True
            elif clean and priority == "I" and int(clean[1]) == pid and int(clean[2]) <= 255:
                evidence["zygote_termination_seen"] = True
                fact("zygote_exit_status", int(clean[2]))
                matched = True
            elif signal and priority == "I" and int(signal[1]) == pid and 1 <= int(signal[2]) <= 64:
                evidence["zygote_termination_seen"] = True
                fact("zygote_signal", int(signal[2]))
                matched = True
        elif tag == "AndroidRuntime" and sender == pid and priority in {"E", "F"}:
            key = sender, tid
            if message.startswith("*** FATAL EXCEPTION IN SYSTEM PROCESS: "):
                evidence["java_fatal_seen"] = True
                pending_fatal[key] = [timestamp, 0, False]
                matched = True
            elif key in pending_fatal:
                block = pending_fatal[key]
                block[1] += 1
                if 0 <= timestamp - block[0] <= 2_000_000 and block[1] <= 16 and not block[2]:
                    throwable = re.fullmatch(r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*){1,15})(?::(?: .*)?)?", message)
                    if throwable and len(throwable[1]) <= 128 and throwable[1].endswith(("Exception", "Error")):
                        fact("java_exception", EXCEPTIONS.get(throwable[1], "other"), identity=throwable[1])
                        block[2] = True
                        matched = True
        elif tag == "libc" and sender == pid and priority == "F":
            signal = LIBC_SIGNAL.fullmatch(message)
            if (signal and 1 <= int(signal[1]) <= 64 and positive_pid(int(signal[2])) and
                    (signal[3] is None or int(signal[3]) == pid)):
                fact("libc_signal", int(signal[1]))
                matched = True
        if not matched:
            ignored += 1
    # A single child cannot exit both normally and by signal. libc-observed and
    # Zygote-termination signals are separate facts, not an inferred cause comparison.
    if {"zygote_exit_status", "zygote_signal"} <= observed_fields:
        evidence.update(ambiguous=True, zygote_exit_status=None, zygote_signal=None)
    return None, parsed, ignored, evidence


def _collect_failure(adb, metadata, role, deadline):
    report = base_report(role, metadata)
    metadata = metadata or unavailable_metadata()
    start_ns = metadata.get("start_epoch_ns")
    if (report["system_server_pid"] is None or not report["zygote_pids"] or
            not isinstance(start_ns, int) or isinstance(start_ns, bool) or not 1_000_000_000 <= start_ns < 10_000_000_000_000_000_000):
        report["reason"] = metadata.get("reason") if metadata.get("reason") in {"invalid_metadata", "no_budget"} else "metadata_unavailable"
        return report
    if deadline - time.monotonic() < 0.05:
        report["reason"] = "no_budget"
        return report
    raw_end = metadata_read(adb, ("date", "+%s.%N"), deadline)
    if raw_end is None:
        return report
    try:
        end_ns = parse_epoch(raw_end)
    except ValueError:
        report["reason"] = "invalid_metadata"
        return report
    if end_ns < start_ns or end_ns - start_ns > MAX_WINDOW_NS:
        report.update(collection_status="invalid_window", reason="invalid_window")
        return report
    report["window_duration_ms"] = (end_ns - start_ns) // 1_000_000
    start = f"{start_ns // 1_000_000_000}.{start_ns % 1_000_000_000:09d}"
    arguments = [str(adb), "-s", SERIAL, "shell", "logcat", "-d", "-b", "main", "-b", "system", "-b", "crash",
                 "-v", "threadtime,epoch,usec,printable", "-s", "AndroidRuntime:E", "Zygote:I", "libc:F", "-t", start]
    collection, raw = read_capped(arguments, LOG_SECONDS, deadline)
    report.update(collection)
    if report["collection_status"] == "complete":
        reason, parsed, ignored, evidence = parse_records(raw, report["system_server_pid"], report["zygote_pids"], start_ns, end_ns)
        report.update(parsed_records=parsed, ignored_records=ignored, evidence=evidence)
        if reason is not None:
            report.update(collection_status="invalid_format", reason=reason)
    return report


def collect_failure(adb, metadata, role, deadline):
    started = time.monotonic()
    report = _collect_failure(adb, metadata, role, deadline)
    report["elapsed_ms"] = ms(time.monotonic() - started)
    return report


def validate_report(report):
    """Reject extra/free-form fields rather than attempting to scrub private text."""
    expected = {"schema", "role", "window_scope", "system_server_pid", "zygote_pids", "window_duration_ms",
                "collection_status", "reason", "exit_code", "elapsed_ms", "stdout_bytes_seen", "stderr_bytes_seen",
                "parsed_records", "ignored_records", "evidence"}
    statuses = {"unavailable", "complete", "timeout", "byte_limit", "command_error", "invalid_format", "invalid_window"}
    reasons = {None, "metadata_unavailable", "invalid_metadata", "invalid_window", "no_budget", "command_failed",
               "stderr_present", "invalid_utf8", "invalid_header", "truncated_record", "output_limit", "timeout", "io_error"}
    evidence = report.get("evidence", {})
    if (set(report) != expected or report["schema"] != 1 or report["role"] not in {"target", "test"} or
            report["window_scope"] != "install_sequence" or report["collection_status"] not in statuses or
            report["reason"] not in reasons or set(evidence) != set(EVIDENCE_FIELDS) | {"ambiguous"}):
        raise ValueError("invalid_metadata")
    if report["system_server_pid"] is not None and not positive_pid(report["system_server_pid"]):
        raise ValueError("invalid_metadata")
    zygotes = report["zygote_pids"]
    if not isinstance(zygotes, list) or len(zygotes) > 2 or not all(positive_pid(pid) for pid in zygotes) or len(set(zygotes)) != len(zygotes):
        raise ValueError("invalid_metadata")

    def integer(value, lower, upper, nullable=False):
        return nullable and value is None or isinstance(value, int) and not isinstance(value, bool) and lower <= value <= upper

    limits = {"window_duration_ms": (0, 210000, True), "exit_code": (-MAX_PID - 1, MAX_PID, True),
              "elapsed_ms": (0, 300000, False), "stdout_bytes_seen": (0, MAX_STDOUT_BYTES, False),
              "stderr_bytes_seen": (0, MAX_STDERR_BYTES, False), "parsed_records": (0, MAX_STDOUT_BYTES, False),
              "ignored_records": (0, MAX_STDOUT_BYTES, False)}
    if any(not integer(report[name], *bounds) for name, bounds in limits.items()):
        raise ValueError("invalid_metadata")
    if (any(evidence[name] is not None and not isinstance(evidence[name], bool) for name in ("zygote_termination_seen", "java_fatal_seen")) or
            not isinstance(evidence["ambiguous"], bool) or
            not integer(evidence["zygote_exit_status"], 0, 255, True) or
            any(not integer(evidence[name], 1, 64, True) for name in ("zygote_signal", "libc_signal")) or
            evidence["java_exception"] not in {None, *EXCEPTIONS.values(), "other"}):
        raise ValueError("invalid_metadata")
    if report["collection_status"] != "complete" and evidence != unknown_evidence():
        raise ValueError("invalid_metadata")


def write_report(path, report):
    """Write only the fixed report, never following an existing symlink/hardlink."""
    path = Path(os.path.abspath(path))
    if path.name != "install-termination.json" or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("invalid_metadata")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError("invalid_metadata")
    validate_report(report)
    encoded = json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("output_limit")
    # Never truncate an unsafe leaf that appeared after the pathname checks.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        identity = os.fstat(file.fileno())
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
            raise ValueError("invalid_metadata")
        os.ftruncate(file.fileno(), 0)
        file.write(encoded)
