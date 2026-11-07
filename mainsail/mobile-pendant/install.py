#!/usr/bin/env python3
"""
Install an upgrade-safe, mobile-only Mainsail "pendant" dashboard.

Changes only Mainsail mobile layout, a dedicated Probe & Level macro group,
one managed Klipper include, and one managed mobile CSS block.

The installer NEVER runs motion, homing, probing, levelling, heaters, restart,
SAVE_CONFIG, or individual Z-motor commands.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

MANAGED_CFG_BEGIN = "# BEGIN COREXY MOBILE PENDANT"
MANAGED_CFG_END = "# END COREXY MOBILE PENDANT"
MANAGED_CSS_BEGIN = "/* BEGIN COREXY MOBILE PENDANT */"
MANAGED_CSS_END = "/* END COREXY MOBILE PENDANT */"
MOBILE_CFG_NAME = "mainsail-mobile.cfg"
GROUP_ID = "6fefb78c-4cf4-4e77-9b37-17d2cd58a2fb"
GROUP_PANEL = f"macrogroup_{GROUP_ID}"

STANDARD_MOBILE_PANELS = [
    "dashboard-settings", "webcam", "toolhead-control", "extruder-control",
    "macros", "temperature", "miniconsole", "gcode-file-card", "gcode-files",
    "machine-settings", "heightmap", "timelapse", "spoolman",
]

FEATURES = [
    ("probe", "MOBILE_PROBE_ACCURACY", "PROBE_ACCURACY"),
    ("bltouch", "MOBILE_PROBE_ACCURACY", "PROBE_ACCURACY"),
    ("bed_mesh", "MOBILE_BED_MESH_CALIBRATE", "BED_MESH_CALIBRATE"),
    ("bed_mesh", "MOBILE_BED_MESH_CLEAR", "BED_MESH_CLEAR"),
    ("quad_gantry_level", "MOBILE_QUAD_GANTRY_LEVEL", "QUAD_GANTRY_LEVEL"),
    ("z_tilt", "MOBILE_Z_TILT_ADJUST", "Z_TILT_ADJUST"),
    ("z_tilt_ng", "MOBILE_Z_TILT_ADJUST", "Z_TILT_ADJUST"),
    ("screws_tilt_adjust", "MOBILE_SCREWS_TILT_CALCULATE", "SCREWS_TILT_CALCULATE"),
    ("bed_tilt", "MOBILE_BED_TILT_CALIBRATE", "BED_TILT_CALIBRATE"),
]

CSS_BLOCK = r"""/* BEGIN COREXY MOBILE PENDANT */
@media (max-width: 767.98px) {
  .toolhead-control-panel .v-btn,
  .extruder-control-panel .v-btn,
  .temperature-panel .v-btn,
  .macrogroup_6fefb78c-4cf4-4e77-9b37-17d2cd58a2fb_panel .v-btn {
    min-width: 48px;
    min-height: 48px;
    font-size: 1rem;
  }

  .toolhead-control-panel input,
  .extruder-control-panel input,
  .temperature-panel input {
    min-height: 44px;
    font-size: 16px;
  }

  .toolhead-control-panel .v-input,
  .extruder-control-panel .v-input,
  .temperature-panel .v-input {
    font-size: 16px;
  }

  .toolhead-control-panel .v-card__text,
  .extruder-control-panel .v-card__text,
  .temperature-panel .v-card__text {
    padding-left: 12px;
    padding-right: 12px;
  }
}
/* END COREXY MOBILE PENDANT */"""

def unwrap(value):
    if isinstance(value, dict) and "result" in value and len(value) == 1:
        return value["result"]
    return value

class Moonraker:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 10.0):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, extra=None):
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    def request(self, method: str, path: str, *, data=None, headers=None, expect_json=True):
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=self._headers(headers)
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
                if not expect_json:
                    return body
                if not body:
                    return None
                return unwrap(json.loads(body.decode("utf-8")))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach Moonraker at {self.base}: {exc.reason}") from exc

    def get_json(self, path):
        return self.request("GET", path)

    def post_json(self, path, payload):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return self.request(
            "POST", path, data=body, headers={"Content-Type": "application/json"}
        )

    def get_file(self, root: str, rel_path: str, *, missing_ok=False):
        quoted = urllib.parse.quote(rel_path, safe="/")
        try:
            data = self.request(
                "GET", f"/server/files/{root}/{quoted}", expect_json=False
            )
            return data.decode("utf-8")
        except RuntimeError as exc:
            if missing_ok and "HTTP 404" in str(exc):
                return None
            raise

    def upload_text(self, root: str, rel_path: str, text: str):
        rel = Path(rel_path.replace("\\", "/"))
        filename = rel.name
        folder = str(rel.parent).replace("\\", "/")
        if folder == ".":
            folder = ""

        boundary = "----corexypendant" + uuid.uuid4().hex
        parts = []

        def add_field(name, value):
            parts.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ])

        add_field("root", root)
        if folder:
            add_field("path", folder)

        payload = text.encode("utf-8")
        add_field("checksum", hashlib.sha256(payload).hexdigest())
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
            payload,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])
        return self.request(
            "POST",
            "/server/files/upload",
            data=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def db_get(self, key: str, *, missing_ok=False):
        query = urllib.parse.urlencode({"namespace": "mainsail", "key": key})
        try:
            obj = self.get_json("/server/database/item?" + query)
            return obj["value"] if isinstance(obj, dict) and "value" in obj else obj
        except RuntimeError as exc:
            if missing_ok and (
                "HTTP 404" in str(exc) or "not found" in str(exc).lower()
            ):
                return None
            raise

    def db_set(self, key: str, value):
        return self.post_json(
            "/server/database/item",
            {"namespace": "mainsail", "key": key, "value": value},
        )

def replace_managed_block(text: str, begin: str, end: str, block: str) -> str:
    start = text.find(begin)
    finish = text.find(end)
    if start != -1 and finish != -1 and finish >= start:
        finish += len(end)
        before = text[:start].rstrip()
        after = text[finish:].lstrip()
        result = (before + "\n\n" if before else "") + block.strip()
        if after:
            result += "\n\n" + after
        return result.rstrip() + "\n"
    save_config_marker = "#*# <---------------------- SAVE_CONFIG ---------------------->"
    marker_start = text.find(save_config_marker)
    if marker_start != -1:
        before = text[:marker_start].rstrip()
        after = text[marker_start:].lstrip()
        result = (before + "\n\n" if before else "") + block.strip()
        return result + "\n\n" + after.rstrip() + "\n"
    base = text.rstrip()
    return (base + "\n\n" if base else "") + block.strip() + "\n"

def config_include_block():
    return (
        f"{MANAGED_CFG_BEGIN}\n"
        f"[include {MOBILE_CFG_NAME}]\n"
        f"{MANAGED_CFG_END}"
    )

def detect_objects(client: Moonraker, main_cfg: str):
    try:
        result = client.get_json("/printer/objects/list")
        objects = set(result.get("objects", [])) if isinstance(result, dict) else set()
        normalized = {item.split()[0].lower() for item in objects}
        if normalized:
            return normalized, "Moonraker printer object list"
    except RuntimeError:
        pass

    normalized = set()
    for line in main_cfg.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            normalized.add(line[1:-1].strip().lower().split()[0])
    return normalized, "main config sections (fallback; includes may be missed)"

def select_macros(objects: set[str]):
    selected, seen = [], set()
    for object_name, wrapper, command in FEATURES:
        if object_name in objects and wrapper not in seen:
            selected.append((wrapper, command))
            seen.add(wrapper)
    return selected

def render_macro_cfg(macros):
    lines = [
        "# Generated by COREXY Mainsail Mobile Pendant installer.",
        "# Wrappers expose existing Klipper calibration commands only.",
        "# No auto-home, SAVE_CONFIG, restart, or individual Z-motor control.",
        "",
    ]
    if not macros:
        lines += [
            "# No supported probe/levelling objects were detected.",
            "# Re-run the installer after those Klipper sections are loaded.",
        ]
    for wrapper, command in macros:
        lines += [
            f"[gcode_macro {wrapper}]",
            f"description: Mobile pendant: {command.replace('_', ' ').title()}",
            "gcode:",
            f"    {command}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"

def build_macro_group(macros):
    buttons = []
    for pos, (wrapper, _command) in enumerate(macros, start=1):
        buttons.append({
            "pos": pos,
            "name": wrapper,
            "color": "group",
            "showInStandby": True,
            "showInPrinting": False,
            "showInPause": False,
        })
    return {
        "id": GROUP_ID,
        "name": "Probe & Level",
        "color": "primary",
        "showInStandby": True,
        "showInPrinting": False,
        "showInPause": False,
        "macros": buttons,
    }

def build_mobile_layout(existing):
    wanted = [
        {"name": "dashboard-settings", "visible": True},
        {"name": "toolhead-control", "visible": True},
        {"name": "extruder-control", "visible": True},
        {"name": "temperature", "visible": True},
        {"name": GROUP_PANEL, "visible": True},
        {"name": "macros", "visible": False},
    ]
    used = {item["name"] for item in wanted}
    names = list(STANDARD_MOBILE_PANELS)
    if isinstance(existing, list):
        names.extend(
            item.get("name")
            for item in existing
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
    for name in names:
        if name and name not in used:
            wanted.append({"name": name, "visible": False})
            used.add(name)
    return wanted

def config_relative_path(client: Moonraker, printer_info, override):
    if override:
        return override.replace("\\", "/")
    config_file = printer_info.get("config_file") or printer_info.get("configfile")
    if not config_file:
        return "printer.cfg"
    try:
        roots = client.get_json("/server/files/roots")
        if isinstance(roots, dict) and "roots" in roots:
            roots = roots["roots"]
        for root in roots or []:
            if root.get("name") != "config":
                continue
            root_path = os.path.normpath(root.get("path", ""))
            cfg_path = os.path.normpath(config_file)
            try:
                rel = os.path.relpath(cfg_path, root_path)
            except ValueError:
                break
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
    except RuntimeError:
        pass
    return os.path.basename(config_file)

def write_backup(backup_dir: Path, name: str, value):
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / name
    if isinstance(value, (dict, list)):
        text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    else:
        text = "" if value is None else str(value)
    path.write_text(text, encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(
        description="Install the COREXY mobile Mainsail pendant view."
    )
    parser.add_argument(
        "--moonraker", default="http://192.168.1.203", help="Moonraker base URL"
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MOONRAKER_API_KEY"),
        help="Moonraker API key, if required",
    )
    parser.add_argument(
        "--printer-config",
        help="Config-root-relative main Klipper config path (auto-detected by default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and create local backups but make no remote changes",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    client = Moonraker(args.moonraker, args.api_key, args.timeout)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(__file__).resolve().parent / "backups" / stamp

    print(f"Connecting to {client.base} ...")
    printer_info = client.get_json("/printer/info")
    if not isinstance(printer_info, dict):
        raise RuntimeError("Unexpected /printer/info response")

    cfg_rel = config_relative_path(client, printer_info, args.printer_config)
    main_cfg = client.get_file("config", cfg_rel)
    existing_css = client.get_file("config", ".theme/custom.css", missing_ok=True)
    existing_layout = client.db_get("dashboard.mobileLayout", missing_ok=True)
    existing_group = client.db_get(
        f"macros.macrogroups.{GROUP_ID}", missing_ok=True
    )

    objects, detection_source = detect_objects(client, main_cfg)
    macros = select_macros(objects)
    macro_cfg = render_macro_cfg(macros)
    macro_group = build_macro_group(macros)
    mobile_layout = build_mobile_layout(existing_layout)

    patched_cfg = replace_managed_block(
        main_cfg, MANAGED_CFG_BEGIN, MANAGED_CFG_END, config_include_block()
    )
    patched_css = replace_managed_block(
        existing_css or "",
        MANAGED_CSS_BEGIN,
        MANAGED_CSS_END,
        CSS_BLOCK,
    )

    write_backup(backup_dir, "printer-info.json", printer_info)
    write_backup(backup_dir, "printer-objects.json", sorted(objects))
    write_backup(backup_dir, "mobile-layout.before.json", existing_layout)
    write_backup(backup_dir, "probe-level-group.before.json", existing_group)
    write_backup(backup_dir, "printer.cfg.before.txt", main_cfg)
    write_backup(backup_dir, "custom.css.before.txt", existing_css or "")
    write_backup(backup_dir, "mainsail-mobile.cfg.generated", macro_cfg)
    write_backup(backup_dir, "mobile-layout.generated.json", mobile_layout)
    write_backup(backup_dir, "probe-level-group.generated.json", macro_group)

    print(f"Printer config: {cfg_rel}")
    print(f"Detection source: {detection_source}")
    if macros:
        print("Probe/level buttons:")
        for wrapper, command in macros:
            print(f"  - {wrapper} -> {command}")
    else:
        print("Probe/level buttons: none detected")
    print(f"Local backup: {backup_dir}")

    if args.dry_run:
        print("DRY RUN: no remote files or Mainsail settings changed.")
        return 0

    client.upload_text("config", MOBILE_CFG_NAME, macro_cfg)
    client.upload_text("config", cfg_rel, patched_cfg)
    client.upload_text("config", ".theme/custom.css", patched_css)

    client.db_set(f"macros.macrogroups.{GROUP_ID}", macro_group)
    client.db_set("dashboard.mobileLayout", mobile_layout)

    print()
    print("INSTALL COMPLETE.")
    print("No motion, homing, probing, levelling, heater command, or restart was run.")
    print("Review mainsail-mobile.cfg and the managed include in your main config.")
    print("Run FIRMWARE_RESTART yourself when ready, then refresh Mainsail on the phone.")
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
