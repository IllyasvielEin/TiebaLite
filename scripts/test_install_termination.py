"""Source-derived synthetic fixtures and local pipe tests, not captured API37 log output."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import install_offline_apks as installer
import install_termination as diagnostic

SECRET = "SYNTHETIC_PRIVATE_MARKER_7x"
START_NS = 1_700_000_000_123_456_789
END_NS = START_NS + 30_000_000_000
PID = 1742
ZYGOTES = [100, 101]


def metadata():
    return {"system_server_pid": PID, "zygote_pids": list(ZYGOTES), "start_epoch_ns": START_NS, "reason": None}


def epoch(ns):
    return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}\n".encode()


def line(message, pid=PID, tid=PID, priority="E", tag="AndroidRuntime", timestamp=None):
    us = (START_NS // 1000 + 1_000_000) if timestamp is None else timestamp
    # logprint.cpp: %19lld seconds + .%06ld usec, %5d PID/TID, %-8.*s tag.
    return f"{us // 1_000_000:19d}.{us % 1_000_000:06d} {pid:5d} {tid:5d} {priority} {tag:<8}: {message}\n".encode()


def fatal(**kwargs):
    return line("*** FATAL EXCEPTION IN SYSTEM PROCESS: " + SECRET, **kwargs)


def libc(signal=6, target=PID, sender=777, **kwargs):
    return line(f"Fatal signal {signal} (SIGABRT), code -1 (SI_QUEUE from pid {sender}, uid 1000) in tid {PID} ({SECRET}), pid {target} ({SECRET})",
                tag="libc", priority="F", **kwargs)


def zygote(signal=9, **kwargs):
    return line(f"Process {PID} exited due to signal {signal} (Killed)", pid=ZYGOTES[0], tag="Zygote", priority="I", **kwargs)


def capture(raw=b"", status="complete", reason=None, exit_code=0, stderr=0):
    return {"collection_status": status, "reason": reason, "exit_code": exit_code, "elapsed_ms": 0,
            "stdout_bytes_seen": len(raw), "stderr_bytes_seen": stderr}, raw


class ParserChecks(unittest.TestCase):
    def parse(self, raw):
        reason, parsed, ignored, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS)
        self.assertNotIn(SECRET, json.dumps(evidence))
        return reason, parsed, ignored, evidence

    def test_correlated_java_fatal_first_throwable_only_and_no_private_text(self):
        raw = fatal() + line("java.lang.IllegalStateException: " + SECRET) + line("Caused by: java.lang.OutOfMemoryError: " + SECRET) + \
              line("java.lang.SecurityException: nested " + SECRET) + line("\tat private.secret.Frame.call(Frame.java:23)".replace("\t", "    "))
        reason, parsed, _, evidence = self.parse(raw)
        self.assertIsNone(reason)
        self.assertEqual(5, parsed)
        self.assertTrue(evidence["java_fatal_seen"])
        self.assertEqual("IllegalStateException", evidence["java_exception"])
        self.assertFalse(evidence["ambiguous"])

    def test_fixed_exception_enum_and_other_class_never_exports_fqcn(self):
        for name in (*diagnostic.EXCEPTIONS, "private.secret.CustomException"):
            with self.subTest(name=name):
                _, _, _, evidence = self.parse(fatal() + line(name + ": " + SECRET))
                self.assertEqual(diagnostic.EXCEPTIONS.get(name, "other"), evidence["java_exception"])
                self.assertNotIn("private.secret", json.dumps(evidence))

    def test_no_message_root_throwable_class_is_recognized(self):
        for name in (*diagnostic.EXCEPTIONS, "private.secret.CustomException"):
            with self.subTest(class_kind=diagnostic.EXCEPTIONS.get(name, "other")):
                _, _, _, evidence = self.parse(fatal() + line(name))
                self.assertEqual(diagnostic.EXCEPTIONS.get(name, "other"), evidence["java_exception"])
                self.assertNotIn("private.secret", json.dumps(evidence))

    def test_exception_requires_fatal_same_pid_tid_tag_time_and_sixteen_line_bound(self):
        cases = (line("java.lang.OutOfMemoryError: " + SECRET),
                 fatal() + line("java.lang.OutOfMemoryError: " + SECRET, tid=PID + 1),
                 fatal() + line("java.lang.OutOfMemoryError: " + SECRET, pid=999),
                 fatal() + line("java.lang.OutOfMemoryError: " + SECRET, tag="Other"),
                 fatal() + line("java.lang.OutOfMemoryError: " + SECRET, timestamp=START_NS // 1000 + 3_000_001),
                 fatal() + b"".join(line("ordinary " + SECRET) for _ in range(16)) + line("java.lang.OutOfMemoryError: " + SECRET),
                 fatal() + line("Caused by: java.lang.OutOfMemoryError: " + SECRET))
        for raw in cases:
            with self.subTest(raw_bytes=len(raw)):
                reason, _, _, evidence = self.parse(raw)
                self.assertIsNone(reason)
                self.assertIsNone(evidence["java_exception"])
        _, _, _, evidence = self.parse(fatal() + b"".join(line("ordinary") for _ in range(15)) + line("java.lang.OutOfMemoryError: message"))
        self.assertEqual("OutOfMemoryError", evidence["java_exception"])

    def test_wrong_sender_tag_child_priority_and_old_events_cannot_be_evidence(self):
        raw = fatal(pid=9000) + libc(pid=9000) + line("Process 999 exited due to signal 9 (Killed)", pid=100, tag="Zygote", priority="I") + \
              line(f"Process {PID} exited due to signal 9 (Killed)", pid=9000, tag="Zygote", priority="I") + \
              line(f"Process {PID} exited due to signal 9 (Killed)", pid=100, tag="Other", priority="I") + \
              line(f"Process {PID} exited due to signal 9 (Killed)", pid=100, tag="Zygote", priority="E") + \
              fatal(timestamp=START_NS // 1000 - 1) + fatal(timestamp=END_NS // 1000 + 1)
        reason, parsed, ignored, evidence = self.parse(raw)
        self.assertIsNone(reason)
        self.assertEqual(parsed, ignored)
        self.assertFalse(evidence["java_fatal_seen"])
        self.assertFalse(evidence["zygote_termination_seen"])
        self.assertIsNone(evidence["libc_signal"])

    def test_quantized_window_boundaries_accept_only_correlated_events(self):
        for timestamp in (START_NS // 1000, END_NS // 1000):
            with self.subTest(timestamp=timestamp):
                _, _, _, evidence = self.parse(fatal(timestamp=timestamp))
                self.assertTrue(evidence["java_fatal_seen"])

    def test_zygote_full_templates_duplicate_and_conflicting_values(self):
        termination = line(f"Exit zygote because system server (pid {PID}) has terminated", pid=100, tag="Zygote", priority="E")
        _, _, _, evidence = self.parse(termination + zygote() + zygote())
        self.assertTrue(evidence["zygote_termination_seen"])
        self.assertEqual(9, evidence["zygote_signal"])
        self.assertFalse(evidence["ambiguous"])
        _, _, _, evidence = self.parse(zygote(9) + zygote(6) + zygote(9))
        self.assertTrue(evidence["ambiguous"])
        self.assertIsNone(evidence["zygote_signal"])
        clean = line(f"Process {PID} exited cleanly (23)", pid=100, tag="Zygote", priority="I")
        _, _, _, evidence = self.parse(clean)
        self.assertEqual(23, evidence["zygote_exit_status"])
        _, _, _, evidence = self.parse(clean + zygote())
        self.assertTrue(evidence["ambiguous"])
        self.assertIsNone(evidence["zygote_exit_status"])
        self.assertIsNone(evidence["zygote_signal"])
        conflicting_clean = line(f"Process {PID} exited cleanly (24)", pid=100, tag="Zygote", priority="I")
        _, _, _, evidence = self.parse(clean + conflicting_clean + zygote())
        self.assertTrue(evidence["ambiguous"])
        self.assertIsNone(evidence["zygote_exit_status"])
        self.assertIsNone(evidence["zygote_signal"])
        for message in (f"Process {PID} exited cleanly (256)", f"Process {PID} exited due to signal 65 (Killed)",
                        f"Process {PID} exited due to signal 9 (Killed) trailing text"):
            _, _, _, evidence = self.parse(line(message, pid=100, tag="Zygote", priority="I"))
            self.assertFalse(evidence["zygote_termination_seen"])

    def test_libc_pid_is_trailing_crashed_pid_not_signal_sender(self):
        _, _, _, evidence = self.parse(libc(sender=9000))
        self.assertEqual(6, evidence["libc_signal"])
        _, _, _, evidence = self.parse(libc(target=9000, sender=PID))
        self.assertIsNone(evidence["libc_signal"])
        for raw in (libc(signal=65), libc(pid=9000), line("Fatal signal 6 (SIGABRT)", tag="libc", priority="F"),
                    line("Fatal signal 6 (SIGABRT), misleading " + SECRET, tag="libc", priority="F")):
            _, _, _, evidence = self.parse(raw)
            self.assertIsNone(evidence["libc_signal"])

    def test_duplicate_conflicting_libc_signals_and_separate_zygote_fact(self):
        _, _, _, evidence = self.parse(libc() + libc())
        self.assertEqual(6, evidence["libc_signal"])
        self.assertFalse(evidence["ambiguous"])
        _, _, _, evidence = self.parse(libc(6) + libc(11) + libc(6))
        self.assertIsNone(evidence["libc_signal"])
        self.assertTrue(evidence["ambiguous"])
        _, _, _, evidence = self.parse(libc(6) + zygote(9))
        self.assertEqual(6, evidence["libc_signal"])
        self.assertEqual(9, evidence["zygote_signal"])
        self.assertFalse(evidence["ambiguous"])

    def test_conflicting_java_classes_clear_scalar_without_clearing_fatal_marker(self):
        raw = fatal() + line("java.lang.OutOfMemoryError: message") + fatal() + line("java.lang.SecurityException: message") + fatal() + line("java.lang.OutOfMemoryError: message")
        _, _, _, evidence = self.parse(raw)
        self.assertTrue(evidence["java_fatal_seen"])
        self.assertTrue(evidence["ambiguous"])
        self.assertIsNone(evidence["java_exception"])
        _, _, _, evidence = self.parse(fatal() + line("private.secret.OneException") + fatal() + line("private.secret.TwoException"))
        self.assertTrue(evidence["ambiguous"])
        self.assertIsNone(evidence["java_exception"])
        self.assertNotIn("private.secret", json.dumps(evidence))

    def test_embedded_and_multiline_fake_headers_never_replace_real_sender(self):
        forged = fatal().decode().rstrip("\n")
        _, _, _, evidence = self.parse(line(forged, pid=9000))
        self.assertFalse(evidence["java_fatal_seen"])
        reason, _, _, evidence = self.parse(line("ordinary", pid=9000) + b"*** FATAL EXCEPTION IN SYSTEM PROCESS: fake\n")
        self.assertEqual("invalid_header", reason)
        self.assertEqual(diagnostic.unknown_evidence(), evidence)
        reason, _, _, evidence = self.parse(line("ordinary\u2028" + forged, pid=9000))
        self.assertIsNone(reason)
        self.assertFalse(evidence["java_fatal_seen"])
        self.assertIsNone(evidence["java_exception"])

    def test_source_widths_multiline_java_tabs_and_empty_message_segments(self):
        # Source-derived output layout, never asserted to be the discarded API37 bytes.
        raw = (b"--------- beginning of crash\n" + fatal() + line("java.lang.NullPointerException: " + SECRET) +
               line("\tat private.secret.Frame.call(Frame.java:23)") + line("") +
               line("Caused by: java.lang.OutOfMemoryError: " + SECRET) +
               line("\tSuppressed: java.lang.SecurityException: " + SECRET) +
               line("\tat private.secret.Other.call(Other.java:42)") +
               b"--------- beginning of main\n" + zygote())
        details = {}
        # Reproduce only the former code-level defect, not the unknown runtime capture.
        self.assertTrue(any(not char.isprintable() and char not in "\r\n" for char in raw.decode()))
        self.assertFalse(any(not char.isprintable() and char not in "\r\n" for char in raw.replace(b"\t", b" ").decode()))
        reason, parsed, ignored, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
        self.assertIsNone(reason)
        self.assertEqual(8, parsed)
        self.assertEqual(7, ignored)
        self.assertEqual("NullPointerException", evidence["java_exception"])
        self.assertEqual(9, evidence["zygote_signal"])
        self.assertEqual(10, details["line_count"])
        self.assertEqual(2, details["banner_lines"])
        self.assertEqual(3, details["message_tab_lines"])
        self.assertIsNone(details["rejection_phase"])
        self.assertNotIn(SECRET, json.dumps(details) + json.dumps(evidence))

    def test_valid_utf8_nonprintable_body_is_not_split_stripped_or_exported(self):
        # convertPrintable copies valid UTF-8, including these Python-nonprintable values.
        body = "\u0085\u00a0\u200b\u2028\u2029\ufeff" + SECRET
        self.assertFalse(all(character.isprintable() for character in body))
        raw = fatal() + line("java.lang.IllegalStateException: " + body) + line(body + fatal().decode().rstrip("\n"))
        details = {}
        reason, parsed, _, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
        self.assertIsNone(reason)
        self.assertEqual(3, parsed)
        self.assertEqual(3, details["line_count"])
        self.assertEqual("IllegalStateException", evidence["java_exception"])
        self.assertFalse(evidence["ambiguous"])
        self.assertNotIn(SECRET, json.dumps(details) + json.dumps(evidence))

    def test_tabs_unicode_header_whitespace_unknown_banners_and_unprefixed_blank_lines_reject(self):
        valid = fatal()
        cases = (valid.replace(b".123456 ", b".123456\t", 1), valid.replace(b" 1742 ", b"\t1742 ", 1),
                 valid.replace(b"E AndroidRuntime", b"E\tAndroidRuntime", 1),
                 valid.replace(b".123456 ", ".123456\u00a0".encode(), 1),
                 b"--------- beginning of radio\n", b"--------- arbitrary separator\n", b"\n", b"\t\n")
        for raw in cases:
            with self.subTest(raw_bytes=len(raw)):
                details = {}
                reason, _, _, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
                self.assertEqual("invalid_header", reason)
                self.assertEqual("header", details["rejection_phase"])
                self.assertEqual(diagnostic.unknown_evidence(), evidence)

    def test_crlf_counts_and_late_rejection_clear_earlier_positive_facts(self):
        raw = (fatal() + line("java.lang.OutOfMemoryError: " + SECRET)).replace(b"\n", b"\r\n")
        details = {}
        reason, parsed, _, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
        self.assertIsNone(reason)
        self.assertEqual(2, parsed)
        self.assertEqual(2, details["crlf_lines"])
        self.assertEqual("OutOfMemoryError", evidence["java_exception"])
        raw += line("bad\rbody " + SECRET)
        reason, parsed, _, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
        self.assertEqual("invalid_header", reason)
        self.assertEqual(2, parsed)
        self.assertEqual(3, details["first_rejected_line"])
        self.assertEqual("control", details["rejection_phase"])
        self.assertEqual("epoch_header", details["first_rejected_shape"])
        self.assertEqual(diagnostic.unknown_evidence(), evidence)

    def test_fixed_structural_rejection_phase_and_shape_vocabulary(self):
        good = fatal()
        cases = ((good + line("bad " + SECRET).replace(b"bad", b"\xff", 1), "decode", "epoch_header", 2),
                 (b"--------- beginning of main", "terminator", "known_banner", 1),
                 (good.replace(b": ", b": \x00", 1), "control", "epoch_header", 1),
                 (line("x" * 4097), "line_length", "epoch_header", 1),
                 (good.replace(b".123456", b".1234567", 1), "header", "epoch_prefix", 1),
                 (good.replace(b"1742", b"2147483648", 1), "pid", "epoch_header", 1),
                 (b"10-13 02:00:00.123 1742 1742 E AndroidRuntime: " + SECRET.encode() + b"\n", "header", "calendar_prefix", 1),
                 (b"unprefixed " + SECRET.encode() + b"\n", "header", "other", 1))
        phases, shapes = set(), set()
        for raw, phase, shape, rejected in cases:
            with self.subTest(phase=phase, shape=shape):
                details = {}
                reason, _, _, evidence = diagnostic.parse_records(raw, PID, ZYGOTES, START_NS, END_NS, details)
                self.assertIsNotNone(reason)
                self.assertEqual(phase, details["rejection_phase"])
                self.assertEqual(shape, details["first_rejected_shape"])
                self.assertEqual(rejected, details["first_rejected_line"])
                self.assertEqual(len(raw.split(b"\n")[rejected - 1]), details["first_rejected_line_bytes"])
                self.assertEqual(max(map(len, raw.split(b"\n"))), details["max_line_bytes"])
                self.assertEqual(diagnostic.unknown_evidence(), evidence)
                self.assertNotIn(SECRET, json.dumps(details))
                phases.add(phase)
                shapes.add(shape)
        self.assertEqual(diagnostic.REJECTION_PHASES, phases)
        self.assertEqual(diagnostic.REJECTED_SHAPES, shapes)

    def test_non_utf8_controls_malformed_overlong_headers_and_partial_records_are_unknown(self):
        good = fatal()
        cases = ((good + b"\xff\n", "invalid_utf8"), (good.replace(b": ", b": \x00", 1), "invalid_header"),
                 (good.replace(b": ", b": \x1b", 1), "invalid_header"), (good.replace(b": ", b": \x7f", 1), "invalid_header"),
                 (good[:-1], "truncated_record"), (b" " * 1000 + good, "invalid_header"),
                 (good.replace(b"1742", b"2147483648", 1), "invalid_header"),
                 (good.replace(b"1700000001", b"170000000100", 1), "invalid_header"),
                 (good.replace(b".123456", b".1234567", 1), "invalid_header"),
                 (good.replace(b"1742", b"-1", 1), "invalid_header"),
                 (good + line("x" * 4097), "invalid_header"))
        for raw, expected in cases:
            with self.subTest(expected=expected, raw_bytes=len(raw)):
                reason, _, _, evidence = self.parse(raw)
                self.assertEqual(expected, reason)
                self.assertEqual(diagnostic.unknown_evidence(), evidence)

    def test_empty_complete_output_and_allowlisted_buffer_banners_mean_no_match_only(self):
        for raw in (b"", b"--------- beginning of main\n--------- beginning of system\n--------- beginning of crash\n"):
            reason, _, _, evidence = self.parse(raw)
            self.assertIsNone(reason)
            self.assertFalse(evidence["java_fatal_seen"])
            self.assertFalse(evidence["zygote_termination_seen"])


class CollectionChecks(unittest.TestCase):
    def test_start_metadata_is_only_two_fixed_bounded_numeric_reads(self):
        with mock.patch.object(diagnostic, "read_capped", side_effect=[capture(b"100 101\n"), capture(epoch(START_NS))]) as reader:
            actual = diagnostic.start_metadata("/official/adb", PID, time.monotonic() + 270)
        self.assertEqual(metadata(), actual)
        self.assertEqual([["/official/adb", "-s", "emulator-5554", "shell", "pidof", "zygote64", "zygote"],
                          ["/official/adb", "-s", "emulator-5554", "shell", "date", "+%s.%N"]], [call.args[0] for call in reader.call_args_list])
        self.assertTrue(all(call.args[1] == 2 and call.kwargs["stdout_limit"] == 128 for call in reader.call_args_list))

    def test_missing_invalid_numeric_metadata_skips_logs_and_never_exports_text(self):
        bad_zygotes = (b"", b"0\n", b"100 101 102\n", b"100 100\n", b"2147483648\n", SECRET.encode(), b"100;id\n")
        for raw in bad_zygotes:
            with self.subTest(raw_bytes=len(raw)), mock.patch.object(diagnostic, "read_capped", return_value=capture(raw)) as reader:
                actual = diagnostic.start_metadata("/official/adb", PID, time.monotonic() + 270)
                report = diagnostic.collect_failure("/official/adb", actual, "target", time.monotonic() + 270)
                self.assertEqual("unavailable", report["collection_status"])
                self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
                self.assertEqual(1, reader.call_count)
                self.assertNotIn(SECRET, json.dumps(report))
        for raw in (b"1700000000\n", b"1700000000.123\n", b"1700000000.123456789 extra\n", SECRET.encode(), b"\xff\n"):
            with self.subTest(raw_bytes=len(raw)), mock.patch.object(diagnostic, "read_capped", side_effect=[capture(b"100\n"), capture(raw)]) as reader:
                actual = diagnostic.start_metadata("/official/adb", PID, time.monotonic() + 270)
                report = diagnostic.collect_failure("/official/adb", actual, "target", time.monotonic() + 270)
                self.assertEqual("invalid_metadata", report["reason"])
                self.assertEqual(2, reader.call_count)
                self.assertNotIn(SECRET, json.dumps(report))

    def test_failure_collection_fixed_log_command_and_schema_under_four_kib(self):
        raw = fatal() + line("java.lang.OutOfMemoryError: " + SECRET) + zygote(9)
        with mock.patch.object(diagnostic, "read_capped", side_effect=[capture(epoch(END_NS)), capture(raw)]) as reader:
            report = diagnostic.collect_failure("/official/adb", metadata(), "test", time.monotonic() + 270)
        self.assertEqual("complete", report["collection_status"])
        self.assertEqual(30000, report["window_duration_ms"])
        self.assertEqual("test", report["role"])
        self.assertEqual("install_sequence", report["window_scope"])
        self.assertEqual("OutOfMemoryError", report["evidence"]["java_exception"])
        self.assertEqual(["/official/adb", "-s", "emulator-5554", "shell", "logcat", "-d", "-b", "main", "-b", "system", "-b", "crash", "-v",
                          "threadtime,epoch,usec,printable", "-s", "AndroidRuntime:E", "Zygote:I", "libc:F", "-t", "1700000000.123456789"], reader.call_args.args[0])
        self.assertEqual(5, reader.call_args.args[1])
        self.assertNotIn("--pid", reader.call_args.args[0])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "install-termination.json"
            diagnostic.write_report(path, report)
            self.assertLessEqual(path.stat().st_size, 4096)
            self.assertNotIn(SECRET, path.read_text())
            self.assertEqual(report, json.loads(path.read_text()))

    def test_reversed_too_long_malformed_or_unavailable_end_window_skips_logcat(self):
        for end, status in ((epoch(START_NS - 1), "invalid_window"), (epoch(START_NS + diagnostic.MAX_WINDOW_NS + 1), "invalid_window"),
                            (b"malformed " + SECRET.encode(), "unavailable")):
            with self.subTest(status=status), mock.patch.object(diagnostic, "read_capped", return_value=capture(end)) as reader:
                report = diagnostic.collect_failure("/official/adb", metadata(), "target", time.monotonic() + 270)
                self.assertEqual(status, report["collection_status"])
                self.assertEqual(1, reader.call_count)
                self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
                self.assertNotIn(SECRET, json.dumps(report))
        with mock.patch.object(diagnostic, "read_capped", return_value=capture(status="timeout", reason="timeout", exit_code=None)) as reader:
            report = diagnostic.collect_failure("/official/adb", metadata(), "target", time.monotonic() + 270)
            self.assertEqual("metadata_unavailable", report["reason"])
            self.assertEqual(1, reader.call_count)

    def test_incomplete_capture_and_invalid_format_null_all_evidence(self):
        for status, reason, exit_code, raw in (("timeout", "timeout", -9, fatal()), ("byte_limit", "output_limit", -9, fatal()),
                                               ("command_error", "stderr_present", 0, fatal()), ("command_error", "command_failed", 17, fatal()),
                                               ("complete", None, 0, fatal()[:-1]), ("complete", None, 0, b"\xff\n")):
            with self.subTest(status=status, reason=reason), mock.patch.object(diagnostic, "read_capped", side_effect=[capture(epoch(END_NS)), capture(raw, status, reason, exit_code)]):
                report = diagnostic.collect_failure("/official/adb", metadata(), "target", time.monotonic() + 270)
                self.assertNotEqual("complete", report["collection_status"])
                self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
                diagnostic.validate_report(report)

    def test_global_deadline_exhaustion_skips_metadata_and_logcat(self):
        with mock.patch.object(diagnostic, "read_capped") as reader:
            actual = diagnostic.start_metadata("/official/adb", PID, time.monotonic() - 1)
            report = diagnostic.collect_failure("/official/adb", metadata(), "target", time.monotonic() - 1)
            reader.assert_not_called()
        self.assertEqual("no_budget", actual["reason"])
        self.assertEqual("no_budget", report["reason"])
        self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])

    def test_all_added_command_budgets_preserve_existing_report_margin(self):
        total = installer.READINESS_SECONDS + 2 * installer.INSTALL_SECONDS + installer.SNAPSHOT_SECONDS + \
                3 * diagnostic.METADATA_SECONDS + diagnostic.LOG_SECONDS
        self.assertEqual(266, total)
        self.assertLessEqual(total, installer.STEP_SECONDS)
        self.assertGreaterEqual(300 - installer.STEP_SECONDS, 30)

    def test_absent_or_out_of_range_epoch_metadata_never_reads_logs(self):
        for value in (None, True, -1, 0, 10**20, SECRET):
            with self.subTest(value_type=type(value).__name__), mock.patch.object(diagnostic, "read_capped") as reader:
                actual = dict(metadata(), start_epoch_ns=value)
                report = diagnostic.collect_failure("/official/adb", actual, "target", time.monotonic() + 270)
                reader.assert_not_called()
                self.assertEqual("unavailable", report["collection_status"])
                self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
                self.assertNotIn(SECRET, json.dumps(report))

    def test_report_writer_rejects_extra_private_fields_and_unsafe_destinations(self):
        report = diagnostic.base_report("target", metadata())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "install-termination.json"
            invalid = dict(report, raw_log=SECRET)
            with self.assertRaises(ValueError):
                diagnostic.write_report(path, invalid)
            self.assertFalse(path.exists())
            invalid = dict(report, reason=SECRET)
            with self.assertRaises(ValueError):
                diagnostic.write_report(path, invalid)
            (root / "private").write_text(SECRET)
            path.symlink_to(root / "private")
            with self.assertRaises(ValueError):
                diagnostic.write_report(path, report)
            self.assertEqual(SECRET, (root / "private").read_text())

    def test_schema_two_structural_diagnostics_reject_extra_keys_bad_enums_and_ranges(self):
        for field, value in (("line_count", -1), ("max_line_bytes", 65537), ("banner_lines", True),
                             ("message_tab_lines", 1), ("crlf_lines", 1), ("first_rejected_line", 0),
                             ("first_rejected_line_bytes", -1), ("rejection_phase", SECRET),
                             ("first_rejected_shape", SECRET), ("raw_prefix", SECRET)):
            with self.subTest(field=field):
                report = diagnostic.base_report("target", metadata())
                report["format_diagnostics"][field] = value
                with self.assertRaises(ValueError):
                    diagnostic.validate_report(report)
        report = diagnostic.base_report("target", metadata())
        self.assertEqual(2, report["schema"])
        self.assertEqual(diagnostic.empty_format_diagnostics(), report["format_diagnostics"])
        diagnostic.validate_report(report)
        report["schema"] = 1
        with self.assertRaises(ValueError):
            diagnostic.validate_report(report)

    def test_structural_details_survive_invalid_format_without_retaining_log_content(self):
        raw = fatal() + line("java.lang.OutOfMemoryError: " + SECRET) + line("bad " + SECRET).replace(b"bad", b"bad\x00", 1)
        with mock.patch.object(diagnostic, "read_capped", side_effect=[capture(epoch(END_NS)), capture(raw)]):
            report = diagnostic.collect_failure("/official/adb", metadata(), "target", time.monotonic() + 270)
        self.assertEqual("invalid_format", report["collection_status"])
        self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
        self.assertEqual(2, report["parsed_records"])
        self.assertEqual(3, report["format_diagnostics"]["line_count"])
        self.assertEqual(3, report["format_diagnostics"]["first_rejected_line"])
        self.assertEqual("control", report["format_diagnostics"]["rejection_phase"])
        self.assertEqual("epoch_header", report["format_diagnostics"]["first_rejected_shape"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "install-termination.json"
            diagnostic.write_report(path, report)
            self.assertNotIn(SECRET, path.read_text())
            self.assertLessEqual(path.stat().st_size, 4096)

    def test_serialized_maximum_fixed_report_remains_within_four_kib(self):
        report = diagnostic.base_report("test", {"system_server_pid": diagnostic.MAX_PID,
                                                "zygote_pids": [diagnostic.MAX_PID - 1, diagnostic.MAX_PID - 2]})
        report.update(collection_status="invalid_format", reason="invalid_header", window_duration_ms=210000,
                      exit_code=diagnostic.MAX_PID, elapsed_ms=300000, stdout_bytes_seen=65536, stderr_bytes_seen=1024,
                      parsed_records=65536, ignored_records=65536)
        report["format_diagnostics"] = {**{name: 65536 for name in diagnostic.FORMAT_COUNTS},
                                        "first_rejected_line": 65536, "first_rejected_line_bytes": 65536,
                                        "rejection_phase": "line_length", "first_rejected_shape": "calendar_prefix"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "install-termination.json"
            diagnostic.write_report(path, report)
            self.assertLessEqual(path.stat().st_size, 4096)
            self.assertEqual(report, json.loads(path.read_text()))

    def test_report_sibling_hardlink_directory_fifo_and_parent_symlink_are_rejected(self):
        report = diagnostic.base_report("target", metadata())
        for kind in ("hardlink", "directory", "fifo", "parent_symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                source = root / "private"
                source.write_text(SECRET)
                path = root / "install-termination.json"
                if kind == "hardlink":
                    path.hardlink_to(source)
                elif kind == "directory":
                    path.mkdir()
                elif kind == "fifo":
                    import os
                    os.mkfifo(path)
                else:
                    (root / "alias").symlink_to(root, target_is_directory=True)
                    path = root / "alias/install-termination.json"
                with self.assertRaises(ValueError):
                    diagnostic.write_report(path, report)
                self.assertEqual(SECRET, source.read_text())


class ReaderChecks(unittest.TestCase):
    def run_local(self, code, seconds=1, deadline_seconds=None):
        processes = []
        original = subprocess.Popen

        def spawn(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process

        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), mock.patch.object(diagnostic.subprocess, "Popen", side_effect=spawn):
            collection, raw = diagnostic.read_capped([sys.executable, "-c", code], seconds,
                                                      time.monotonic() + (seconds if deadline_seconds is None else deadline_seconds))
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.assertTrue(all(process.stdout.closed and process.stderr.closed for process in processes))
        self.assertNotIn(SECRET, stdout.getvalue() + stderr.getvalue() + json.dumps(collection))
        self.assertLessEqual(len(raw), 65536)
        self.assertLessEqual(collection["stdout_bytes_seen"], 65536)
        self.assertLessEqual(collection["stderr_bytes_seen"], 1024)
        return collection, raw

    def test_real_stdout_flood_stops_at_cap_and_reaps_without_echo(self):
        collection, raw = self.run_local("import os,time; os.write(1, (b'" + SECRET + "'*100000)); time.sleep(10)")
        self.assertEqual("byte_limit", collection["collection_status"])
        self.assertEqual("output_limit", collection["reason"])
        self.assertEqual(65536, len(raw))

    def test_real_stderr_flood_and_both_pipes_are_bounded_and_reaped(self):
        for code in ("import os,time; os.write(2, b'" + SECRET + "'*100000); time.sleep(10)",
                     "import os,time; os.write(1,b'x'*4096); os.write(2,b'" + SECRET + "'*100000); time.sleep(10)"):
            with self.subTest(case=len(code)):
                collection, _ = self.run_local(code)
                self.assertEqual("byte_limit", collection["collection_status"])
                self.assertEqual(1024, collection["stderr_bytes_seen"])

    def test_real_timeout_kills_reaps_and_includes_cleanup_in_deadline(self):
        started = time.monotonic()
        collection, _ = self.run_local("import os,time; os.write(1,b'partial " + SECRET + "'); time.sleep(10)", seconds=0.4)
        self.assertEqual("timeout", collection["collection_status"])
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertLess(collection["elapsed_ms"], 800)

    def test_real_nonzero_or_any_stderr_warning_makes_capture_unknown(self):
        collection, _ = self.run_local("import sys; print('" + SECRET + "'); sys.exit(17)")
        self.assertEqual("command_error", collection["collection_status"])
        self.assertEqual("command_failed", collection["reason"])
        self.assertEqual(17, collection["exit_code"])
        collection, _ = self.run_local("import os; os.write(2,b'warning " + SECRET + "')")
        self.assertEqual("command_error", collection["collection_status"])
        self.assertEqual("stderr_present", collection["reason"])

    def test_real_log_reader_clips_five_second_budget_to_remaining_global_deadline(self):
        started = time.monotonic()
        collection, _ = self.run_local("import time; time.sleep(10)", seconds=5, deadline_seconds=0.4)
        self.assertEqual("timeout", collection["collection_status"])
        self.assertLess(time.monotonic() - started, 0.8)

    def test_no_budget_never_spawns_process(self):
        with mock.patch.object(diagnostic.subprocess, "Popen") as spawn:
            collection, raw = diagnostic.read_capped(["unused"], 5, time.monotonic() - 1)
        spawn.assert_not_called()
        self.assertEqual("no_budget", collection["reason"])
        self.assertEqual(b"", raw)


class HookChecks(unittest.TestCase):
    def invoke(self, folder, failure="target", bad_metadata=False, diagnostic_error=False, write_error=False):
        root = Path(folder)
        apks = root / "apks"
        apks.mkdir()
        for name in ("target.apk", "test.apk", "SHA256SUMS"):
            (apks / name).write_bytes(b"caller verified bytes")
        if failure == "inputs":
            (apks / "unexpected.apk").write_bytes(b"unexpected")
        output = root / "reports/install-diagnostics.json"
        clock = [0.0]
        events = []

        def run(arguments, **kwargs):
            events.append(("ordinary", arguments))
            clock[0] += 0.1
            if arguments[3] == "install":
                role = Path(arguments[-1]).stem
                return subprocess.CompletedProcess(arguments, 23 if role == failure else 0,
                                                   b"Failure\n" if role == failure else b"Success\n", b"Broken pipe (32)\n" if role == failure else b"")
            command = arguments[4:]
            value = b"1\n" if command[0] == "getprop" else b"1742\n" if command[0] == "pidof" else b"package:/system/framework/framework-res.apk\n"
            if failure == "readiness" and command[0] == "getprop":
                value = b"0\n"
            if failure == "post_install_health" and command[0] == "pidof" and any(args[3] == "install" for _, args in events):
                value = b""
            return subprocess.CompletedProcess(arguments, 0, value, b"")

        dates = [epoch(START_NS), epoch(END_NS)]

        def read(arguments, seconds, deadline, **kwargs):
            events.append(("diagnostic", arguments))
            clock[0] += 0.05
            if arguments[4] == "pidof":
                return capture(SECRET.encode() if bad_metadata else b"100 101\n")
            if arguments[4] == "date":
                return capture(dates.pop(0))
            return capture(fatal() + line("java.lang.IllegalStateException: " + SECRET) + zygote())

        argv = ["installer", "--adb", "/official/adb", "--apks", str(apks), "--report", str(output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        stack = contextlib.ExitStack()
        with stack:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(installer.subprocess, "run", side_effect=run))
            stack.enter_context(mock.patch.object(diagnostic, "read_capped", side_effect=read))
            stack.enter_context(mock.patch.object(installer.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(mock.patch.object(installer.time, "sleep", side_effect=lambda value: clock.__setitem__(0, clock[0] + value)))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            if diagnostic_error:
                stack.enter_context(mock.patch.object(diagnostic, "collect_failure", side_effect=RuntimeError(SECRET)))
            if failure == "deadline":
                stack.enter_context(mock.patch.object(installer, "install", return_value={"status": "deadline", "passed": False,
                                                                                         "role": "target", "stage": "install"}))
            if write_error:
                stack.enter_context(mock.patch.object(diagnostic, "write_report", side_effect=OSError(SECRET)))
            code = installer.main()
        primary = json.loads(output.read_text())
        new_path = output.with_name("install-termination.json")
        report = json.loads(new_path.read_text()) if new_path.exists() else None
        self.assertNotIn(SECRET, stdout.getvalue() + stderr.getvalue() + json.dumps(primary) + json.dumps(report))
        self.assertLessEqual(output.stat().st_size, 4096)
        if new_path.exists():
            self.assertLessEqual(new_path.stat().st_size, 4096)
        return code, primary, report, events

    def test_target_and_test_failures_collect_only_after_existing_snapshot_preserving_original(self):
        for role in ("target", "test"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder:
                code, primary, report, events = self.invoke(folder, failure=role)
                self.assertEqual(1, code)
                self.assertEqual(role + "_install", primary["stage"])
                self.assertEqual(role + "_install_failed", primary["error"])
                self.assertEqual(23, primary["installs"][-1]["exit_code"])
                self.assertEqual(role, report["role"])
                self.assertEqual("complete", report["collection_status"])
                self.assertEqual("IllegalStateException", report["evidence"]["java_exception"])
                self.assertEqual(1 if role == "target" else 2, sum(args[3] == "install" for _, args in events))
                install_index = next(index for index, (_, args) in enumerate(events) if args[3] == "install")
                before = [args[4] for kind, args in events[:install_index] if kind == "diagnostic"]
                self.assertEqual(["pidof", "date"], before)
                log_index = next(index for index, (_, args) in enumerate(events) if args[4] == "logcat")
                self.assertEqual("date", events[log_index - 1][1][4])
                self.assertEqual("cmd", events[log_index - 2][1][4])
                self.assertEqual("ordinary", events[log_index - 2][0])

    def test_success_readiness_failure_and_post_success_health_failure_never_read_logs(self):
        for failure, expected in ((None, 0), ("inputs", 1), ("readiness", 1), ("post_install_health", 1), ("deadline", 1)):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                code, _, report, events = self.invoke(folder, failure=failure)
                self.assertEqual(expected, code)
                self.assertIsNone(report)
                self.assertFalse(any(args[4] == "logcat" for _, args in events))
                self.assertEqual(0 if failure in {"readiness", "inputs"} else 2, sum(kind == "diagnostic" for kind, _ in events))

    def test_unavailable_metadata_does_not_block_successful_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            code, primary, report, events = self.invoke(folder, failure=None, bad_metadata=True)
        self.assertEqual(0, code)
        self.assertEqual("passed", primary["status"])
        self.assertIsNone(report)
        self.assertEqual(2, sum(args[3] == "install" for _, args in events))
        self.assertEqual(1, sum(kind == "diagnostic" for kind, _ in events))

    def test_unavailable_metadata_skips_logcat_without_changing_failed_install(self):
        with tempfile.TemporaryDirectory() as folder:
            code, primary, report, events = self.invoke(folder, bad_metadata=True)
        self.assertEqual(1, code)
        self.assertEqual("target_install_failed", primary["error"])
        self.assertEqual("unavailable", report["collection_status"])
        self.assertEqual("invalid_metadata", report["reason"])
        self.assertEqual(1, sum(kind == "diagnostic" for kind, _ in events))
        self.assertFalse(any(args[4] == "logcat" for _, args in events))

    def test_diagnostic_exception_or_report_write_error_never_replaces_original_failure(self):
        for diagnostic_error, write_error in ((True, False), (False, True)):
            with self.subTest(diagnostic_error=diagnostic_error, write_error=write_error), tempfile.TemporaryDirectory() as folder:
                code, primary, report, _ = self.invoke(folder, diagnostic_error=diagnostic_error, write_error=write_error)
                self.assertEqual(1, code)
                self.assertEqual("target_install", primary["stage"])
                self.assertEqual("target_install_failed", primary["error"])
                self.assertEqual(23, primary["installs"][0]["exit_code"])
                if diagnostic_error:
                    self.assertEqual("io_error", report["reason"])
                    self.assertEqual(diagnostic.unknown_evidence(), report["evidence"])
                else:
                    self.assertIsNone(report)


if __name__ == "__main__":
    unittest.main()
