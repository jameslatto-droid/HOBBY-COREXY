# Mainsail Mobile Pendant

A phone-focused Mainsail dashboard for the COREXY printer, with a shared modern visual treatment for both mobile and desktop Mainsail.

The implementation deliberately uses Mainsail and Moonraker's existing configuration mechanisms rather than forking Mainsail or creating a second printer-control web app.

## Mobile view

The mobile dashboard is reduced to:

1. **Toolhead control** — native Mainsail X/Y/Z jog, positions and homing controls.
2. **Extruder control** — native Mainsail extrude/retract controls.
3. **Temperature** — native Mainsail heater current/target controls.
4. **Probe & Level** — a dedicated mobile-only macro group populated from the Klipper objects actually loaded on the printer.

The normal generic **Macros** panel is hidden on the phone. Desktop and tablet dashboard layouts are not modified.

## Visual treatment

`custom.css` is a presentation-only layer over stock Mainsail/Vuetify. It is intentionally conservative about application structure so Mainsail remains upgradeable.

The shared desktop/mobile treatment includes:

- softer panel corners, subtle borders and reduced heavy shadows;
- sentence-case buttons instead of visually noisy all-caps controls;
- cleaner text-field and button geometry;
- restrained application-bar and navigation styling;
- clearer panel headings;
- tabular numeric rendering for temperatures and machine values;
- a cleaner temperature table with stronger emphasis on current temperature.

The phone view additionally gets larger touch targets, tighter card spacing, simplified heater rows and a two-column **Probe & Level** action grid.

The theme does not alter G-code, movement behaviour, limits, homing, heater logic or printer safety behaviour.

### Apply visual changes only

Once the pendant itself is installed, visual iterations can be applied without touching Klipper configuration:

```powershell
py .\mainsail\mobile-pendant\apply_theme.py
```

`apply_theme.py` backs up the live `.theme/custom.css`, replaces only the marked COREXY theme block, and uploads the result through Moonraker. It performs no Mainsail database writes and no printer-control calls.

A **hard browser refresh is required** after applying the theme. A `FIRMWARE_RESTART` is not required for a CSS-only update.

## Probe & Level detection

The installer checks `/printer/objects/list` and creates wrapper macros only for features that exist:

| Klipper object | Mobile macro |
| --- | --- |
| `probe` / `bltouch` | `MOBILE_PROBE_ACCURACY` |
| `bed_mesh` | `MOBILE_BED_MESH_CALIBRATE`, `MOBILE_BED_MESH_CLEAR` |
| `quad_gantry_level` | `MOBILE_QUAD_GANTRY_LEVEL` |
| `z_tilt` / `z_tilt_ng` | `MOBILE_Z_TILT_ADJUST` |
| `screws_tilt_adjust` | `MOBILE_SCREWS_TILT_CALCULATE` |
| `bed_tilt` | `MOBILE_BED_TILT_CALIBRATE` |

Interactive calibration routines such as `PROBE_CALIBRATE`, `BED_SCREWS_ADJUST` and `Z_ENDSTOP_CALIBRATE` are intentionally not added because the mobile mini-console is hidden.

The wrappers do **not** home first, call `SAVE_CONFIG`, restart Klipper, or control individual Z motors. If a calibration command requires homed axes, home the printer yourself first from the native Toolhead panel.

## Install

From the local `COREXY` repository, run a read-only dry run first if desired.

Windows PowerShell:

```powershell
py .\mainsail\mobile-pendant\install.py --dry-run
```

Linux / macOS:

```bash
python3 mainsail/mobile-pendant/install.py --dry-run
```

The default Moonraker/Mainsail address is `http://192.168.1.203`. Override it with `--moonraker` if required.

The dry run reads the live printer/Mainsail state and writes a timestamped local backup under `backups/`, but performs no remote writes.

Then install:

```powershell
py .\mainsail\mobile-pendant\install.py
```

The installer:

- backs up the current mobile layout, existing managed macro group, main printer config and `.theme/custom.css`;
- writes `mainsail-mobile.cfg`;
- adds one marked `[include mainsail-mobile.cfg]` block to the main Klipper config;
- preserves any unrelated existing custom CSS and adds the managed pendant CSS block;
- creates/updates the dedicated `Probe & Level` Mainsail macro group;
- replaces only `dashboard.mobileLayout`.

It does **not** call any Moonraker printer-control endpoint.

## Activate

After first installation, inspect the generated `mainsail-mobile.cfg` and the managed include from desktop Mainsail.

When you are ready, run `FIRMWARE_RESTART` yourself so Klipper loads newly-created wrapper macros. The installer intentionally does not restart the printer.

Refresh Mainsail on the phone after the restart. A hard refresh may be needed for the custom CSS.

For later CSS-only visual changes, use `apply_theme.py`; those do not require a Klipper restart.

## Files managed on the printer

```text
printer_data/config/
├── <main printer config>       # one marked include block
├── mainsail-mobile.cfg         # generated wrapper macros
└── .theme/
    └── custom.css              # one marked COREXY CSS block
```

All edits use `BEGIN/END COREXY MOBILE PENDANT` markers so rerunning the tooling updates its own block instead of duplicating it.

## Safety boundary

This repository code configures the UI only. Installation and theme application perform no G-code execution, no movement, no homing, no probing, no levelling, no heating, and no printer restart.
