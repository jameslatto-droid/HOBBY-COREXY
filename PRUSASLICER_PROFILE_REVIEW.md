# PrusaSlicer Profile Review — Full Parameter Notes (2026-09-20)

Full expert-mode review of the three active profiles + physical printer connection,
read directly from `%APPDATA%\PrusaSlicer\`. Goal: identify anything not at the
"theoretical ideal" for this specific machine (CoreXY, STM32F407/SKR Pro-class MCU,
BLTouch, Bondtech BMG extruder, ADXL345-measured input shaping at 65.0Hz X / 46.2Hz Y
mzv, Klipper firmware, 0.4mm nozzle, PLA).

Files reviewed:
- `printer/CoreXY.ini`
- `print/0.4mm PLA COREXY 0.2.ini`
- `filament/Generic PLA COREXY Fast.ini`
- `physical_printer/COREY.ini`

These are **not tracked in this git repo** (PrusaSlicer stores them under
`%APPDATA%\PrusaSlicer`) — this file is a reference document only.

---

## ⚑ Action items (read this part first)

1. **Overhang speed tiers are configured but the feature is OFF.** Print profile
   sets `overhang_speed_0..3 = 15/15/20/25` (a full slowdown curve by overhang
   %), but `enable_dynamic_overhang_speeds = 0`. As-is, those four values are
   dead weight and overhangs print at normal perimeter speed with no slowdown.
   Either set `enable_dynamic_overhang_speeds = 1` to actually use the curve you
   already tuned, or remove the values if the slowdown isn't wanted. **Recommend
   enabling** — free overhang-quality improvement with no downside for a
   direct-drive-quality setup.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE (qualifies Action Item #1 above):** enabling
`enable_dynamic_overhang_speeds` is reasonable, but do not enable it with the values that
are currently there, and be aware of a Klipper-specific bug.
**Reasoning:** (a) The four thresholds are **percentage overlap with the previous layer**,
not overhang angle — `overhang_speed_0` is 0% overlap (full bridge), `_3` is 75% overlap,
linearly interpolated. (b) `15/15/20/25` are PrusaSlicer's hard-coded code defaults, not a
tuned curve, and `_0` equalling `_1` means there is no slowdown gradient at all between a
full bridge and 25% overlap — so the original review's "the curve you already tuned" is not
quite right, nothing was tuned. Prusa's own MK4IS profile uses **15 / 25 / 30 / 80%**.
(c) There is an open Klipper-specific defect:
[PrusaSlicer#10064](https://github.com/prusa3d/PrusaSlicer/issues/10064), *"Dynamic Overhang
causing 'Invalid speed in G1 F0'"* — Klipper rejects `F0`. Full detail in **Astra Second
Opinion — PrusaSlicer Side** below.

</div>
2. **`autoemit_temperature_commands = 1` alongside a custom `START_PRINT` macro
   that already handles staged heating.** `start_gcode` calls
   `START_PRINT EXTRUDER={first_layer_temperature[0]} BED=[first_layer_bed_temperature]`,
   and the macro (in `config/macro.cfg`) deliberately interleaves heating with
   homing/mesh-load (`M140` before `G28`, `M190`/`M109` after mesh load) to save
   time and reduce oozing dwell. PrusaSlicer's autoemit feature is *supposed* to
   detect that your custom start G-code already references the temperature
   placeholders and skip auto-inserting its own `M104/M109/M140/M190`, but this
   is worth **explicitly confirming** rather than trusting blindly: slice any
   test object, check the first ~40 lines of exported G-code, and make sure no
   `M109`/`M190` appears *before* the `START_PRINT` line (which would force a
   premature wait-for-temp ahead of homing) or duplicated right after it. If you
   see duplicates, set `autoemit_temperature_commands = 0`.

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN (disagrees with Action Item #2 above):**
`autoemit_temperature_commands` — current `1` → **`0`**. This is not a "verify, probably
fine" item. It is confirmed broken from source, and no test slice is needed to establish it.
**Reasoning:** PrusaSlicer's detector `custom_gcode_sets_temperature()` in
`src/libslic3r/GCode.cpp` is a **literal M-code line scan**, not placeholder detection — it
requires the first non-whitespace character of a line to be `M`, followed by 104/109/140/190.
The expanded start G-code is `START_PRINT EXTRUDER=205 BED=55`, which begins with `S`, so it
is never detected. PrusaSlicer therefore emits `M140` and `M190` (**waiting for the bed**)
*before* the macro, and `M109` *after* it — so the printer soaks before `G28` ever runs,
defeating the exact interleaving of heating with homing and mesh load that the macro was
written for, and then sets both temperatures a second time. Prusa's developers treat setting
the flag to `0` as the intended fix for this class of Klipper macro:
[PrusaSlicer#11597](https://github.com/prusa3d/PrusaSlicer/issues/11597) was closed with
*"Disabled with configuration update 1.0.4"*, and Prusa's shipped Voron and RatRig Klipper
profiles both set `autoemit_temperature_commands = 0`. Full argument in **Astra Second
Opinion — PrusaSlicer Side**, item 1, below.

</div>
3. **`fill_density = 0%` in the default print profile.** Either intentional
   (every project overrides infill per-part) or a leftover from when this
   profile was last used for a specific print. Worth a conscious decision either
   way, not a bug.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE (disagrees with Action Item #3 above):** `fill_density` —
current `0%` → suggested `10%`. This is closer to a bug than to a neutral choice.
**Reasoning:** `fill_density == 0` does not merely mean "no infill" — in
`src/libslic3r/PrintObject.cpp`, `discover_horizontal_shells()` short-circuits shell
propagation whenever `fill_density == 0` **or** `ensure_vertical_shell_thickness` is
disabled, treating them identically on the assumption that *"the user expects the object to
be void"*. So the `ensure_vertical_shell_thickness = enabled` setting that the review
correctly praises further down is **bypassed** at 0% infill, internal solid shells are not
generated, and top surfaces must bridge open air. Prusa's own guidance: *"Most models can be
printed with 10-15% infill... though we generally do not recommend"* printing hollow
([Infill](https://help.prusa3d.com/article/infill_42/)). This matters more than it first
appears because this is the **default** print profile, so every new project inherits it.

</div>
4. **`extrusion_multiplier = 1` (filament) and `pressure_advance = 0.05`
   (firmware) are both still uncalibrated placeholders** — already tracked in
   the calibration backlog, just re-flagging here since they live in these
   profile files.
5. **`travel_ramping_lift = 0`** — minor, optional. Enabling ramping lift (with
   a small `travel_max_lift`) shaves a bit of travel time vs. the flat
   `retract_lift = 0.2` Z-hop on every travel move. Not necessary, just a small
   available win given the accel/speed headroom this machine has.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE (adds a prerequisite to Action Item #5 above):** before
enabling ramping lift, note that **all** Z-hop — both the flat `retract_lift` and ramping
lift — is gated on `retract_length != 0`, *even when `use_firmware_retraction = 1`*.
**Reasoning:** `src/libslic3r/GCode.cpp` computes
`bool can_be_flat{!needs_retraction || retract_length == 0};` and takes a travel path with no
lift at all when that is true. Since the GUI greys out `retract_length` whenever firmware
retraction is enabled, it is an easy trap to zero it out "because the firmware decides" and
silently lose every Z-hop. This profile is fine today at `retract_length = 0.6` — this is a
note to keep it non-zero. See also the `use_firmware_retraction` + `wipe` conflict in
**Astra Second Opinion — PrusaSlicer Side**, item 2, which affects the same group of settings.

</div>

Everything else below was checked and is either already at a sensible value for
this hardware or is a cosmetic/inapplicable (MMU-only, SLA-only, etc.) setting.

---

## `printer/CoreXY.ini` — Printer Settings

### Size & shape
| Key | Value | Note |
|---|---|---|
| `bed_shape` | 0x0,300x0,300x300,0x300 | Matches 300×300 bed. ✅ |
| `max_print_height` | 400 | Matches Z max. ✅ |
| `z_offset` | 0 | Correct — Klipper's own probe `z_offset` already accounts for real nozzle height; slicer-side offset would double-apply. ✅ |
| `bed_custom_model` / `bed_custom_texture` | blank | Cosmetic 3D-preview only, optional, no functional effect. |

### Extruder / general
| Key | Value | Note |
|---|---|---|
| `extruder_offset` | 0x0 | Correct for single extruder. |
| `extruder_colour` | blank | Cosmetic only. |
| `nozzle_high_flow` | 0 | Correct (not a high-flow hardened hotend as far as known). |
| `single_extruder_multi_material` | 0 | Correct, no MMU. |
| `high_current_on_filament_swap` | 0 | MMU-only, correct as-is. |
| `extruder_clearance_height` / `_radius` | 20 / 20 | Used for sequential-print / arrange collision checks. Not currently using sequential printing (`complete_objects = 0`), so low-impact, but values are plausible for a BMG+BLTouch toolhead. |

### Custom G-code
| Key | Value | Note |
|---|---|---|
| `start_gcode` | `START_PRINT EXTRUDER={first_layer_temperature[0]} BED=[first_layer_bed_temperature]` | Correctly passes both placeholders as macro params matching `macro.cfg`'s expected `EXTRUDER=`/`BED=` args. ✅ |
| `end_gcode` | `END_PRINT` | Matches macro. ✅ |
| `before_layer_gcode` | `;BEFORE_LAYER_CHANGE\n;[layer_z]\nG92 E0\n\n` | Resets E position every layer — safe/common practice with `use_relative_e_distances=1`, prevents float drift on long prints. Fine. |
| `layer_gcode` | `;AFTER_LAYER_CHANGE\n;[layer_z]\n` | Comment-only marker, harmless. |
| `between_objects_gcode` / `toolchange_gcode` / `color_change_gcode` / `template_custom_gcode` | blank | Correct — none of these apply (single extruder, no color changes scripted). |
| `pause_print_gcode` | `PAUSE` | Correct Klipper macro name (not `M601`). ✅ |
| `custom_parameters_printer` | blank | Just a metadata field. |

### Firmware / machine limits
| Key | Value | Note |
|---|---|---|
| `gcode_flavor` | klipper | ✅ |
| `host_type` | klipper | ✅ |
| `machine_limits_usage` | time_estimate_only | **Correct choice for Klipper** — prevents the slicer from emitting `M201/M203/M205` that would fight with Klipper's own `[printer]` section limits; values below are only used for the slicer's print-time estimate. |
| `machine_max_feedrate_x/y` | 300 / 300 | Matches live `[printer] max_velocity: 300` in `tuning.cfg`. ✅ consistent, so time estimates are accurate. |
| `machine_max_feedrate_z` | 15 | Matches live `max_z_velocity: 15`. ✅ |
| `machine_max_feedrate_e` | 60 | Matches live `max_extrude_only_velocity: 60` in `thermistors.cfg`. ✅ |
| `machine_max_acceleration_x/y` | 3000 | Matches live `max_accel: 3000`. ✅ |
| `machine_max_acceleration_z` | 350 | Matches live `max_z_accel: 350`. ✅ |
| `machine_max_acceleration_e` | 2000 | Matches live `max_extrude_only_accel: 2000`. ✅ |
| `machine_max_acceleration_extruding` / `_retracting` | 3000 / 2000 | Reasonable, consistent with the above. |
| `machine_max_acceleration_travel` | 3000,350 | Matches XY/Z accel. Fine. |
| `machine_max_jerk_x/y` | 10 | Not sent to firmware (time-estimate only); reasonable placeholder for estimate purposes. Klipper's actual equivalent is `square_corner_velocity: 5.0` (different math, not directly comparable) — no action needed since this is estimate-only. |
| `machine_max_jerk_z` | 0.2 | Same as above — estimate-only. |
| `machine_max_jerk_e` | 5 | Estimate-only. |
| `machine_max_junction_deviation` | 0,0 | Unused (jerk-based estimate model instead), fine. |
| `machine_min_extruding_rate` / `machine_min_travel_rate` | 0 | Marlin-specific concept, meaningless for Klipper, harmless at 0 (disabled). |
| `silent_mode` | 0 | No dual-limit (silent/normal) firmware profile needed for Klipper. Correct. |

### Retraction / advanced (Extruder 1 page)
| Key | Value | Note |
|---|---|---|
| `use_firmware_retraction` | 1 | ✅ Correct — defers to Klipper's `[firmware_retraction]` in `tuning.cfg` rather than duplicating retract logic in G-code. |
| `retract_length` | 0.6 | Matches `tuning.cfg`'s `retract_length: 0.6`. Kept in sync as a safety net in case `use_firmware_retraction` is ever toggled off. ✅ |
| `retract_speed` | 40 | Matches `tuning.cfg`'s `retract_speed: 40`. ✅ |
| `deretract_speed` | 30 | Matches `tuning.cfg`'s `unretract_speed: 30`. ✅ |
| `retract_lift` | 0.2 | Small Z-hop, reasonable for reducing stringing/collisions without adding much travel time. |
| `retract_lift_above` / `_below` | 0.2 / 0 | Z-hop applies everywhere above Z=0.2 (i.e. always after first layer). Fine default. |
| `retract_before_travel` | 3 | Only retract for travel ≥3mm — standard, avoids needless micro-retracts. |
| `retract_before_wipe` | 70% | Standard Prusa default, fine. |
| `retract_restart_extra` | 0 | Fine, no extra prime needed (no known under-extrusion after retract). |
| `retract_layer_change` | 0 | Off — since `before_layer_gcode` already does `G92 E0` and firmware retraction is in effect; leaving this off avoids a redundant retract right at the `before_layer_gcode` boundary. Fine as-is. |
| `deretract_speed` | 30 | covered above |
| `wipe` | 1 | Enabled, reduces oozing on retract — good with a direct-drive-quality BMG setup. |
| `extra_loading_move` | -2 | MMU-only, harmless unused value. |
| `parking_pos_retraction` | 92 | MMU-only, unused. |
| `cooling_tube_length` / `cooling_tube_retraction` | 5 / 91.5 | MMU-only, unused. |
| `multimaterial_purging` | 140 | MMU-only, unused. |
| `retract_length_toolchange` / `retract_restart_extra_toolchange` | 1 / 0 | MMU-only, unused. |

### Other advanced/behavior
| Key | Value | Note |
|---|---|---|
| `autoemit_temperature_commands` | 1 | **See Action Item #2** — verify no duplicate heating commands are emitted around the `START_PRINT` macro call. |
| `use_relative_e_distances` | 1 | ✅ Required for Klipper (`M83` mode). |
| `use_volumetric_e` | 0 | ✅ Correct — Klipper doesn't use volumetric E-values. |
| `variable_layer_height` | 1 | Feature toggle only (per-project opt-in), harmless enabled. |
| `binary_gcode` | 0 | Off — fine unless you specifically want smaller binary `.bgcode` files (Mainsail/Fluidd support varies); text G-code is the safe default. |
| `remaining_times` | 1 | Nice-to-have print-time-remaining display, no downside. |
| `thumbnails` | 64x64/PNG, 400x300/PNG | Good for Mainsail/Fluidd previews. |
| `thumbnails_format` | PNG | Correct choice for Klipper-adjacent front ends. |
| `print_host` / `printhost_apikey` / `printhost_cafile` | blank | Connection now lives in the separate `physical_printer/COREY.ini` profile instead — correct modern approach. |
| `prefer_clockwise_movements` | 0 | Subjective/cosmetic (seam direction), not a correctness issue. |
| `travel_lift_before_obstacle` / `travel_max_lift` / `travel_ramping_lift` / `travel_slope` | 0 | Ramping lift off — see Action Item #5 (optional minor time-saver, not required). |
| `printer_model` / `printer_variant` / `printer_vendor` / `printer_settings_id` | CoreXY / 0.4 / blank / CoreXY | Fine, accurate metadata, no stale references. |
| `printer_notes` | accurate CoreXY hardware description | ✅ Clean, no leftover RatRig text. |
| `printer_technology` | FFF | ✅ |
| `printhost_authorization_type` (n/a here, see physical_printer) | — | See below. |
| `remaining fields` (`inherits`, etc.) | blank | Not using profile inheritance, fine for a single custom profile. |

---

## `print/0.4mm PLA COREXY 0.2.ini` — Print Settings

### Layers & perimeters
| Key | Value | Note |
|---|---|---|
| `layer_height` | 0.2 | Standard "fast/quality balance" for 0.4 nozzle. ✅ |
| `first_layer_height` | 0.2 | Equal to layer height — fine given Z-offset/mesh are freshly (re-)calibrated; some prefer a taller first layer (e.g. 0.25-0.3mm) for easier adhesion/less mesh sensitivity, optional. |
| `perimeters` | 2 | Reasonable default (≈0.88mm wall thickness with 0.44 width). 3 perimeters is a common alternative for more strength; not "wrong," just a strength/speed tradeoff choice. |
| `perimeter_generator` | arachne | ✅ Correct modern choice over "classic." |
| `extra_perimeters` / `extra_perimeters_on_overhangs` | 1 / 1 | ✅ Good for overhang strength. |
| `external_perimeters_first` | 0 | Standard (inner-then-outer generally gives better external surface quality). Fine. |
| `only_one_perimeter_first_layer` | 0 | Fine default. |
| `ensure_vertical_shell_thickness` | enabled | ✅ Prevents gaps under sparse infill near top/bottom transitions. |
| `top_solid_layers` / `bottom_solid_layers` | 4 / 4 | 0.8mm coverage each — solid Prusa-recommended rule-of-thumb for 0.2mm layers. ✅ |
| `top_solid_min_thickness` / `bottom_solid_min_thickness` | 0 | Using layer-count method instead of thickness method — consistent choice, fine. |
| `top_one_perimeter_type` | top | Fine default. |

### Extrusion widths
| Key | Value | Note |
|---|---|---|
| `extrusion_width` (global fallback) | 0.44 | 110% of nozzle — good middle-ground default. |
| `external_perimeter_extrusion_width` | 0.42 | Slightly thinner than internal — improves external surface quality, standard good practice. ✅ |
| `perimeter_extrusion_width` | 0.44 | ✅ |
| `infill_extrusion_width` / `solid_infill_extrusion_width` / `top_infill_extrusion_width` | 0.44 | ✅ consistent. |
| `support_material_extrusion_width` | 0.44 | Fine (supports currently off by default anyway). |
| `automatic_extrusion_widths` | 0 | Manual widths set explicitly instead — fine, matches the values above. |

### Infill
| Key | Value | Note |
|---|---|---|
| `fill_density` | 0% | **See Action Item #3** — likely meant to be overridden per-project; worth a deliberate choice. |
| `fill_pattern` | gyroid | Good general-purpose pattern (fast, decent strength, no seams). ✅ |
| `top_fill_pattern` / `bottom_fill_pattern` | rectilinear | ✅ Standard/ideal for solid top-bottom surfaces. |
| `fill_angle` | 45 | Standard. |
| `infill_overlap` | 20% | Standard, ensures perimeter/infill bonding. |
| `infill_every_layers` | 1 | Standard (no combined infill layers). |
| `infill_anchor` / `infill_anchor_max` | 0 / 50 | Sensible defaults. |
| `infill_first` | 0 | Standard order (perimeters before infill) — better external surface quality. |
| `automatic_infill_combination` | 0 | Fine, not needed at 0.2mm layer height. |

### Speeds
| Key | Value | Note |
|---|---|---|
| `perimeter_speed` | 80 | Well within machine capability (300mm/s max, 65/46Hz shaper). Reasonable for quality/speed balance on outer geometry. |
| `external_perimeter_speed` | 50 | Slower than internal perimeters — correct practice for best visible-surface quality. ✅ |
| `small_perimeter_speed` | 60 | Slower for small/tight perimeters to avoid overheating/ringing on tiny features — good practice. ✅ |
| `infill_speed` / `solid_infill_speed` | 80 | Reasonable given headroom. |
| `top_solid_infill_speed` | 50 | Slower for best top-surface finish — good practice. ✅ |
| `gap_fill_speed` | 60 | Fine. |
| `first_layer_speed` | 30 | Conservative — good for first-layer adhesion reliability. ✅ |
| `first_layer_speed_over_raft` | 30 | N/A (no rafts used), harmless. |
| `first_layer_infill_speed` | 0 (inherit) | Fine. |
| `bridge_speed` | 60 | Reasonable. |
| `overhang_speed_0..3` | 15/15/20/25 | **See Action Item #1 — currently inert, feature disabled.** |
| `enable_dynamic_overhang_speeds` | 0 | **See Action Item #1.** |
| `travel_speed` | 250 | Reasonable given 300mm/s max feedrate headroom, leaves margin. |
| `travel_speed_z` | 0 (inherit) | Fine. |
| `support_material_speed` / `_interface_speed` | 90 / 70 | Fine (supports off by default anyway). |
| `min_print_speed` (filament ini) | 15 | Standard cooling-driven speed floor for thin/small features. |
| `max_print_speed` | 300 | Matches machine ceiling. Consistent. ✅ |

### Acceleration
| Key | Value | Note |
|---|---|---|
| `perimeter_acceleration` | 1500 | Half of machine max — good practice, lower accel on visible perimeters improves dimensional accuracy/reduces ringing. ✅ |
| `external_perimeter_acceleration` | 800 | Even lower for the outermost wall — excellent practice for best surface quality. ✅ |
| `infill_acceleration` | 3000 | Full machine max — fine since infill isn't visible/quality-critical, maximizes speed. ✅ |
| `solid_infill_acceleration` | 2500 | Slightly reduced from full infill accel — reasonable middle ground. |
| `top_solid_infill_acceleration` | 1200 | Lower for best top-surface finish. ✅ |
| `first_layer_acceleration` | 500 | Very conservative — excellent for adhesion reliability. ✅ |
| `bridge_acceleration` | 800 | Moderate, reasonable for bridge quality. |
| `travel_acceleration` | 3000 | Matches machine max — travel isn't extrusion-quality-sensitive, correct to maximize. ✅ |
| `default_acceleration` | 0 | Correctly "unset" — defers to the specific per-feature values above rather than one blanket value. ✅ |
| `travel_short_distance_acceleration` | 0 (inherit) | Fine. |

This acceleration profile (conservative on visible perimeters/top surfaces, full-speed
on infill/travel) is close to textbook-ideal tuning for a well-tuned CoreXY with
input shaping already measured — no changes recommended here.

### Retraction-adjacent / seams
| Key | Value | Note |
|---|---|---|
| `avoid_crossing_perimeters` | 1 | Good default, reduces visible travel stringing. |
| `avoid_crossing_perimeters_max_detour` | 0 (unlimited) | Fine — lets it fully avoid crossing when needed. |
| `avoid_crossing_curled_overhangs` | 0 | Fine, not typically needed unless curling is observed. |
| `only_retract_when_crossing_perimeters` | 1 | Standard optimization, fine. |
| `seam_position` | rear | Subjective aesthetic choice, not a correctness issue. |
| `staggered_inner_seams` | 0 | Fine default. |
| `scarf_seam_placement` | nowhere | Scarf seams disabled — standard sharp seam used instead. Fine/subjective (scarf seams can look better but add complexity; not required). |
| `seam_gap_distance` | 15% | N/A while scarf seams disabled. |

### Bridging / overhangs
| Key | Value | Note |
|---|---|---|
| `bridge_flow_ratio` | 0.8 | Standard reduced-flow bridging value. ✅ |
| `bridge_angle` | 0 (auto) | Fine, let the slicer compute. |
| `dont_support_bridges` | 1 | Model-dependent risk tradeoff (skips supports under bridges) — not wrong, just worth knowing if a specific model has long unsupported bridges. |
| `thick_bridges` | 0 | Standard/fine. |
| `overhangs` | 1 | ✅ Enables Arachne variable-width overhang handling. |
| `enable_dynamic_overhang_speeds` | 0 | See Action Item #1. |

### Skirt / brim / support
| Key | Value | Note |
|---|---|---|
| `skirts` | 1 | Fine for priming/inspection, slight redundancy with the macro's own purge line but harmless. |
| `skirt_height` | 1 | Standard single-layer skirt. |
| `skirt_distance` | 3 | Fine. |
| `min_skirt_length` | 20 | Ensures enough prime even for small first layers. Fine. |
| `brim_type` | outer_only | Sensible default when brim is enabled per-project. |
| `brim_width` / `brim_separation` | 0 | Off by default — enabled per-project as needed. Fine. |
| `draft_shield` | disabled | Fine default. |
| `support_material` | 0 | Off by default, enabled per-project. Fine. |
| `support_material_auto` | 1 | Sensible default for when supports are turned on. |
| `support_material_threshold` | 30° | Standard Prusa default. |
| `support_material_style` | grid | Reasonable default (organic/tree supports also available per-project). |
| `support_material_pattern` / `_interface_pattern` | rectilinear-grid / rectilinear | Standard. |
| `support_material_spacing` / `_interface_spacing` | 4 / 0.2 | Standard defaults. |
| `support_material_xy_spacing` | 0.6 | Standard clearance. |
| `support_material_contact_distance` / `_bottom_contact_distance` | 0.2 / 0 | Standard. |
| `support_material_interface_layers` / `_bottom_interface_layers` | 2 / -1 (auto) | Standard. |
| `support_material_buildplate_only` | 0 | Fine, model-dependent. |
| `support_tree_*` | Prusa stock defaults | Only relevant if tree supports selected per-project; unmodified defaults are fine. |

### Cooling-adjacent (lives partly in filament profile too)
| Key | Value | Note |
|---|---|---|
| `slowdown_below_layer_time` (filament) | 10 | Fine standard. |
| `fan_below_layer_time` (filament) | 100 | Fine standard. |

### Output / misc
| Key | Value | Note |
|---|---|---|
| `output_filename_format` | `{input_filename_base}_{layer_height}mm_{filament_type[0]}_{print_time}.gcode` | Informative filenames, nice for tracking. |
| `gcode_comments` | 0 | Smaller files, faster transfer/parsing — fine default. |
| `gcode_label_objects` | octoprint | ✅ Correct flavor for Klipper's `EXCLUDE_OBJECT` support via Moonraker's octoprint-compat layer. |
| `gcode_resolution` | 0.0125 | High resolution for arc/curve fidelity, negligible performance cost. Fine/good. |
| `resolution` | 0 | Legacy/deprecated field, superseded by `gcode_resolution` + `slice_closing_radius`; harmless at 0. |
| `slice_closing_radius` | 0.049 | Prusa stock default, fine. |
| `min_bead_width` | 85% | Arachne stock default, fine. |
| `min_feature_size` | 25% | Arachne stock default, fine. |
| `wall_transition_angle` / `_filter_deviation` / `_length` / `wall_distribution_count` | 10 / 25% / 100% / 1 | Arachne stock defaults, fine. |
| `xy_size_compensation` | 0 | Fine, no compensation currently applied — could be tuned later if calipers show consistent over/under-sizing, not urgent. |
| `elefant_foot_compensation` | 0.1 | Small standard compensation, reasonable alongside a well-calibrated Z-offset. |
| `ironing` | 0 | Off — optional top-surface quality feature, per-project choice, not required. |
| `spiral_vase` | 0 | Off, correct for normal (non-vase) prints. |
| `wipe_tower` | 0 | Correct, no MMU/multi-material. |
| `interlocking_*` | Prusa stock defaults | Multi-material-only, unused, harmless. |
| `standby_temperature_delta` | -5 | Multi-extruder-only (idle nozzle temp drop), harmless unused on single extruder. |
| `complete_objects` | 0 | Off — sequential printing not in use; fine given `extruder_clearance_*` is set but not exercised. |
| `mmu_segmented_region_*` | Prusa stock defaults | MMU-only, unused. |
| `custom_parameters_print` | blank | Metadata field only. |
| `notes` | blank | Free-text field, optional. |
| `compatible_printers` / `compatible_printers_condition` | blank | Not restricted — fine for a single-printer setup. |

---

## `filament/Generic PLA COREXY Fast.ini` — Filament Settings

### Temperatures
| Key | Value | Note |
|---|---|---|
| `temperature` | 200 | Standard PLA body temp. Reasonable. |
| `first_layer_temperature` | 205 | Slightly hotter first layer for adhesion — good practice. ✅ |
| `bed_temperature` | 50 | Standard PLA bed temp. |
| `first_layer_bed_temperature` | 55 | Slightly hotter first layer for adhesion — matches the temp actually used during the 2026-09-13 Z-offset/bed-mesh calibration (bed 55°C), so mesh/offset data is temperature-consistent with what's actually printed at. ✅ Good — a mismatch here would have been a real flag. |
| `idle_temperature` | nil | Multi-extruder-only, unused. |
| `chamber_temperature` / `chamber_minimal_temperature` | 0 | No enclosure/chamber heater, correct. |

### Cooling
| Key | Value | Note |
|---|---|---|
| `cooling` | 1 | ✅ Enabled. |
| `fan_always_on` | 1 | ✅ |
| `min_fan_speed` / `max_fan_speed` | 100 / 100 | Fan pinned at 100% — common, reasonable choice specifically for PLA (benefits from max cooling almost always). Note: this makes `full_fan_speed_layer` and all `overhang_fan_speed_0..3` moot (no ramp/no range to ramp within) — not wrong, just worth knowing they're currently no-ops. |
| `disable_fan_first_layers` | 1 | ✅ Good — avoids weak first-layer adhesion from cooling airflow. |
| `full_fan_speed_layer` | 4 | Currently a no-op given min=max=100% (see above). |
| `bridge_fan_speed` | 100 | Matches max — consistent. |
| `overhang_fan_speed_0..3` | 0/0/0/0 | Currently moot (fan already always 100%). No action needed unless `max_fan_speed` is ever lowered. |
| `slowdown_below_layer_time` | 10 | Standard. |
| `fan_below_layer_time` | 100 | Standard. |
| `min_print_speed` | 15 | Standard cooling-driven floor. |
| `enable_dynamic_fan_speeds` | 0 | Consistent with the fixed-100% approach above; fine. |

### Extrusion / flow
| Key | Value | Note |
|---|---|---|
| `extrusion_multiplier` | 1 | **Uncalibrated placeholder** — flow calibration (single-wall-cube test) not yet done. Tracked in the calibration backlog, not new. |
| `filament_max_volumetric_speed` | 15 mm³/s | Reasonable conservative cap for a stock/unknown hotend at 200-210°C. At current settings (infill 80mm/s × 0.44mm width × 0.2mm layer ≈ 7.0mm³/s) this cap isn't even close to being hit, so no throttling currently occurs — headroom exists if speeds are pushed later. |
| `filament_diameter` | 1.75 | ✅ Standard. |
| `filament_density` | 1.24 | Generic PLA default, in the normal 1.24–1.25 range. Fine unless you have the exact spool spec sheet for a small accuracy gain (affects weight/cost estimate only, not print quality). |
| `filament_shrinkage_compensation_xy` / `_z` | 0% | PLA shrinkage is minimal; 0% is a reasonable default. Could calibrate later for higher dimensional precision, low priority. |
| `filament_type` | PLA | ✅ |
| `filament_soluble` | 0 | ✅ Correct. |
| `filament_abrasive` | 0 | Correct (standard PLA, not a wear-causing composite). |

### Retraction (deferred to printer profile)
| Key | Value | Note |
|---|---|---|
| `filament_retract_length` / `_speed` / `_lift` / etc. | all `nil` | ✅ Correctly deferring to the printer profile's retraction settings (which in turn defer to Klipper's `[firmware_retraction]`) rather than double-specifying at the filament level. Good practice — avoids a filament-profile override silently fighting the firmware retraction config. |
| `filament_deretract_speed` | nil | Same as above. |

### Start/end filament G-code
| Key | Value | Note |
|---|---|---|
| `start_filament_gcode` | `SET_PRESSURE_ADVANCE ADVANCE=0.05` | ✅ Correctly synced with the live `pressure_advance` in `thermistors.cfg` (both 0.05). Still a placeholder pending real PA calibration, but internally consistent. |
| `end_filament_gcode` | `"\n"` | Effectively empty, fine — `END_PRINT` in the printer profile handles all real end-of-print behavior. |

### MMU/ramming (all unused — single extruder)
`filament_multitool_ramming*`, `filament_ramming_parameters`, `filament_cooling_moves`,
`filament_cooling_initial_speed`, `filament_cooling_final_speed`, `filament_loading_speed*`,
`filament_unloading_speed*`, `filament_load_time`, `filament_unload_time`,
`filament_toolchange_delay`, `filament_minimal_purge_on_wipe_tower`,
`filament_purge_multiplier` — all Prusa MMU-specific stock defaults, completely
inert on a single-extruder setup. No action needed.

### Misc
| Key | Value | Note |
|---|---|---|
| `filament_cost` | 20 | Cost-estimate display only, cosmetic. |
| `filament_spool_weight` | 0 | Cosmetic/tracking only. |
| `filament_colour` | #FF3232 | Cosmetic UI color only. |
| `filament_notes` | blank | Optional free text. |
| `compatible_printers` / `compatible_prints` (+ `_condition`) | blank | Not restricted — fine for single-printer use. |

---

## `physical_printer/COREY.ini` — Connection

| Key | Value | Note |
|---|---|---|
| `host_type` | moonraker | ✅ Correct for Klipper/Moonraker. |
| `print_host` | 192.168.1.203 | Direct LAN IP. |
| `printhost_port` | blank (default 7125) | Fine — Moonraker's default port. |
| `printhost_authorization_type` | key | Set to key-based auth, but... |
| `printhost_apikey` | blank | ...no key is actually set. **This is fine** — checked `moonraker.conf`'s `[authorization] trusted_clients` list, which includes `192.168.0.0/16`, so this machine's LAN IP is already trusted and doesn't need an API key. Just noting the dependency: if `trusted_clients` in `moonraker.conf` is ever tightened, this profile will need a real API key added. |
| `printhost_cafile` | blank | No custom CA cert — fine for local HTTP (not HTTPS) LAN connection. |
| `printhost_user` / `_password` | blank | Not using basic auth — consistent with the trusted-client approach above. |

---

## Summary

Out of ~380 individual settings across all four files, the vast majority are
already at sensible, internally-consistent values for this specific machine —
machine limits match the live Klipper config exactly (good for accurate time
estimates), retraction correctly defers to firmware retraction, temperatures are
consistent with actual calibration conditions, and the acceleration/speed profile
follows good practice (conservative on visible surfaces, fast on infill/travel).

Only one item is a clear "fix this" (`enable_dynamic_overhang_speeds` should
probably be `1` to activate the overhang speed tiers that are already
configured), one is a "verify, probably fine" (`autoemit_temperature_commands`
interaction with the custom `START_PRINT` macro), and the rest are either
deliberate per-project choices (infill %, brim, supports) or genuinely optional
micro-optimizations (ramping lift, exact filament density).

---
---

# Part 2 — Klipper Firmware Config Review (Astra research pass)

**Added 2026-09-20.** Everything above this line is the original PrusaSlicer-side
review and is left untouched. This part extends the same parameter-by-parameter
exercise to the live Klipper config, and adds a second opinion on some of the
slicer-side findings above.

**Method.** Every active `.cfg` in the include graph of `config/printer.cfg` was read
line by line. Claims below are checked against primary sources — the Klipper
`Config_Reference.md`, the module source in `Klipper3d/klipper`, and the official
board config `config/generic-bigtreetech-skr-pro.cfg` — rather than from memory.
Where a source does not settle a question, that is said explicitly instead of guessed.
Full source list at the end.

**Nothing in `config/` was modified.** This is a research-and-recommend pass only.

### How to read the coloured blocks

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** orange — a suggested value change or improvement.

</div>

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** red — something I consider a genuine safety or
machine-damage concern, or a defect that will bite during a real print.

</div>

---

## Klipper Config Review — Headline Findings

Six things are worth acting on before anything else. They are argued in full in the
per-file sections below and listed again with priorities in the final summary.

1. **The first-layer height knob on this machine is `[stepper_z] position_endstop`,
   not the BLTouch `z_offset`.** Z homes to a physical switch, so `PROBE_CALIBRATE`
   cannot move the nozzle datum. This reverses outstanding task #1 in `HANDOFF.md`.
2. **`SAVE_CONFIG` will refuse to persist that value**, and will equally refuse to
   persist a new input shaper result, because both options are already set inside
   `[include]`d files. This is a hard error, not a silent failure.
3. **The reverted extruder `uart_pin: PD4` was the correct pin**, confirmed against
   Klipper's official SKR Pro board config. The `IFCNT` fault was not a pin error,
   so the note in `HANDOFF.md` is chasing the wrong cause.
4. **`[stepper_z]` and `[stepper_z1]` have their `dir`, `enable` and `uart` pins
   crossed** between the Z and E1 driver sockets. Harmless for motion, actively
   misleading for driver diagnostics.
5. **Seven config sections are defined twice**, and Klipper merges them silently
   per-option rather than erroring. One consequence is a real print-losing bug.
6. **`max_accel: 3000` is roughly half** of what the measured resonance frequencies
   support. Klipper's own formula gives 6300 on the binding axis.

---


## Klipper Firmware Config Review — `printer.cfg` (structure, includes, autosave)

### Include graph and section collisions

`printer.cfg` includes 14 files. Klipper does **not** error when a section is defined in
two of them. `klippy/configfile.py` builds the parser with `strict=False`, which is
exactly the flag that suppresses Python's `DuplicateSectionError` and
`DuplicateOptionError`. Includes are expanded in place at their exact line position, so
the effective rule is **last definition wins, merged per option key**.
([configfile.py](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py))

The critical subtlety is *per option key*. A second `[gcode_macro PAUSE]` that omits
`description:` silently inherits the first file's `description:`. You end up with one
macro assembled from two files, with no warning anywhere.

Seven sections in this config are defined twice:

| Section | Defined in | Which wins |
|---|---|---|
| `[virtual_sdcard]` | `mainsail.cfg`, `system.cfg` | `system.cfg` sets `path`; `mainsail.cfg`'s `on_error_gcode: CANCEL_PRINT` **survives**, because `system.cfg` never mentions that key |
| `[pause_resume]` | `mainsail.cfg`, `system.cfg` | both empty, harmless |
| `[display_status]` | `mainsail.cfg`, `system.cfg` | both empty, harmless |
| `[respond]` | `mainsail.cfg`, `system.cfg` | both empty, harmless |
| `[gcode_macro PAUSE]` | `mainsail.cfg`, `macro.cfg` | `macro.cfg` (included later) |
| `[gcode_macro RESUME]` | `mainsail.cfg`, `macro.cfg` | `macro.cfg`, but `mainsail.cfg`'s three `variable_*` lines survive as orphans |
| `[gcode_macro CANCEL_PRINT]` | `mainsail.cfg`, `macro.cfg` | `macro.cfg` |

The three empty duplicates are genuinely harmless. The macro ones are not — see the
`macro.cfg` section below for the print-losing consequence.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `system.cfg` — remove the duplicate `[virtual_sdcard]`,
`[pause_resume]`, `[display_status]` and `[respond]` sections and let `mainsail.cfg` own them.
**Reasoning:** They are already provided by `mainsail.cfg`, which is the upstream
[mainsail-config](https://github.com/mainsail-crew/mainsail-config) file and is meant to own
them. Keeping the duplicates means the effective `[virtual_sdcard]` config is assembled from
two files (`path` from one, `on_error_gcode` from the other), which is invisible when reading
either file alone, because Klipper's parser merges rather than warns
([configfile.py](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py)).
Note also that `system.cfg` hardcodes `/home/pi/printer_data/gcodes` where `mainsail.cfg` uses
`~/printer_data/gcodes` — the same directory today, but the `~` form survives a username change.

</div>

### The `SAVE_CONFIG` autosave block — two latent hard errors

This is the most consequential structural finding in the audit.

Before writing, `SAVE_CONFIG` runs `_disallow_include_conflicts()`, which raises a **hard
command error** if any option it wants to autosave is already set in the regular
(non-autosave) config. Included files very much count:

```python
def _disallow_include_conflicts(self, regular_fileconfig):
    for section in self.fileconfig.sections():
        for option in self.fileconfig.options(section):
            if regular_fileconfig.has_option(section, option):
                msg = ("SAVE_CONFIG section '%s' option '%s' conflicts "
                       "with included value" % (section, option))
                raise self.printer.command_error(msg)
```

Two calibration workflows on this machine are therefore already broken, and each will fail
only at the moment you try to save a result you just spent real time measuring.

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `SHAPER_CALIBRATE` followed by `SAVE_CONFIG` **will fail** with
`SAVE_CONFIG section 'input_shaper' option 'shaper_freq_x' conflicts with included value`,
because `tuning.cfg` sets `shaper_freq_x` / `shaper_type_x` / `shaper_freq_y` / `shaper_type_y`
explicitly.
**Reasoning:** `_disallow_include_conflicts()` in
[configfile.py](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py) raises
`command_error` on any overlap between the autosave block and included config. The empty
`#*# [input_shaper]` stub already sitting at the bottom of `printer.cfg` is the fingerprint of
this having been hit before. This is not a machine-damage risk, but it silently throws away a
completed resonance run. Before re-running `SHAPER_CALIBRATE`, comment out the four `shaper_*`
lines in `tuning.cfg` so the autosave block can own them, or plan to transcribe the printed
values into `tuning.cfg` by hand and skip `SAVE_CONFIG` entirely.

</div>

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `Z_OFFSET_APPLY_ENDSTOP` followed by `SAVE_CONFIG` **will fail**
the same way, because `hardware.cfg` sets `[stepper_z] position_endstop: 0`.
**Reasoning:** `cmd_Z_OFFSET_APPLY_ENDSTOP` calls
`configfile.set(self.z_endstop_config_name, 'position_endstop', ...)`
([manual_probe.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/manual_probe.py)),
which collides with the included value. Since this is the only command that can make a babystep
permanent on this printer (see the Z-datum finding in `hardware.cfg` below), the practical
effect is that **there is currently no working path to persist a first-layer height
correction** — which is very likely the real reason the 2026-09-14 babystep of −0.185 mm never
stuck.
**CORRECTION (2026-09-20, while applying Tier 1):** an earlier draft of this block suggested
commenting out `position_endstop: 0` so the autosave block could own it. **Do not do that** —
Config_Reference states `position_endstop` *"must be provided for the X, Y, and Z steppers on
cartesian style printers"*, so Klipper refuses to start without it, and there is no way to
seed the autosave block first. The working procedure is: run `Z_OFFSET_APPLY_ENDSTOP`, read
the `position_endstop` value Klipper prints, hand-edit `hardware.cfg`, then `FIRMWARE_RESTART`.
Never call `SAVE_CONFIG` for it. (`shaper_freq_x` *can* safely be commented out, because it
defaults to 0 — the two cases are not symmetric.)

</div>

By contrast, `PROBE_CALIBRATE` → `SAVE_CONFIG` **does** work, and did: `probe.cfg`'s
`[bltouch]` deliberately does not set `z_offset`, so the autosaved `z_offset = 1.782` has
nothing to collide with. That asymmetry is worth internalising — it is precisely why one
calibration persisted and the other two cannot.

### Comment drift

`HANDOFF.md` flagged one stale pressure-advance comment. There are three, plus two wrong pin
comments:

| Location | Comment says | Reality |
|---|---|---|
| `printer.cfg`, Pressure Advance header block | `Current: 0.06` | `0.05` in `thermistors.cfg` |
| `tuning.cfg`, footer | `Current value in [extruder] section: 0.06` | `0.05` |
| `tuning.cfg`, footer | `Adjust via: SET_PRESSURE_ADVANCE ADVANCE=0.06` | `0.05` |
| `thermistors.cfg` | `sensor_pin: PF4   # T0` | PF4 is the **T1** header |
| `thermistors.cfg` | `sensor_pin: PF3   # T3` | PF3 is the **T0** header |

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Fix all five stale comments, and delete the Pressure Advance
comment block in `printer.cfg` entirely rather than keeping a duplicated value that has to be
maintained in three places.
**Reasoning:** The two pin comments contradict the official board config
([generic-bigtreetech-skr-pro.cfg](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg),
which labels `sensor_pin: PF4 # T1 Header` for the extruder and `sensor_pin: PF3 # T0` for the
bed). Wrong pin comments are worse than no comments when you are tracing a thermistor fault.
The pressure advance value should live in exactly one place, `thermistors.cfg`, since it is
going to change as soon as real PA calibration happens.

</div>

---


## Klipper Firmware Config Review — `hardware.cfg`

### Socket map — reconstructed against the official board config

Every pin in this file was cross-referenced against Klipper's
[generic-bigtreetech-skr-pro.cfg](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg),
independently corroborated against BigTreeTech's own
[SKR-PRO-V1.2 schematic](https://github.com/bigtreetech/BIGTREETECH-SKR-PRO-V1.1/blob/master/SKR-PRO-V1.2/Schematic/SKR-PRO-V1.2.PDF).
The official per-socket map is:

| Socket | step | dir | enable | uart | DIAG |
|---|---|---|---|---|---|
| X | PE9 | PF1 | PF2 | PC13 | PB10 |
| Y | PE11 | PE8 | PD7 | PE3 | PE12 |
| Z | PE13 | PC2 | PC0 | PE1 | PG8 |
| E0 | PE14 | PA0 | PC3 | **PD4** | PE15 |
| E1 | PD15 | PE7 | PA3 | PD1 | PE10 |
| E2 | PD13 | PG9 | PF0 | PD6 | PG5 |

Mapping this config onto it:

| Config section | step | dir | enable | uart | Physical socket |
|---|---|---|---|---|---|
| `stepper_x` | PE9 | PF1 | PF2 | PC13 | **X** — fully consistent |
| `stepper_y` | PE11 | PE8 | PD7 | PE3 | **Y** — fully consistent |
| `stepper_z` | PE13 (Z) | PE7 (E1) | PA3 (E1) | PD1 (E1) | **crossed** |
| `stepper_z1` | PD15 (E1) | PC2 (Z) | PC0 (Z) | PE1 (Z) | **crossed** |
| `extruder` | PE14 | PA0 | PC3 | — | **E0**, confirmed by `heater_pin: PB1` = Heat0 |

A full pin-conflict scan across all 14 live includes (resolving the `[board_pins]`
aliases) found **no pin used twice**. That part is clean.

### The crossed Z / E1 driver pins

`stepper_z` takes its STEP from the Z socket but its DIR, ENABLE and UART from the E1
socket, and `stepper_z1` does the reverse. This works today only because the two
sections are byte-for-byte identical in every setting that matters, and because the
two Z motors are always enabled together and always commanded in the same direction.

The practical cost is diagnostic. `DUMP_TMC STEPPER=stepper_z` actually reads the
driver in the **E1** socket, and a driver over-temperature warning attributed to
`stepper_z` refers to the other physical module. Any future attempt to give one Z
motor a different current or invert one direction will land on the wrong driver.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Swap the `dir_pin`, `enable_pin` and `uart_pin` values
between `[stepper_z]`/`[tmc2209 stepper_z]` and `[stepper_z1]`/`[tmc2209 stepper_z1]`
so each section holds one complete socket. Target: `stepper_z` → dir `PC2`, enable
`!PC0`, uart `PE1`; `stepper_z1` → dir `PE7`, enable `!PA3`, uart `PD1`.
**Reasoning:** Matches the documented socket grouping in the
[official board config](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg).
Motion is unchanged, because both motors share direction and enable state and both
drivers have identical settings — but driver diagnostics start pointing at the right
module. **Verify direction after the change**: swapping which physical motor gets which
non-inverted `dir_pin` should be neutral here since neither is inverted, but confirm a
`G1 Z10` still moves the gantry the right way before trusting it.

</div>

### The Z datum is the endstop switch, not the probe

`[stepper_z]` has `endstop_pin: PG8` and `[stepper_z1]` has `endstop_pin: PG5` — real
mechanical switches, not `probe:z_virtual_endstop`. Klipper documents that behaviour
explicitly for additional steppers:

> `endstop_pin:` — *If an endstop_pin is defined for the additional stepper then the
> stepper will home until the endstop is triggered. Otherwise, the stepper will home
> until the endstop on the primary stepper for the axis is triggered.*
> ([Config_Reference, `[stepper_z1]`](https://www.klipper3d.org/Config_Reference.html#stepper_z1))

So each Z motor homes to its own switch, which self-levels the gantry mechanically on
every `G28`. **That is why disabling `[z_tilt]` in `probe.cfg` was the right call** —
`z_tilt` would fight the per-stepper homing, which fully explains the "causing gantry
issues" note. This is a good setup and should not be reverted.

The consequence nobody appears to have drawn out yet:

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN (correctness, not damage):** **`PROBE_CALIBRATE` cannot fix
first-layer height on this printer, and outstanding task #1 in `HANDOFF.md` is aimed at
the wrong parameter.** Because Z homes to a physical switch at `position_endstop: 0`,
the nozzle-to-bed datum is set by that switch. The BLTouch `z_offset` (currently
1.782) does **not** enter into it.
**Reasoning:** `Z_OFFSET_APPLY_PROBE` *"subtract[s] it from the probe's z_offset"*,
whereas `Z_OFFSET_APPLY_ENDSTOP` *"subtract[s] it from the stepper_z endstop_position"*
([G-Codes.md](https://www.klipper3d.org/G-Codes.html)). Klipper registers
`Z_ENDSTOP_CALIBRATE` and `Z_OFFSET_APPLY_ENDSTOP` on this machine precisely because
`[stepper_z] position_endstop` exists — see the registration guard in
[manual_probe.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/manual_probe.py).
`z_offset` additionally has almost no effect on the mesh here, because
`zero_reference_position: 150,150` normalises the mesh at the centre point, so a
constant `z_offset` error cancels out exactly.
**Correct workflow:** use **`Z_ENDSTOP_CALIBRATE`** (paper test) to set first-layer
height, and **`Z_OFFSET_APPLY_ENDSTOP`** to bake in a babystep — after first commenting
out `position_endstop: 0` in this file, or `SAVE_CONFIG` will refuse (see the
`printer.cfg` section above).

</div>

### The endstop pins are shared with driver DIAG lines

`stepper_x` uses `PE15`, `stepper_y` uses `PE10`, `stepper_z1` uses `PG5`. Per the
table above, those are the **E0, E1 and E2 sockets' DIAG/stallguard lines**. On the
SKR Pro the DIAG net and the corresponding endstop header are the same MCU pin, so a
driver module whose DIAG pin is still fitted sits electrically in parallel with the
mechanical switch. BigTreeTech documents the mitigation directly:

> *"when the stallguard function is not used, the stallguard pin of the TMC2209 needs
> to be cut off so that the mechanical switch can work normally."*
> ([BTT SKR PRO V1.2 docs](https://github.com/bigtreetech/docs/blob/master/docs/SKR%20PRO%20V1.2.md))

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** The X endstop (`PE15`) shares a pin with the **E0** driver's
DIAG line and the Y endstop (`PE10`) with the **E1** driver's DIAG line. If either of
those driver modules still has its DIAG/stallguard pin fitted, a driver fault or stall
assertion registers as a **phantom X or Y endstop trigger**.
**Reasoning:** Klipper's own board config documents `diag1_pin: PE15` for the E0 socket
and `PE10` for E1
([generic-bigtreetech-skr-pro.cfg](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg)),
and BTT instructs cutting that pin when stallguard is unused (quote above). The E1
socket here holds a Z driver run at `run_current: 1.1` with `hold_current: 0.8`, which is
a realistic candidate for a thermal DIAG assertion. This is worth checking because
`HANDOFF.md` records an earlier failed print attributed to *"lost steps near axis
limits"* — a spurious endstop trigger mid-print produces exactly that signature.
**Check:** with the printer powered down, pull the E0 and E1 driver modules and confirm
their DIAG pins are cut or bent out. `stepper_z1` on `PG5` (E2 socket) is safe — that
socket is empty. This is an inspection item, not a config change; I could not determine
the physical state from the config alone.

</div>

### `rotation_distance` — X, Y and Z were calibrated against the wrong reference

| Axis | Configured | Geometric ideal | Deviation |
|---|---|---|---|
| `stepper_x` / `stepper_y` | 39.77 | 40.0 (20-tooth GT2, 2 mm pitch) | −0.575 % |
| `stepper_z` / `stepper_z1` | 4.018 | 4.0 (lead screw lead, with `gear_ratio: 3:1`) | +0.450 % |

The inline comments say both were *"Calibrated 2025-12-31"* from a measured print error.
For a belt-driven axis, `rotation_distance` is fixed by tooth count and belt pitch —
20 × 2 mm is exactly 40 mm, with no tolerance stack to absorb. A lead screw's lead is
likewise exact. A sub-1 % dimensional error on a printed part comes from extrusion width,
flow and elephant-foot, not from steps per millimetre, and "correcting" it in
`rotation_distance` bakes a flow error into every axis motion including travel and
non-extruding moves.

This is directly analogous to the extruder lesson already recorded in `HANDOFF.md`, where
a `rotation_distance` of 19.4391 turned out to be a mechanical slippage problem wearing a
calibration costume. Same shape of mistake, different axis.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `rotation_distance` (X and Y) — current `39.77` → suggested
`40`. `rotation_distance` (Z and Z1) — current `4.018` → suggested `4`.
**Reasoning:** These are geometrically exact for a 20-tooth 2 mm-pitch pulley and a 4 mm
lead screw. Klipper's
[Rotation_Distance.md](https://www.klipper3d.org/Rotation_Distance.html) derives belt axes
as `rotation_distance = <belt_pitch> * <number_of_teeth_on_pulley>` and states for lead
screws that it *"is the distance the axis moves with one full rotation of the screw"* —
both are computed, not measured. The widely cited community position is the same: Ellis's
[Print Tuning Guide](https://ellis3dp.com/Print-Tuning-Guide/) does not include an X/Y
steps calibration step at all, and directs dimensional error to flow and
`xy_size_compensation` instead. If parts still measure small after reverting, correct it
with the slicer's `xy_size_compensation` (currently `0`), which affects only the printed
outline and not machine motion. **Caveat:** reverting changes absolute part size by
~0.57 %, so re-check a calibration cube afterwards rather than assuming.

</div>

### Homing margins

`position_endstop: 300` equals `position_max: 300` on both X and Y, so after homing the
toolhead sits exactly on its soft limit with zero margin. `homing_retract_dist: 5` and
`homing_speed: 25` are sensible; `second_homing_speed` is unset and defaults to half of
`homing_speed`.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[stepper_x]` / `[stepper_y]` — leave `position_max: 300`
but set `position_endstop: 299.5`, or raise `position_max` slightly above the endstop.
**Reasoning:** With the two values equal, the post-homing position is exactly on the soft
limit and any macro that rounds up, or any `PAUSE` park at `X=295 Y=295` combined with a
`_CLIENT_RETRACT`, is operating with no headroom. This is a low-severity robustness
tidy-up rather than a bug — but `HANDOFF.md` already records one failed print blamed on
behaviour *"near axis limits"*, and the earlier purge-line fix (`G0 X2 Y2` → `X10 Y10`)
was the same class of problem at the other end of the axis.

</div>

### TMC2209 driver settings

Common to all four configured drivers: `sense_resistor: 0.110` (matches Klipper's default
and the standard BTT stepstick), `driver_TBL: 2`, `driver_TOFF: 3`.

`driver_TBL: 2` and `driver_TOFF: 3` are **already Klipper's defaults** for TMC2209
(confirmed against the `set_config_field` calls in
[tmc2209.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc2209.py)),
so both lines are no-ops. Harmless, but they read as deliberate tuning when they are not.

| Setting | X / Y | Z / Z1 | Assessment |
|---|---|---|---|
| `run_current` | 1.1 | 1.1 | High — see below |
| `hold_current` | unset | 0.8 | Appropriate for a gantry that must not sag |
| `stealthchop_threshold` | 0 (spreadCycle) | 1000 | **Z is inconsistent — see below** |
| `interpolate` | True | False | **Inverted relative to Klipper's advice — see below** |
| `microsteps` | 32 | 128 | See step-rate note |

#### Z combines two settings that cancel each other out

`[stepper_z]` uses `microsteps: 128` with `interpolate: False`, which is exactly Klipper's
documented recipe for maximum positional accuracy:

> *"For best positional accuracy consider using spreadCycle mode and disable interpolation
> (set `interpolate: False`). ... Typically, a microstep setting of `64` or `128` will have
> similar audible noise as interpolation, and do so without introducing a systemic
> positional error."* ([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html))

But the same section is set to `stealthchop_threshold: 1000`, which puts the driver in
stealthChop for every Z move (max Z velocity is only 15 mm/s). Klipper is explicit that
this negates the benefit:

> *"If using stealthChop mode then the positional inaccuracy from interpolation is small
> relative to the positional inaccuracy introduced from stealthChop mode. Therefore tuning
> interpolation is not considered useful when in stealthChop mode."*

and quantifies the cost:

> *"Tests comparing modes have shown an increased 'positional lag' of around 75% of a
> full-step during constant velocity moves when using stealthChop mode."*

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[tmc2209 stepper_z]` and `[tmc2209 stepper_z1]` —
`stealthchop_threshold` current `1000` → suggested `0`.
**Reasoning:** `interpolate: False` + `microsteps: 128` was chosen for accuracy, and
stealthChop throws that accuracy away
([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html), quoted above). spreadCycle
also gives *"greater torque and greater positional accuracy"*, which is what a heavy
gantry on 3:1 reduction wants. Separately, a nonzero threshold means the driver **switches
mode mid-move**, which the same doc warns against directly: *"the drivers often produce
poor and confusing results if the mode changes while the motor is at a non-zero velocity"*
— its guidance is to either omit the option entirely or set `999999`, never something in
between. **Tradeoff:** Z will be audibly louder. If that matters more than accuracy, the
consistent alternative is `stealthchop_threshold: 999999` **plus** `interpolate: True` and
`microsteps: 32`, which is coherent in the other direction.

</div>

#### Step rate from 128 microsteps on Z

At `microsteps: 128`, `full_steps_per_rotation: 200`, `rotation_distance: 4.018` and
`gear_ratio: 3:1`, Z works out to **19 114 steps/mm**:

| Quantity | Value |
|---|---|
| Z steps/mm | 19 114 |
| Steps/s per Z motor at `max_z_velocity: 15` | 286 710 |
| Both Z motors together | **573 420** |
| Same at `microsteps: 32` | 143 355 |
| X or Y motor at 300 mm/s | 48 278 |

For context, Klipper's synthetic three-stepper benchmark for the STM32F407 is
`ticks: 205` at 168 MHz, i.e. about 2.46 M steps/s aggregate — but
[Benchmarks.md](https://www.klipper3d.org/Benchmarks.html) is emphatic that *"this
benchmark stepping rate is not achievable in day-to-day use as Klipper needs to perform
other tasks."* So 573 k steps/s is not an imminent failure, and no `Timer too close`
errors are reported in `HANDOFF.md` — but it is roughly four times more MCU and host work
than the axis needs, on a board that also drives a mini12864, 60 NeoPixels and a second
MCU link. This is a watch item rather than a required change; if `stealthchop_threshold`
is set to `0` as suggested above, the 128 microsteps start earning their keep and are
worth retaining.

#### `run_current: 1.1` and driver cooling

Klipper documents no numeric ceiling here, only *"prefer higher current values as long as
the stepper motor does not get too hot and the stepper motor driver does not report
warnings or errors"* ([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html)). I am
not going to invent a limit that the docs do not state. What I can say concretely is that
1.1 A RMS across four drivers is toward the upper end for TMC2209 stepsticks, and this
machine caps its driver cooling fan at 60 % duty — see the `fans.cfg` section, where the
two settings are worth considering together.

---


## Klipper Firmware Config Review — `tuning.cfg`

### `max_accel: 3000` against the measured resonance frequencies

This was the most interesting question in the brief, and it has a precise answer.

Klipper's `Resonance_Compensation.md` gives no formula — it is a printed tuning-tower
procedure. The number Klipper prints after `SHAPER_CALIBRATE` comes from
`find_shaper_max_accel()` in
[shaper_calibrate.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/shaper_calibrate.py),
which bisects for the acceleration at which shaper smoothing reaches a fixed target:

```python
def find_shaper_max_accel(self, shaper, scv):
    # Just some empirically chosen value which produces good projections
    # for max_accel without much smoothing
    TARGET_SMOOTHING = 0.12
    max_accel = self._bisect(lambda test_accel: self._get_shaper_smoothing(
        shaper, test_accel, scv) <= TARGET_SMOOTHING)
    return max_accel
```

I reproduced that routine verbatim, together with Klipper's own `get_mzv_shaper()` from
[shaper_defs.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/shaper_defs.py),
using the default damping ratio of 0.1 and this printer's `square_corner_velocity: 5.0`:

| Axis | Measured | Shaper | Smoothing-limited max_accel |
|---|---|---|---|
| X | 65.0 Hz | mzv | **12 400 mm/s²** |
| Y | 46.2 Hz | mzv | **6 300 mm/s²** |

Smoothing actually incurred at various accelerations, against the 0.12 target:

| max_accel | X (65.0 Hz) | Y (46.2 Hz) |
|---|---|---|
| 1500 | 0.024 | 0.040 |
| 3000 (current) | 0.035 | **0.061** |
| 4000 | 0.042 | 0.076 |
| 5000 | 0.049 | 0.095 |
| 6300 | — | 0.120 (limit) |

So at the configured 3000, Y is using half of its available smoothing budget and X barely
a quarter. Y is the binding axis, as expected for CoreXY, where a Y move drags the whole
gantry.

The honest caveat, from the docs themselves: this is the **smoothing** limit only. Klipper
instructs you to *"choose the minimum out of the two acceleration values (from ringing and
smoothing)"* ([Resonance_Compensation.md](https://www.klipper3d.org/Resonance_Compensation.html)),
and the ringing limit depends on frame stiffness, belt tension and moving mass — none of
which this calculation can see. 6300 is a ceiling, not a recommendation.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[printer] max_accel` — current `3000` → suggested `4000`
as a first step, with a ringing test before going further, and `6000` as the realistic
ceiling.
**Reasoning:** Klipper's own `find_shaper_max_accel()` bisection
([shaper_calibrate.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/shaper_calibrate.py))
gives 6300 mm/s² for mzv at the measured 46.2 Hz Y frequency and 12 400 for 65.0 Hz X, so
3000 leaves roughly half the available headroom unused. **Do not jump straight to 6300** —
that is the smoothing limit, and the docs require taking the minimum of the smoothing and
ringing limits. Step up via the documented ringing tower
([Resonance_Compensation.md](https://www.klipper3d.org/Resonance_Compensation.html)) and
stop where corners start to degrade. Note the slicer's per-feature accelerations
(perimeter 1500, external 800, first layer 500) are all below 3000 already, so this mainly
buys faster infill and travel, and the print profile's `infill_acceleration = 3000` and
`travel_acceleration = 3000` would need raising in step to actually use it.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[printer] square_corner_velocity` — current `5.0` →
**keep at 5.0**. Flagging this explicitly because it is a tempting knob to raise alongside
`max_accel`, and it should not be.
**Reasoning:** *"Another parameter that can impact smoothing is `square_corner_velocity`,
so it is not advisable to increase it above the default 5 mm/sec to prevent increased
smoothing."* ([Resonance_Compensation.md](https://www.klipper3d.org/Resonance_Compensation.html)).
Confirmed numerically: raising it to 10 drops the Y-axis smoothing-limited accel from 6300
to 5900, while leaving X unchanged. No change needed — this entry exists to stop a future
session from "helpfully" raising it.

</div>

### `[input_shaper]`, `[adxl345]` and `[resonance_tester]`

| Setting | Value | Assessment |
|---|---|---|
| `shaper_freq_x` / `shaper_type_x` | 65.0 / mzv | Plausible for a CoreXY toolhead. ✅ |
| `shaper_freq_y` / `shaper_type_y` | 46.2 / mzv | Lower than X, which is the expected ordering for CoreXY (a Y move carries the whole gantry). This is a useful sanity check that the accelerometer's axes are not swapped. ✅ |
| `[adxl345] cs_pin: rpi:None`, `spi_bus: spidev0.0` | — | Correct form for CE0 on the Pi's SPI0. ✅ |
| `[adxl345] axes_map` | unset (default `x,y,z`) | Not set, and the frequency ordering above suggests it does not need to be. ✅ |
| `[resonance_tester] probe_points: 150,150,20` | — | Bed centre at 20 mm. ✅ |

`mzv` on both axes is what Klipper's autotuner usually selects and is a reasonable
default. For reference, at the Y frequency the alternatives give: `zv` → 8300 mm/s²
(less vibration suppression, more headroom), `ei` → 3900 (more suppression, less
headroom). No change recommended; `mzv` is the sensible middle.

### `[firmware_retraction]`

| Setting | Value | Assessment |
|---|---|---|
| `retract_length` | 0.6 | Reasonable for a direct-drive BMG. Matches the slicer. ✅ |
| `retract_speed` | 40 | Fine. ✅ |
| `unretract_extra_length` | 0 | Fine — no evidence of post-retract under-extrusion. ✅ |
| `unretract_speed` | 30 | Fine. ✅ |

Nothing to change here. Note that these values only take effect because the printer
profile sets `use_firmware_retraction = 1`; see the slicer second-opinion section for one
real problem with that pairing.

---


## Klipper Firmware Config Review — `thermistors.cfg`

### `[extruder]`

| Setting | Value | Assessment |
|---|---|---|
| `rotation_distance` | 26.5475 | Freshly reconfirmed to ~0.05 % across two trials after the slippage fix, and within 0.8 % of the untouched theoretical 26.76116. High confidence. ✅ |
| `gear_ratio` | 50:17 | Standard BMG. ✅ |
| `microsteps` | 16 | Fine — 354.5 steps/mm is ample for a geared extruder. |
| `max_extrude_only_distance` | 200 | Raised from Klipper's default of **50**. Deliberate and necessary for the 100 mm/80 mm filament calibration extrudes, but it is a safety check being relaxed — see below. |
| `max_extrude_only_velocity` | 60 | Matches the slicer's `machine_max_feedrate_e`. ✅ |
| `max_extrude_only_accel` | 2000 | Matches the slicer's `machine_max_acceleration_e`. ✅ |
| `max_extrude_cross_section` | unset | Defaults to `4.0 × nozzle_diameter²` = **0.64 mm²**. The `START_PRINT` purge line peaks at 0.20 mm², so it clears comfortably. ✅ No change needed. |
| `pressure_advance` | 0.05 | Placeholder, already tracked. |
| `pressure_advance_smooth_time` | 0.040 | Equals Klipper's default. Redundant but harmless. |
| `min_extrude_temp` | 160 | Lowered from the default of 170. Fine for PLA. |
| `max_temp` | 280 | Fine. |
| `min_temp` | 0 | See below. |

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[extruder] max_extrude_only_distance` — current `200` →
suggested `200` during calibration work, `100` otherwise; or leave as-is with a comment
explaining why it is raised.
**Reasoning:** Klipper's default is 50 mm and the option exists to catch a runaway
extrude-only move ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#extruder)).
200 was clearly set to allow the `G1 E100` calibration extrudes in `HANDOFF.md`, which is
legitimate — but the file carries no comment saying so, and a future reader will assume it
is load-length tuning. This is a documentation fix more than a value change.

</div>

### `[heater_bed]` and `min_temp` values

`min_temp` is a micro-controller-level guard: if the measured temperature leaves the
range, the MCU shuts down. Klipper's guidance is directional rather than numeric:

> *"This controls a safety feature implemented in the micro-controller code — should the
> measured temperature ever fall outside this range then the micro-controller will go into
> a shutdown state. This check can help detect some heater and sensor hardware failures.
> **Set this range just wide enough so that reasonable temperatures do not result in an
> error.**"* ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#extruder))

Klipper itself accepts anything above absolute zero without warning — `heaters.py` only
enforces `min_temp >= -273.15` and `max_temp > min_temp`.

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `[heater_bed] min_temp` — current `-50` → suggested `0`.
**Reasoning:** −50 °C is far below anything a working NTC thermistor will ever report on
this machine, which means **the low-side disconnected-or-failing-sensor shutdown for the
bed is effectively disabled**. Klipper's own instruction is to set the range *"just wide
enough so that reasonable temperatures do not result in an error"*
([Config_Reference](https://www.klipper3d.org/Config_Reference.html#extruder)); −50 is far
wider than that. Klipper accepts it silently — `heaters.py` validates only against
absolute zero — so nothing has ever flagged it. The extruder's `min_temp: 0` matches
Klipper's own shipped example configs and is fine as-is; it is the bed value that is out
of line. Note this is a *detection* weakness, not an active hazard: `[verify_heater]` is
separately and automatically enabled for both heaters and still guards runaway heating.

</div>

`max_temp: 110` on the bed is sensible. `[verify_heater]` is not present in the config,
which is correct — it is enabled automatically for every heater:

> *"Heater verification is automatically enabled for each heater that is configured on the
> printer. Use verify_heater sections to change the default settings."*
> ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#verify_heater))

Defaults are `max_error: 120`, `check_gain_time: 20 s` for extruders and 60 s for the bed,
`hysteresis: 5`, `heating_gain: 2`. Nothing here needs overriding.

### Temperature sensors

`[temperature_sensor raspberry_pi]` and `[temperature_sensor mcu_temp]` are both present
and sensibly bounded. ✅ Good practice — these give early warning of MCU or host thermal
problems and many configs omit them.

---

## Klipper Firmware Config Review — `fans.cfg`

| Section | Setting | Assessment |
|---|---|---|
| `[fan]` | `pin: PC8` | Matches the official board config's part-cooling fan. ✅ |
| `[heater_fan extruder_fan]` | `pin: PE5`, `heater_temp: 50` | PE5 matches the official `heater_fan fan1`. `heater_temp: 50` is Klipper's default. ✅ |
| `[controller_fan stepper_fan]` | `pin: PE6` | Matches the official (commented) `heater_fan fan2` pin. ✅ |
| | `heater: extruder, heater_bed` | Fine. `stepper:` is unset, which defaults to **all** steppers — correct for a driver-cooling fan. ✅ |
| | `max_power: 0.6` | See below. |
| | `idle_timeout: 30` / `idle_speed: 0.6` | 30 s is Klipper's default. `idle_speed: 0.6` is scaled by `max_power`, so the real idle duty is 0.36. Intentional-looking. |
| | `shutdown_speed: 0` | Acceptable here, because Klipper drives the stepper enable pins to their disabled state on shutdown, so the drivers de-energise. |
| | `kick_start_time: 0.100`, `cycle_time: 0.010`, `hardware_pwm: False` | Standard, fine. ✅ |

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[controller_fan stepper_fan] max_power` — current `0.6` →
suggested `1.0`; **or** reduce `run_current` on the four TMC2209 drivers from `1.1`.
**Reasoning:** These two settings need to be considered together, and currently they pull
against each other: four drivers at 1.1 A RMS are cooled by a fan capped at 60 % duty.
Klipper gives no numeric current ceiling, only *"prefer higher current values as long as
the stepper motor does not get too hot and the stepper motor driver does not report
warnings or errors"*, and lists the remedy for an over-temperature driver as *"decrease the
stepper motor current, increase cooling on the stepper motor driver, and/or increase
cooling on the stepper motor"* ([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html)).
Right now the config has chosen high current **and** reduced cooling, which is the one
combination the doc argues against. **How to decide rather than guess:** run a long print,
then `DUMP_TMC STEPPER=stepper_x` and check the `DRV_STATUS` `otpw` (over-temperature
pre-warning) flag. If `otpw` never sets, the current setup is fine and this is a non-issue;
if it does, raise `max_power` first since that costs only noise. Note the driver
temperature flags are readable for X/Y/Z/Z1 but **not** for the extruder, which has no
UART link — see the extruder section below.

</div>

---


## Klipper Firmware Config Review — `probe.cfg`

### `[bltouch]` — three values differ from Klipper's defaults, and they interact

| Setting | Configured | Klipper default | Note |
|---|---|---|---|
| `pin_move_time` | **0.4** | **0.680** | Reduced by 41 %. See below. |
| `samples` | 3 | 1 | Good practice. ✅ |
| `samples_tolerance` | **0.050** | 0.100 | Tightened 2×. |
| `samples_tolerance_retries` | **6** | 0 | Raised a lot. |
| `speed` | 5 | 5.0 | Default. ✅ |
| `lift_speed` | 4 | = `speed` | Slightly slower than probe speed; fine. |
| `sample_retract_dist` | 5 | 2.0 | Raised; safe, costs time. |
| `stow_on_each_sample` | true | True | Default. See below. |
| `probe_with_touch_mode` | unset | False | See below. |
| `x_offset` / `y_offset` | −27 / −20 | — | ✅ |

The file header calls this *"LENIENT MODE"*, and the three non-default values tell a
consistent story: probing is not repeatable enough, so the retry budget was raised until
it stopped erroring. That treats the symptom. The tolerance is *tighter* than default
while the retry count is 6, so the config is simultaneously demanding more precision and
tolerating more failures to reach it.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[bltouch] pin_move_time` — current `0.4` → suggested `0.680`
(Klipper's default).
**Reasoning:** This is *"The amount of time (in seconds) to wait for the BLTouch pin to move
up or down"* ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#bltouch)).
At 0.4 s the pin may not have finished travelling before Klipper proceeds, which produces
exactly the kind of scattered, occasionally-wrong readings that `samples_tolerance_retries: 6`
was presumably added to paper over. This is my best candidate for the root cause of the probe
flakiness, and it costs about 0.3 s per deploy to test. **Test method:** set it back to
0.680, run `PROBE_ACCURACY`, and compare the reported range and standard deviation against
the current value.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[bltouch] samples_tolerance_retries` — current `6` →
suggested `3`, **after** measuring actual repeatability with `PROBE_ACCURACY` and setting
`samples_tolerance` to roughly 3× the measured standard deviation.
**Reasoning:** `samples_tolerance_retries` defaults to 0, which *"causes an error to be
reported on the first sample that exceeds samples_tolerance"*
([Config_Reference](https://www.klipper3d.org/Config_Reference.html#probe)). A budget of 6
means a genuinely degrading probe can silently keep producing meshes rather than telling you
it is failing. Setting the tolerance from a measurement instead of from a guess turns this
from a workaround into a real quality gate. This is a diagnostic-quality change, not a
print-quality one.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[bltouch] stow_on_each_sample` — current `true` → suggested
`false`, **paired with** `probe_with_touch_mode: true`.
**Reasoning:** This directly addresses a documented pain point in `HANDOFF.md` — the 7×7
mesh is slow enough that the long gcode-script POST triggers a `BlockingIOError` and crashes
klippy. At 49 points × 3 samples with a stow and deploy between every single one, that is
294 pin cycles per mesh. Klipper: *"Klipper supports leaving the probe deployed between
consecutive probes, which can reduce the total time of probing"*, and *"It is recommended to
use `probe_with_touch_mode` configured to True when using `stow_on_each_sample` configured to
False"* ([BLTouch.md](https://www.klipper3d.org/BLTouch.html)).
**Two documented cautions, both of which apply:** (1) *"Setting `stow_on_each_sample` to False
can lead to Klipper making horizontal toolhead movements while the probe is deployed... If
there is insufficient clearance then a horizontal move may cause the pin to catch on an
obstruction and result in damage to the printer."* `horizontal_move_z: 10` gives roughly 3 mm
of pin clearance above a flat bed here, which should be adequate, but verify it physically
before enabling — this is the one suggestion in this document with a genuine crash risk if
the clearance assumption is wrong. (2) *"Some 'clone' devices and the BL-Touch v2.0 (and
earlier) may have reduced accuracy when `probe_with_touch_mode` is set to True... be sure to
test the probe accuracy before and after setting this value (use the `PROBE_ACCURACY`
command)."* If accuracy degrades, revert.

</div>

### `[bed_mesh]`

| Setting | Value | Assessment |
|---|---|---|
| `mesh_min` / `mesh_max` | 35,35 / 270,270 | These are **probe** coordinates — *"This coordinate is relative to the probe's location"* ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#bed_mesh)), confirmed by `use_xy_offsets(True)` in [bed_mesh.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bed_mesh.py). So the nozzle reaches X=297, Y=290 at the far corner, inside `position_max: 300`. ✅ Correct, and correctly reasoned in `HANDOFF.md`. |
| `probe_count` | 7,7 | ✅ Meets the documented 4-per-axis minimum for bicubic. |
| `algorithm` / `bicubic_tension` | bicubic / 0.2 | ✅ Correct choice at 7 points per axis; below 4 Klipper silently forces lagrange. |
| `zero_reference_position` | 150,150 | ✅ The modern option. `relative_reference_index` was deprecated 2023-06-19 and **removed** 2024-02-15 ([Config_Changes.md](https://www.klipper3d.org/Config_Changes.html)) — it would now be a hard startup error. This config is correctly on the current option. |
| `speed` / `horizontal_move_z` | 150 / 10 | Fine. ✅ |
| `mesh_pps` | 2,2 | Default. ✅ |
| `fade_start` / `fade_end` | 0.5 / 5.0 | See below. |
| `fade_target` | unset | See below. |

The saved mesh itself is worth noting, because it changes how much any of this matters:

| Metric | Value |
|---|---|
| Probed points | 49 |
| Minimum | −0.0682 mm |
| Maximum | +0.0356 mm |
| **Total range** | **0.1038 mm** |
| Mean | +0.00018 mm |

That is an exceptionally flat bed — the entire variation is about half a layer height, and
the mean is essentially zero. Most of the risk normally associated with mesh settings simply
does not apply here. The only real structure is a slight droop at the far-X edge (the X=270
column averages −0.035 mm against roughly +0.008 mm everywhere else).

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[bed_mesh] fade_end` — current `5.0` → suggested `10.0`, and
add `fade_target: 0`.
**Reasoning:** Klipper's own recommendation is explicit: *"If a user wishes to enable fade, a
value of 10.0 is recommended"*, and on the target, *"Users that wish to converge to the z
homing position should set this to 0"* — the default is otherwise *"the average z value of the
mesh"* ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#bed_mesh)).
`fade_start: 0.5` is also below the default of 1.0, meaning mesh correction starts fading out
at the second layer. **Low impact in practice**: the mesh mean here is +0.00018 mm, so the
implicit `fade_target` is already within a rounding error of 0, and a 0.10 mm total range
means fade has very little to fade. This is a correctness-of-intent fix rather than a
print-quality one.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Add adaptive bed meshing — `BED_MESH_CALIBRATE ADAPTIVE=1` in
`START_PRINT`, with `adaptive_margin: 5` in `[bed_mesh]`.
**Reasoning:** This is already item 4 on the `HANDOFF.md` backlog, and this bed qualifies:
*"adaptive bed meshing is best used on machines that can normally probe the entire bed and
achieve a maximum variance less than or equal to 1 layer height"*
([Bed_Mesh.md](https://www.klipper3d.org/Bed_Mesh.html)) — measured variance here is 0.104 mm
against a 0.2 mm layer. It scales probe count down by the ratio of adapted to default mesh
area, so a small part probes far fewer points, which also sidesteps the long-POST
`BlockingIOError` problem. Requires the `exclude_object` labels the slicer already emits.
**Caveat from the same doc:** *"adapted bed meshes should not be re-used"* — a new mesh is
generated per print, so this replaces `BED_MESH_PROFILE LOAD=default` in `START_PRINT` rather
than supplementing it, and it adds probing time to every print.

</div>

### `[screws_tilt_adjust]` — subtly correct, and worth a comment so nobody "fixes" it

The four screw positions (57,50 / 297,50 / 297,290 / 57,290) look wrong at first glance
against the `[bed_screws]` positions (30,30 / 270,30 / 270,270 / 30,270). They are not.
Each is the `bed_screws` position plus exactly the probe offset (+27, +20), which is
precisely what Klipper requires:

> *"The (X, Y) coordinate of the first bed leveling screw. This is a position to command the
> **nozzle** to so that the **probe** is directly above the bed screw."*
> ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#screws_tilt_adjust))

Confirmed in source: `screws_tilt_adjust.py` passes the coordinates straight to
`ProbePointsHelper` and **never calls `use_xy_offsets()`**, so no offset is applied and the
nozzle goes exactly where you tell it. This is the opposite convention from `[bed_mesh]`,
which does opt in — a genuinely easy trap, navigated correctly here.

The far corner commands the nozzle to X=297, Y=290, inside `position_max: 300`. ✅

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Add a one-line comment above `[screws_tilt_adjust]` recording
that the coordinates are `[bed_screws]` positions plus the probe offset, and that this is
required because `screws_tilt_adjust` does not apply probe offsets while `bed_mesh` does.
**Reasoning:** No value change — the config is correct. But the two Klipper sections use
opposite conventions ([`screws_tilt_adjust.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/screws_tilt_adjust.py)
never calls `use_xy_offsets`, [`bed_mesh.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bed_mesh.py)
does), and the numbers look like a mistake to anyone who has not just read both source files.
This is exactly the kind of correct-but-surprising config that gets "corrected" into being
wrong during a future cleanup.

</div>

### `[safe_z_home]` and the disabled `[z_tilt]`

`home_xy_position: 30,30`, `z_hop: 5`, `z_hop_speed: 4`, `speed: 100`. Harmless. With a
physical Z endstop at a fixed frame position, the XY location does not actually affect where
Z triggers, so `safe_z_home` here is mostly providing the pre-homing Z hop — which is still
worth having.

`[z_tilt]` is commented out with the note *"causing gantry issues"*. **Leave it that way.**
As established in the `hardware.cfg` section, the two Z steppers have independent endstops,
so `G28` already levels the gantry mechanically; `z_tilt` would fight that. The existing
comment does not explain *why*, which is how it ends up being re-enabled later.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Replace the `[z_tilt]` comment *"DISABLED (causing gantry
issues)"* with the actual reason: independent per-stepper Z endstops (`stepper_z` on PG8,
`stepper_z1` on PG5) already level the gantry during homing, so `z_tilt` is redundant and
conflicts with it.
**Reasoning:** Documented Klipper behaviour — *"If an endstop_pin is defined for the
additional stepper then the stepper will home until the endstop is triggered"*
([Config_Reference](https://www.klipper3d.org/Config_Reference.html#stepper_z1)). Recording
the mechanism rather than the symptom prevents someone re-enabling `z_tilt` in six months and
rediscovering the gantry issues the hard way.

</div>

---


## Klipper Firmware Config Review — `advanced.cfg`

| Section | Setting | Assessment |
|---|---|---|
| `[exclude_object]` | — | ✅ Present and required. See the `gcode_label_objects` finding in the slicer section — it is currently being fed the weaker of the two available input formats. |
| `[gcode_arcs]` | `resolution: 0.1` | Klipper's default is **1.0**. See below. |
| `[skew_correction]` | — | Inert until `SET_SKEW` is issued; no profile is currently applied. Correct as a placeholder for the backlog item. ✅ |

### `[gcode_arcs] resolution: 0.1` works against the slicer's arc fitting

Klipper's documentation for this option:

> *"An arc will be split into segments. Each segment's length will equal the resolution
> in mm set above. Lower values will produce a finer arc, but also more work for your
> machine. Arcs smaller than the configured value will become straight lines. The
> default is 1mm."* ([Config_Reference](https://www.klipper3d.org/Config_Reference.html#gcode_arcs))

The print profile sets `arc_fitting = emit_center`, so PrusaSlicer is actively
converting polyline runs into `G2`/`G3` commands. The entire point of that conversion is
to send *fewer* commands. Klipper then re-expands every arc at 0.1 mm per segment, which
at the configured `travel_speed = 250` mm/s is 2500 segments per second, and at
`perimeter_speed = 80` mm/s is 800 per second.

Meanwhile the slicer's own `gcode_resolution = 0.0125` already bounds the geometric
error of the path it emits. Re-expanding at 0.1 mm adds no fidelity the source geometry
contains — it just reconstitutes (and likely exceeds) the segment count that arc fitting
was meant to remove, on both the Pi and the MCU.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `[gcode_arcs] resolution` — current `0.1` → suggested `1.0`
(Klipper's default), or `0.5` if you want to be conservative.
**Reasoning:** 0.1 mm segments produce *"more work for your machine"*
([Config_Reference](https://www.klipper3d.org/Config_Reference.html#gcode_arcs)) for no
visible gain, and it partly cancels the benefit of the slicer's `arc_fitting = emit_center`.
A 0.1 mm chord on a curve large enough to have been arc-fitted is far below what a 0.4 mm
nozzle can resolve. This is also worth doing before raising `max_accel`, since higher speeds
multiply the segment rate. **Low risk**, easily reverted if curves visibly facet.

</div>

---

## Klipper Firmware Config Review — `system.cfg`

| Section | Setting | Assessment |
|---|---|---|
| `[force_move]` | `enable_force_move: False` | ✅ Correct and safe default. Worth knowing that with independently-endstopped Z steppers there is no scenario here where `FORCE_MOVE` would be the right gantry fix anyway. |
| `[virtual_sdcard]` | `path: /home/pi/printer_data/gcodes` | Duplicate of `mainsail.cfg` — see the `printer.cfg` section. |
| `[pause_resume]`, `[display_status]`, `[respond]` | — | Duplicates of `mainsail.cfg`, harmless. |
| `[neopixel top_lights]` | `pin: PD5`, `chain_count: 60` | No pin conflict (PD5 is used nowhere else in the live config). Note 60 WS2812s at full white would draw roughly 3.6 A on the 5 V rail; the effects actually configured in `neopixel1.cfg` are dim (peak around `(1,0,0)` on a breathing layer), so real draw is a fraction of that. Only relevant if the strip is ever driven bright from board power. |
| `[idle_timeout]` | `timeout: 1800` + custom gcode | See below. |

### `[idle_timeout]` disables X, Y and E while paused

The macro is thoughtful in one respect — it deliberately avoids `TURN_OFF_HEATERS` when
the printer is paused, so a paused print does not go cold. But both branches run
`M84 X Y E`:

```
{% if printer.pause_resume.is_paused %}
    M84 X Y E  ; Disable XYE only when paused, keep Z enabled
{% else %}
    TURN_OFF_HEATERS
    M84 X Y E  ; Disable XYE, keep Z motors enabled to prevent creep
{% endif %}
```

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** A pause that lasts longer than 30 minutes will disable
**every stepper, including Z**, **clear the homed state, and make the print unresumable** —
and the macro's own heater-preservation logic means the printer will sit there hot, looking
resumable, while this has already happened.
**Reasoning:** **Klipper's `M84` ignores its axis arguments entirely** — `stepper_enable.py`
registers `M18` and `M84` to the same `cmd_M18`, which calls `motor_off()`, disabling every
stepper and then calling `clear_homing_state("xyz")`
([stepper_enable.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/stepper_enable.py)).
So `M84 X Y E` is not selective, the `; keep Z enabled` comments on both branches are wrong,
and the homed state is wiped outright rather than merely risked. A
subsequent `RESUME` then has no valid position to return to. The upstream Mainsail `PAUSE`
macro solves exactly this by extending the idle timeout for the duration of the pause
(`SET_IDLE_TIMEOUT TIMEOUT={client.idle_timeout}` in `mainsail.cfg`), and restoring it on
resume or cancel. **That protection is currently inactive on this printer**, because
`macro.cfg` redefines `[gcode_macro PAUSE]` and its version does not carry the
`SET_IDLE_TIMEOUT` logic — see the `macro.cfg` section. Two independent fixes, either of
which closes it: (a) drop the `macro.cfg` overrides and let `mainsail.cfg` own PAUSE/RESUME,
or (b) change the paused branch here to disable nothing. If you want selective shutdown on the
non-paused branch, it has to be `SET_STEPPER_ENABLE STEPPER=<name> ENABLE=0` per stepper —
that call does **not** clear homing state, unlike `M84`.

</div>

---


## Klipper Firmware Config Review — `macro.cfg`

### The PAUSE / RESUME / CANCEL_PRINT overrides

`macro.cfg` redefines all three macros that `mainsail.cfg` already provides. Because
`macro.cfg` is included later, its `gcode:` bodies win — but the upstream versions'
`variable_*` lines survive as orphans, and every behaviour the upstream macros provided
through their bodies is silently lost.

What the overrides give up, concretely:

| Upstream behaviour (in `mainsail.cfg`) | Still active? |
|---|---|
| `SET_IDLE_TIMEOUT` extended during pause, restored on resume/cancel | **No** — this is the unresumable-pause bug above |
| Nozzle temperature saved on pause and restored on resume (`last_extruder_temp`) | **No** |
| `_CLIENT_VARIABLE`-driven park position, retract lengths, speeds | **No** |
| Park height clamped against `axis_maximum.z` | **No** — see the END_PRINT finding below |
| `SET_PAUSE_NEXT_LAYER ENABLE=0` / `SET_PAUSE_AT_LAYER ENABLE=0` reset on cancel | **No** — a "pause at layer N" stays armed after a cancel |
| Runout-sensor and can-extrude guards before resuming | Partially |

The `macro.cfg` versions are not bad macros in isolation. The problem is that they are
competing with a maintained upstream file that is also loaded, so the effective behaviour
is a merge that matches neither file as written.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Delete `[gcode_macro PAUSE]`, `[gcode_macro RESUME]` and
`[gcode_macro CANCEL_PRINT]` from `macro.cfg`, and add a `[gcode_macro _CLIENT_VARIABLE]`
section to configure the upstream Mainsail macros instead (park position, `idle_timeout`,
retract lengths, `use_fw_retract`).
**Reasoning:** `mainsail.cfg` is the upstream
[mainsail-config](https://github.com/mainsail-crew/mainsail-config) client macro set and is
designed to be configured through `_CLIENT_VARIABLE` rather than replaced. Overriding it
costs the idle-timeout protection, temperature restore, park clamping and pause-at-layer
reset listed above, and Klipper merges the two definitions per-option with no warning
([configfile.py](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py)),
so reading either file alone misrepresents what actually runs. **The LED status calls are
the one thing worth preserving** — `_CLIENT_VARIABLE` supports `user_pause_macro`,
`user_resume_macro` and `user_cancel_macro` hooks for exactly that. This is the largest
single change suggested in this document; it is worth doing carefully and testing a pause
and resume on a throwaway print before trusting it.

</div>

### `END_PRINT` — the Z lift is unclamped

```
G91
G1 E-3 F300
G1 Z15 F3000     <-- relative, unclamped
G90
G1 X150 Y150 F6000
M84
```

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `END_PRINT` lifts Z by 15 mm in relative mode with no clamp
against `position_max: 400`. **Any print finishing above Z=385 will end with a "Move out of
range" error instead of a clean finish**, and because `CANCEL_PRINT` calls `END_PRINT`, the
same failure hits any cancel of a tall print.
**Reasoning:** The upstream Mainsail helper handles exactly this case by clamping —
`_TOOLHEAD_PARK_PAUSE_CANCEL` in `mainsail.cfg` computes
`z_park = [[(act.z + park_dz), z_min]|max, (max.z - origin.z)]|min`. The suggested fix is
the same pattern:
`{% set z_safe = [printer.toolhead.position.z + 15, printer.toolhead.axis_maximum.z]|min %}`
followed by an absolute `G1 Z{z_safe}`. Note this is a real 400 mm Z machine, so the
affected range is not hypothetical.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `END_PRINT` — if you want Z to stay energised, replace the
bare `M84` with per-stepper `SET_STEPPER_ENABLE STEPPER=stepper_x ENABLE=0` (and `stepper_y`,
`extruder`). **`M84 X Y E` would not work.**
**Reasoning:** **Klipper's `M84` and `M18` ignore axis arguments entirely.**
`stepper_enable.py` registers both to `cmd_M18`, which calls `motor_off()`, which disables
every stepper and then calls `clear_homing_state("xyz")`
([stepper_enable.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/stepper_enable.py)).
So the existing `M84 X Y E` lines in `system.cfg` and the bare `M84` here behave identically —
both drop Z as well, and **the "keep Z motors enabled to prevent creep" comment has never been
true.** Only `SET_STEPPER_ENABLE` acts on an individual stepper, and it does not clear homing
state. This also makes the `[idle_timeout]` pause bug strictly worse than described above: the
paused branch was not merely disabling X and Y, it was wiping the homed state outright.

</div>

### `START_PRINT`

The macro is broadly well-built. Confirmed-good points worth recording so they are not
disturbed: `SET_GCODE_OFFSET Z=0` and `BED_MESH_CLEAR` at the top prevent a stale offset or
mesh carrying into a new print; bed heating is started before `G28` so homing overlaps with
heat-up; and the purge line's peak extrusion cross-section is 0.20 mm², comfortably inside
the 0.64 mm² default `max_extrude_cross_section`, so it will not trip Klipper's extrusion
guard. The earlier `G0 X2 Y2` → `X10 Y10` collision fix is present.

Two smaller observations:

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `START_PRINT` — add an explicit `G90` (and `M83`) before the
purge-line block, and `M107` near the top.
**Reasoning:** The macro relies on the gcode state being absolute when it runs. That is
normally true, but the `macro.cfg` `PAUSE` macro can exit leaving `G91` set when the printer
is not homed, and `START_PRINT` does not reset it before `G1 Z5 F3000`. An explicit `G90`
costs nothing and removes the dependency on prior state. `M107` ensures the part fan is off
during the purge regardless of how the previous print ended.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `START_PRINT` — move `M109 S{EXTRUDER}` to just before the
purge line rather than before the `_LED_STATUS STATE=PRINTING` call, and consider a modest
`M104 S{EXTRUDER-40}` pre-heat earlier.
**Reasoning:** As written, the nozzle reaches full print temperature and then sits at Z5
over the bed until the purge line starts, oozing. Bringing the nozzle to temperature as late
as possible reduces the ooze that the purge line then has to clear. Minor, quality-of-life
only.

</div>

### Beeper and `M300`

`[output_pin beeper] pin: PG4` with `pwm: True`, `cycle_time: 0.0024`, `shutdown_value: 0`.
PG4 is `EXP1_1` in the `[board_pins]` aliases, which is the standard mini12864 beeper pin —
correct, and no conflict. The only nit is that `macro.cfg` uses the raw `PG4` where an alias
`EXP1_1` already exists; using the alias would make the display dependency obvious. Cosmetic.

---

## Klipper Firmware Config Review — `calibration.cfg`, `menu.cfg`, `neopixel1.cfg`, `mainsail-mobile.cfg`

These four are in good shape and I found nothing worth changing. Recording the checks so
the audit is complete:

- **`calibration.cfg`** — every wrapper guards on `printer.toolhead.homed_axes != "xyz"` and
  raises rather than silently homing. Deliberately does not auto-home, heat, save or restart.
  This is genuinely good macro hygiene. ✅
- **`mainsail-mobile.cfg`** — same guards, same discipline, no overlap with `calibration.cfg`
  macro names. ✅
- **`menu.cfg`** — the `[display]` pins all resolve through `[board_pins]` to the standard
  SKR Pro EXP1/EXP2 mapping, with no conflicts. ✅
- **`neopixel1.cfg` / `menu.cfg` LED effects** — the two NeoPixel chains (`top_lights`, 60
  LEDs on PD5; `fysetc_mini12864`, 3 LEDs on EXP1_6) are addressed by distinct effect names,
  and the header comment correctly explains why that matters given Klipper's linear include
  parsing. `_LED_STATUS` raises on an unknown state rather than failing silently. ✅
- **`timelapse.cfg`** — stock `moonraker-timelapse`, matched by the `[timelapse]` section in
  `moonraker.conf`. No section collisions with the rest of the config. ✅

One cross-cutting note, since `calibration.cfg` is the user-facing calibration surface:

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `calibration.cfg` — add a `CAL_Z_ENDSTOP` wrapper around
`Z_ENDSTOP_CALIBRATE`, alongside the existing `CAL_Z_OFFSET`.
**Reasoning:** As established in the `hardware.cfg` section, `PROBE_CALIBRATE` (which
`CAL_Z_OFFSET` wraps) tunes the probe's `z_offset`, which on this machine does **not** set
first-layer height — `Z_ENDSTOP_CALIBRATE` does, because Z homes to a physical switch
([G-Codes.md](https://www.klipper3d.org/G-Codes.html),
[manual_probe.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/manual_probe.py)).
Right now the menu offers only the one that cannot fix the thing people actually want to
fix, which is very likely how the wrong parameter ended up at the top of the `HANDOFF.md`
task list. Same guard pattern as the existing wrappers. Note `CAL_SAVE` will still fail on
the include conflict — persist the result by hand-editing `hardware.cfg` instead, per the
correction in the `printer.cfg` section above.

</div>

---


## The Extruder TMC2209 UART Problem — Revisited

`HANDOFF.md` currently records this conclusion:

> *"**Do not retry without physically verifying UART wiring/continuity on the extruder
> driver socket first** — PD4 may not be reliably wired for UART on this board despite
> matching the generic template."*

That conclusion is wrong on its central point, and the note should be corrected.

### PD4 was the correct pin

Two independent primary sources agree:

1. Klipper's official board config lists `uart_pin: PD4` for the E0 socket
   ([generic-bigtreetech-skr-pro.cfg](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg)).
   The pin assignments in that file have not changed since it was added in 2019.
2. BigTreeTech's own
   [SKR-PRO-V1.2 schematic](https://github.com/bigtreetech/BIGTREETECH-SKR-PRO-V1.1/blob/master/SKR-PRO-V1.2/Schematic/SKR-PRO-V1.2.PDF)
   labels the STM32F407 net on PD4 as **`E0_UART`**.

And the extruder is unambiguously in the E0 socket: `step_pin: PE14`, `dir_pin: PA0`,
`enable_pin: PC3` and `heater_pin: PB1` (Heat0) are an exact four-way match for E0 in both
sources. PD4 is also used nowhere else in the live config.

So the `IFCNT` failure was **not** a pin error, and "verify the wiring is present" is not the
right next step. Something about that specific driver module's configuration is preventing it
answering on address 0.

### Why the failure looked intermittent

Worth understanding, because it shapes how to test safely. From
[tmc.py](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc.py):

- `_handle_connect()` wraps `_init_registers()` in a `try` and on failure only does
  `logging.info("TMC %s failed to init: %s", ...)`. **A completely dead UART link does not
  stop Klipper from starting**, which is why nothing failed at boot.
- `_handle_stepper_enable()` → `_do_enable()` → `_init_registers()`; any `command_error`
  there calls `self.printer.invoke_shutdown()`.
- `TMCErrorCheck._do_periodic_check()` re-reads `DRV_STATUS`/`GSTAT` **once per second while
  the motor is enabled**, and calls `invoke_shutdown()` on failure.

So "intermittent hard shutdowns" really means "a shutdown every time the extruder motor gets
enabled". That is the signature of a link that is **absent**, not one that is marginal.

### The most likely cause, and it is testable in software

Klipper's own FAQ lists the causes:

> *"Make sure that the motor power is enabled... If this error occurs after flashing Klipper
> for the first time, then the stepper driver may have been previously programmed in a state
> that is not compatible with Klipper... Otherwise, this error is typically the result of
> incorrect UART pin wiring or an incorrect Klipper configuration of the UART pin settings."*
> ([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html))

The last clause is the relevant one, and there is a specific mechanism that fits every
observed fact.

On a TMC2209, **MS1 and MS2 are reused in UART mode as the node address** — MS1 is bit 0,
MS2 is bit 1 ([Watterott SilentStepStick TMC2209 pin config](https://learn.watterott.com/silentstepstick/pinconfig/tmc2209/),
[TMC2209 datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf)).
In standalone mode those same pins select microstepping, and the standalone table is:

| MS2 | MS1 | Microsteps |
|---|---|---|
| low | low | 1/8 |
| low | high | 1/32 |
| high | low | 1/64 |
| **high** | **high** | **1/16** |

Klipper's `uart_address` defaults to 0, and a driver strapped for address 3 will never answer.

**Here is the evidence that the E0 driver is strapped for 1/16, and therefore address 3.**
The extruder has just been carefully recalibrated to `rotation_distance: 26.5475`, which is
within 0.8 % of the untouched theoretical BMG value of 26.76116. Klipper's config says
`microsteps: 16`. If the driver were actually running at the no-jumper default of 1/8, every
commanded pulse would advance twice as far, and the calibration would have landed near 53.5,
not 26.5. At 1/32 it would have landed near 13.4. It landed on the value that only works if
**the driver is genuinely at 1/16** — which, in standalone mode, requires both MS jumpers
fitted high, which is address 3.

This also explains the otherwise odd fact recorded in `HANDOFF.md` that the extruder has
*never* had a `[tmc2209]` section in any config snapshot going back to the original
monolithic `printer.cfg`: whoever built the machine set that socket up standalone, with
jumpers, and set its current on the module's Vref potentiometer.

I want to be clear about the epistemic status: the pin identification is **confirmed** from
two primary sources; the address-3 explanation is a **hypothesis**, but one that is consistent
with every observed fact and costs nothing to test.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Retry the extruder TMC section **with `uart_address: 3`** —
no hardware disassembly required for the first test.

```
[tmc2209 extruder]
uart_pin: PD4
uart_address: 3        # hypothesis: MS1+MS2 strapped high for standalone 1/16
run_current: 0.6       # start low; the Vref pot currently sets this
sense_resistor: 0.110
stealthchop_threshold: 0
interpolate: True
# do NOT set tx_pin — the SKR Pro UART is single-wire
```

**Reasoning:** `uart_address` is *"an integer between 0 and 3... typically used when multiple
TMC2209 chips are connected to the same UART pin"*
([Config_Reference](https://www.klipper3d.org/Config_Reference.html#tmc2209)), but on a
TMC2209 the address is set by the MS1/MS2 strapping regardless of how many chips share a pin.
The calibrated `rotation_distance` proves the driver is at 1/16, which in standalone mode is
the MS1-high/MS2-high strap, which is address 3.
**Test safely and non-destructively:** add the section, `FIRMWARE_RESTART`, then run
**`DUMP_TMC STEPPER=extruder` before moving the extruder motor**. That reads registers over
UART without going through the motor-enable path that triggers `invoke_shutdown`. If it
returns register values, the link is alive. If address 3 fails, sweep `uart_address` 1 and 2
the same way — it is four cheap tests.
**Important follow-up if it works:** once UART is established Klipper takes over both the
microstep setting (writing `MRES` from `microsteps: 16`) and the run current, so the Vref pot
stops being the limit. Microstepping will be unchanged at 1/16, so `rotation_distance: 26.5475`
remains valid — but re-verify with a single 50 mm extrude before printing, and raise
`run_current` from 0.6 only if you see skipped steps.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** If the `uart_address` sweep fails, the next step is the UART
enable jumper under the E0 socket, **not** wiring continuity.
**Reasoning:** BigTreeTech documents a per-socket UART jumper: *"When using UART mode, you
need to short the needle in the red box with a jumper cap... the 4th Pin pin from the top to
the bottom"* ([BTT SKR PRO V1.2 docs](https://global.bttwiki.com/SKR%20PRO%20V1.2.html)). The
schematic shows six matching 2-pin headers carrying `X_PDN` through `E2_PDN`. With that jumper
absent the driver is in standalone mode and PD4 is not connected to anything, which produces
this exact fault. **Concrete procedure**, printer fully powered down including USB (USB
back-powers the MCU): pull the E0 module, photograph the jumper field under E0 and under the
working X socket, and compare. Also confirm the module's own UART select resistor is in the
factory position — BTT: *"The factory has connected the UART Pin to the fourth Pin, namely the
PDN_UART Pin"* ([BTT TMC2209 page](https://global.bttwiki.com/TMC2209.html)). While the module
is out, check its chip marking is actually a TMC2209 and not a TMC2208 (which would need a
`[tmc2208 extruder]` section instead), and check whether its DIAG pin is cut — see the DIAG
finding in the `hardware.cfg` section, which concerns this same module.
**If it still fails after that**, swap the E0 module with the one from the Z socket, which is
proven to talk over UART. If the fault follows the module it is a dead driver, which is the
documented outcome in both resolved SKR Pro cases I found
([klipper.discourse.group/t/skr-pro-tmc-2209-uart/3605](https://klipper.discourse.group/t/skr-pro-tmc-2209-uart/3605),
[.../18328](https://klipper.discourse.group/t/so-i-had-a-unable-to-read-tmc-uart-extruder-register-ifcnt/18328)).

</div>

### There is no way to set TMC2209 current without UART

Confirmed, in case it saves a future search. `run_current` is a required parameter of
`[tmc2209]` and is applied by writing the `IHOLD_IRUN` register over the UART link; there is no
non-UART path. Klipper is explicit:

> *"Klipper can also use Trinamic drivers in their 'standalone mode'. However, when the drivers
> are in this mode, no special Klipper configuration is needed and the advanced Klipper features
> discussed in this document are not available."*
> ([TMC_Drivers.md](https://www.klipper3d.org/TMC_Drivers.html))

So the current state — no `[tmc2209 extruder]` section, current set by the module's Vref
potentiometer — is a **legitimate and working configuration**, not a broken one. What it costs
is `run_current` control, `stealthchop_threshold`, `DUMP_TMC`, and driver
temperature/error monitoring on that one axis. Given the extruder was recently slipping, being
able to set and read its current is genuinely useful, which is why this is worth one more
attempt. But it is an improvement, not a repair, and if all the tests above fail the honest
answer is to leave it standalone and adjust the Vref pot by hand.

---


## Astra Second Opinion — PrusaSlicer Side

The original review above was reasoned rather than sourced. Checking it against
PrusaSlicer's actual source at tag `version_2.9.6` turns up **four settings that the
original review passed as correct or optional but which are genuinely wrong for this
machine**, and confirms the rest. Inline disagreement blocks have been added next to the
relevant Action Items above; this section gives the full argument and evidence.

### 1. `autoemit_temperature_commands = 1` is definitively wrong here

Action Item #2 above called this "verify, probably fine". It is not fine, and the
verification can be done from source rather than by slicing a test object.

The detector, `custom_gcode_sets_temperature()` in `src/libslic3r/GCode.cpp`, is a **literal
M-code line scan**, not placeholder detection. It requires the first non-whitespace
character of a line to be `M` (or `G`, for `G10`, on RepRapFirmware only) followed by
104/109, 140/190 or 141/191. The option's own tooltip says so:

> *"PrusaSlicer will check whether your custom Start G-Code contains G-codes to set extruder,
> bed or chamber temperature (**M104, M109, M140, M190, M141 and M191**)."*

The custom start G-code here expands to `START_PRINT EXTRUDER=205 BED=55`. The first
character is `S`. The detector returns false, so PrusaSlicer emits its own commands in this
order:

1. `M140 S55` then `M190 S55` — bed, **waits for temperature**
2. `M104 S205` — nozzle, no wait
3. `START_PRINT EXTRUDER=205 BED=55`
4. `M109 S205` — nozzle, **waits for temperature**

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `autoemit_temperature_commands` — current `1` → **`0`**.
**Reasoning:** This is not a cosmetic duplication. The injected `M190` **waits for the bed
before `START_PRINT` ever runs**, which defeats the entire design of the macro — the whole
point of `M140` before `G28` and `M190` after `BED_MESH_PROFILE LOAD` is to overlap heating
with homing and mesh load. The printer instead soaks first and homes afterwards, and then
sets both temperatures a second time inside the macro. Prusa's developers treat this as
working as designed and the fix as setting the flag to 0 — from
[PrusaSlicer#11597](https://github.com/prusa3d/PrusaSlicer/issues/11597), where the reporter's
start G-code had exactly this shape: *"I believe that all you need to do is to disable the
checkbox 'Emit temperature command automatically' (which was added specifically for this use
case)"*, and the issue was closed with *"Disabled with configuration update 1.0.4."* Prusa's
own shipped Voron profile now sets `autoemit_temperature_commands = 0` alongside
`gcode_flavor = klipper`. **This is the single highest-value slicer-side change in this
document** — it costs one line and restores the heating strategy the macro was written for.

</div>

### 2. `use_firmware_retraction = 1` together with `wipe = 1` is an invalid combination

The original review praised both settings independently. PrusaSlicer explicitly forbids
having both. `src/libslic3r/PrintConfig.cpp` contains a hard validator:

```cpp
if (cfg.use_firmware_retraction.value)
    for (unsigned char wipe : cfg.wipe.values)
         if (wipe)
            return "--use-firmware-retraction is not compatible with --wipe";
```

and the GUI shows *"The Wipe option is not available when using the Firmware Retraction
mode."* The reason this profile can hold both is a known open bug,
[PrusaSlicer#7449](https://github.com/prusa3d/PrusaSlicer/issues/7449): the dialog only fires
when the Printer Settings → Extruder page is open, and GUI slicing does not re-run the
validator.

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN:** `wipe` — current `1` → suggested `0` (keeping
`use_firmware_retraction = 1`); **or** set `use_firmware_retraction = 0` and keep `wipe = 1`.
Either is fine. Having both is not.
**Reasoning:** PrusaSlicer's own validator rejects the pair
(`PrintConfig.cpp`, quoted above), and the CLI and config export both hard-error on it. When
it slips past the GUI, `GCodeGenerator::retract_and_wipe()` emits real negative-E wipe moves
*and* a `G10`, with the two drawing from the same internal retraction budget. At this
profile's `retract_length = 0.6` the likely outcome is that the `G10` consumes the budget and
the wipe degenerates to nothing, rather than active under-extrusion — but that is an accident
of internal bookkeeping, not designed behaviour, and it is not something to rely on.
**Which to drop:** Prusa's own Klipper profiles (Voron 1.0.4, RatRig 1.1.1) all ship
`use_firmware_retraction = 0`, and firmware retraction additionally breaks print-time
estimates ([#987](https://github.com/prusa3d/PrusaSlicer/issues/987),
[#13189](https://github.com/prusa3d/PrusaSlicer/issues/13189)) and the retraction preview,
and prevents per-filament retraction tuning since PrusaSlicer never emits `SET_RETRACTION`.
**My recommendation is `use_firmware_retraction = 0`, `wipe = 1`** — the slicer-side retract
values are already synced to `tuning.cfg`, so behaviour is unchanged, and you gain wipe,
accurate estimates and a correct preview. Klipper's `[firmware_retraction]` section stays
useful for manual `G10`/`G11` and the Mainsail client macros regardless.
**Related gotcha if you go the other way:** keep `retract_length` non-zero. `GCode.cpp` gates
all Z-hop on `retract_length != 0`, *even under firmware retraction*, so setting it to 0
"because the firmware decides" silently disables `retract_lift` entirely.

</div>

### 3. `gcode_label_objects = octoprint` is the weaker of the two options for Klipper

The original review marked this "✅ Correct flavor for Klipper's `EXCLUDE_OBJECT` support via
Moonraker's octoprint-compat layer". It does work today, but only because
`moonraker.conf` has `enable_object_processing: True` — and it is not the native path.

In PrusaSlicer 2.9.x the enum has three values: `disabled`, `octoprint`, `firmware`.

| Value | What it emits |
|---|---|
| `octoprint` | `; printing object <name>` comments — Klipper ignores these entirely |
| `firmware` | Native `EXCLUDE_OBJECT_DEFINE` / `EXCLUDE_OBJECT_START` / `EXCLUDE_OBJECT_END` |

The setting was a bool until 2.6.2 and old `= 1` values auto-migrate to `octoprint`, so this
is very likely a migration artifact rather than a deliberate choice.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `gcode_label_objects` — current `octoprint` → suggested
`firmware`.
**Reasoning:** With `gcode_flavor = klipper`, `firmware` emits the `EXCLUDE_OBJECT_*` commands
that Klipper's [Exclude_Object.md](https://github.com/Klipper3d/klipper/blob/master/docs/Exclude_Object.md)
actually defines, including correct object polygons and centres, and it sanitises object names
against Klipper's illegal-character set. The `octoprint` comments require Moonraker to
re-process every uploaded file — *"Note that this process is file I/O intensive, it is not
recommended for usage on low resource SBCs"*
([Moonraker configuration docs](https://github.com/Arksine/moonraker/blob/master/docs/configuration.md)).
Prusa's own vendor profiles use `firmware`. **Follow-up:** once changed, you can set
`enable_object_processing: False` in `moonraker.conf` and get faster uploads. **Caveat:**
incompatible with single-extruder multi-material and wipe-into-object, neither of which applies
here.

</div>

### 4. `fill_density = 0%` is more harmful than "a conscious decision"

Action Item #3 above called this "either intentional or a leftover... worth a conscious
decision either way, not a bug." The source says it actively disables a protection the
original review credited elsewhere.

`PrintObject.cpp`, in `discover_horizontal_shells()`:

```cpp
if (region_config.fill_density.value == 0 || region_config.ensure_vertical_shell_thickness.value == EnsureVerticalShellThickness::Disabled) {
    // If user expects the object to be void (for example a hollow sloping vase),
    // don't continue the search.
    goto EXTERNAL;
}
```

So `fill_density == 0` short-circuits shell propagation **exactly as if
`ensure_vertical_shell_thickness` were disabled**. The original review separately praised
`ensure_vertical_shell_thickness = enabled` as *"Prevents gaps under sparse infill near
top/bottom transitions"* — with 0 % infill, it does not.

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** `fill_density` — current `0%` → suggested `10%` (or
`fill_pattern = lightning` at a low density if the goal is minimum material).
**Reasoning:** Prusa's own guidance is *"Most models can be printed with 10-15% infill. If
the top of the model closes gradually, it can be printed hollow (0% infill), though we
generally **do not recommend it**"* ([Infill](https://help.prusa3d.com/article/infill_42/)).
More concretely, `fill_density == 0` bypasses `ensure_vertical_shell_thickness` in
`PrintObject.cpp` (quoted above), so top surfaces must bridge open air and will sag on
anything that is not a gradually-closing shape. 0 % is only genuinely correct in spiral-vase
mode, which PrusaSlicer enforces separately. This matters more than it looks because this is
the **default** print profile — every new project starts here.

</div>

### 5. Corrections to two smaller claims in the original review

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Correction, no config change — the original review states that
`full_fan_speed_layer` is *"Currently a no-op given min=max=100%"*. **That is not correct.**
`CoolingBuffer.cpp` applies `full_fan_speed_layer` as a *multiplicative* ramp factor on the
already-computed fan speed, independent of whether `min_fan_speed == max_fan_speed`, so it
still works. What genuinely *does* collapse to a no-op at `min = max = 100` with
`fan_always_on = 1` is `overhang_fan_speed_0..3` **and also `bridge_fan_speed`** — the latter
because `bridge_fan_control = bridge_fan_speed > fan_speed_new` can never be true when the
base speed is already 100. The review identified the overhang values correctly but missed
`bridge_fan_speed`. Additionally, `overhang_fan_speed_*` requires `enable_dynamic_fan_speeds`
(currently `0`) to have any effect at all, independent of the min/max question.

</div>

<div style="color:#e67e22; border-left: 3px solid #e67e22; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SUGGESTED CHANGE:** Qualification of Action Item #1 (`enable_dynamic_overhang_speeds`).
The recommendation to enable it is reasonable, but two facts change how to do it, and one is
Klipper-specific.
**Reasoning:** (a) The four thresholds are **percentage overlap with the previous layer**, not
overhang angle — `overhang_speed_0` is 0 % overlap (full bridge) and `_3` is 75 % overlap, with
linear interpolation between. (b) The configured 15/15/20/25 are PrusaSlicer's hard-coded code
defaults, not a tuned curve; `_0` and `_1` being equal means there is no gradient at all
between a full bridge and 25 % overlap. Prusa's own MK4IS profile uses **15 / 25 / 30 / 80%**,
where the last value is a percentage of external perimeter speed. (c) There is an **open
Klipper-specific bug**: [PrusaSlicer#10064](https://github.com/prusa3d/PrusaSlicer/issues/10064),
*"Dynamic Overhang causing 'Invalid speed in G1 F0'"* — Klipper rejects `F0`. If you enable
this, use a monotonic curve like Prusa's rather than the defaults, and watch for that error.

</div>

### Confirmed as correct

`binary_gcode = 0` is right — neither Klipper's `virtual_sdcard.py` (`['gcode', 'g', 'gco']`)
nor Moonraker's file manager (`['.gcode', '.g', '.gco', '.ufp', '.nc']`) accepts `.bgcode` as
of today. `machine_limits_usage = time_estimate_only`, `use_relative_e_distances = 1`,
`use_volumetric_e = 0`, `pause_print_gcode = PAUSE`, the machine-limit values matching
`tuning.cfg`, and the acceleration profile were all checked and are correct as the original
review states.

---


## Astra Research Summary

Every suggested change in one place, safety-relevant first. The "File" column says where the
edit goes. Nothing in this list has been applied.

### Tier 1 — Safety, or will lose you a print

| # | Change | File | Note |
|---|---|---|---|
| 1 | `autoemit_temperature_commands` `1` → `0` | PrusaSlicer `printer/CoreXY.ini` | Slicer currently injects `M190` **before** `START_PRINT`, so the printer soaks before homing and the macro's staged heating never happens. One-line fix, biggest single win. |
| 2 | Persist `Z_OFFSET_APPLY_ENDSTOP` by hand-editing `position_endstop`, **not** via `SAVE_CONFIG` | `hardware.cfg` | `SAVE_CONFIG` hard-errors on the include conflict, and the option cannot be commented out because it is required. Procedure now documented in the file itself. |
| 3 | Comment out the four `shaper_*` lines before running `SHAPER_CALIBRATE` | `tuning.cfg` | Same include-conflict error; a completed resonance run is discarded at the save step. |
| 4 | Use `Z_ENDSTOP_CALIBRATE` / `Z_OFFSET_APPLY_ENDSTOP`, not `PROBE_CALIBRATE` | workflow | **Corrects outstanding task #1 in `HANDOFF.md`.** Z homes to a physical switch, so the BLTouch `z_offset` does not set first-layer height. |
| 5 | Stop disabling X/Y in the paused branch of `[idle_timeout]` | `system.cfg` | A pause longer than 30 min clears the homed state and makes the print unresumable, while the macro keeps the heaters on so it still looks resumable. |
| 6 | Clamp the `END_PRINT` Z lift against `axis_maximum.z` | `macro.cfg` | Any print finishing above Z=385 errors out instead of ending cleanly. Also affects `CANCEL_PRINT`. |
| 7 | **Inspect** whether the E0 and E1 driver modules have their DIAG pins cut | hardware | X and Y endstops share MCU pins `PE15`/`PE10` with those sockets' DIAG lines. BTT: *"the stallguard pin of the TMC2209 needs to be cut off so that the mechanical switch can work normally."* |
| 8 | `heater_bed min_temp` `-50` → `0` | `thermistors.cfg` | −50 °C effectively disables the bed's disconnected-thermistor shutdown. |
| 9 | Resolve `use_firmware_retraction = 1` + `wipe = 1` | PrusaSlicer `printer/CoreXY.ini` | Invalid per PrusaSlicer's own validator. Recommend `use_firmware_retraction = 0`, keep `wipe = 1`. |

### Tier 2 — Wrong parameter or wrong value

| # | Change | File | Note |
|---|---|---|---|
| 10 | `fill_density` `0%` → `10%` | PrusaSlicer `print/…0.2.ini` | 0 % bypasses `ensure_vertical_shell_thickness`; tops sag. This is the default profile. |
| 11 | `gcode_label_objects` `octoprint` → `firmware` | PrusaSlicer `printer/CoreXY.ini` | Native `EXCLUDE_OBJECT_*` instead of comments needing Moonraker re-processing. Then set `enable_object_processing: False`. |
| 12 | `[bltouch] pin_move_time` `0.4` → `0.680` | `probe.cfg` | Below Klipper's default; best candidate for the probe flakiness that `samples_tolerance_retries: 6` is masking. |
| 13 | `[tmc2209 stepper_z]`/`[stepper_z1] stealthchop_threshold` `1000` → `0` | `hardware.cfg` | stealthChop negates the `interpolate: False` + 128-microstep accuracy choice, and a mid-range threshold causes mode switching mid-move. |
| 14 | `rotation_distance` X/Y `39.77` → `40`, Z `4.018` → `4` | `hardware.cfg` | Belt and lead-screw values are geometric, not measured. Fix dimensional error with `xy_size_compensation` instead. Re-check a cube afterwards. |
| 15 | Retry `[tmc2209 extruder]` with `uart_pin: PD4` **and `uart_address: 3`** | `hardware.cfg` | `PD4` was always correct. Test with `DUMP_TMC STEPPER=extruder` before moving the motor. |
| 16 | `[gcode_arcs] resolution` `0.1` → `1.0` | `advanced.cfg` | Re-expanding arcs at 0.1 mm cancels the benefit of the slicer's `arc_fitting`. |
| 17 | `[bed_mesh] fade_end` `5.0` → `10.0`, add `fade_target: 0` | `probe.cfg` | Klipper's documented recommendation. Low impact given how flat this bed is. |
| 18 | Remove the `PAUSE` / `RESUME` / `CANCEL_PRINT` overrides | `macro.cfg` | Restores idle-timeout protection, temperature restore, park clamping and pause-at-layer reset. Largest change here — test a pause/resume afterwards. |

### Tier 3 — Performance and headroom

| # | Change | File | Note |
|---|---|---|---|
| 19 | `[printer] max_accel` `3000` → `4000`, ceiling ~6000 | `tuning.cfg` | Klipper's own formula gives 6300 for the 46.2 Hz Y axis and 12 400 for X. Step up with a ringing test; do **not** jump to 6300. |
| 20 | Keep `square_corner_velocity` at `5.0` | `tuning.cfg` | Explicitly flagged so a future session does not raise it alongside `max_accel`. |
| 21 | `[bltouch] stow_on_each_sample` `true` → `false` + `probe_with_touch_mode: true` | `probe.cfg` | Directly addresses the slow-mesh `BlockingIOError`. **Verify pin clearance first** — this is the one suggestion with a real crash risk if clearance is wrong. |
| 22 | Adaptive bed mesh (`BED_MESH_CALIBRATE ADAPTIVE=1`, `adaptive_margin: 5`) | `probe.cfg`, `macro.cfg` | Bed variance is 0.104 mm against a 0.2 mm layer, well inside the documented criterion. Backlog item 4. |
| 23 | `[bltouch] samples_tolerance_retries` `6` → `3`, tolerance set from `PROBE_ACCURACY` | `probe.cfg` | Turns a workaround into a real quality gate. |
| 24 | `[controller_fan] max_power` `0.6` → `1.0`, or lower `run_current` from `1.1` | `fans.cfg` / `hardware.cfg` | Decide from `DUMP_TMC` `otpw` after a long print rather than guessing. |

### Tier 4 — Hygiene, correctness of intent, documentation

| # | Change | File |
|---|---|---|
| 25 | Remove duplicate `[virtual_sdcard]`, `[pause_resume]`, `[display_status]`, `[respond]` | `system.cfg` |
| 26 | Fix five stale comments (three PA values, two wrong thermistor pin labels) | `printer.cfg`, `tuning.cfg`, `thermistors.cfg` |
| 27 | Un-cross the Z / E1 `dir`, `enable` and `uart` pins | `hardware.cfg` |
| 28 | `position_endstop` `300` → `299.5` on X and Y for margin | `hardware.cfg` |
| 29 | Comment why `[screws_tilt_adjust]` coordinates include the probe offset | `probe.cfg` |
| 30 | Replace the `[z_tilt]` "causing gantry issues" comment with the real reason | `probe.cfg` |
| 31 | Add a `CAL_Z_ENDSTOP` wrapper for `Z_ENDSTOP_CALIBRATE` | `calibration.cfg` |
| 32 | `END_PRINT` `M84` → per-stepper `SET_STEPPER_ENABLE` (only if Z should stay held; `M84 X Y E` is a no-op) | `macro.cfg` |
| 33 | `START_PRINT`: add explicit `G90`/`M83` and `M107`; move `M109` later | `macro.cfg` |
| 34 | Comment why `max_extrude_only_distance` is raised to 200 | `thermistors.cfg` |
| 35 | If enabling dynamic overhang speeds, use Prusa's 15/25/30/80% curve, not 15/15/20/25 | PrusaSlicer `print/…0.2.ini` |

### Suggested order of operations

1. **Slicer first** — items 1, 9, 10, 11. Four one-line edits, no printer downtime, and item 1
   changes how every subsequent test print heats.
2. **Then the Z datum** — items 2 and 4, then re-establish first-layer height with
   `Z_ENDSTOP_CALIBRATE`. This unblocks `HANDOFF.md` tasks 1 and 2.
3. **Then the safety items that need no calibration** — 5, 6, 8.
4. **Then the hardware inspection pass** — items 7 and 15 together, since both need the driver
   modules out.
5. **Then tuning** — 12, 13, 19, 21, and only then real pressure-advance calibration
   (`HANDOFF.md` task 3), so PA is tuned against the final accel and retraction behaviour.
6. **Hygiene last**, as a single cleanup commit.

### Checked and found clean

Recording the negatives so they are not re-audited: no pin is used twice anywhere in the 14
live includes (verified by resolving all `[board_pins]` aliases and scanning every `*_pin`
key); no deprecated or removed Klipper options are in use, in particular
`relative_reference_index` is correctly absent and `zero_reference_position` is used instead;
`[verify_heater]` is automatically active for both heaters and needs no config;
`max_extrude_cross_section` defaults comfortably above the purge line's 0.20 mm²;
`[screws_tilt_adjust]` correctly pre-applies the probe offset while `[bed_mesh]` correctly
does not; `mesh_max: 270,270` keeps the nozzle inside `position_max`; disabling `[z_tilt]` is
correct given per-stepper Z endstops; `bicubic` is valid at 7 points per axis; the ADXL345
axis mapping is consistent with the measured X-above-Y frequency ordering; and
`calibration.cfg` / `mainsail-mobile.cfg` guard every wrapper on homed state.

### Sources consulted

**Klipper documentation**
- [Config_Reference](https://www.klipper3d.org/Config_Reference.html) — `bltouch`, `probe`, `bed_mesh`, `screws_tilt_adjust`, `stepper_z1`, `safe_z_home`, `tmc2209`, `tmc2208`, `extruder`, `verify_heater`, `controller_fan`, `heater_fan`, `gcode_arcs`, `include`
- [G-Codes](https://www.klipper3d.org/G-Codes.html) — `Z_OFFSET_APPLY_ENDSTOP`, `Z_OFFSET_APPLY_PROBE`
- [TMC_Drivers](https://www.klipper3d.org/TMC_Drivers.html) — stealthChop vs spreadCycle, interpolation error, IFCNT FAQ, current/heat guidance
- [BLTouch](https://www.klipper3d.org/BLTouch.html) — `stow_on_each_sample` / `probe_with_touch_mode` tradeoff
- [Bed_Mesh](https://www.klipper3d.org/Bed_Mesh.html) — adaptive meshing criteria
- [Resonance_Compensation](https://www.klipper3d.org/Resonance_Compensation.html) — `max_accel` selection, `square_corner_velocity` guidance
- [Rotation_Distance](https://www.klipper3d.org/Rotation_Distance.html) — belt and lead-screw derivation
- [Benchmarks](https://www.klipper3d.org/Benchmarks.html) — STM32F407 step-rate figures
- [Config_Changes](https://www.klipper3d.org/Config_Changes.html) — `relative_reference_index` removal dates
- [Exclude_Object](https://github.com/Klipper3d/klipper/blob/master/docs/Exclude_Object.md)

**Klipper source (`Klipper3d/klipper`, master)**
- [`config/generic-bigtreetech-skr-pro.cfg`](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-pro.cfg) — authoritative socket/pin map
- [`klippy/configfile.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/configfile.py) — `strict=False` merge behaviour, `_disallow_include_conflicts`
- [`klippy/extras/manual_probe.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/manual_probe.py) — `Z_OFFSET_APPLY_ENDSTOP` registration and implementation
- [`klippy/extras/shaper_calibrate.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/shaper_calibrate.py) and [`shaper_defs.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/shaper_defs.py) — `find_shaper_max_accel`, MZV definition (both re-run locally to produce the 12 400 / 6300 figures)
- [`klippy/extras/screws_tilt_adjust.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/screws_tilt_adjust.py), [`probe.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/probe.py), [`bed_mesh.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bed_mesh.py) — `use_xy_offsets` convention difference
- [`klippy/extras/tmc.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc.py), [`tmc2209.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/tmc2209.py) — init/shutdown paths, register defaults
- [`klippy/extras/heaters.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/heaters.py), [`verify_heater.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/verify_heater.py)
- [`klippy/extras/virtual_sdcard.py`](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/virtual_sdcard.py) — accepted gcode extensions

**BigTreeTech**
- [SKR-PRO-V1.2 schematic](https://github.com/bigtreetech/BIGTREETECH-SKR-PRO-V1.1/blob/master/SKR-PRO-V1.2/Schematic/SKR-PRO-V1.2.PDF) — `E0_UART` = PD4, per-socket PDN nets
- [SKR PRO V1.2 docs](https://github.com/bigtreetech/docs/blob/master/docs/SKR%20PRO%20V1.2.md) and [BTT wiki](https://global.bttwiki.com/SKR%20PRO%20V1.2.html) — UART jumper requirement, stallguard-pin cutting instruction
- [BTT TMC2209 page](https://global.bttwiki.com/TMC2209.html) — factory UART pin position

**Trinamic / Watterott**
- [TMC2209 datasheet rev 1.09](https://www.analog.com/media/en/technical-documentation/data-sheets/tmc2209_datasheet_rev1.09.pdf)
- [Watterott SilentStepStick TMC2209 pin configuration](https://learn.watterott.com/silentstepstick/pinconfig/tmc2209/) — MS1/MS2 as UART address and standalone microstep table

**PrusaSlicer (`prusa3d/PrusaSlicer`, tag `version_2.9.6`)**
- `src/libslic3r/GCode.cpp` — `custom_gcode_sets_temperature()`, `retract_and_wipe()`, Z-hop gating
- `src/libslic3r/PrintConfig.cpp` — firmware-retraction/wipe validator, `gcode_label_objects` enum, option defaults
- `src/libslic3r/PrintObject.cpp` — `fill_density == 0` bypassing `ensure_vertical_shell_thickness`
- `src/libslic3r/GCode/CoolingBuffer.cpp`, `ExtrusionProcessor.cpp`, `GCodeWriter.cpp`, `LabelObjects.cpp`
- `src/slic3r/GUI/Tab.cpp` — the wipe/firmware-retraction dialog
- Issues [#7449](https://github.com/prusa3d/PrusaSlicer/issues/7449), [#11597](https://github.com/prusa3d/PrusaSlicer/issues/11597), [#10064](https://github.com/prusa3d/PrusaSlicer/issues/10064), [#987](https://github.com/prusa3d/PrusaSlicer/issues/987), [#13189](https://github.com/prusa3d/PrusaSlicer/issues/13189), [#10618](https://github.com/prusa3d/PrusaSlicer/issues/10618)
- [PrusaSlicer-settings vendor profiles](https://github.com/prusa3d/PrusaSlicer-settings/blob/master/live/Voron/1.0.4.ini) — Voron and RatRig Klipper profiles
- [Infill](https://help.prusa3d.com/article/infill_42/), [Cooling](https://help.prusa3d.com/article/cooling_127569), [Speed settings](https://help.prusa3d.com/article/speed-settings_480325)

**Moonraker**
- [configuration docs](https://github.com/Arksine/moonraker/blob/master/docs/configuration.md) — `enable_object_processing` cost
- `moonraker/components/file_manager/file_manager.py` — accepted extensions

**Community reports (secondary, used only for IFCNT root-cause patterns)**
- [SKR Pro TMC2209 UART](https://klipper.discourse.group/t/skr-pro-tmc-2209-uart/3605) — resolved: dead driver modules
- [Unable to read tmc uart extruder register IFCNT](https://klipper.discourse.group/t/so-i-had-a-unable-to-read-tmc-uart-extruder-register-ifcnt/18328) — resolved: failing driver

### Things I could not confirm, stated rather than guessed

- **A maximum safe `run_current` for an uncooled TMC2209.** Klipper documents no number, only
  qualitative heat guidance. The commonly cited ~0.8 A figure is community lore; I have not
  presented it as sourced, and item 24 is framed as a measurement rather than a value change.
- **A recommended `min_temp`.** Klipper gives only the directional instruction to set the range
  *"just wide enough"*. The bed's `-50` clearly fails that test; the extruder's `0` matches
  Klipper's own shipped examples and is left alone.
- **Whether the E0/E1 driver DIAG pins are physically cut**, and whether the E0 socket's UART
  and MS jumpers are fitted. Both are visual inspections I cannot perform from the config.
- **`driver_TOFF`/`TBL`/`HSTRT`/`HEND` tuning values.** Klipper explicitly defers to Trinamic's
  datasheets and publishes none. The two values set here happen to equal Klipper's defaults, so
  they are no-ops rather than tuning.
- **The `uart_address: 3` hypothesis itself.** The pin is confirmed; the address explanation is
  inference from the calibrated `rotation_distance` plus the TMC2209 standalone microstep table.
  It is cheap to test and falsifiable, which is why it is proposed as a test rather than a fix.

---

## Tier 1 Application Log — 2026-09-20

Worked through Tier 1 in a follow-up session. Status of each item.

### Applied to local files (Klipper config — **not yet deployed to the Pi**)

| # | Item | File | What changed |
|---|---|---|---|
| 2 | `SAVE_CONFIG` conflict on `position_endstop` | `hardware.cfg` | Comment block added above `position_endstop` documenting that this is the first-layer datum, that `SAVE_CONFIG` cannot persist it, and that the option **cannot** be commented out because it is required. Value unchanged at `0`. |
| 3 | `SAVE_CONFIG` conflict on the shaper values | `tuning.cfg` | Comment block added above `shaper_freq_x` with the comment-out-then-calibrate procedure, and why it is safe here but not for `position_endstop`. Values unchanged. |
| 4 | Wrong Z calibration command | `calibration.cfg` | Added `CAL_Z_ENDSTOP` wrapping `Z_ENDSTOP_CALIBRATE`, with the same homed-axes guard as the other wrappers. Relabelled `CAL_Z_OFFSET` so the two are not confused. |
| 5 | Unresumable pause | `system.cfg` | Paused branch no longer disables anything, and emits a `RESPOND` note instead. Non-paused branch now uses three `SET_STEPPER_ENABLE` calls, which actually achieves the "keep Z energised" intent that `M84 X Y E` never did. |
| 6 | Unclamped `END_PRINT` Z lift | `macro.cfg` | Lift now computed in G-code coordinates and clamped against `axis_maximum.z - homing_origin.z`, matching `_TOOLHEAD_PARK_PAUSE_CANCEL`. Retract block switched back to absolute before the lift. |
| 8 | Bed sensor-failure detection | `thermistors.cfg` | `heater_bed min_temp` `-50` → `0`, with rationale. Also fixed the stale `# T3` pin comment to `# T0`. |
| — | Stale pressure-advance comments | `tuning.cfg` | Footer no longer repeats a (wrong) PA value; points at `thermistors.cfg` instead. |

### Applied to PrusaSlicer (`%APPDATA%\PrusaSlicer\printer\CoreXY.ini`)

PrusaSlicer was confirmed closed first, since it rewrites its `.ini` files on exit.

| # | Item | What changed |
|---|---|---|
| 1 | `autoemit_temperature_commands` | `1` → `0`. `START_PRINT` now owns all heating, which it already does completely (`M140`, then `M190` and `M109` after mesh load). |
| 9 | Firmware retraction vs wipe | `use_firmware_retraction` `1` → `0`, keeping `wipe = 1`. Matches Prusa's own Klipper profiles, restores correct time estimates and retraction preview. `retract_length` left at `0.6` — it must stay non-zero or all Z-hop is silently disabled. Slicer retract values already match `tuning.cfg`, so retraction behaviour is unchanged. |

### Verification performed

Klipper was not available to test against, so the expanded config was parsed offline the same
way `klippy/configfile.py` does it — `[include]` expansion in place, then
`RawConfigParser(strict=False, inline_comment_prefixes=(';','#'))`.

| Check | Result |
|---|---|
| Expanded config parses | 1763 lines, 101 sections, autosave block 5 sections |
| Jinja tag balance over all templates | 34 checked, 0 problems |
| Edited sections survive parsing (no inline-`#` truncation) | all 4 intact |
| Required options still present | `position_endstop`, `position_max`, `min_temp`, `max_temp`, `rotation_distance` all resolve |
| Line endings | LF only on all six files, per `.gitattributes` |

Replicating `_disallow_include_conflicts()` against the real config also **confirms the
headline finding empirically** rather than by reading alone:

| Command | Can it `SAVE_CONFIG`? |
|---|---|
| `Z_OFFSET_APPLY_ENDSTOP` | **Blocked** — `[stepper_z] position_endstop` is an included value |
| `SHAPER_CALIBRATE` | **Blocked** — `[input_shaper] shaper_freq_x` is an included value |
| `PROBE_CALIBRATE` | Can save — `[bltouch] z_offset` is not set in any included file |

### Not done, and why

- **Deploy to the printer.** The `scp` + `FIRMWARE_RESTART` step was refused by this
  environment's permission layer as a production deploy. The printer was confirmed idle
  (`print_stats.state: standby`, not homed) at the time, so it is safe to deploy when
  approved. Nothing has been sent to the Pi and no remote file has been touched.
- **Item 4's actual calibration run.** `Z_ENDSTOP_CALIBRATE` is a physical paper test at the
  nozzle; the macro wrapper is now in place but a human has to run it.
- **Item 7, the DIAG pin inspection.** Physical inspection of the E0 and E1 driver modules.
  Nothing to change in software.

### Two corrections to this document, found while applying it

Both were errors in earlier sections above, now fixed in place:

1. **`position_endstop` cannot be commented out.** Config_Reference: it *"must be provided for
   the X, Y, and Z steppers on cartesian style printers"*. The original advice would have
   stopped Klipper starting. The `shaper_freq_x` case genuinely is safe to comment out
   (it defaults to 0), so the two are not symmetric.
2. **`M84` ignores axis arguments.** `stepper_enable.py` maps both `M18` and `M84` to
   `cmd_M18` → `motor_off()`, which disables every stepper and calls
   `clear_homing_state("xyz")`. So the suggested `END_PRINT` change to `M84 X Y E` would have
   been a no-op, the existing `; keep Z enabled` comments were never true, and the pause bug
   was worse than originally described.

---

## Tier 2-4 Application Log — 2026-09-20

Worked through every remaining tier with the printer idle, deploying and verifying each
batch the way Tier 1 was done. Two things happened worth recording separately: an item
that carried real motion risk was skipped by design (14, revert-only rows), and one
active test (15) produced a definite negative result that required an immediate revert.

### Applied and deployed

All of Tier 2 (10-18), all of Tier 3 except the three flagged below (19, 20 no-op),
and all of Tier 4 except 21/23/24/28/31/32 (already done or dropped) and the physical
items. Commits `7972187` (bulk apply) and `a1a3f93` (extruder UART revert).

Verification for the bulk apply matched Tier 1's method: offline parse against the same
rules `klippy/configfile.py` uses (103 sections, 35 Jinja templates balanced, zero
duplicate sections, zero pin conflicts after resolving `[board_pins]` aliases), every
`_CLIENT_VARIABLE` literal checked with `ast.literal_eval` the way Klipper's
`gcode_macro.py` actually parses `variable_*` options, and every `_CLIENT_VARIABLE`
name cross-checked against what `mainsail.cfg`'s `PAUSE`/`RESUME`/`CANCEL_PRINT`/
`_TOOLHEAD_PARK_PAUSE_CANCEL` macros actually read. Deployed, checksum-verified,
`FIRMWARE_RESTART`, confirmed `ready` with no config warnings, then re-queried the
live config for the changed values and confirmed `DUMP_TMC` still succeeds on
`stepper_z` and `stepper_z1` after their pin un-crossing.

### Item 15 — extruder UART: hypothesis tested live, falsified, reverted

This one could not be left as a static "applied" edit, because it makes a claim that
only a live test can settle, and the wrong outcome has a real failure mode. The plan
from the summary above was executed exactly as written:

1. Added `[tmc2209 extruder]` with `uart_pin: PD4`, `uart_address: 3`.
2. Confirmed from `klippy/extras/tmc.py` before testing that `DUMP_TMC` reads
   registers directly with no stepper-enable step, so a failed read there raises a
   plain command error, not `invoke_shutdown` — the test genuinely could not trigger
   the original hard-shutdown fault.
3. Deployed, restarted, ran `DUMP_TMC STEPPER=extruder`. Failed:
   `"Unable to read tmc uart 'extruder' register GCONF"`.
4. Swept `uart_address` 1 and then 2 the same way (edit, deploy, restart, test).
   **All three explicit addresses, plus the implicit default of 0, failed
   identically.**

GCONF is one of the very first registers any read touches, so this is not a
addressing mismatch — it is a completely absent electrical link. The `uart_address`
hypothesis from the original summary is **falsified**.

<div style="color:#c0392b; border-left: 3px solid #c0392b; padding-left: 10px; margin: 8px 0;">

**🔬 ASTRA SAFETY CONCERN, found while testing:** leaving `[tmc2209 extruder]` in
place after this result would have been actively dangerous, not merely wrong.
**Reasoning:** the connect-time init failure is logged and harmless
(`klippy/extras/tmc.py`'s `_handle_connect()` only logs on failure), but
`TMCErrorCheck._do_periodic_check()` re-reads driver registers once per second
**while the motor is enabled** and calls `invoke_shutdown()` on failure. The extruder
motor gets enabled by the very first purge-line extrusion in `START_PRINT`. So a
non-functional `[tmc2209 extruder]` section sitting in the deployed config would have
looked fine through every restart and every idle check, then hard-shut-down the
printer the moment a real print actually started extruding — reproducing the exact
fault this change was meant to fix. **Reverted immediately, before any further use of
the printer**, restoring the standalone/Vref-pot configuration that has been the
actual working state all along.

</div>

Confirmed next step, physical, mains and USB power both off (USB back-powers the MCU):
pull the E0 driver module and compare its jumper field against a working socket (X or
Y) — the UART-enable jumper should be fitted and no MS1/MS2 jumpers should be present
(those set node address in UART mode on a TMC2209, which is what motivated the address
sweep in the first place). Check the module's UART select resistor position, confirm
the chip is actually a TMC2209 and not a TMC2208, and check whether its DIAG pin is
cut — the same module's DIAG line shares an MCU pin (PE15) with the X endstop. If the
jumpers and resistor look correct, swap the E0 module with the Z socket's proven-working
one and see whether the fault follows the module (dead driver) or stays with the socket
(board/trace fault).

### Not done, and why

- **`stow_on_each_sample`, item 21.** Real crash risk if the assumed pin clearance is
  wrong — needs eyes on the machine before flipping it.
- **`samples_tolerance_retries`, item 23.** The right value depends on a
  `PROBE_ACCURACY` baseline that does not exist yet; setting it from a guess would
  just replace one arbitrary number with another.
- **`controller_fan max_power` vs `run_current`, item 24.** Needs a `DUMP_TMC`
  `otpw` reading after a real print under load to decide which side of the tradeoff
  to move, not a config edit made blind.
- **The DIAG-pin inspection (item 7) and the E0 driver module inspection (item 15's
  follow-up)** are both purely physical.
- **Item 28** (X/Y `position_endstop` margin) was withdrawn in an earlier pass — see
  the Tier 1 log above for why.
- `Z_ENDSTOP_CALIBRATE`'s actual paper test (item 4) still needs a human at the
  machine, though the macro and the persistence procedure are in place.

### One correction to the original Tier 1 record

The Tier 1 log above states the printer's Klipper reports `v0.13.0-745-gf0892d82b-dirty`.
That is still accurate and unrelated to this batch — noting only that it was rechecked
after every restart in this session and the `-dirty` suffix persisted throughout, so it
is a standing fact about the installation, not something introduced here.
