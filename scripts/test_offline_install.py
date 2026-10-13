"""Mocked host-only install/readiness guards; no emulator, SDK, ACL or network operations."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import install_offline_apks as helper

PACKAGE_PATH = b"package:/system/framework/framework-res.apk\n"
BROKEN_PIPE = b"cmd: Failure calling service package: Broken pipe (32)\n"


def result(stdout=b"", returncode=0, stderr=b""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def ready(pid=432, boot=b"1\n", package=PACKAGE_PATH, stderr=b""):
    return [result(boot, stderr=stderr), result(f"{pid}\n".encode(), stderr=stderr),
            result(package, stderr=stderr)]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class InstallChecks(unittest.TestCase):
    def invoke(self, folder, sequence=None, run_function=None, sha=True, apks=None, report_path=None, transport=None):
        root = Path(folder)
        directory = root / "apks"
        directory.mkdir(exist_ok=True)
        for role in ("target", "test"):
            path = directory / f"{role}.apk"
            if not path.exists() and not path.is_symlink():
                path.write_bytes(("synthetic " + role).encode())
        if sha and not (directory / "SHA256SUMS").exists():
            (directory / "SHA256SUMS").write_text("caller-owned verified hashes\n")
        output = report_path or root / "reports/install-diagnostics.json"
        argv = ["install_offline_apks.py", "--apks", str(apks or directory),
                "--adb", "/official-sdk/platform-tools/adb", "--serial", helper.SERIAL,
                "--report", str(output)]
        if transport is not None:
            argv.extend(["--transport", transport])
        clock = FakeClock()
        calls = []
        pending = iter(sequence or [])

        def run(arguments, **kwargs):
            calls.append((arguments, kwargs))
            if run_function is not None:
                value = run_function(arguments, kwargs, clock)
            else:
                value = next(pending)
            if isinstance(value, subprocess.TimeoutExpired):
                clock.now += kwargs["timeout"]
            if isinstance(value, BaseException):
                raise value
            return value

        with mock.patch.object(sys, "argv", argv), mock.patch.object(helper.subprocess, "run", side_effect=run), \
                mock.patch.object(helper.termination, "start_metadata", return_value=helper.termination.unavailable_metadata(432)), \
                mock.patch.object(helper.time, "monotonic", side_effect=clock.monotonic), \
                mock.patch.object(helper.time, "sleep", side_effect=clock.sleep), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = helper.main()
        report = None
        if output.exists() and output.name == "install-diagnostics.json":
            self.assertLessEqual(output.stat().st_size, helper.MAX_REPORT_BYTES)
            report = json.loads(output.read_text())
        return code, report, calls, clock

    def install_calls(self, calls):
        return [arguments for arguments, _ in calls if arguments[3] == "install"]

    def test_cold_start_then_two_same_pid_samples_and_exact_once_installs(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence = ready(boot=b"0\n") + ready() + ready() + [
                result(b"Performing Streamed Install\nSuccess\n"), result(b"Success\r\n")] + ready()
            code, report, calls, clock = self.invoke(folder, sequence)
            self.assertEqual(0, code)
            self.assertEqual("default", report["requested_transport"])
            self.assertEqual("passed", report["status"])
            self.assertEqual("post_success", report["snapshot"]["stage"])
            self.assertEqual(3, report["readiness"]["samples"])
            self.assertEqual(1, report["readiness"]["failed_samples"])
            self.assertEqual(432, report["readiness"]["stable_pid"])
            self.assertEqual([2000, 4000], report["readiness"]["stable_sample_elapsed_ms"])
            self.assertEqual(["target.apk", "test.apk"], [Path(call[-1]).name for call in self.install_calls(calls)])
            self.assertEqual(4.0, clock.now)
            for arguments, kwargs in calls:
                self.assertEqual(["-s", "emulator-5554"], arguments[1:3])
                self.assertTrue(kwargs["capture_output"])
                self.assertFalse(kwargs["check"])
                self.assertNotIn("shell", kwargs)
                self.assertNotIn("text", kwargs)
                if arguments[3] == "shell":
                    self.assertIn(tuple(arguments[4:]), [command for _, command in helper.PROBES])
                    self.assertLessEqual(kwargs["timeout"], 5)
                else:
                    self.assertEqual(["install", "-t"], arguments[3:5])
                    self.assertEqual(90, kwargs["timeout"])

    def test_explicit_default_preserves_baseline_install_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() +
                                                [result(b"Success\n"), result(b"Success\n")] + ready(),
                                                transport="default")
            expected = [["/official-sdk/platform-tools/adb", "-s", helper.SERIAL, "install", "-t",
                         str(Path(folder) / "apks" / f"{role}.apk")] for role in ("target", "test")]
            self.assertEqual(expected, self.install_calls(calls))
        self.assertEqual(0, code)
        self.assertEqual("default", report["requested_transport"])

    def test_no_streaming_installs_verified_target_then_test_once_with_exact_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, clock = self.invoke(folder, ready() + ready() +
                                                    [result(b"Performing Push Install\nSuccess\n"), result(b"Success\n")] + ready(),
                                                    transport="no-streaming")
            expected = [["/official-sdk/platform-tools/adb", "-s", helper.SERIAL, "install", "--no-streaming", "-t",
                         str(Path(folder) / "apks" / f"{role}.apk")] for role in ("target", "test")]
            self.assertEqual(expected, self.install_calls(calls))
            self.assertEqual({"target.apk", "test.apk", "SHA256SUMS"}, {path.name for path in (Path(folder) / "apks").iterdir()})
            self.assertEqual(b"synthetic target", (Path(folder) / "apks/target.apk").read_bytes())
            self.assertEqual(b"synthetic test", (Path(folder) / "apks/test.apk").read_bytes())
        self.assertEqual(0, code)
        self.assertEqual("passed", report["status"])
        self.assertEqual("no-streaming", report["requested_transport"])
        self.assertEqual("post_success", report["snapshot"]["stage"])
        self.assertEqual(2, clock.now)
        for arguments, kwargs in calls:
            self.assertEqual(["-s", helper.SERIAL], arguments[1:3])
            if arguments[3] == "install":
                self.assertEqual(90, kwargs["timeout"])
            else:
                self.assertIn(tuple(arguments[4:]), [command for _, command in helper.PROBES])
                self.assertLessEqual(kwargs["timeout"], 5)

    def test_no_streaming_target_failures_never_fallback_retry_or_install_test(self):
        failures = (result(b"Failure\n", 23, BROKEN_PIPE), result(b"", 0),
                    result(b" Success\n", 0), result(b"Success\n", 1), result(b"Success\nSuccess\n", 0),
                    subprocess.TimeoutExpired("not retained", 90, output=b"Success\n", stderr=BROKEN_PIPE))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as folder:
                code, report, calls, _ = self.invoke(folder, ready() + ready() + [failure] + ready(package=b""),
                                                     transport="no-streaming")
            self.assertEqual(1, code)
            self.assertEqual("no-streaming", report["requested_transport"])
            self.assertEqual("target_install", report["stage"])
            self.assertEqual("target_install_failed", report["error"])
            self.assertFalse(report["snapshot"]["ready"])
            installs = self.install_calls(calls)
            self.assertEqual(1, len(installs))
            self.assertEqual(["install", "--no-streaming", "-t"], installs[0][3:6])
            self.assertEqual("target.apk", Path(installs[0][-1]).name)
            record = report["installs"][0]
            self.assertFalse(record["passed"])
            self.assertEqual(90_000, record["timeout_ms"])
            if isinstance(failure, subprocess.TimeoutExpired):
                self.assertEqual("timeout", record["status"])
                self.assertEqual(90_000, record["elapsed_ms"])
            else:
                self.assertEqual(failure.returncode, record["exit_code"])

    def test_no_streaming_test_failure_retains_original_exit_without_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() +
                                                [result(b"Success\n"), result(b"Failure\n", 23, BROKEN_PIPE)] + ready(package=b""),
                                                transport="no-streaming")
        self.assertEqual(1, code)
        self.assertEqual("no-streaming", report["requested_transport"])
        self.assertEqual("test_install", report["stage"])
        self.assertEqual("test_install_failed", report["error"])
        self.assertEqual(23, report["installs"][1]["exit_code"])
        self.assertIn("Broken pipe (32)", report["installs"][1]["stderr_preview"])
        self.assertEqual([True, False], [record["passed"] for record in report["installs"]])
        self.assertFalse(report["snapshot"]["ready"])
        self.assertEqual(["target.apk", "test.apk"], [Path(call[-1]).name for call in self.install_calls(calls)])
        self.assertTrue(all(call[3:6] == ["install", "--no-streaming", "-t"] for call in self.install_calls(calls)))

    def test_no_streaming_both_successes_still_require_post_install_health(self):
        timeout = subprocess.TimeoutExpired("not retained", 5, output=b"", stderr=b"")
        for snapshot in (ready(package=b""), [timeout, timeout, timeout]):
            with self.subTest(snapshot=type(snapshot[0]).__name__), tempfile.TemporaryDirectory() as folder:
                code, report, calls, _ = self.invoke(folder, ready() + ready() +
                                                     [result(b"Success\n"), result(b"Success\n")] + snapshot,
                                                     transport="no-streaming")
            self.assertEqual(1, code)
            self.assertEqual("no-streaming", report["requested_transport"])
            self.assertEqual("post_install_health", report["stage"])
            self.assertEqual("post_install_health_failed", report["error"])
            self.assertEqual([True, True], [record["passed"] for record in report["installs"]])
            self.assertEqual(2, len(self.install_calls(calls)))

    def test_no_streaming_diagnostic_errors_do_not_replace_original_failure(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(helper.termination, "collect_failure", side_effect=RuntimeError("not retained")) as collector, \
                mock.patch.object(helper.termination, "write_report", side_effect=OSError("not retained")) as writer:
            code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Failure\n", 23, BROKEN_PIPE)] + ready(),
                                                transport="no-streaming")
            collector.assert_called_once_with(Path("/official-sdk/platform-tools/adb"),
                                              helper.termination.unavailable_metadata(432), "target", 270)
            writer.assert_called_once()
        self.assertEqual(1, code)
        self.assertEqual("target_install_failed", report["error"])
        self.assertEqual(23, report["installs"][0]["exit_code"])
        self.assertEqual(1, len(self.install_calls(calls)))
        self.assertEqual("post_failure", report["snapshot"]["stage"])
        self.assertNotIn("not retained", json.dumps(report))

    def test_requested_transport_remains_recorded_on_readiness_or_input_failure(self):
        for stage in ("readiness", "inputs"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                if stage == "inputs":
                    directory = Path(folder) / "apks"
                    directory.mkdir()
                    (directory / "unexpected.apk").write_bytes(b"untrusted")
                def run(arguments, kwargs, clock):
                    return dict(boot_completed=result(b"0\n"), system_server=result(b"432\n"),
                                package_path=result(PACKAGE_PATH))[self.probe_name(arguments)]
                code, report, calls, _ = self.invoke(folder, run_function=run, transport="no-streaming")
            self.assertEqual(1, code)
            self.assertEqual(stage, report["stage"])
            self.assertEqual("no-streaming", report["requested_transport"])
            self.assertEqual([], self.install_calls(calls))

    def test_both_transport_choices_clip_install_to_unchanged_global_deadline(self):
        self.assertEqual(90, helper.INSTALL_SECONDS)
        self.assertEqual(270, helper.STEP_SECONDS)
        for transport in helper.TRANSPORTS:
            with self.subTest(transport=transport):
                clock = FakeClock()
                clock.now = 269
                def run(arguments, **kwargs):
                    self.assertEqual(1, kwargs["timeout"])
                    clock.now += kwargs["timeout"]
                    raise subprocess.TimeoutExpired("not retained", kwargs["timeout"], output=b"Success\n")
                with mock.patch.object(helper.subprocess, "run", side_effect=run) as commands, \
                        mock.patch.object(helper.time, "monotonic", side_effect=clock.monotonic):
                    record = helper.install("/official-sdk/platform-tools/adb", Path("/verified/target.apk"), "target", 270, transport)
                    self.assertEqual("timeout", record["status"])
                    self.assertEqual(1000, record["timeout_ms"])
                    self.assertFalse(record["passed"])
                    expired = helper.install("/official-sdk/platform-tools/adb", Path("/verified/test.apk"), "test", 270, transport)
                    self.assertEqual("deadline", expired["status"])
                    self.assertEqual(0, expired["timeout_ms"])
                    self.assertEqual(1, commands.call_count)
                    self.assertEqual(["install", "-t"] if transport == "default" else ["install", "--no-streaming", "-t"],
                                     commands.call_args.args[0][3:-1])
                self.assertEqual(30, 300 - clock.now)

    def test_transport_cli_rejects_unknown_values_before_any_adb_or_report(self):
        for transport in ("streaming", "auto", "--streaming", "no-streaming;id", "NO-STREAMING"):
            argv = ["installer", "--apks", "unused", "--adb", "unused", "--report", "unused",
                    "--transport=" + transport]
            with self.subTest(transport=transport), mock.patch.object(sys, "argv", argv), \
                    contextlib.redirect_stderr(io.StringIO()), mock.patch.object(helper.subprocess, "run") as run, \
                    mock.patch.object(helper, "prepare_report_path") as report, self.assertRaises(SystemExit) as error:
                helper.main()
            self.assertEqual(2, error.exception.code)
            run.assert_not_called()
            report.assert_not_called()
        with mock.patch.object(helper.subprocess, "run") as run, self.assertRaisesRegex(helper.InstallError, "^invalid_requested_transport$"):
            helper.install("unused", Path("unused"), "target", 270, "unknown")
        run.assert_not_called()

    def test_readiness_deadline_is_monotonic_and_no_install_occurs(self):
        def run(arguments, kwargs, clock):
            return dict(boot_completed=result(b"0\n"), system_server=result(b"432\n"),
                        package_path=result(PACKAGE_PATH))[self.probe_name(arguments)]
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, clock = self.invoke(folder, run_function=run)
        self.assertEqual(1, code)
        self.assertEqual("readiness", report["stage"])
        self.assertEqual("readiness_deadline", report["error"])
        self.assertEqual(60_000, report["readiness"]["elapsed_ms"])
        self.assertEqual(30, report["readiness"]["samples"])
        self.assertEqual(30, report["readiness"]["probe_counts"]["boot_completed"]["not_ready"])
        self.assertEqual([], self.install_calls(calls))
        self.assertEqual(60, clock.now)
        self.assertEqual("post_failure", report["snapshot"]["stage"])

    def probe_name(self, arguments):
        return next(name for name, command in helper.PROBES if tuple(arguments[4:]) == command)

    def test_pid_switch_resets_stability_and_requires_two_new_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready(123) + ready(456) + ready(456) +
                                                [result(b"Success\n"), result(b"Success\n")] + ready(456))
        self.assertEqual(0, code)
        self.assertEqual(3, report["readiness"]["samples"])
        self.assertEqual(1, report["readiness"]["pid_changes"])
        self.assertEqual(456, report["readiness"]["stable_pid"])
        self.assertEqual([2000, 4000], report["readiness"]["stable_sample_elapsed_ms"])
        self.assertEqual(2, len(self.install_calls(calls)))

    def test_failed_sample_resets_same_pid_consecutive_successes(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, _, _ = self.invoke(folder, ready() + ready(boot=b"0\n") + ready() + ready() +
                                             [result(b"Success\n"), result(b"Success\n")] + ready())
        self.assertEqual(0, code)
        self.assertEqual(4, report["readiness"]["samples"])
        self.assertEqual([4000, 6000], report["readiness"]["stable_sample_elapsed_ms"])

    def test_missing_malformed_multiple_pid_and_package_outputs_are_unknown(self):
        bad = {"boot_completed": (b"", b"true\n", b"1\n1\n", b"1\x00\n", b"\xff\n"),
               "system_server": (b"", b"0\n", b"-1\n", b"432 433\n", b"432\n433\n", b"2147483648\n"),
               "package_path": (b"", b"package:\n", b"package:relative.apk\n", b"package:/a/../b.apk\n",
                                b"package:/a//b.apk\n", b"package:/a;id.apk\n", b"package:/a.apk\x00\n",
                                b"package:/a.apk\n\n", b"package:/a.apk\rpackage:/b.apk",
                                b"package:/a.apk\vpackage:/b.apk", b"x" * 4097)}
        for name, values in bad.items():
            for value in values:
                with self.subTest(probe=name, output=value[:50]), tempfile.TemporaryDirectory() as folder:
                    def run(arguments, kwargs, clock):
                        actual = self.probe_name(arguments)
                        if actual == name:
                            return result(value)
                        return dict(boot_completed=result(b"1\n"), system_server=result(b"432\n"),
                                    package_path=result(PACKAGE_PATH))[actual]
                    code, report, calls, _ = self.invoke(folder, run_function=run)
                    self.assertEqual(1, code)
                    self.assertEqual([], self.install_calls(calls))
                    self.assertEqual("unknown", report["readiness"]["last_sample"]["probes"][name]["parse_status"])

    def test_nonzero_probes_remain_unknown_even_when_stdout_looks_ready(self):
        def run(arguments, kwargs, clock):
            name = self.probe_name(arguments)
            stdout = {"boot_completed": b"1\n", "system_server": b"432\n", "package_path": PACKAGE_PATH}[name]
            return result(stdout, 1, b"read-only probe failed\n")
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, run_function=run)
        self.assertEqual(1, code)
        self.assertEqual([], self.install_calls(calls))
        for record in report["readiness"]["last_sample"]["probes"].values():
            self.assertEqual(1, record["exit_code"])
            self.assertEqual("unknown", record["parse_status"])

    def test_probe_timeouts_clip_to_deadline_and_partial_output_never_passes(self):
        def run(arguments, kwargs, clock):
            return subprocess.TimeoutExpired("not retained", kwargs["timeout"], output=b"1\n", stderr=b"partial\n")
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, clock = self.invoke(folder, run_function=run)
        self.assertEqual(1, code)
        self.assertEqual([], self.install_calls(calls))
        self.assertEqual(60_000, report["readiness"]["elapsed_ms"])
        self.assertEqual(75, clock.now)
        self.assertTrue(any(kwargs["timeout"] < 5 for _, kwargs in calls))
        self.assertTrue(all(0 < kwargs["timeout"] <= 5 for _, kwargs in calls))
        self.assertEqual("timeout", report["snapshot"]["probes"]["boot_completed"]["status"])
        self.assertNotIn("not retained", json.dumps(report))

    def test_target_failure_blocks_test_install_and_never_replays(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Failure\n", 1)] + ready())
        self.assertEqual(1, code)
        self.assertEqual("target_install", report["stage"])
        self.assertEqual(["target.apk"], [Path(call[-1]).name for call in self.install_calls(calls)])
        self.assertEqual(1, report["installs"][0]["exit_code"])

    def test_test_failure_blocks_return_zero_and_no_role_is_replayed(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Success\n"),
                                                result(b"Failure [INSTALL_FAILED_TEST_ONLY]\n", 1)] + ready())
        self.assertEqual(1, code)
        self.assertEqual("test_install", report["stage"])
        self.assertEqual([True, False], [record["passed"] for record in report["installs"]])
        self.assertEqual(2, len(self.install_calls(calls)))

    def test_zero_exit_requires_exact_single_success_line(self):
        for stdout, exit_code in ((b"", 0), (b"Not Success\n", 0), (b" Success\n", 0),
                                  (b"Success trailing\n", 0), (b"Success\nSuccess\n", 0),
                                  (b"Success\n", 1), (b"Success\n" + b"x" * 4097, 0)):
            with self.subTest(stdout=stdout[:30], exit_code=exit_code), tempfile.TemporaryDirectory() as folder:
                code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(stdout, exit_code)] + ready())
                self.assertEqual(1, code)
                self.assertEqual(1, len(self.install_calls(calls)))
                self.assertFalse(report["installs"][0]["passed"])

    def test_broken_pipe_original_exit_and_stage_survive_failed_postmortem(self):
        timeout = subprocess.TimeoutExpired("not retained", 5, output=b"", stderr=b"snapshot timed out\n")
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Performing Streamed Install\n", 1, BROKEN_PIPE)] +
                                                [timeout, OSError("not retained"), result(b"", 1)])
        self.assertEqual(1, code)
        self.assertEqual("target_install", report["stage"])
        self.assertEqual("target_install_failed", report["error"])
        self.assertEqual(1, report["installs"][0]["exit_code"])
        self.assertIn("Broken pipe (32)", report["installs"][0]["stderr_preview"])
        self.assertEqual("post_failure", report["snapshot"]["stage"])
        self.assertFalse(report["snapshot"]["ready"])
        self.assertEqual(1, len(self.install_calls(calls)))
        self.assertNotIn("not retained", json.dumps(report))

    def test_install_timeout_with_partial_success_blocks_second_install(self):
        timeout = subprocess.TimeoutExpired("not retained", 90, output=b"Success\n", stderr=BROKEN_PIPE)
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, clock = self.invoke(folder, ready() + ready() + [timeout] + ready())
        self.assertEqual(1, code)
        self.assertEqual("timeout", report["installs"][0]["status"])
        self.assertEqual(90_000, report["installs"][0]["elapsed_ms"])
        self.assertEqual(1, report["installs"][0]["success_lines"])
        self.assertFalse(report["installs"][0]["passed"])
        self.assertEqual(1, len(self.install_calls(calls)))
        self.assertEqual(92, clock.now)

    def test_timeout_post_install_health_blocks_success_after_both_installs(self):
        timeout = subprocess.TimeoutExpired("not retained", 5, output=b"", stderr=b"")
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Success\n"), result(b"Success\n")] +
                                                [timeout, timeout, timeout])
        self.assertEqual(1, code)
        self.assertEqual("blocked", report["status"])
        self.assertEqual("post_install_health", report["stage"])
        self.assertEqual("post_install_health_failed", report["error"])
        self.assertTrue(all(record["passed"] for record in report["installs"]))
        self.assertFalse(report["snapshot"]["ready"])
        self.assertEqual("post_success", report["snapshot"]["stage"])
        self.assertEqual(2, len(self.install_calls(calls)))

    def test_malformed_unknown_or_not_ready_post_install_health_blocks_success(self):
        bad_snapshots = (ready(boot=b"0\n"), ready(package=b""), ready(package=b"package:malformed\n"),
                         [result(b"1\n"), result(b"432 433\n"), result(PACKAGE_PATH)],
                         [OSError("not retained"), result(b"432\n"), result(PACKAGE_PATH)],
                         [result(b"1\n", 1), result(b"432\n"), result(PACKAGE_PATH)])
        for snapshot in bad_snapshots:
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as folder:
                code, report, calls, _ = self.invoke(folder, ready() + ready() +
                                                     [result(b"Success\n"), result(b"Success\n")] + list(snapshot))
                self.assertEqual(1, code)
                self.assertEqual("post_install_health", report["stage"])
                self.assertEqual("post_install_health_failed", report["error"])
                self.assertFalse(report["snapshot"]["ready"])
                self.assertEqual([True, True], [record["passed"] for record in report["installs"]])
                self.assertEqual(2, len(self.install_calls(calls)))
                self.assertNotIn("not retained", json.dumps(report))

    def test_original_test_install_failure_is_not_replaced_by_health_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report, calls, _ = self.invoke(folder, ready() + ready() +
                                                [result(b"Success\n"), result(b"Failure\n", 23)] + ready(package=b""))
        self.assertEqual(1, code)
        self.assertEqual("test_install", report["stage"])
        self.assertEqual("test_install_failed", report["error"])
        self.assertEqual(23, report["installs"][1]["exit_code"])
        self.assertEqual("post_failure", report["snapshot"]["stage"])
        self.assertFalse(report["snapshot"]["ready"])
        self.assertEqual(2, len(self.install_calls(calls)))

    def test_global_command_deadline_reserves_thirty_seconds_for_report(self):
        self.assertEqual(270, helper.STEP_SECONDS)
        self.assertGreaterEqual(5 * 60 - helper.STEP_SECONDS, 30)
        self.assertLessEqual(helper.READINESS_SECONDS + 2 * helper.INSTALL_SECONDS + helper.SNAPSHOT_SECONDS,
                             helper.STEP_SECONDS)
        clock = FakeClock()
        clock.now = 269

        def run(arguments, **kwargs):
            self.assertEqual(1, kwargs["timeout"])
            clock.now += kwargs["timeout"]
            raise subprocess.TimeoutExpired("not retained", kwargs["timeout"], output=b"partial\n", stderr=b"")

        with mock.patch.object(helper.subprocess, "run", side_effect=run) as commands, \
                mock.patch.object(helper.time, "monotonic", side_effect=clock.monotonic):
            record, _ = helper.command("/official-sdk/platform-tools/adb", ["install", "-t", "/verified/target.apk"],
                                       helper.INSTALL_SECONDS, helper.STEP_SECONDS)
            self.assertEqual("timeout", record["status"])
            self.assertEqual(1000, record["timeout_ms"])
            self.assertEqual(1000, record["elapsed_ms"])
            expired, _ = helper.command("/official-sdk/platform-tools/adb", ["shell", "getprop", "sys.boot_completed"],
                                        helper.PROBE_SECONDS, helper.STEP_SECONDS)
            self.assertEqual("deadline", expired["status"])
            self.assertEqual(0, expired["timeout_ms"])
            self.assertEqual(1, commands.call_count)
        encoded = helper.encode_report({"schema": 1, "requested_transport": "default", "status": "blocked", "stage": "target_install",
                                        "elapsed_ms": 270_000, "installs": [record],
                                        "snapshot": {"probes": {"boot_completed": expired}}})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "install-diagnostics.json"
            path.write_text(encoded)
            self.assertEqual(270_000, json.loads(path.read_text())["elapsed_ms"])
            self.assertLessEqual(path.stat().st_size, helper.MAX_REPORT_BYTES)
        self.assertGreaterEqual(300 - clock.now, 30)

    def test_invalid_utf8_oversized_control_bytes_preserve_counts_in_four_kib_report(self):
        large = b"\xff\x00\x1b\x7f" * 100_000
        output = b"Failure\n" + large
        for transport in helper.TRANSPORTS:
            with self.subTest(transport=transport), tempfile.TemporaryDirectory() as folder:
                code, report, _, _ = self.invoke(folder, ready(stderr=large) + ready(stderr=large) +
                                                 [result(b"Success\n", stderr=large), result(output, 19, large)] + ready(stderr=large),
                                                 transport=transport)
            self.assertEqual(1, code)
            self.assertEqual(transport, report["requested_transport"])
            self.assertEqual(19, report["installs"][1]["exit_code"])
            self.assertEqual(400_008, report["installs"][1]["stdout_bytes"])
            self.assertEqual(400_008, report["installs"][1]["stdout_characters"])
            self.assertEqual(2, report["readiness"]["probe_counts"]["system_server"]["ready"])
            self.assertEqual(432, report["readiness"]["stable_pid"])
            for record in helper.records(report):
                for stream in ("stdout", "stderr"):
                    preview = record[stream + "_preview"]
                    self.assertLessEqual(len(preview), 128)
                    self.assertTrue(all(" " <= character <= "~" for character in preview))
                    self.assertEqual(record[stream + "_characters"] - len(preview), record[stream + "_omitted_characters"])
                    if stream == "stderr":
                        self.assertEqual(400_000, record["stderr_bytes"])

    def test_actual_apk_triplet_and_optional_hash_file_remain_unchanged(self):
        for sha in (True, False):
            with self.subTest(sha=sha), tempfile.TemporaryDirectory() as folder:
                code, _, calls, _ = self.invoke(folder, ready() + ready() + [result(b"Success\n"), result(b"Success\n")] + ready(), sha=sha)
                root = Path(folder) / "apks"
                self.assertEqual(b"synthetic target", (root / "target.apk").read_bytes())
                self.assertEqual(b"synthetic test", (root / "test.apk").read_bytes())
                self.assertEqual({"target.apk", "test.apk"} | ({"SHA256SUMS"} if sha else set()), {path.name for path in root.iterdir()})
                self.assertEqual(0, code)
                self.assertEqual(2, len(self.install_calls(calls)))

    def test_unexpected_empty_symlink_hardlink_or_directory_files_block_all_adb(self):
        for kind in ("extra", "empty", "symlink_apk", "symlink_hash", "hardlink", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                apks = root / "apks"
                apks.mkdir()
                (apks / "target.apk").write_bytes(b"target")
                (apks / "test.apk").write_bytes(b"test")
                if kind == "extra":
                    (apks / "unexpected.apk").write_bytes(b"extra")
                elif kind == "empty":
                    (apks / "target.apk").write_bytes(b"")
                elif kind == "symlink_apk":
                    (apks / "test.apk").unlink()
                    (apks / "test.apk").symlink_to(apks / "target.apk")
                elif kind == "symlink_hash":
                    (apks / "SHA256SUMS").symlink_to(apks / "target.apk")
                elif kind == "hardlink":
                    (root / "alias.apk").hardlink_to(apks / "target.apk")
                else:
                    (apks / "test.apk").unlink()
                    (apks / "test.apk").mkdir()
                code, report, calls, _ = self.invoke(folder)
                self.assertEqual(1, code)
                self.assertEqual([], calls)
                self.assertEqual("inputs", report["stage"])
                self.assertNotIn("snapshot", report)

    def test_symlink_directory_or_parent_is_rejected_without_adb(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "actual").mkdir()
            (root / "alias").symlink_to(root / "actual", target_is_directory=True)
            for path in (root / "alias", root / "alias/apks"):
                code, _, calls, _ = self.invoke(folder, apks=path)
                self.assertEqual(1, code)
                self.assertEqual([], calls)

    def test_report_path_cannot_overwrite_apk_or_be_inside_apk_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in (root / "apks/target.apk", root / "apks/install-diagnostics.json",
                         root / "apks/reports/install-diagnostics.json"):
                code, _, calls, _ = self.invoke(folder, report_path=path)
                self.assertEqual(1, code)
                self.assertEqual([], calls)
                self.assertEqual(b"synthetic target", (root / "apks/target.apk").read_bytes())
                self.assertFalse((root / "apks/reports").exists())

    def test_fixed_serial_rejects_other_devices(self):
        argv = ["install_offline_apks.py", "--apks", "unused", "--adb", "unused", "--report", "unused", "--serial", "device-123"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(helper.subprocess, "run") as run, self.assertRaises(SystemExit) as error:
            helper.main()
        self.assertEqual(2, error.exception.code)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
