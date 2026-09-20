# CoreXY Klipper Config — Handoff (2026-09-20)

Context dump for picking up this project in a new session/tool. This is a personal
CoreXY 3D printer running Klipper + Moonraker, config tracked in this git repo,
currently in the middle of a post-rebuild recalibration pass.

## Repo / access basics

- Workspace root: `f:\dev\COREXY-config-cleanup` (Windows).
- Git branch: `cleanup/config-2026-08-29`, currently 3 commits ahead of
  `origin/cleanup/config-2026-08-29` (not yet pushed). Latest commits:
  - `bc2490f` Recalibrate extruder rotation_distance to 26.5475 after fixing filament slippage
  - `a87517a` Fix purge line collision risk, sync PA, recalibrate extruder rotation_distance (superseded)
  - `01de0a1` Add ADXL345 accelerometer, retensioned-belt input shaper, new bed mesh, PrusaSlicer backup
- Needed `git config --global --add safe.directory F:/dev/COREXY-config-cleanup`
  once (dubious ownership warning) before git worked in this environment.
- Config lives on the printer's Raspberry Pi at `/home/pi/printer_data/config/`,
  mirrored in this repo's `config/` folder.
- SSH alias `klipper` → the Pi (key-based auth, no password prompt needed).
- Moonraker HTTP API on the Pi at `http://127.0.0.1:7125` (call it via
  `ssh klipper "curl -s ..."` from a dev machine — there's no port forward set up
  locally). Gcode script endpoint: `POST /printer/gcode/script -d 'script=<cmd>'`.
  Useful debug endpoint: `GET /server/gcode_store?count=N` returns the raw
  command/response history — use this to verify exactly what was sent if a result
  looks surprising, before assuming a physical/mechanical explanation.
- Deploy pattern for config changes: edit local `config/*.cfg` → `scp` to the Pi →
  `FIRMWARE_RESTART` (via Moonraker gcode/script, or the Moonraker service-restart
  endpoint if klippy itself is wedged) → verify via `/printer/objects/query` →
  `scp` the file back if Klipper appended a `#*# SAVE_CONFIG` block → commit.

## Hardware summary

- CoreXY, bed 300×300, Z max 400 (position_min -2 for probe compensation).
- MCU: STM32F407 (SKR Pro-like) + Raspberry Pi as second "rpi" MCU.
- BLTouch: x_offset=-27, y_offset=-20. Because X travel max is 300, probe corners
  near X=275 would need nozzle X=302 (exceeds the limit) — use ~270 inset on
  far-X corners instead of the literal 25/275mm.
- ADXL345 accelerometer on Pi SPI0, CS on CE0 (`spidev0.0`, `cs_pin: rpi:None`).
  CE1 did NOT work. Connector must be fully seated or you get
  `Invalid adxl345 id (got 0/ff vs e5)`. Input shaper currently 65.0Hz X / 46.2Hz Y
  (mzv both), measured after belt retensioning.
- Extruder: Bondtech BMG, min_extrude_temp 160, max_temp 280. Bed heater max_temp 110.
- Extruder TMC2209 has **never** had a `[tmc2209 extruder]` section in any config
  snapshot going back to the original monolithic printer.cfg — it runs on
  board/UART default current, unlike stepper_x/y/z/z1 which explicitly set
  run_current=1.1. An attempt to add one (uart_pin=PD4, run_current=0.9) caused
  intermittent hard shutdowns (`Unable to read tmc uart 'extruder' register
  IFCNT`) and was reverted. **CORRECTED 2026-09-20: `uart_pin: PD4` was the
  right pin.** Klipper's official `config/generic-bigtreetech-skr-pro.cfg` and
  BigTreeTech's own SKR-PRO-V1.2 schematic both map PD4 to the E0 socket's
  `E0_UART` net, and the extruder is unambiguously in E0 (step PE14 / dir PA0 /
  enable PC3 / heater PB1 = Heat0). So this is not a wiring-continuity problem.
  Leading hypothesis is a UART node-address mismatch: on a TMC2209, MS1/MS2 set
  the microstep resolution in standalone mode and the UART address in UART mode,
  and standalone 1/16 requires both strapped high, which is address 3 while
  Klipper defaults to 0. The calibrated `rotation_distance` of 26.5475 (within
  0.8% of the theoretical 26.76116) proves the driver really is at 1/16 — at the
  no-jumper 1/8 default it would have calibrated near 53.5. **Next step is a free
  software test, not disassembly:** add `[tmc2209 extruder]` with `uart_pin: PD4`
  and `uart_address: 3`, then run `DUMP_TMC STEPPER=extruder` *before moving the
  extruder motor* (that reads registers without the motor-enable path that
  triggers `invoke_shutdown`). Sweep addresses 1 and 2 if 3 fails. Only then go
  looking at the UART jumper under the E0 socket. Full reasoning and sources in
  `PRUSASLICER_PROFILE_REVIEW.md`.
  **UPDATE 2026-09-20, later same day: hypothesis tested and falsified.**
  Tried `[tmc2209 extruder]` with `uart_pin: PD4` live and remotely, sweeping
  `uart_address` 0/1/2/3, restarting and running `DUMP_TMC STEPPER=extruder`
  after each (no motor movement - confirmed safe from source first: `DUMP_TMC`
  reads registers directly, no stepper-enable step, so a failure there is a
  plain command error, not `invoke_shutdown`). **All four addresses failed
  identically**: `"Unable to read tmc uart 'extruder' register GCONF"`. GCONF
  is one of the first registers any read touches, so this is a fully absent
  link, not a wrong node address. Reverted the section entirely - leaving it
  in would reproduce the original hard-shutdown fault the next time the
  extruder motor is enabled (any print's purge line), since Klipper's periodic
  driver check would catch the dead link once the motor is running, even
  though the connect-time failure alone is harmless. **The extruder currently
  has no `[tmc2209]` section again**, running on the Vref pot as before -
  this is the known-safe state, not a regression.
  **Confirmed next step is physical**, at the machine, mains and USB both off:
  pull the E0 driver module, compare its jumper field against a working socket
  (X or Y) - check the UART-enable jumper is fitted and that no MS1/MS2
  jumpers are present (those set node address in UART mode), check the
  module's UART select resistor position, confirm it's actually a TMC2209 not
  a TMC2208, and check whether its DIAG pin is cut (same module - PE15, X's
  endstop, is also E0's DIAG line, see the pin-conflict note in `hardware.cfg`).
  If all that looks right, swap the E0 module with the Z socket's (proven
  working) module and see if the fault follows the module or stays with the
  socket. Full test log in `hardware.cfg` and commit `a1a3f93`.

## Chronological status

### 2026-09-13/14 session
- ADXL345 wired/verified, input shaper re-measured after belt retensioning.
- 4-corner bed probe sanity check (diagnostic only, not persisted).
- `SCREWS_TILT_CALCULATE` converged and physically adjusted.
- `PROBE_CALIBRATE` (Z-offset) run, saved `z_offset` = 1.782 (was 1.660).
- `BED_MESH_CALIBRATE` new 7×7 mesh saved (worked around a `BlockingIOError`
  crash from the long gcode-script POST — see "Klipper/Moonraker quirks" below).
- PrusaSlicer profiles restored from an old pre-reinstall backup
  (`E:\PRE_REINSTALL_BACKUP\APP_SETTINGS\PrusaSlicer\`) — NOT tracked in this repo.
- Extruder `rotation_distance` recalibrated from the untouched theoretical
  26.76116 down to 19.4391, based on 4 mark/extrude/measure trials — **but those
  trials had ±10% scatter** (ratios 0.894/0.799/0.877/0.82), noted at the time as
  "probably measurement noise, one more confirmation pass recommended."
- Pressure advance synced to 0.05 (firmware + slicer), still just a placeholder,
  never actually tuned.
- A live Z babystep of `-0.185mm` was applied mid-print to fix adhesion, with
  intent to bake it in via `Z_OFFSET_APPLY_PROBE` + `SAVE_CONFIG` later — several
  `FIRMWARE_RESTART`s happened before that ever happened, so **it almost
  certainly did not persist**. This still needs to be re-verified/redone.

### 2026-08-29 → 2026-09-13 (earlier cleanup)
- Purge line collision risk fixed in `macro.cfg` (`G0 X2 Y2` → `X10 Y10`) — this
  was likely the real cause of an earlier failed print (lost steps near axis
  limits), not the z_offset changes originally suspected.
- Extruder TMC2209 UART attempt made and reverted (see hardware section above).

### 2026-09-20 session (today — most recent, root cause found)
- **User physically remade the slipping extruder parts** (fixing filament grip).
- Root cause of the ±10% scatter in the 2026-09-14 rotation_distance trials was
  identified: **real filament slippage in the extruder**, not measurement noise.
  The 19.4391 value baked in that slippage instead of reflecting true
  rotation_distance.
- Re-ran mark-filament/extrude/measure tests after the parts fix. Method: `M83`
  (relative extrusion) + `G1 E<n> F100` via Moonraker gcode/script, user marks
  filament and measures remaining distance by hand.
  - Trial 1: 100mm commanded → ran way over the mark (discarded, mark too short).
  - Trial 2: 50mm commanded from an 83.3mm mark → 15mm remaining → 68.3mm actual
    → ratio 1.36600.
  - Trial 3: 80mm commanded from a 109.42mm mark → ran out near zero (not
    precisely measurable, but consistent with the ratio above — qualitative
    confirmation only).
  - Trial 4: 58.3mm commanded from a 99.6mm mark → exactly 20mm remaining →
    79.6mm actual → ratio 1.36535.
  - Trials 2 and 4 agreed within ~0.05% (vs. the old ±10% spread) — treated as a
    clean, trustworthy result.
- Before trusting the surprising "way over 100mm" over-extrusion result, checked
  `/server/gcode_store?count=20` on Moonraker to confirm each gcode command was
  actually sent exactly once (ruled out an accidental double-send bug).
- New `rotation_distance` = 19.4391 × 1.36568 (avg of trials 2 & 4) ≈ **26.5475**.
  This is very close to the original untouched theoretical Bondtech BMG value
  (26.76116) — strong confirmation that slippage, not gearing/config error, was
  the real problem all along.
- Deployed: updated `config/thermistors.cfg`, `scp`'d to the Pi, `FIRMWARE_RESTART`,
  confirmed live value via `/printer/objects/query?configfile=settings` =
  26.5475, committed as `bc2490f`.
- Printer left safe afterward: heater targets reset to 0 (restart side effect),
  extruder cooling naturally from ~192°C, bed from ~54°C.

**Lesson learned (recorded for future calibration work):** if a rotation_distance
(or similar) calibration shows large trial-to-trial variance (more than a
couple percent), suspect mechanical slippage in the drive train before trusting
an averaged "corrected" value — inspect/fix the hardware first, then recalibrate.

### 2026-09-20 (later) — full config audit + Tier 1 applied

- Full parameter-by-parameter audit of every live `.cfg` plus the PrusaSlicer
  profiles, checked against primary sources (Klipper docs and module source,
  Klipper's official SKR Pro board config, BTT's schematic, PrusaSlicer source
  at tag `version_2.9.6`). Written up in `PRUSASLICER_PROFILE_REVIEW.md`, which
  now carries 35 suggestions across four priority tiers.
- **Tier 1 applied and deployed**, commit `1ea7299` plus the deploy. All six
  changed files checksum-match on the Pi, `FIRMWARE_RESTART` came back ready
  with no config warnings, and the live values were re-queried to confirm.
  - `system.cfg` — `[idle_timeout]` no longer disables steppers while paused.
    **Klipper's `M84` ignores axis arguments** (`stepper_enable.py` maps M18/M84
    to `cmd_M18` → `motor_off()`, which drops every stepper and calls
    `clear_homing_state("xyz")`), so the old `M84 X Y E` was wiping the homed
    state and making any pause past 30 min unresumable. The non-paused branch now
    uses `SET_STEPPER_ENABLE` per stepper, which finally achieves the "keep Z
    energised" intent the comment always claimed.
  - `macro.cfg` — `END_PRINT` Z lift clamped against `axis_maximum.z` minus the
    gcode offset. The bare relative `G1 Z15` errored out on any print finishing
    above Z=385, and took `CANCEL_PRINT` with it.
  - `thermistors.cfg` — `heater_bed min_temp` −50 → 0, restoring the low-side
    disconnected-thermistor shutdown. Stale `# T3` pin comment corrected to `# T0`.
  - `calibration.cfg` — added `CAL_Z_ENDSTOP`; relabelled `CAL_Z_OFFSET`.
  - `hardware.cfg` / `tuning.cfg` — documented the two `SAVE_CONFIG` include
    conflicts in place, with the correct procedure for each.
- **PrusaSlicer** (`%APPDATA%\PrusaSlicer\printer\CoreXY.ini`, untracked):
  `autoemit_temperature_commands` 1 → 0, because PrusaSlicer's detector is a
  literal M-code line scan and never recognised `START_PRINT EXTRUDER=...`, so it
  was injecting an `M190` bed-wait *before* the macro and defeating the staged
  heating entirely. Also `use_firmware_retraction` 1 → 0 keeping `wipe = 1`,
  since PrusaSlicer's own validator rejects that pair as invalid.
- **Still open from Tier 1:** run `CAL_Z_ENDSTOP` (physical paper test), and
  inspect whether the E0/E1 driver modules have their DIAG pins cut — X and Y
  endstops share MCU pins PE15/PE10 with those sockets' stallguard lines, and BTT
  documents that the pin must be cut for a mechanical switch to work reliably.
- Noted in passing: the Pi's Klipper reports `v0.13.0-745-gf0892d82b-dirty`. The
  `-dirty` suffix means that checkout has uncommitted local edits, which will
  conflict on the next update.

### 2026-09-20 (later still) — Tier 2-4 applied, extruder UART hypothesis tested and falsified

- Worked through the rest of `PRUSASLICER_PROFILE_REVIEW.md`'s tiers with the
  machine idle and no physical intervention, deploying and verifying each
  batch the same way as Tier 1 (offline parse against the same rules
  `klippy/configfile.py` uses, then checksum-verified upload, `FIRMWARE_RESTART`,
  re-query live config, check `klippy.log`). Commits `7972187` and `a1a3f93`.
- **Reverted X/Y `rotation_distance` 39.77→40 and Z/Z1 4.018→4.** These were
  calibrated against a printed part's dimensions, which is a flow/extrusion
  error, not a steps-per-mm error - belt pitch and lead screw lead are
  geometric. Use the slicer's `xy_size_compensation` for real dimensional
  correction instead. **Re-check a calibration cube** - absolute part size
  shifted about 0.57% on X/Y from this revert.
- **Un-crossed `stepper_z`/`stepper_z1`'s `dir_pin`/`enable_pin`/`uart_pin`**,
  which were split across the Z and E1 sockets (each stepper's `step_pin` was
  correct for its socket, but the other three pins came from the other
  stepper's socket). Motion was unaffected throughout (neither `dir_pin` is
  inverted and both Z motors always move together), and `DUMP_TMC` on both
  confirmed still-working UART after the swap.
- **Extruder UART: tested and falsified, see the corrected entry above** in
  the hardware summary section. Section is not present in the live config.
- Raised `max_accel` 3000→4000 (Klipper's own bisection gives 6300 as the
  smoothing ceiling for the measured 46.2Hz Y shaper; stepped partway rather
  than to the ceiling since the real limit is min(smoothing, ringing) and only
  a print-based ringing test finds the latter - **still on the backlog**).
  Also `stepper_z`/`stepper_z1` `stealthchop_threshold` 1000→0 (spreadCycle,
  matching `interpolate: False`), `[bltouch] pin_move_time` 0.4→0.680 (default,
  best candidate for the probe scatter `samples_tolerance_retries: 6` was
  masking), bed mesh `fade_end` 5.0→10.0 with `fade_target: 0`, `adaptive_margin: 5`
  added and `START_PRINT` now calls `BED_MESH_CALIBRATE ADAPTIVE=1` when the
  gcode carries `EXCLUDE_OBJECT` markers, `gcode_arcs resolution` 0.1→1.0.
- **Removed the `PAUSE`/`RESUME`/`CANCEL_PRINT` overrides in `macro.cfg`** that
  were shadowing `mainsail.cfg`'s versions and silently running with a
  mixed-file config (Klipper merges duplicate sections per-option). Added
  `[gcode_macro _CLIENT_VARIABLE]` configuring the upstream macros instead,
  every option cross-checked by name against what `mainsail.cfg` actually
  reads - this restores idle-timeout extension during a pause, temperature
  restore on resume, and park-height clamping. **Test a real pause and resume**
  before trusting this on an important print.
- `START_PRINT` now sets a known gcode state (`G90`/`M83`/`M107`) up front and
  preheats the nozzle to `max(target-60, 150)` before homing instead of full
  target, so it isn't oozing at temperature through mesh load.
- Removed duplicate `[virtual_sdcard]`/`[pause_resume]`/`[display_status]`/
  `[respond]` sections from `system.cfg` (already provided by `mainsail.cfg`),
  and the stale "Pressure Advance ... 0.06" comment block from `printer.cfg`.
- **PrusaSlicer** (`%APPDATA%\PrusaSlicer`, untracked): `gcode_label_objects`
  octoprint→firmware (native `EXCLUDE_OBJECT_*` instead of comments needing
  Moonraker reprocessing - paired with `moonraker.conf`'s
  `enable_object_processing` True→False, which needs a **Moonraker service
  restart**, not just `FIRMWARE_RESTART`, to take effect); `fill_density`
  0%→10% (0% was bypassing `ensure_vertical_shell_thickness` per PrusaSlicer's
  own source); `overhang_speed_0..3` 15/15/20/25→15/25/30/80% (Prusa's own
  MK4IS curve). `enable_dynamic_overhang_speeds` deliberately left at 0 - a
  preference call, not a fix.
- **Still deferred to physical intervention**, unchanged from the Tier 1 list:
  `Z_ENDSTOP_CALIBRATE` paper test, DIAG-pin inspection on E0/E1, plus now also
  `stow_on_each_sample` (needs verified pin clearance before enabling),
  `samples_tolerance_retries` (needs a `PROBE_ACCURACY` baseline first),
  `controller_fan max_power` vs `run_current` (needs a `DUMP_TMC` `otpw` check
  after a real print), and the E0 driver module inspection above.

## Current known-good config values

- `rotation_distance` (extruder): **26.5475** (config/thermistors.cfg) — just
  reconfirmed, high confidence.
- `pressure_advance`: 0.05 (placeholder, synced between firmware and slicer,
  never actually tuned via TUNING_TOWER or a printed test).
- `z_offset`: 1.782 as last saved — **NOT trustworthy**, see priority #1 below.
- Input shaper: 65.0Hz X / 46.2Hz Y, mzv, post-retensioning.
- Bed mesh: 7×7 "default" profile, captured 2026-09-13.

## Remaining work, in priority order

1. **Re-establish first-layer height — but with `Z_ENDSTOP_CALIBRATE`, not
   `PROBE_CALIBRATE`.** *(Corrected 2026-09-20.)* Z homes to a physical switch
   (`stepper_z` on PG8, `stepper_z1` on PG5), so the nozzle datum is
   `[stepper_z] position_endstop`, **not** the BLTouch `z_offset`.
   `PROBE_CALIBRATE` tunes the probe trigger point, which feeds bed mesh and
   `PROBE`, but cannot move the first layer — and because
   `zero_reference_position: 150,150` normalises the mesh at the centre, a
   constant `z_offset` error cancels out anyway. The saved 1.782 is therefore
   fine to leave alone. Run `CAL_Z_ENDSTOP` (new wrapper in `calibration.cfg`)
   and do the paper test.
   **Persisting the result needs a hand edit.** `Z_OFFSET_APPLY_ENDSTOP` stages
   a new `position_endstop`, but `SAVE_CONFIG` aborts with *"conflicts with
   included value"* because `hardware.cfg` sets it — and it cannot be commented
   out to dodge that, since `position_endstop` is a required parameter and
   Klipper will not start without it. So: read the value Klipper prints, edit
   `hardware.cfg`, `FIRMWARE_RESTART`. Never call `SAVE_CONFIG` for it.
   The same conflict blocks `SHAPER_CALIBRATE` + `SAVE_CONFIG` (via
   `tuning.cfg`'s `shaper_freq_*`), but there commenting the lines out first
   *is* safe, because those options default to 0.
2. **Fresh baseline calibration cube print** with rotation_distance fixed,
   Z-offset re-verified, and the purge-line fix in place — first real
   end-to-end confirmation print since the rebuild.
3. **Real pressure advance calibration** (TUNING_TOWER or a printed line-pattern
   test) — 0.05 is currently just a carried-over placeholder.
4. Broader deferred calibration backlog (not yet started, roughly in this order):
   - Skew correction
   - Axis twist compensation
   - Max acceleration / jerk headroom tuning
   - Flow rate / volumetric speed limits
   - Thermal bed mesh refinement (cold vs. printing temp)
   - Adaptive mesh + smarter `PRINT_START` macro overhaul
   - Resonance/input-shaper health-monitoring baseline
5. New default PrusaSlicer 0.4mm/0.2mm print+printer profile — was in progress
   (reviewed `CoreXY.ini` and `0.4mm PLA COREXY 0.2.ini` as templates), not yet
   created. Planned approach:
   - Clean up restored `CoreXY.ini`: fix stale RatRig printer_notes/model, reset
     slicer z_offset to 0 (Klipper's probe z_offset already accounts for it),
     set machine_max_* to real values (XY vel 300/accel 3000, Z vel 15/accel 350,
     E vel 60/accel 2000), enable `use_firmware_retraction=1`, remove the broken
     `SET_FILAMENT_SENSOR SENSOR=my_sensor` reference (no filament sensor exists).
   - New print profile: 0.2mm layer, 0.4 nozzle, perimeter ~60mm/s, infill
     ~120mm/s, travel ~250mm/s, first layer ~30mm/s.
   - Default filament profile → the already-restored "PLA COREXY Fast".
   - Note: this PrusaSlicer profile work happens in
     `%APPDATA%\PrusaSlicer` on the Windows side and is **not tracked in this
     git repo**.

## Klipper/Moonraker quirks worth knowing

- `PROBE` only retracts by `sample_retract_dist` (5mm above trigger), not to a
  safe fixed height — always re-issue `G1 Z<safe>` before subsequent XY travel
  between probe points or the pin can drag/re-trigger.
- Long-running gcode script POSTs (e.g. a 7×7 `BED_MESH_CALIBRATE`) can trigger
  a `BlockingIOError: [Errno 11] Resource temporarily unavailable` in Klipper's
  gcode response writer, crashing/restarting klippy — but the physical
  probing usually still completed and the result may still be queryable via
  `/printer/objects/query` even though the HTTP response never arrived. Capture
  it and manually write the `#*# SAVE_CONFIG` block + restart rather than
  re-running the whole physical calibration blindly.
- If the gcode-script POST endpoint hangs (curl times out with 0 bytes) even for
  unrelated commands, GET-style status queries still work fine — the klippy
  gcode response channel specifically is jammed. Fix: restart klipper via
  Moonraker's own API (works without a password):
  `POST /machine/services/restart?service=klipper` (query-string param, not
  JSON body). `sudo systemctl restart klipper` over SSH needs an interactive
  password and won't work in an unattended/automated environment.
- After any klipper service restart: `homed_axes` resets to `""` and heater
  targets reset to 0 (residual heat remains, but target=0) — must re-home and
  re-set temps before assuming anything is hot, cold, or homed.
- Occasionally after a service restart the MCU serial gives `Got EOF when
  reading from device` / `klippy_state=error`; a second
  `/machine/services/restart?service=klipper` call typically clears it.

## Environment note for whichever agent/tool picks this up

- SSH sessions to the printer's Pi work fine with key-based auth (alias
  `klipper`) — no password prompt.
- If your automation environment auto-cancels any terminal command that prompts
  for a password/secret, avoid ever triggering a password prompt (e.g. don't run
  bare `ssh` to a host without key auth configured) — ask the human to run such
  commands directly instead.
