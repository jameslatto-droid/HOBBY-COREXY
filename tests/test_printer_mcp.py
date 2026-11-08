from __future__ import annotations

import hashlib
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import paramiko

from printer_mcp.server import PrinterMcp, Settings, _confirmation_token


class PrinterMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        for category in ("printer", "physical_printer", "print", "filament", "cache/vendor"):
            (self.root / category).mkdir(parents=True, exist_ok=True)
        (self.root / "printer" / "CoreXY.ini").write_text("printer_model = CoreXY\n")
        (self.root / "printer" / "CoreXY.ini.before-old").write_text("old\n")
        (self.root / "filament" / "PLA.ini").write_text("temperature = 210\n")
        (self.root / "PrusaSlicer.ini").write_text("api_key = hidden\n")
        self.settings = Settings(
            local_root=self.root,
            ssh_host="printer.invalid",
            ssh_user="pi",
            ssh_port=22,
            ssh_key=self.root / "key",
            known_hosts=self.root / "known_hosts",
            remote_config_dir=PurePosixPath("/home/pi/printer_data/config"),
        )
        self.service = PrinterMcp(self.settings)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_listing_excludes_backups_and_marks_writable_profiles(self) -> None:
        files = self.service.list_local_profiles("printer")
        self.assertEqual([item["filename"] for item in files], ["printer/CoreXY.ini"])
        self.assertTrue(files[0]["writable"])

    def test_application_settings_are_read_only_and_redacted(self) -> None:
        result = self.service.read_local_profile("application", "PrusaSlicer.ini")
        self.assertIn("[REDACTED]", result["content"])
        self.assertTrue(result["redacted"])
        with self.assertRaises(ValueError):
            self.service.preview_config_update(
                "prusaslicer", "application", "PrusaSlicer.ini", result["sha256"], "x\n"
            )

    def test_rejects_path_traversal_and_backup_files(self) -> None:
        with self.assertRaises(ValueError):
            self.service.read_local_profile("printer", "../PrusaSlicer.ini")
        with self.assertRaises(ValueError):
            self.service.read_local_profile("printer", "CoreXY.ini.before-old")

    def test_preview_and_apply_require_current_hash_and_confirmation(self) -> None:
        path = self.root / "filament" / "PLA.ini"
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        preview = self.service.preview_config_update(
            "prusaslicer", "filament", "PLA.ini", digest, "temperature = 215\n"
        )
        self.assertIn("-temperature = 210", preview["diff"])
        with self.assertRaises(ValueError):
            self.service.apply_config_update(
                "prusaslicer",
                "filament",
                "PLA.ini",
                digest,
                "temperature = 215\n",
                preview["confirmation_token"],
                False,
            )
        with self.assertRaises(ValueError):
            self.service.apply_config_update(
                "prusaslicer",
                "filament",
                "PLA.ini",
                "0" * 64,
                "temperature = 215\n",
                preview["confirmation_token"],
                True,
            )
        with self.assertRaises(ValueError):
            self.service.apply_config_update(
                "prusaslicer",
                "filament",
                "PLA.ini",
                digest,
                "temperature = 215\n",
                "wrong",
                True,
            )

    def test_confirmed_apply_creates_backup(self) -> None:
        path = self.root / "filament" / "PLA.ini"
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        preview = self.service.preview_config_update(
            "prusaslicer", "filament", "PLA.ini", digest, "temperature = 215\n"
        )
        result = self.service.apply_config_update(
            "prusaslicer",
            "filament",
            "PLA.ini",
            digest,
            "temperature = 215\n",
            preview["confirmation_token"],
            True,
        )
        self.assertTrue(result["written"])
        self.assertFalse(result["printer_restarted"])
        self.assertEqual(path.read_text(), "temperature = 215\n")
        self.assertEqual((path.parent / result["backup"]).read_bytes(), original)

    def test_klipper_paths_are_flat_active_cfg_names_only(self) -> None:
        with self.assertRaises(ValueError):
            self.service._remote_path("../moonraker.conf")
        with self.assertRaises(ValueError):
            self.service._remote_path("hardware.cfg.before-test")
        self.assertEqual(
            self.service._remote_path("hardware.cfg"),
            "/home/pi/printer_data/config/hardware.cfg",
        )

    def test_allowed_include_symlink_is_read_only(self) -> None:
        class FakeSftp:
            def lstat(self, path: str) -> paramiko.SFTPAttributes:
                attrs = paramiko.SFTPAttributes()
                attrs.st_mode = stat.S_IFLNK | 0o777
                return attrs

            def normalize(self, path: str) -> str:
                return "/home/pi/mainsail-config/mainsail.cfg"

            def stat(self, path: str) -> paramiko.SFTPAttributes:
                attrs = paramiko.SFTPAttributes()
                attrs.st_mode = stat.S_IFREG | 0o644
                attrs.st_size = 100
                return attrs

        resolved, _, is_symlink = self.service._resolve_remote_config(
            FakeSftp(), "mainsail.cfg"
        )
        self.assertEqual(resolved, "/home/pi/mainsail-config/mainsail.cfg")
        self.assertTrue(is_symlink)
        with self.assertRaises(ValueError):
            self.service._resolve_remote_config(
                FakeSftp(), "mainsail.cfg", writing=True
            )

    def test_include_symlink_outside_approved_roots_is_rejected(self) -> None:
        class FakeSftp:
            def lstat(self, path: str) -> paramiko.SFTPAttributes:
                attrs = paramiko.SFTPAttributes()
                attrs.st_mode = stat.S_IFLNK | 0o777
                return attrs

            def normalize(self, path: str) -> str:
                return "/home/pi/.ssh/authorized_keys"

        with self.assertRaises(ValueError):
            self.service._resolve_remote_config(FakeSftp(), "mainsail.cfg")

    def test_apply_rechecks_klipper_include_before_write(self) -> None:
        original = b"old\n"
        replacement = "new\n"
        expected_hash = hashlib.sha256(original).hexdigest()
        replacement_hash = hashlib.sha256(replacement.encode()).hexdigest()
        token = _confirmation_token(
            "klipper", "", "hardware.cfg", expected_hash, replacement_hash
        )

        @contextmanager
        def fake_sftp():
            yield object()

        with (
            patch.object(
                self.service, "_current_config", return_value=(original, None)
            ),
            patch.object(self.service, "_sftp", fake_sftp),
            patch.object(self.service, "_klipper_config_names", return_value=[]),
            patch.object(self.service, "_resolve_remote_config") as resolve,
        ):
            with self.assertRaisesRegex(ValueError, "active files"):
                self.service.apply_config_update(
                    "klipper",
                    "",
                    "hardware.cfg",
                    expected_hash,
                    replacement,
                    token,
                    True,
                )
            resolve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
