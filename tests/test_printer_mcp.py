from __future__ import annotations

import hashlib
import io
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import paramiko

from printer_mcp.server import (
    MAX_FILE_BYTES, PrinterMcp, Settings, _confirmation_token,
)


class FixtureSftp:
    def __init__(self, root: Path):
        self.root = root
        self.modes: list[str] = []

    def _path(self, path: str) -> Path:
        return self.root / PurePosixPath(path).name

    def lstat(self, path: str) -> paramiko.SFTPAttributes:
        return paramiko.SFTPAttributes.from_stat(self._path(path).lstat())

    def stat(self, path: str) -> paramiko.SFTPAttributes:
        return paramiko.SFTPAttributes.from_stat(self._path(path).stat())

    def listdir_attr(self, path: str) -> list[paramiko.SFTPAttributes]:
        return [
            paramiko.SFTPAttributes.from_stat(p.lstat(), p.name)
            for p in self.root.iterdir()
        ]

    def open(self, path: str, mode: str):
        self.modes.append(mode)
        if "x" in mode:
            if "w" not in mode:
                raise OSError("SFTP exclusive creation requires the write flag.")
            mode = mode.replace("w", "")
        return self._path(path).open(mode)

    def chmod(self, path: str, mode: int) -> None:
        self._path(path).chmod(mode)

    def rename(self, source: str, destination: str) -> None:
        if os.path.lexists(self._path(destination)):
            raise FileExistsError(destination)
        self._path(source).rename(self._path(destination))

    def remove(self, path: str) -> None:
        self._path(path).unlink()


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

    def test_local_create_read_delete_and_verified_backup(self) -> None:
        filename = "test-new.ini"
        content = "# disposable profile\n"
        preview = self.service.preview_config_create(
            "prusaslicer", "printer", filename, content
        )
        path = self.root / "printer" / filename
        self.assertFalse(path.exists())
        created = self.service.apply_config_create(
            "prusaslicer", "printer", filename, content,
            preview["confirmation_token"], True,
        )
        self.assertTrue(created["created"])
        read = self.service.read_local_profile("printer", filename)
        self.assertEqual(read["content"], content)
        delete_preview = self.service.preview_config_delete(
            "prusaslicer", "printer", filename, read["sha256"]
        )
        self.assertTrue(path.exists())
        deleted = self.service.apply_config_delete(
            "prusaslicer", "printer", filename, read["sha256"],
            delete_preview["confirmation_token"], True,
        )
        self.assertTrue(deleted["deleted"])
        self.assertFalse(path.exists())
        self.assertEqual((path.parent / deleted["backup"]).read_text(), content)
        self.assertFalse(created["printer_restarted"])
        self.assertFalse(deleted["printer_restarted"])

    def test_create_confirms_exact_preview_and_rejects_existing_destination(self) -> None:
        args = ("prusaslicer", "printer", "test-new.ini", "# test\n")
        preview = self.service.preview_config_create(*args)
        token = preview["confirmation_token"]
        with self.assertRaises(ValueError):
            self.service.apply_config_create(*args, token, False)
        with self.assertRaises(ValueError):
            self.service.apply_config_create(*args, "wrong", True)
        with self.assertRaises(ValueError):
            self.service.apply_config_create(
                "prusaslicer", "printer", "test-new.ini", "# changed\n", token, True
            )
        path = self.root / "printer" / "test-new.ini"
        path.write_text("concurrent content\n")
        with self.assertRaises(FileExistsError):
            self.service.apply_config_create(*args, token, True)
        self.assertEqual(path.read_text(), "concurrent content\n")
        self.assertFalse(list(path.parent.glob(".*.tmp")))

    def test_local_lifecycle_rejects_read_only_categories_paths_and_secrets(self) -> None:
        for category, name, content in (
            ("application", "new.ini", "# test\n"),
            ("vendor", "new.ini", "# test\n"),
            ("printer", "../new.ini", "# test\n"),
            ("printer", "test.cfg", "# test\n"),
            ("printer", "new.ini", "password = secret\n"),
            ("printer", "new.ini", "x" * (MAX_FILE_BYTES + 1)),
            ("printer", "new.ini", "\0"),
        ):
            with self.subTest(category=category, name=name), self.assertRaises(ValueError):
                self.service.preview_config_create("prusaslicer", category, name, content)
        path = self.root / "printer" / "linked.ini"
        path.symlink_to(self.root / "filament" / "PLA.ini")
        with self.assertRaises(ValueError):
            self.service.preview_config_create("prusaslicer", "printer", path.name, "# test\n")
        with self.assertRaises(ValueError):
            self.service.preview_config_delete("prusaslicer", "printer", path.name, "0" * 64)

    def test_delete_rejects_stale_hash_unconfirmed_and_wrong_operation_token(self) -> None:
        args = ("prusaslicer", "filament", "PLA.ini")
        read = self.service.read_local_profile("filament", "PLA.ini")
        preview = self.service.preview_config_delete(*args, read["sha256"])
        token = preview["confirmation_token"]
        with self.assertRaises(ValueError):
            self.service.apply_config_delete(*args, read["sha256"], token, False)
        with self.assertRaises(ValueError):
            self.service.apply_config_create(*args, read["content"], token, True)
        path = self.root / "filament" / "PLA.ini"
        path.write_text("temperature = 220\n")
        with self.assertRaises(ValueError):
            self.service.apply_config_delete(*args, read["sha256"], token, True)
        self.assertTrue(path.exists())
        self.assertFalse(list(path.parent.glob("*.before-printer-mcp-delete-*")))

    def test_preview_tokens_expire_and_cannot_be_reused(self) -> None:
        args = ("prusaslicer", "printer", "test-new.ini", "# test\n")
        with patch("printer_mcp.server.time.monotonic", return_value=100):
            preview = self.service.preview_config_create(*args)
        with patch("printer_mcp.server.time.monotonic", return_value=701):
            with self.assertRaises(ValueError):
                self.service.apply_config_create(*args, preview["confirmation_token"], True)
        preview = self.service.preview_config_create(*args)
        self.service.apply_config_create(*args, preview["confirmation_token"], True)
        with self.assertRaises(ValueError):
            self.service.apply_config_create(*args, preview["confirmation_token"], True)

    def test_local_delete_preserves_original_if_backup_verification_fails(self) -> None:
        read = self.service.read_local_profile("filament", "PLA.ini")
        args = ("prusaslicer", "filament", "PLA.ini", read["sha256"])
        preview = self.service.preview_config_delete(*args)
        original_read = Path.read_bytes

        def corrupt_read(path: Path) -> bytes:
            if ".before-printer-mcp-delete-" in path.name:
                return b"incorrect backup bytes"
            return original_read(path)

        with patch.object(Path, "read_bytes", corrupt_read):
            with self.assertRaisesRegex(ValueError, "verification failed"):
                self.service.apply_config_delete(*args, preview["confirmation_token"], True)
        self.assertEqual((self.root / "filament" / "PLA.ini").read_text(), read["content"])


class RemoteLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "printer.cfg").write_text("[include hardware.cfg]\n")
        (self.root / "hardware.cfg").write_text("# active hardware fixture\n")
        self.sftp = FixtureSftp(self.root)
        self.service = PrinterMcp()

        @contextmanager
        def fixture_connection():
            yield self.sftp

        self.connection_patch = patch.object(self.service, "_sftp", fixture_connection)
        self.connection_patch.start()

    def tearDown(self) -> None:
        self.connection_patch.stop()
        self.tempdir.cleanup()

    def create(self, filename: str = "mcp-test.cfg") -> dict:
        content = "# unreferenced disposable fixture\n"
        preview = self.service.preview_config_create("klipper", "", filename, content)
        self.assertFalse((self.root / filename).exists())
        return self.service.apply_config_create(
            "klipper", "", filename, content, preview["confirmation_token"], True
        )

    def test_remote_create_read_delete_retains_backup_and_active_files(self) -> None:
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        created = self.create()
        self.assertTrue(created["created"])
        self.assertFalse(created["automatically_activated"])
        names = self.service.list_klipper_config_files()
        self.assertNotIn("mcp-test.cfg", [item["filename"] for item in names])
        names = self.service.list_klipper_config_files(include_unreferenced=True)
        staged = next(item for item in names if item["filename"] == "mcp-test.cfg")
        self.assertFalse(staged["included"])
        with self.assertRaises(ValueError):
            self.service.read_klipper_config("mcp-test.cfg")
        read = self.service.read_klipper_config("mcp-test.cfg", include_unreferenced=True)
        preview = self.service.preview_config_delete("klipper", "", "mcp-test.cfg", read["sha256"])
        result = self.service.apply_config_delete(
            "klipper", "", "mcp-test.cfg", read["sha256"], preview["confirmation_token"], True
        )
        self.assertTrue(result["deleted"])
        self.assertFalse((self.root / "mcp-test.cfg").exists())
        self.assertEqual((self.root / result["backup"]).read_text(), read["content"])
        self.assertEqual({name: (self.root / name).read_bytes() for name in before}, before)
        self.assertIn("wxb", self.sftp.modes)
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_remote_lifecycle_rejects_root_active_references_and_symlinks(self) -> None:
        for name in ("printer.cfg", "hardware.cfg"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.service.preview_config_delete(
                    "klipper", "", name, hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                )
        (self.root / "dormant.cfg").write_text("[include spare-*.cfg]\n")
        with self.assertRaisesRegex(ValueError, "referenced"):
            self.service.preview_config_create("klipper", "", "spare-new.cfg", "# test\n")
        (self.root / "linked.cfg").symlink_to(self.root / "hardware.cfg")
        with self.assertRaises(ValueError):
            self.service.preview_config_delete("klipper", "", "linked.cfg", "0" * 64)
        for name in ("../test.cfg", "moonraker.conf", "hardware.cfg.before-test"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.service.preview_config_create("klipper", "", name, "# test\n")

    def test_remote_create_never_overwrites_destination_and_cleans_temporary_file(self) -> None:
        args = ("klipper", "", "mcp-test.cfg", "# test\n")
        preview = self.service.preview_config_create(*args)

        def concurrent_rename(source: str, destination: str) -> None:
            (self.root / "mcp-test.cfg").write_text("concurrent\n")
            raise FileExistsError(destination)

        with patch.object(self.sftp, "rename", side_effect=concurrent_rename):
            with self.assertRaises(FileExistsError):
                self.service.apply_config_create(*args, preview["confirmation_token"], True)
        self.assertEqual((self.root / "mcp-test.cfg").read_text(), "concurrent\n")
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_remote_delete_rechecks_includes_and_hash_before_writing(self) -> None:
        self.create()
        read = self.service.read_klipper_config("mcp-test.cfg", True)
        args = ("klipper", "", "mcp-test.cfg", read["sha256"])
        preview = self.service.preview_config_delete(*args)
        (self.root / "hardware.cfg").write_text("[include mcp-test.cfg]\n")
        with self.assertRaisesRegex(ValueError, "referenced"):
            self.service.apply_config_delete(*args, preview["confirmation_token"], True)
        (self.root / "hardware.cfg").write_text("# active\n")
        preview = self.service.preview_config_delete(*args)
        (self.root / "mcp-test.cfg").write_text("# changed\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.service.apply_config_delete(*args, preview["confirmation_token"], True)
        self.assertTrue((self.root / "mcp-test.cfg").exists())
        self.assertFalse(list(self.root.glob("*.before-printer-mcp-delete-*")))

    def test_remote_missing_check_does_not_hide_permission_errors(self) -> None:
        with patch.object(self.sftp, "lstat", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(PermissionError):
                self.service.preview_config_create("klipper", "", "mcp-test.cfg", "# test\n")

    def test_remote_delete_preserves_original_if_backup_verification_fails(self) -> None:
        self.create()
        read = self.service.read_klipper_config("mcp-test.cfg", True)
        args = ("klipper", "", "mcp-test.cfg", read["sha256"])
        preview = self.service.preview_config_delete(*args)
        original_open = self.sftp.open

        def corrupt_read(path: str, mode: str):
            if ".before-printer-mcp-delete-" in path and mode == "rb":
                return io.BytesIO(b"incorrect backup bytes")
            return original_open(path, mode)

        with patch.object(self.sftp, "open", side_effect=corrupt_read):
            with self.assertRaisesRegex(ValueError, "Backup verification failed"):
                self.service.apply_config_delete(*args, preview["confirmation_token"], True)
        self.assertEqual((self.root / "mcp-test.cfg").read_text(), read["content"])

    def test_existing_remote_update_uses_writable_exclusive_backup(self) -> None:
        read = self.service.read_klipper_config("hardware.cfg")
        args = ("klipper", "", "hardware.cfg", read["sha256"], "# revised fixture\n")
        preview = self.service.preview_config_update(*args)
        result = self.service.apply_config_update(*args, preview["confirmation_token"], True)
        self.assertTrue(result["written"])
        self.assertEqual((self.root / result["backup"]).read_text(), read["content"])
        self.assertIn("wxb", self.sftp.modes)

if __name__ == "__main__":
    unittest.main()
