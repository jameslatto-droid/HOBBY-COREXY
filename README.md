# HOBBY-COREXY Printer MCP

A separate ChatGPT MCP for inspecting the PrusaSlicer production profiles and
the Klipper configuration on the printer Pi. It runs on the JL-System server
and bridges to the Pi over a pinned SSH host key and SFTP-only account. It
does not use Brain as a filesystem proxy.

## Capabilities

- List, search, and read active local PrusaSlicer profiles, setup files, and
  vendor presets. Git metadata and backup files are excluded.
- Read `printer.cfg` and the `.cfg` files it includes, including the two
  in-home Mainsail/timelapse symlink targets. Moonraker settings are not
  exposed.
- Preview a full-file replacement before applying it. Apply requires the
  current SHA-256, the preview's confirmation token, and `confirmed=true`.
  A timestamped backup is retained. Symlinked config files are read-only.
- Never run remote shell commands, reload Klipper, move or heat the printer,
  or start a print.
- Secret-like settings are redacted; a file containing such a setting cannot
  be updated through the MCP.

The PrusaSlicer app preferences and Klipper/Moonraker secrets are not writable
through this service. Do not edit the shared profile files through MCP while
PrusaSlicer is open on another machine.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

See [operations](docs/OPERATIONS.md) for the server bridge and
[validation](docs/VALIDATION.md) for acceptance checks.
