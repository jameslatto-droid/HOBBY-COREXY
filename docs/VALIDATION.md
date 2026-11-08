# Validation

## Repository checks

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q printer_mcp tests
```

The tests cover path confinement, backup exclusion, redaction, preview
confirmation, stale-hash rejection, and backup creation. They do not write to
the live printer.

## Live read-only acceptance

With the restricted SFTP key installed and the printer reachable:

1. `list_local_profiles` returns active profile files, not `.git` or backups.
2. `list_klipper_config_files` returns only `printer.cfg` and recursive
   includes. Symlinked Mainsail/timelapse files report `writable=false`.
3. `read_klipper_config` returns no unredacted secret-like values.
4. A preview is non-writing; an apply without `confirmed=true`, a matching
   confirmation token, or the expected SHA-256 is rejected.
5. A confirmed disposable profile-fixture update creates a backup. Never run
   a write acceptance test against the live printer config.

## Tunnel acceptance

Use the dedicated ChatGPT connector and verify tool discovery plus read-only
profile/config inspection. Confirm the local tunnel health listener remains
bound only to `127.0.0.1:18084`. Do not test by starting a print, moving the
printer, heating it, or reloading Klipper.
