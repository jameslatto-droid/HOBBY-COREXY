#!/usr/bin/env python3
"""Apply only the COREXY Mainsail visual theme block.

This script changes `.theme/custom.css` through Moonraker and nothing else.
It performs no G-code, movement, homing, probing, levelling, heating, restart,
or Mainsail layout/database changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import sys

from install import (
    MANAGED_CSS_BEGIN,
    MANAGED_CSS_END,
    Moonraker,
    replace_managed_block,
    write_backup,
)


def source_block() -> str:
    path = Path(__file__).resolve().with_name("custom.css")
    text = path.read_text(encoding="utf-8")

    start = text.find(MANAGED_CSS_BEGIN)
    finish = text.find(MANAGED_CSS_END)
    if start == -1 or finish == -1 or finish < start:
        raise RuntimeError(
            f"{path.name} does not contain the expected managed CSS markers"
        )

    finish += len(MANAGED_CSS_END)
    return text[start:finish]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the COREXY visual theme to Mainsail only."
    )
    parser.add_argument(
        "--moonraker", default="http://192.168.1.203", help="Moonraker base URL"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MOONRAKER_API_KEY"),
        help="Moonraker API key, if required",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    client = Moonraker(args.moonraker, args.api_key, args.timeout)
    block = source_block()

    print(f"Connecting to {client.base} ...")
    existing = client.get_file("config", ".theme/custom.css", missing_ok=True) or ""
    patched = replace_managed_block(
        existing,
        MANAGED_CSS_BEGIN,
        MANAGED_CSS_END,
        block,
    )

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(__file__).resolve().parent / "backups" / stamp
    write_backup(backup_dir, "custom.css.before.txt", existing)
    write_backup(backup_dir, "custom.css.generated.txt", patched)

    if patched == existing:
        print("Theme is already current; no remote write required.")
        print(f"Local backup: {backup_dir}")
        return 0

    client.upload_text("config", ".theme/custom.css", patched)

    print("THEME APPLIED.")
    print(f"Local backup: {backup_dir}")
    print("No Klipper configuration or printer command was changed or run.")
    print("No FIRMWARE_RESTART is required; hard-refresh Mainsail in the browser.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
