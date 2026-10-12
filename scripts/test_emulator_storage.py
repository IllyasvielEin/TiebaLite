"""Mocked host checks for storage accounting; no emulator or ACL operations are performed."""
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

    def test_df_uses_explicit_kib_and_exact_data_mount(self):
        self.assertEqual(5_120_000_000, storage.parse_df(DF)["available_bytes"])
        for value in (DF.replace("1024-blocks", "1K-blocks"),):
            storage.parse_df(value)
        for value in ("", DF.replace("1024-blocks", "512-blocks"), DF.replace("/data", "/system"),
                      DF + DF.splitlines()[1], DF.replace("5000000", "unknown"), DF.replace("5000000", "9000000"), DF.replace("Used Available", "Available Used"),
                      DF.replace("17%", "bad"), DF.replace("1000000 5000000", "2000000 5000000")):
            with self.subTest(value=value), self.assertRaises(storage.StorageError):
                storage.parse_df(value)

    def test_guest_gate_uses_lower_measurement_and_fixed_read_only_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_apks(root)
            with mock.patch.object(storage.subprocess, "run", side_effect=[mock.Mock(stdout=STAT), mock.Mock(stdout=DF)]) as run:
                code, report = self.invoke(root, "guest")
            self.assertEqual(0, code)
            self.assertEqual("passed", report["status"])
            self.assertLess(len(json.dumps(report)), storage.MAX_REPORT_BYTES)
            self.assertEqual([call.args[0][4] for call in run.call_args_list], ["stat", "df"])
            for call in run.call_args_list:
                self.assertEqual(["-s", "emulator-5554", "shell"], call.args[0][1:4])
                self.assertEqual(15, call.kwargs["timeout"])
            low_df = DF.replace("5000000", "1")
            with mock.patch.object(storage.subprocess, "run", side_effect=[mock.Mock(stdout=STAT), mock.Mock(stdout=low_df)]):
                code, report = self.invoke(root, "guest")
            self.assertEqual(1, code)
            self.assertEqual(1024, report["guest"]["available_bytes_for_gate"])
            self.assertIn("installation reserve", report["error"])

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
        self.assertLess(source.index("check_emulator_storage.py guest"), source.index("install -t"))
        self.assertIn("python3 scripts/test_emulator_storage.py", source)
        self.assertIn("storage-host.json", source)
        self.assertIn("storage-guest.json", source)
        for bypass in ("sys_storage_threshold", "set-install-location", "-writable-system"):
            self.assertNotIn(bypass, source)


if __name__ == "__main__":
    unittest.main()
