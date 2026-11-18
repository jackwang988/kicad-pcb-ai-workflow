# R10 — GND first pour → approved stitching → refill → full native DRC / G4

**Mandatory ordering.** GND is intentionally excluded from ordinary Freerouting
trace routing and normally connects through approved copper-zone/plane geometry.
**Never run the final full-board connectivity/DRC gate on an unfilled board** and
treat expected GND airwires as final route failures. Pre-layout Board Setup
rule checks, placement/courtyard checks and source audits may still run earlier;
they are NOT the G4 full-board DRC.

## Actual execution (separate KiCad/Konnect save/readback snapshots)

1. **After routing** — Finish/verify allowed P0–P3 non-GND traces. Preserve the
   saved `pre_ground_board` checkpoint, all protected copper and net membership.
2. **First real GND fill** — Use the accepted KiCad/Konnect operation to create
   and fill real GND zones **only on explicitly approved ground-bearing copper
   layers** (for example F.Cu and B.Cu on a two-layer design, or explicit In*.Cu
   ground layers on multilayer designs). Check plane priorities, keepouts,
   clearances, thermal relief and verify zone definitions on each layer. A currently unanchored plane can temporarily produce **no filled polygon** because KiCad removes an isolated copper island; that is acceptable only when approved stitching follows and the **final** re-fill shows real GND copper on every required layer. Save,
   reload and hash the board as `first_filled_board`. A zone outline is not fill.
3. **Review GND topology** — Inspect pads, split/isolated islands, reference
   return continuity and actual points with ground copper on intended layers.
   Zone fill can remove floating islands. Determine whether ANY stitching via
   is needed; an open-looking patch is not enough. An approved via needs a
   grounded endpoint, a legal via type and actual copper on the relevant
   layers. Via stitching does NOT automatically make every copper region
   continuous; no proof without native connectivity and engineering review.
4. **Only required, approved stitching vias** — Via placement is bounded and
   explicit (UUID, net GND, X/Y, actual via span, approved GND contact layers, diameter, drill, purpose). Check
   copper-to-hole / via-to-pad clearance, drill/annular ring/edge/keepout,
   signal/return clearance, antenna exclusion, layer span, current/heat/EMC
   where applicable. Use the accepted sole KiCad/Konnect writer; save/reload
   `stitched_board`. No arbitrary mass via placement.
5. **Refill AFTER stitching** — Refill all modified GND zones again, save,
   reload and hash `final_refilled_board`. Repeat after ANY edit to via,
   copper, zone, component position, clearance or board geometry.
6. **Pre-DRC ground gate** — Run `routing_seven_stage.py audit-ground` over
   those four hash-bound actual PCB files. It checks GND-zone definitions for every expected layer, explicitly records any first-fill unanchored layers, and requires **actual final filled polygons** on every approved GND layer, unchanged non-ground tracks/footprints and exactly
   approved, correctly sized GND stitching vias. Produce a fresh immutable
   `GROUND_FILLED_STITCHING_AUDITED_READY_FOR_NATIVE_DRC` JSON report.
   **This is a READ-ONLY geometry/snapshot gate, NOT proof of connectivity
   and NOT a G4 pass.**
7. **Only then full KiCad DRC** — On an isolated saved candidate run:
   `kicad-cli pcb drc --refill-zones --save-board --format json --output reports/final-drc.json checkpoints/after-refill.kicad_pcb`
   KiCad 10's CLI refills **before** DRC with `--refill-zones`; it only
   persists that refill when `--save-board` is also specified. Reopen
   and hash this post-DRC board and the JSON report, including both
   `violations` and `unconnected_items`. No DRC merely run on an unfilled
   routing candidate counts as G4.
8. **Final audit and G4** — Run `audit-final` with `before_board` bound to
   the ground-gate final-refilled board, `after_board` bound to the post-DRC
   saved board, `gnd_completion_report` binding, `native_drc_board_sha256`
   matching the post-DRC board, `native_drc_json` binding and
   `zone_refill_completed:true`. Native errors, remaining GND
   unconnected items, invalid plane islands or failed engineering return
   paths BLOCK G4. Engineer signs off SI/PI, thermal, DFX and manufacture
   separately. Gerbers stay `EXPORTED_NOT_RELEASED` without release gates.

## Example ground-stage config

Replace all placeholder hashes with SHA-256 of **real saved project files**.
If no stitching via is warranted, `approved_stitching_vias` must be `[]`
and actual newly added GND vias must also be zero.

~~~json
{
  "schema_version": 1,
  "stage": "ground",
  "pre_ground_board": {"file":"checkpoints/routed.kicad_pcb", "sha256":"<actual-sha>"},
  "first_filled_board": {"file":"checkpoints/first-fill.kicad_pcb", "sha256":"<actual-sha>"},
  "stitched_board": {"file":"checkpoints/stitched.kicad_pcb", "sha256":"<actual-sha>"},
  "final_refilled_board": {"file":"checkpoints/final-refilled.kicad_pcb", "sha256":"<actual-sha>"},
  "gnd_zone_layers": {"GND":["F.Cu","B.Cu"]},
  "copper_layer_stack": ["F.Cu","B.Cu"],
  "approved_stitching_vias": [
    {"uuid":"<actual-via-uuid>", "net":"GND",
     "at_mm":[12.0,8.0], "layers":["F.Cu","B.Cu"],
     "ground_contact_layers":["F.Cu","B.Cu"],
     "min_diameter_mm":0.6, "min_drill_mm":0.3,
     "purpose":"Bridge verified separate ground copper regions"}
  ]
}
~~~

## Commands

~~~bash
# After the accepted KiCad/Konnect writer has physically filled/stitched/refilled:
python scripts/routing_seven_stage.py audit-ground PROJECT \
  --config ground-config.json --output reports/ground-pre-drc.json
# BLOCKED means do not execute the following full-board DRC as final G4.
kicad-cli pcb drc --refill-zones --save-board --format json \
  --output reports/final-drc.json PROJECT/checkpoints/final-refilled.kicad_pcb
# Reopen saved post-DRC PCB and bind all source/output hashes in final config:
python scripts/routing_seven_stage.py audit-final PROJECT --config final-config.json
~~~

Via `workflow.py` use task `pcb.ground_plane_audit` with
`--routing-stage-config ground-config.json --ground-audit-output reports/ground-pre-drc.json`
and later `pcb.routing_final_audit` with the final config.

**Limitations:** The read-only snapshot auditor cannot authenticate the native
tool by merely reading a JSON receipt, and cannot calculate plated barrel
contact, floating copper/island adjacency, thermal/EMC, characteristic
impedance or 3D return continuity. The user/engineer must validate accepted
native calls and inspect actual KiCad DRC + plane/return-path results. A real
KiCad/Freerouting *route-only* fixture that does not contain complete GND
zones must not run or report a final full-board DRC.

References: KiCad 10 PCB Editor zone fill documentation and KiCad 10 CLI
`pcb drc --refill-zones --save-board` command.
