"""Synthetic/source-derived probe checks; no captured API37 output, emulator or ACL operations."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import check_emulator_storage as storage

ROOT = Path(__file__).resolve().parents[1]
DF = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/block/dm-0 6000000 1000000 5000000 17% /data\n"
STAT = "4096,1500000,1250000,1250000\n"
ALIAS_DF = DF.replace("/data", "/data/user/0")
IDENTITY = "253\n253\n"


def probe(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class StorageChecks(unittest.TestCase):
    def make_apks(self, root):
        for role in ("target", "test"):
            with zipfile.ZipFile(root / f"{role}.apk", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("synthetic.bin", bytes(1024))

    def invoke(self, root, phase):
        report = root / f"storage-{phase}.json"
        args = ["check_emulator_storage.py", phase, "--apks", str(root), "--report", str(report),
                "--adb", "/official-sdk/platform-tools/adb"]
        with mock.patch.object(sys, "argv", args), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = storage.main()
        self.assertLessEqual(report.stat().st_size, storage.MAX_REPORT_BYTES)
        return code, json.loads(report.read_text())

    def test_reserve_uses_actual_apk_and_expanded_zip_sizes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            budget = storage.apk_budget(root)
            actual = sum((root / f"{role}.apk").stat().st_size for role in ("target", "test"))
            self.assertEqual(actual, budget["apk_total_bytes"])
            self.assertEqual(2048, budget["uncompressed_total_bytes"])
            self.assertEqual(2 * actual + 2048 + 1024 ** 3, budget["required_guest_available_bytes"])

    def test_statfs_accounting_and_invalid_values(self):
        result = storage.parse_statfs(STAT)
        self.assertEqual(5_120_000_000, result["available_bytes"])
        for value in ("", "4096,10,11,8", "4096,10,8,9", "0,10,8,8", "4096,-1,0,0", STAT + STAT):
            with self.subTest(value=value), self.assertRaises(storage.StorageError):
                storage.parse_statfs(value)

    def test_df_uses_explicit_kib_and_validates_schema_accounting_and_safe_mounts(self):
        self.assertEqual(5_120_000_000, storage.parse_df(DF)["available_bytes"])
        for value in (DF.replace("1024-blocks", "1K-blocks"), ALIAS_DF):
            storage.parse_df(value)
        self.assertEqual("/data/user/0", storage.parse_df(ALIAS_DF)["reported_mount"])
        for value in ("", DF.replace("1024-blocks", "512-blocks"), DF.replace("1024-blocks", "Size"),
                      DF + DF.splitlines()[1], DF.replace("5000000", "unknown"), DF.replace("5000000", "9000000"), DF.replace("Used Available", "Available Used"),
                      DF.replace("17%", "bad"), DF.replace("5000000", "-1"),
                      DF.replace("1000000 5000000", "2000000 5000000")):
            with self.subTest(value=value), self.assertRaises(storage.StorageError):
                storage.parse_df(value)

    def test_guest_gate_uses_lower_measurement_and_fixed_read_only_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(DF)]) as run:
                code, report = self.invoke(root, "guest")
            self.assertEqual(0, code)
            self.assertEqual("passed", report["status"])
            self.assertLess(len(json.dumps(report)), storage.MAX_REPORT_BYTES)
            self.assertEqual([call.args[0][4] for call in run.call_args_list], ["stat", "df"])
            for call in run.call_args_list:
                self.assertEqual(["-s", "emulator-5554", "shell"], call.args[0][1:4])
                self.assertEqual(15, call.kwargs["timeout"])
                self.assertFalse(call.kwargs["check"])
                self.assertEqual("utf-8", call.kwargs["encoding"])
                self.assertEqual("replace", call.kwargs["errors"])
            low_df = DF.replace("5000000", "1")
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(low_df)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual(1024, report["guest"]["available_bytes_for_gate"])
            self.assertIn("installation reserve", report["error"])

    def test_source_derived_mount_alias_requires_equal_device_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(ALIAS_DF), probe(IDENTITY)]) as run:
                code, report = self.invoke(root, "guest")
            self.assertEqual(0, code)
            self.assertEqual("same_device", report["guest"]["df"]["mount_validation"])
            self.assertEqual(253, report["guest"]["df_mount_identity"]["data_device"])
            self.assertEqual(["stat", "-L", "-c", "%d", "/data", "/data/user/0"], run.call_args.args[0][4:])
            self.assertEqual(["-s", "emulator-5554", "shell"], run.call_args.args[0][1:4])
            self.assertEqual(5_120_000_000, report["guest"]["available_bytes_for_gate"])

    def test_alias_identity_mismatch_malformed_or_failed_probe_stays_blocked(self):
        failures = (probe("253\n254\n"), probe("0\n0\n"), probe("253\n"),
                    probe("253\n253\n253\n"), probe("253\nunknown\n"),
                    probe("253\n253\n", returncode=1, stderr="stat: permission denied\n"),
                    subprocess.TimeoutExpired("hidden command detail", 15, output=b"253\n", stderr=b"partial\n"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            for failure in failures:
                with self.subTest(failure=type(failure).__name__), mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(DF.replace("/data", "/system")), failure]):
                    code, report = self.invoke(root, "guest")
                self.assertEqual(1, code)
                self.assertEqual("blocked", report["status"])
                self.assertIn("statfs", report["guest"])
                self.assertIn("df", report["guest"])
                self.assertIn("mount_identity", report["guest"]["probes"])
                self.assertNotIn("available_bytes_for_gate", report["guest"])
                self.assertNotIn("hidden command detail", json.dumps(report))

    def test_mount_metacharacters_and_noncanonical_paths_never_reach_a_shell_probe(self):
        mounts = ("/data/user 0", "/data;id", "/data/$USER", '/data/"user"', "/data/'user'",
                  "/data/user\\0", "/data/user\n0", "/data/../system", "/data/./user",
                  "/data//user", "/data/", "data/user", "/", "/" + "x" * storage.MAX_MOUNT_PATH_CHARS)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            for mount in mounts:
                with self.subTest(mount=mount), mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(DF.replace("/data", mount))]) as run:
                    code, report = self.invoke(root, "guest")
                self.assertEqual(1, code)
                self.assertEqual(2, run.call_count)
                self.assertEqual("df_parse", report["failure_stage"])
                self.assertIn("statfs", report["guest"])

    def test_failed_df_retains_successful_statfs_and_bounded_raw_evidence(self):
        cases = (probe("unsupported df header\n", stderr="warning\n"),
                 probe(DF, returncode=1, stderr="df: permission denied\n"),
                 subprocess.TimeoutExpired("hidden command detail", 15, output=b"Filesystem partial\n", stderr=b"partial timeout\n"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            for result in cases:
                with self.subTest(result=type(result).__name__), mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), result]):
                    code, report = self.invoke(root, "guest")
                self.assertEqual(1, code)
                self.assertEqual(5_120_000_000, report["guest"]["statfs"]["available_bytes"])
                diagnostic = report["guest"]["probes"]["df"]
                self.assertTrue(diagnostic["stdout_preview"])
                self.assertTrue(diagnostic["stderr_preview"])
                self.assertNotIn("available_bytes_for_gate", report["guest"])
                self.assertIn(report["failure_stage"], ("df_command", "df_parse"))
                self.assertNotIn("hidden command detail", json.dumps(report))

    def test_escaped_oversized_diagnostics_still_write_a_four_kib_report(self):
        noisy = '"\\\n\x00\u202e' * 2000
        mount = "/" + "x" * (storage.MAX_MOUNT_PATH_CHARS - 1)
        long_df = DF.replace("/dev/block/dm-0", "\\" * 1000).replace("/data", mount)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT, stderr=noisy), probe(long_df, stderr=noisy), probe(IDENTITY, stderr=noisy)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(0, code)
            for diagnostic in report["guest"]["probes"].values():
                self.assertTrue(diagnostic["stderr_truncated"])
                self.assertLessEqual(len(diagnostic["stderr_preview"]), storage.MAX_PROBE_TEXT_CHARS)
            self.assertNotIn("\u202e", json.dumps(report))
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(noisy, stderr=noisy)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertTrue(report["guest"]["probes"]["df"]["stdout_truncated"])
            self.assertEqual("df_parse", report["failure_stage"])

    def test_report_budget_trims_only_previews_when_a_later_capacity_error_is_added(self):
        maximum = "9" * 20
        noisy = '"\\\n' * 4000
        mount = "/" + "x" * (storage.MAX_MOUNT_PATH_CHARS - 1)
        # Maximum allowed numeric fields, safe alias and escaped diagnostic text exercise
        # the real JSON bound; low statfs availability must still prevent installation.
        stat = f"1048576,{maximum},88888888888888888888,1\n" + "\t" * 1000
        df = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n" + "\\" * 1000 +
              f" {maximum} 22222222222222222222 77777777777777777777 23% {mount}\n")
        identity = maximum + "\n" + maximum + "\n"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for role in ("target", "test"):
                with zipfile.ZipFile(root / f"{role}.apk", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("synthetic.bin", bytes(1_000_000))
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe(stat, stderr=noisy), probe(df, stderr=noisy), probe(identity, stderr=noisy)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual("guest_capacity", report["failure_stage"])
            self.assertEqual(1048576, report["guest"]["available_bytes_for_gate"])
            self.assertEqual(int(maximum), report["guest"]["statfs"]["total_blocks"])
            self.assertEqual(mount, report["guest"]["df"]["reported_mount"])
            self.assertEqual(int(maximum), report["guest"]["df_mount_identity"]["data_device"])
            self.assertTrue(any(len(item["stderr_preview"]) < storage.MAX_PROBE_TEXT_CHARS
                                for item in report["guest"]["probes"].values()))
            for diagnostic in report["guest"]["probes"].values():
                self.assertTrue(diagnostic["stderr_truncated"])
                self.assertEqual(len(noisy), diagnostic["stderr_characters"])

    def test_failed_initial_statfs_parse_is_saved_and_never_reaches_df(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", return_value=probe("unknown statfs\n")) as run:
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual(1, run.call_count)
            self.assertEqual("statfs_parse", report["failure_stage"])
            self.assertEqual("unknown statfs\n", report["guest"]["probes"]["statfs"]["stdout_preview"])
            self.assertNotIn("statfs", report["guest"])
            self.assertNotIn("available_bytes_for_gate", report["guest"])

    def test_actual_subprocess_decoding_keeps_invalid_utf8_in_a_blocked_report(self):
        actual_run = subprocess.run

        def controlled_byte_probe(_command, **kwargs):
            # Execute only the current Python interpreter emitting known bytes, not adb.
            # This exercises subprocess's decoding policy instead of supplying decoded mocks.
            return actual_run([sys.executable, "-c",
                               "import sys; sys.stdout.buffer.write(b'\\xff\\n'); "
                               "sys.stderr.buffer.write(b'\\xfe\\n')"], **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=controlled_byte_probe) as run:
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual(1, run.call_count)
            self.assertEqual("statfs_parse", report["failure_stage"])
            diagnostic = report["guest"]["probes"]["statfs"]
            self.assertEqual(0, diagnostic["exit_code"])
            self.assertEqual("?\n", diagnostic["stdout_preview"])
            self.assertEqual("?\n", diagnostic["stderr_preview"])
            self.assertNotIn("available_bytes_for_gate", report["guest"])

    def test_reserve_boundary_still_uses_the_lower_validated_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            budget = storage.apk_budget(root)["required_guest_available_bytes"]
            total_kib = 6000000
            for available_kib, expected in (((budget - 1) // 1024, 1), ((budget + 1023) // 1024, 0)):
                df = DF.replace("1000000 5000000", f"{total_kib - available_kib} {available_kib}")
                with mock.patch.object(storage.subprocess, "run", side_effect=[probe(STAT), probe(df)]):
                    code, report = self.invoke(root, "guest")
                self.assertEqual(expected, code)
                self.assertEqual(available_kib * 1024, report["guest"]["available_bytes_for_gate"])
            # A high df cannot compensate for a lower statfs measurement.
            with mock.patch.object(storage.subprocess, "run", side_effect=[probe("4096,1500000,1,1\n"), probe(DF)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual(4096, report["guest"]["available_bytes_for_gate"])

    def test_host_gate_fails_before_guest_commands_when_capacity_is_low(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.shutil, "disk_usage", return_value=mock.Mock(total=10**10, free=1)), mock.patch.object(storage.subprocess, "run") as run:
                code, report = self.invoke(root, "host")
            self.assertEqual(1, code)
            self.assertEqual(1, report["host_available_bytes"])
            self.assertGreater(report["required_host_available_bytes"], 6144 * 1024**2)
            run.assert_not_called()

    def test_probe_timeout_and_bad_apk_fail_with_small_sanitized_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=subprocess.TimeoutExpired("hidden command detail", 15)):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertNotIn("hidden command detail", json.dumps(report))
            (root / "target.apk").write_bytes(b"not a zip")
            code, report = self.invoke(root, "host")
            self.assertEqual(1, code)
            self.assertIn("BadZipFile", report["error"])

    def test_workflow_checks_space_before_kvm_and_before_install(self):
        source = (ROOT / ".github/workflows/emulator.yml").read_text()
        self.assertIn(f"-partition-size {storage.PARTITION_MIB}", source)
        self.assertLess(source.index("check_emulator_storage.py host"), source.index("kvm_access.py acquire"))
        self.assertLess(source.index("sha256sum -c SHA256SUMS"), source.index("check_emulator_storage.py guest"))
        self.assertLess(source.index("check_emulator_storage.py guest"), source.index("install_offline_apks.py"))
        self.assertIn("python3 scripts/test_emulator_storage.py", source)
        self.assertIn("storage-host.json", source)
        self.assertIn("storage-guest.json", source)
        for bypass in ("sys_storage_threshold", "set-install-location", "-writable-system"):
            self.assertNotIn(bypass, source)


if __name__ == "__main__":
    unittest.main()
