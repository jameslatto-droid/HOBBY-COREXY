from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import posixpath
import sys
import uuid
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from printer_mcp.server import PrinterMcp, Settings


async def call(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content}")
    if result.structuredContent is None:
        raise RuntimeError(f"{name} returned no structured result.")
    return result.structuredContent


async def verify(session: ClientSession, settings: Settings) -> None:
    checker = PrinterMcp(settings)
    local_before = {
        item["filename"]: hashlib.sha256(
            (settings.local_root / item["filename"]).read_bytes()
        ).hexdigest()
        for item in (await call(session, "list_local_profiles", {}))["result"]
    }
    remote_before = {
        item["filename"]: item["sha256"]
        for item in (await call(session, "list_klipper_config_files", {}))["result"]
    }
    suffix = uuid.uuid4().hex
    content = f"# Disposable MCP file lifecycle test {suffix}\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    for target, category, extension in (
        ("prusaslicer", "printer", ".ini"), ("klipper", "", ".cfg"),
    ):
        filename = f"printer-mcp-test-{suffix}{extension}"
        arguments = {"target": target, "category": category, "filename": filename}
        created = False
        print(f"Testing {target}: {filename}", flush=True)
        try:
            preview = await call(
                session, "preview_config_create", {**arguments, "content": content}
            )
            creation = await call(session, "apply_config_create", {
                **arguments, "content": content,
                "confirmation_token": preview["confirmation_token"], "confirmed": True,
            })
            created = True
            if creation["created"] is not True or creation["sha256"] != digest:
                raise RuntimeError(f"{target}: create result did not match test content.")
            if target == "prusaslicer":
                read = await call(session, "read_local_profile", {
                    "category": category, "filename": filename,
                })
            else:
                read = await call(session, "read_klipper_config", {
                    "filename": filename, "include_unreferenced": True,
                })
            if read["content"] != content or read["sha256"] != digest:
                raise RuntimeError(f"{target}: test-file read-back failed.")
        finally:
            if created:
                preview = await call(session, "preview_config_delete", {
                    **arguments, "expected_sha256": digest,
                })
                deletion = await call(session, "apply_config_delete", {
                    **arguments, "expected_sha256": digest,
                    "confirmation_token": preview["confirmation_token"], "confirmed": True,
                })
                if deletion["deleted"] is not True:
                    raise RuntimeError(f"{target}: test-file deletion was not confirmed.")
                if target == "prusaslicer":
                    path = settings.local_root / category / filename
                    if os.path.lexists(path):
                        raise RuntimeError("Local test filename remains after deletion.")
                    backup = path.with_name(deletion["backup"])
                    backup_content = backup.read_bytes()
                else:
                    with checker._sftp() as sftp:
                        if filename in sftp.listdir(str(settings.remote_config_dir)):
                            raise RuntimeError("Remote test filename remains after deletion.")
                        backup = posixpath.join(
                            str(settings.remote_config_dir), deletion["backup"]
                        )
                        with sftp.open(backup, "rb") as backup_file:
                            backup_content = backup_file.read(len(content.encode()) + 1)
                if backup_content != content.encode():
                    raise RuntimeError(f"{target}: retained backup does not match test bytes.")
                print(f"PASS {target}: created, read back, deleted {filename}")
                print(f"Retained verified backup: {backup}")
    local_after = {
        item["filename"]: hashlib.sha256(
            (settings.local_root / item["filename"]).read_bytes()
        ).hexdigest()
        for item in (await call(session, "list_local_profiles", {}))["result"]
    }
    remote_after = {
        item["filename"]: item["sha256"]
        for item in (await call(session, "list_klipper_config_files", {}))["result"]
    }
    if local_after != local_before or remote_after != remote_before:
        raise RuntimeError("Pre-existing profile/config hashes or active inventories changed.")
    print("PASS: all pre-existing profiles and active Klipper configs are unchanged.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit live disposable MCP create/delete test.")
    parser.add_argument("--live", action="store_true", help="Authorize two disposable file tests.")
    arguments = parser.parse_args()
    if not arguments.live:
        parser.error("--live is required; this test writes to the configured live locations.")
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "printer_mcp.server"], env=dict(os.environ)
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            await verify(session, Settings.from_env())


if __name__ == "__main__":
    asyncio.run(main())
