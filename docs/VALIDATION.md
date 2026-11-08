# Validation

## Repository checks

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q printer_mcp tests
```

The tests cover path confinement, backup exclusion, redaction, preview
confirmation, stale-hash rejection, and backup creation. Local and fake-SFTP
fixtures also cover create/read/delete, exclusive creation, expired/consumed
tokens, protected references, symlinks, remote failures, and the SFTP write
flag required for exclusive backup creation. They do not write to the live
printer.

## Live read-only acceptance

With the restricted SFTP key installed and the printer reachable:

1. `list_local_profiles` returns active profile files, not `.git` or backups.
2. `list_klipper_config_files` returns only `printer.cfg` and recursive
   includes. Symlinked Mainsail/timelapse files report `writable=false`.
3. `read_klipper_config` returns no unredacted secret-like values.
4. A preview is non-writing; an apply without `confirmed=true`, a matching
   confirmation token, or the expected SHA-256 is rejected.
5. A confirmed disposable profile-fixture update creates a backup. Never
   replace or delete an existing live printer config as a write test.

## Explicit live create/delete acceptance

Only with operator authorization, use comment-only uniquely named `.ini` and
`.cfg` files for live tests. Do not add a Klipper include or select a profile.
Use the MCP preview/create/read/preview-delete/delete sequence, check the
returned hashes against the test content, and verify the original filenames
are absent afterward. Read the new Klipper file with
`include_unreferenced=true`. Verify both recovery backups match the test
content and all pre-existing active config hashes remain unchanged. Retain
the deletion backups; do not remove production evidence to clean a test.

The repeatable stdio MCP check is:

```bash
set -a
. /home/james/.config/hobby-printer-mcp.env
set +a
.venv/bin/python scripts/verify-file-lifecycle.py --live
```

This exercises the real MCP transport and live SFTP key, not a raw
filesystem workaround. The explicit `--live` flag authorizes only creation
and deletion of the script's unique disposable filenames.

## Tunnel acceptance

Use the dedicated ChatGPT connector and verify tool discovery plus read-only
profile/config inspection. Confirm the local tunnel health listener remains
bound only to `127.0.0.1:18084`. Do not test by starting a print, moving the
printer, heating it, or reloading Klipper.
