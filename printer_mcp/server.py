from __future__ import annotations

import difflib
import errno
import fnmatch
import hashlib
import logging
import os
import posixpath
import re
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import paramiko
from mcp.server.fastmcp import FastMCP

MAX_FILE_BYTES = 512 * 1024
MAX_SEARCH_MATCHES = 100
CONFIG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]*\.cfg$")
INCLUDE_RE = re.compile(r"^\s*\[include\s+([^\]]+)\]", re.IGNORECASE)
SENSITIVE_LINE_RE = re.compile(
    r"(?im)^(\s*[^#\r\n]*(?:api[_-]?key|token|password|secret|authorization)"
    r"[^=\r\n]*[=:]\s*)(.*)$"
)

CATEGORY_DIRS = {
    "printer": Path("printer"),
    "physical_printer": Path("physical_printer"),
    "print": Path("print"),
    "filament": Path("filament"),
    "application": Path("."),
    "vendor": Path("cache/vendor"),
}
ROOT_FILES = {
    "ArchiveRepositoryManifest.json",
    "LINUX-SETUP.txt",
    "PrusaSlicer.ini",
    "workflows.json",
}
PROFILE_CATEGORIES = {"printer", "physical_printer", "print", "filament"}
TEXT_SUFFIXES = {".cfg", ".ini", ".info", ".json", ".md", ".txt"}


@dataclass(frozen=True)
class Settings:
    local_root: Path
    ssh_host: str
    ssh_user: str
    ssh_port: int
    ssh_key: Path
    known_hosts: Path
    remote_config_dir: PurePosixPath

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            local_root=Path(
                os.environ.get(
                    "PRINTER_MCP_LOCAL_ROOT",
                    "/srv/data/3D-Printing/PrusaSlicer/production",
                )
            ),
            ssh_host=os.environ.get("PRINTER_MCP_SSH_HOST", ""),
            ssh_user=os.environ.get("PRINTER_MCP_SSH_USER", "pi"),
            ssh_port=int(os.environ.get("PRINTER_MCP_SSH_PORT", "22")),
            ssh_key=Path(
                os.environ.get(
                    "PRINTER_MCP_SSH_KEY",
                    "/home/james/.ssh/printer-mcp_ed25519",
                )
            ),
            known_hosts=Path(
                os.environ.get(
                    "PRINTER_MCP_KNOWN_HOSTS",
                    "/home/james/.ssh/known_hosts",
                )
            ),
            remote_config_dir=PurePosixPath(
                os.environ.get(
                    "PRINTER_MCP_REMOTE_CONFIG_DIR",
                    "/home/pi/printer_data/config",
                )
            ),
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _redact(text: str) -> str:
    return SENSITIVE_LINE_RE.sub(r"\1[REDACTED]", text)


def _has_sensitive_lines(text: str) -> bool:
    return SENSITIVE_LINE_RE.search(text) is not None


logging.getLogger("paramiko").setLevel(logging.WARNING)


def _is_backup(name: str) -> bool:
    lower = name.lower()
    return (
        lower.endswith((".bak", ".backup", ".orig", ".old"))
        or ".before-" in lower
        or ".before_" in lower
    )


def _validate_replacement(content: str) -> bytes:
    if "\x00" in content:
        raise ValueError("Configuration content must not contain NUL bytes.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Configuration content exceeds {MAX_FILE_BYTES} bytes.")
    return encoded


def _safe_config_name(filename: str) -> str:
    if (
        not CONFIG_NAME_RE.fullmatch(filename)
        or ".." in filename
        or "/" in filename
        or "\\" in filename
        or _is_backup(filename)
    ):
        raise ValueError("Only plain Klipper .cfg filenames are allowed.")
    return filename


def _confirmation_token(
    target: str,
    category: str,
    filename: str,
    current_sha256: str,
    replacement_sha256: str,
) -> str:
    value = "\0".join(
        (target, category, filename, current_sha256, replacement_sha256)
    )
    return _sha256(value.encode("utf-8"))


class PrinterMcp:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self._file_proposals: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._proposal_lock = threading.Lock()

    def _local_path(
        self, category: str, filename: str, *, writing: bool = False,
        creating: bool = False,
    ) -> Path:
        if category not in CATEGORY_DIRS:
            raise ValueError(f"Unknown PrusaSlicer category: {category}")
        if (
            not filename
            or filename in {".", ".."}
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or _is_backup(filename)
        ):
            raise ValueError("Use an active profile filename, not a path or backup.")
        if writing and category not in PROFILE_CATEGORIES:
            raise ValueError("Only user printer, print, filament, and physical-printer profiles can be updated.")
        if category == "application" and filename not in ROOT_FILES:
            raise ValueError("Only the documented PrusaSlicer setup files are available.")
        if category != "application" and Path(filename).suffix.lower() not in TEXT_SUFFIXES:
            raise ValueError("Only supported text-based profile files are available.")

        root = self.settings.local_root.resolve(strict=True)
        directory = (root / CATEGORY_DIRS[category]).resolve(strict=True)
        if not directory.is_relative_to(root):
            raise ValueError("Profile directory resolves outside the configured data directory.")
        path = directory / filename
        if path.is_symlink():
            raise ValueError("Symbolic links are not exposed through the MCP.")
        if creating:
            if path.exists():
                raise FileExistsError("The profile already exists; use preview_config_update.")
            return path
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("Profile is not a regular file inside the configured data directory.")
        return resolved

    def list_local_profiles(self, category: str = "all") -> list[dict[str, Any]]:
        categories = list(CATEGORY_DIRS) if category == "all" else [category]
        if any(item not in CATEGORY_DIRS for item in categories):
            raise ValueError(f"Unknown PrusaSlicer category: {category}")

        root = self.settings.local_root.resolve(strict=True)
        results: list[dict[str, Any]] = []
        for item in categories:
            directory = (root / CATEGORY_DIRS[item]).resolve(strict=True)
            if not directory.is_relative_to(root):
                raise ValueError("Profile directory resolves outside the configured data directory.")
            if item == "application":
                candidates = [directory / name for name in sorted(ROOT_FILES)]
            elif item == "vendor":
                candidates = sorted(directory.rglob("*.ini"))
            else:
                candidates = sorted(directory.glob("*"))

            for path in candidates:
                if path.is_symlink() or not path.is_file() or _is_backup(path.name):
                    continue
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    continue
                results.append(
                    {
                        "category": item,
                        "filename": resolved.relative_to(root).as_posix(),
                        "size_bytes": resolved.stat().st_size,
                        "writable": item in PROFILE_CATEGORIES,
                    }
                )
        return results

    def read_local_profile(self, category: str, filename: str) -> dict[str, Any]:
        path = self._local_path(category, filename)
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"File exceeds the {MAX_FILE_BYTES}-byte read limit.")
        text = data.decode("utf-8")
        return {
            "category": category,
            "filename": path.relative_to(self.settings.local_root.resolve()).as_posix(),
            "sha256": _sha256(data),
            "content": _redact(text),
            "redacted": _has_sensitive_lines(text),
        }

    def search_local_profiles(self, query: str, category: str = "all") -> dict[str, Any]:
        if not query or len(query) > 200:
            raise ValueError("Search query must contain 1 to 200 characters.")
        files = self.list_local_profiles(category)
        matches: list[dict[str, Any]] = []
        query_folded = query.casefold()
        root = self.settings.local_root.resolve(strict=True)
        for item in files:
            path = root / item["filename"]
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                continue
            text = data.decode("utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query_folded in line.casefold():
                    matches.append(
                        {
                            "category": item["category"],
                            "filename": item["filename"],
                            "line": line_number,
                            "text": _redact(line)[:500],
                        }
                    )
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    @contextmanager
    def _sftp(self) -> Iterator[paramiko.SFTPClient]:
        if not self.settings.ssh_host:
            raise ValueError("PRINTER_MCP_SSH_HOST is required.")
        if not self.settings.ssh_key.is_file():
            raise FileNotFoundError(f"SSH key not found: {self.settings.ssh_key}")
        if not self.settings.known_hosts.is_file():
            raise FileNotFoundError(f"SSH known-hosts file not found: {self.settings.known_hosts}")

        client = paramiko.SSHClient()
        client.load_host_keys(str(self.settings.known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=self.settings.ssh_host,
            port=self.settings.ssh_port,
            username=self.settings.ssh_user,
            key_filename=str(self.settings.ssh_key),
            look_for_keys=False,
            allow_agent=False,
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
        )
        sftp = client.open_sftp()
        try:
            yield sftp
        finally:
            sftp.close()
            client.close()

    def _remote_path(self, filename: str) -> str:
        safe_name = _safe_config_name(filename)
        return posixpath.join(str(self.settings.remote_config_dir), safe_name)

    def _resolve_remote_config(
        self, sftp: paramiko.SFTPClient, filename: str, *, writing: bool = False
    ) -> tuple[str, paramiko.SFTPAttributes, bool]:
        safe_name = _safe_config_name(filename)
        logical_path = posixpath.join(str(self.settings.remote_config_dir), safe_name)
        link_attrs = sftp.lstat(logical_path)
        is_symlink = stat.S_ISLNK(link_attrs.st_mode)
        if is_symlink:
            if writing:
                raise ValueError("Symlinked Klipper include files are read-only through the MCP.")
            resolved_path = sftp.normalize(logical_path)
            home = str(self.settings.remote_config_dir.parents[1])
            allowed_roots = (
                str(self.settings.remote_config_dir),
                posixpath.join(home, "mainsail-config"),
                posixpath.join(home, "moonraker-timelapse", "klipper_macro"),
            )
            if not any(
                resolved_path == root or resolved_path.startswith(root.rstrip("/") + "/")
                for root in allowed_roots
            ):
                raise ValueError("Klipper include symlink resolves outside approved config directories.")
        else:
            resolved_path = logical_path
            if posixpath.dirname(resolved_path) != str(self.settings.remote_config_dir):
                raise ValueError("Klipper config resolves outside the configured config directory.")
        attrs = sftp.stat(resolved_path) if is_symlink else link_attrs
        if not stat.S_ISREG(attrs.st_mode):
            raise ValueError("Klipper config must resolve to a regular file.")
        if attrs.st_size > MAX_FILE_BYTES:
            raise ValueError(f"File exceeds the {MAX_FILE_BYTES}-byte read limit.")
        return resolved_path, attrs, is_symlink

    def _read_sftp_file(self, sftp: paramiko.SFTPClient, filename: str) -> bytes:
        resolved_path, attrs, _ = self._resolve_remote_config(sftp, filename)
        with sftp.open(resolved_path, "rb") as remote_file:
            data = remote_file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"File exceeds the {MAX_FILE_BYTES}-byte read limit.")
        if attrs.st_size != len(data):
            raise ValueError("Klipper config changed while it was being read; retry the read.")
        return data

    def _klipper_config_names(self, sftp: paramiko.SFTPClient) -> list[str]:
        pending = ["printer.cfg"]
        discovered: set[str] = set()
        while pending:
            filename = _safe_config_name(pending.pop())
            if filename in discovered:
                continue
            data = self._read_sftp_file(sftp, filename)
            text = data.decode("utf-8")
            discovered.add(filename)
            for line in text.splitlines():
                match = INCLUDE_RE.match(line)
                if not match:
                    continue
                include_name = match.group(1).strip()
                if not CONFIG_NAME_RE.fullmatch(include_name):
                    raise ValueError(f"Unsupported Klipper include directive in {filename}.")
                pending.append(_safe_config_name(include_name))
        return sorted(discovered)

    def _remote_config_names(self, sftp: paramiko.SFTPClient) -> list[str]:
        return sorted(
            entry.filename
            for entry in sftp.listdir_attr(str(self.settings.remote_config_dir))
            if CONFIG_NAME_RE.fullmatch(entry.filename)
            and ".." not in entry.filename
            and not _is_backup(entry.filename)
        )

    def _require_unreferenced(self, sftp: paramiko.SFTPClient, filename: str) -> None:
        if filename == "printer.cfg":
            raise ValueError("printer.cfg cannot be created or deleted through these tools.")
        for source in self._remote_config_names(sftp):
            text = self._read_sftp_file(sftp, source).decode("utf-8")
            for line in text.splitlines():
                match = INCLUDE_RE.match(line)
                if match and fnmatch.fnmatchcase(filename, match.group(1).strip()):
                    raise ValueError(f"The file is referenced by {source}; remove its include first.")

    def list_klipper_config_files(
        self, include_unreferenced: bool = False
    ) -> list[dict[str, Any]]:
        with self._sftp() as sftp:
            active = self._klipper_config_names(sftp)
            names = self._remote_config_names(sftp) if include_unreferenced else active
            result = []
            for filename in names:
                _, attrs, is_symlink = self._resolve_remote_config(sftp, filename)
                data = self._read_sftp_file(sftp, filename)
                result.append(
                    {
                        "filename": filename,
                        "size_bytes": len(data),
                        "sha256": _sha256(data),
                        "writable": not is_symlink,
                        "included": filename in active,
                        "modified": int(attrs.st_mtime),
                    }
                )
            return result

    def read_klipper_config(
        self, filename: str, include_unreferenced: bool = False
    ) -> dict[str, Any]:
        with self._sftp() as sftp:
            allowed = self._klipper_config_names(sftp)
            if filename not in allowed and not include_unreferenced:
                raise ValueError("Only active files included by printer.cfg are available.")
            _, attrs, is_symlink = self._resolve_remote_config(sftp, filename)
            data = self._read_sftp_file(sftp, filename)
        text = data.decode("utf-8")
        return {
            "filename": filename,
            "sha256": _sha256(data),
            "content": _redact(text),
            "redacted": _has_sensitive_lines(text),
            "writable": not is_symlink,
            "included": filename in allowed,
            "modified": int(attrs.st_mtime),
        }

    def _current_config(
        self, target: str, category: str, filename: str, *, writing: bool = False
    ) -> tuple[bytes, Path | None]:
        if target == "prusaslicer":
            path = self._local_path(category, filename, writing=True)
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                raise ValueError(f"File exceeds the {MAX_FILE_BYTES}-byte update limit.")
            return data, path
        if target == "klipper":
            with self._sftp() as sftp:
                if filename not in self._klipper_config_names(sftp):
                    raise ValueError("Only active files included by printer.cfg can be updated.")
                resolved_path, _, _ = self._resolve_remote_config(
                    sftp, filename, writing=writing
                )
                data = self._read_sftp_file(sftp, filename)
                if writing and resolved_path != self._remote_path(filename):
                    raise ValueError("Resolved Klipper config path is not a direct config file.")
            return data, None
        raise ValueError("Target must be 'prusaslicer' or 'klipper'.")

    def preview_config_update(
        self,
        target: str,
        category: str,
        filename: str,
        expected_sha256: str,
        replacement_content: str,
    ) -> dict[str, Any]:
        current, _ = self._current_config(
            target, category, filename, writing=True
        )
        if _sha256(current) != expected_sha256.lower():
            raise ValueError("The file changed since it was read; read it again before proposing an update.")
        old_text = current.decode("utf-8")
        if _has_sensitive_lines(old_text):
            raise ValueError("Sensitive settings make this file read-only through the MCP.")
        replacement = _validate_replacement(replacement_content)
        new_text = replacement.decode("utf-8")
        if _has_sensitive_lines(new_text):
            raise ValueError("Sensitive settings cannot be written through the MCP.")
        replacement_sha256 = _sha256(replacement)
        confirmation = _confirmation_token(
            target, category, filename, _sha256(current), replacement_sha256
        )
        diff = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"current/{filename}",
                tofile=f"proposed/{filename}",
            )
        )
        return {
            "target": target,
            "filename": filename,
            "expected_sha256": _sha256(current),
            "replacement_sha256": replacement_sha256,
            "confirmation_token": confirmation,
            "diff": diff or "(no changes)",
            "apply_requires_explicit_confirmation": True,
            "klipper_will_not_be_restarted": target == "klipper",
        }

    def apply_config_update(
        self,
        target: str,
        category: str,
        filename: str,
        expected_sha256: str,
        replacement_content: str,
        confirmation_token: str,
        confirmed: bool,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise ValueError("Set confirmed=true only after reviewing the proposed diff.")
        replacement = _validate_replacement(replacement_content)
        current, local_path = self._current_config(
            target, category, filename, writing=True
        )
        if _sha256(current) != expected_sha256.lower():
            raise ValueError("The file changed since preview; no changes were written.")
        if _has_sensitive_lines(current.decode("utf-8")) or _has_sensitive_lines(
            replacement.decode("utf-8")
        ):
            raise ValueError("Sensitive settings make this file read-only through the MCP.")
        replacement_sha256 = _sha256(replacement)
        expected_confirmation = _confirmation_token(
            target, category, filename, _sha256(current), replacement_sha256
        )
        if confirmation_token != expected_confirmation:
            raise ValueError("Confirmation token does not match the reviewed file and replacement.")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{filename}.before-printer-mcp-{stamp}-{uuid.uuid4().hex[:8]}"
        if local_path is not None:
            backup = local_path.with_name(backup_name)
            current_mode = stat.S_IMODE(local_path.stat().st_mode)
            backup.write_bytes(current)
            os.chmod(backup, current_mode)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{filename}.printer-mcp-",
                suffix=".tmp",
                dir=local_path.parent,
            )
            try:
                with os.fdopen(fd, "wb") as temp_file:
                    temp_file.write(replacement)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.chmod(temp_name, current_mode)
                if _sha256(local_path.read_bytes()) != expected_sha256.lower():
                    raise ValueError("The file changed during apply; no changes were written.")
                os.replace(temp_name, local_path)
            except OSError:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                raise
            except ValueError:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                backup.unlink(missing_ok=True)
                raise
        else:
            with self._sftp() as sftp:
                if filename not in self._klipper_config_names(sftp):
                    raise ValueError("Only active files included by printer.cfg can be updated.")
                remote_path = self._remote_path(filename)
                self._resolve_remote_config(sftp, filename, writing=True)
                current = self._read_sftp_file(sftp, filename)
                if _sha256(current) != expected_sha256.lower():
                    raise ValueError("The file changed during apply; no changes were written.")
                backup_path = posixpath.join(str(self.settings.remote_config_dir), backup_name)
                temp_path = posixpath.join(
                    str(self.settings.remote_config_dir),
                    f".{filename}.printer-mcp-{uuid.uuid4().hex}.tmp",
                )
                holding_path = posixpath.join(
                    str(self.settings.remote_config_dir),
                    f".{filename}.printer-mcp-{uuid.uuid4().hex}.old",
                )
                mode = stat.S_IMODE(sftp.lstat(remote_path).st_mode)
                backup_created = False
                temp_created = False
                original_moved = False
                try:
                    with sftp.open(backup_path, "wxb") as backup_file:
                        backup_file.write(current)
                    backup_created = True
                    sftp.chmod(backup_path, mode)
                    with sftp.open(temp_path, "wb") as temp_file:
                        temp_file.write(replacement)
                    temp_created = True
                    sftp.chmod(temp_path, mode)
                    if _sha256(self._read_sftp_file(sftp, filename)) != expected_sha256.lower():
                        raise ValueError("The file changed during apply; no changes were written.")
                    sftp.rename(remote_path, holding_path)
                    original_moved = True
                    try:
                        sftp.rename(temp_path, remote_path)
                    except OSError:
                        try:
                            sftp.rename(holding_path, remote_path)
                            original_moved = False
                        except OSError as restore_error:
                            raise RuntimeError(
                                f"Apply failed and the original could not be restored; "
                                f"preserve {holding_path} and {backup_path} for recovery."
                            ) from restore_error
                        raise
                    temp_created = False
                    try:
                        sftp.remove(holding_path)
                    except OSError as cleanup_error:
                        raise RuntimeError(
                            f"Config was updated, but temporary recovery file remains at {holding_path}."
                        ) from cleanup_error
                    original_moved = False
                except OSError:
                    if temp_created:
                        sftp.remove(temp_path)
                    if backup_created and not original_moved:
                        sftp.remove(backup_path)
                    raise
                except ValueError:
                    if temp_created:
                        sftp.remove(temp_path)
                    if backup_created and not original_moved:
                        sftp.remove(backup_path)
                    raise
        return {
            "target": target,
            "filename": filename,
            "backup": backup_name,
            "sha256": replacement_sha256,
            "written": True,
            "printer_restarted": False,
        }

    def _file_proposal(
        self, operation: str, target: str, category: str, filename: str, digest: str,
        confirmation_token: str | None = None, confirmed: bool = False,
    ) -> str:
        with self._proposal_lock:
            now = time.monotonic()
            self._file_proposals = {
                token: proposal for token, proposal in self._file_proposals.items()
                if proposal[0] > now
            }
            binding = (operation, target, category, filename, digest)
            if confirmation_token is not None:
                if confirmed is not True:
                    raise ValueError("Explicit confirmation is required after reviewing the preview.")
                proposal = self._file_proposals.get(confirmation_token)
                if proposal is None or proposal[1] != binding:
                    raise ValueError("Preview token is expired, used, or does not match this operation.")
                del self._file_proposals[confirmation_token]
                return confirmation_token
            if len(self._file_proposals) >= 100:
                raise ValueError("Too many pending previews; wait for them to expire.")
            token = uuid.uuid4().hex
            self._file_proposals[token] = (now + 600, binding)
            return token

    def _lifecycle_local_path(
        self, category: str, filename: str, *, creating: bool = False
    ) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*\.ini", filename) or ".." in filename:
            raise ValueError("Profile creation/deletion requires a plain .ini user-profile filename.")
        if category not in PROFILE_CATEGORIES:
            raise ValueError("Only user-profile categories support creation/deletion.")
        if (self.settings.local_root / CATEGORY_DIRS[category]).is_symlink():
            raise ValueError("Symlinked profile directories cannot be changed through these tools.")
        return self._local_path(category, filename, writing=True, creating=creating)

    def _require_remote_missing(self, sftp: paramiko.SFTPClient, filename: str) -> None:
        path = self._remote_path(filename)
        try:
            sftp.lstat(path)
        except OSError as error:
            if error.errno != errno.ENOENT:
                raise
        else:
            raise FileExistsError("The config already exists; use preview_config_update.")
        self._require_unreferenced(sftp, filename)

    def preview_config_create(
        self, target: str, category: str, filename: str, content: str
    ) -> dict[str, Any]:
        data = _validate_replacement(content)
        if _has_sensitive_lines(content):
            raise ValueError("Sensitive settings cannot be created through the MCP.")
        if target == "prusaslicer":
            self._lifecycle_local_path(category, filename, creating=True)
        elif target == "klipper":
            if category:
                raise ValueError("Use an empty category for Klipper.")
            with self._sftp() as sftp:
                self._require_remote_missing(sftp, filename)
        else:
            raise ValueError("Target must be 'prusaslicer' or 'klipper'.")
        digest = _sha256(data)
        return {
            "target": target, "category": category, "filename": filename,
            "sha256": digest,
            "confirmation_token": self._file_proposal(
                "create", target, category, filename, digest
            ),
            "diff": "".join(difflib.unified_diff(
                [], content.splitlines(keepends=True),
                fromfile="/dev/null", tofile=f"proposed/{filename}",
            )),
            "expires_in_seconds": 600,
            "apply_requires_explicit_confirmation": True,
            "automatically_activated": False,
        }

    def apply_config_create(
        self, target: str, category: str, filename: str, content: str,
        confirmation_token: str, confirmed: bool = False,
    ) -> dict[str, Any]:
        data = _validate_replacement(content)
        if _has_sensitive_lines(content):
            raise ValueError("Sensitive settings cannot be created through the MCP.")
        digest = _sha256(data)
        self._file_proposal(
            "create", target, category, filename, digest, confirmation_token, confirmed
        )
        if target == "prusaslicer":
            path = self._lifecycle_local_path(category, filename, creating=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{filename}.printer-mcp-", suffix=".tmp", dir=path.parent
            )
            try:
                with os.fdopen(fd, "wb") as temp_file:
                    temp_file.write(data)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.chmod(temp_name, 0o644)
                os.link(temp_name, path)
            finally:
                os.unlink(temp_name)
        elif target == "klipper":
            with self._sftp() as sftp:
                self._require_remote_missing(sftp, filename)
                path = self._remote_path(filename)
                temp_path = posixpath.join(
                    str(self.settings.remote_config_dir),
                    f".{filename}.printer-mcp-{uuid.uuid4().hex}.tmp",
                )
                temp_created = False
                try:
                    with sftp.open(temp_path, "wxb") as remote_file:
                        temp_created = True
                        remote_file.write(data)
                    sftp.chmod(temp_path, 0o644)
                    with sftp.open(temp_path, "rb") as remote_file:
                        if remote_file.read(MAX_FILE_BYTES + 1) != data:
                            raise ValueError("Remote create read-back failed; no config was installed.")
                    self._require_remote_missing(sftp, filename)
                    sftp.rename(temp_path, path)
                except (OSError, ValueError):
                    if temp_created:
                        sftp.remove(temp_path)
                    raise
        else:
            raise ValueError("Target must be 'prusaslicer' or 'klipper'.")
        return {
            "target": target, "category": category, "filename": filename,
            "created": True, "sha256": digest, "printer_restarted": False,
            "automatically_activated": False,
        }

    def _deletion_content(
        self, target: str, category: str, filename: str,
        sftp: paramiko.SFTPClient | None = None,
    ) -> tuple[bytes, Path | None]:
        if target == "prusaslicer":
            path = self._lifecycle_local_path(category, filename)
            data = path.read_bytes()
        elif target == "klipper":
            if category:
                raise ValueError("Use an empty category for Klipper.")
            if sftp is None:
                with self._sftp() as connection:
                    return self._deletion_content(target, category, filename, connection)
            self._resolve_remote_config(sftp, filename, writing=True)
            self._require_unreferenced(sftp, filename)
            data = self._read_sftp_file(sftp, filename)
            path = None
        else:
            raise ValueError("Target must be 'prusaslicer' or 'klipper'.")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("File exceeds the deletion read limit.")
        if _has_sensitive_lines(data.decode("utf-8")):
            raise ValueError("Sensitive settings make this file read-only through the MCP.")
        return data, path

    def preview_config_delete(
        self, target: str, category: str, filename: str, expected_sha256: str
    ) -> dict[str, Any]:
        data, _ = self._deletion_content(target, category, filename)
        digest = _sha256(data)
        if digest != expected_sha256.lower():
            raise ValueError("The file changed; read it again before previewing deletion.")
        return {
            "target": target, "category": category, "filename": filename,
            "expected_sha256": digest,
            "confirmation_token": self._file_proposal(
                "delete", target, category, filename, digest
            ),
            "diff": "".join(difflib.unified_diff(
                data.decode("utf-8").splitlines(keepends=True), [],
                fromfile=f"current/{filename}", tofile="/dev/null",
            )),
            "expires_in_seconds": 600,
            "backup_will_be_retained": True,
            "apply_requires_explicit_confirmation": True,
        }

    def apply_config_delete(
        self, target: str, category: str, filename: str, expected_sha256: str,
        confirmation_token: str, confirmed: bool = False,
    ) -> dict[str, Any]:
        digest = expected_sha256.lower()
        self._file_proposal(
            "delete", target, category, filename, digest, confirmation_token, confirmed
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{filename}.before-printer-mcp-delete-{stamp}-{uuid.uuid4().hex[:8]}"
        if target == "prusaslicer":
            data, path = self._deletion_content(target, category, filename)
            if _sha256(data) != digest:
                raise ValueError("The file changed since preview; nothing was deleted.")
            if path is None:
                raise ValueError("Missing local deletion path.")
            backup = path.with_name(backup_name)
            with backup.open("xb") as backup_file:
                backup_file.write(data)
                backup_file.flush()
                os.fsync(backup_file.fileno())
            os.chmod(backup, stat.S_IMODE(path.stat().st_mode))
            current, _ = self._deletion_content(target, category, filename)
            if _sha256(current) != digest or backup.read_bytes() != data:
                raise ValueError("Deletion verification failed; original and backup were retained.")
            path.unlink()
        elif target == "klipper":
            with self._sftp() as sftp:
                data, _ = self._deletion_content(target, category, filename, sftp)
                if _sha256(data) != digest:
                    raise ValueError("The file changed since preview; nothing was deleted.")
                path = self._remote_path(filename)
                backup = posixpath.join(str(self.settings.remote_config_dir), backup_name)
                with sftp.open(backup, "wxb") as backup_file:
                    backup_file.write(data)
                sftp.chmod(backup, stat.S_IMODE(sftp.lstat(path).st_mode))
                with sftp.open(backup, "rb") as backup_file:
                    if backup_file.read(MAX_FILE_BYTES + 1) != data:
                        raise ValueError("Backup verification failed; original was not deleted.")
                current, _ = self._deletion_content(target, category, filename, sftp)
                if _sha256(current) != digest:
                    raise ValueError("The file changed during deletion; original was retained.")
                sftp.remove(path)
        else:
            raise ValueError("Target must be 'prusaslicer' or 'klipper'.")
        return {
            "target": target, "category": category, "filename": filename,
            "deleted": True, "backup": backup_name, "sha256": digest,
            "printer_restarted": False,
        }


server = PrinterMcp()
mcp = FastMCP("HOBBY-COREXY Printer")


@mcp.tool()
def list_local_profiles(category: str = "all") -> list[dict[str, Any]]:
    """List active PrusaSlicer profiles and setup files. Categories: printer, physical_printer, print, filament, application, vendor, or all. Backups and .git are excluded."""
    return server.list_local_profiles(category)


@mcp.tool()
def read_local_profile(category: str, filename: str) -> dict[str, Any]:
    """Read one PrusaSlicer profile or setup file by category and basename. Secret-like values are redacted."""
    return server.read_local_profile(category, filename)


@mcp.tool()
def search_local_profiles(query: str, category: str = "all") -> dict[str, Any]:
    """Search active local PrusaSlicer text profiles and setup files. Secret-like values are redacted."""
    return server.search_local_profiles(query, category)


@mcp.tool()
def list_klipper_config_files(include_unreferenced: bool = False) -> list[dict[str, Any]]:
    """List active Klipper includes. Set include_unreferenced=true to also inspect staged .cfg files in the config folder. Backups and Moonraker settings are excluded."""
    return server.list_klipper_config_files(include_unreferenced)


@mcp.tool()
def read_klipper_config(
    filename: str, include_unreferenced: bool = False
) -> dict[str, Any]:
    """Read an active Klipper config. Set include_unreferenced=true for a staged .cfg file. Secret-like values are redacted."""
    return server.read_klipper_config(filename, include_unreferenced)


@mcp.tool()
def preview_config_update(
    target: str,
    category: str,
    filename: str,
    expected_sha256: str,
    replacement_content: str,
) -> dict[str, Any]:
    """Preview a full-file replacement for an active user profile or included Klipper config. No file is written."""
    return server.preview_config_update(
        target, category, filename, expected_sha256, replacement_content
    )


@mcp.tool()
def apply_config_update(
    target: str,
    category: str,
    filename: str,
    expected_sha256: str,
    replacement_content: str,
    confirmation_token: str,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Apply the exact reviewed profile/config replacement only with confirmed=true, its preview token, and the current SHA-256. A backup is made; Klipper is never restarted."""
    return server.apply_config_update(
        target,
        category,
        filename,
        expected_sha256,
        replacement_content,
        confirmation_token,
        confirmed,
    )


@mcp.tool()
def preview_config_create(
    target: str, category: str, filename: str, content: str
) -> dict[str, Any]:
    """Preview creating a new .ini user profile or unreferenced Klipper .cfg. Target: prusaslicer or klipper; category is empty for klipper. Never includes/activates a config."""
    return server.preview_config_create(target, category, filename, content)


@mcp.tool()
def apply_config_create(
    target: str, category: str, filename: str, content: str,
    confirmation_token: str, confirmed: bool = False,
) -> dict[str, Any]:
    """Create the exact previewed file with explicit user confirmation and its unused 10-minute token. Refuses existing files. Does not activate configs or restart Klipper."""
    return server.apply_config_create(
        target, category, filename, content, confirmation_token, confirmed
    )


@mcp.tool()
def preview_config_delete(
    target: str, category: str, filename: str, expected_sha256: str
) -> dict[str, Any]:
    """Preview deletion of a .ini user profile or unreferenced Klipper .cfg. Requires current hash; forbids printer.cfg, referenced configs, symlinks, and backups."""
    return server.preview_config_delete(target, category, filename, expected_sha256)


@mcp.tool()
def apply_config_delete(
    target: str, category: str, filename: str, expected_sha256: str,
    confirmation_token: str, confirmed: bool = False,
) -> dict[str, Any]:
    """Delete the exact previewed file after explicit user confirmation with current hash and unused 10-minute token. Retains a verified recovery backup. Never restarts Klipper."""
    return server.apply_config_delete(
        target, category, filename, expected_sha256, confirmation_token, confirmed
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
