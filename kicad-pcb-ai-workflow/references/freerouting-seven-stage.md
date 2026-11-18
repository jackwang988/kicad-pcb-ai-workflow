# Seven-stage KiCad PCB routing using Freerouting 2.5.0 (R10 preview)

> **Execution status:** Seven-stage routing policy and verification integrated into Skill. Freerouting is the *preferred candidate generator for qualified ordinary nets*, NOT a universally production-accepted router. The native KiCad/Konnect writer, G4 and manufacture gates remain authoritative. No live GUI/complex-board end-to-end acceptance is claimed.

## Immutable stages and ownership

| Stage | Owner | Mandatory evidence / stop conditions |
|---|---|---|
| 1. Full net inventory | Skill + `routing_policy.py` | All real XML/KiCad nets classified, two-endpoint connections, design currents/criticality, NC separately; unknown names or incomplete classes = BLOCKED |
| 2. Design rules | Skill + verified Konnect/KiCad | Approved factory stackup; effective layer/copper, NetClass, track width/clearance, via diameter/drill, edge, keepouts, H/V/45 preference, SI/PI; **read back actual native values** |
| 3. Critical routing | KiCad via accepted Konnect tools/engineer | Complete P0–P2 routes and protection record; verify locked/previous traces and actual saved board hash; power trunk >= current/thermal/drop table + 0.254 mm; explicit pad/layer/region/length-limited neckdowns only |
| 4. Ordinary autorouting | Freerouting **v2.5.0** external CLI | Export saved board as reviewed Specctra DSN; hash-locked DSN, external `.rules` and JAR; `-inc` must exclude separate **GND, critical power, RF, differential, clock, other protected NetClasses**; output SES **candidate only** |
| 5. Import and geometry audit | Konnect/KiCad + `routing_seven_stage.py audit-import` | **Isolated candidate** import; save/reload; same net inventory; preserved critical copper/object UUIDs; new ordinary H/V/45 segments, per-net widths, legal layers, via geometry/count |
| 6. Bounded repair | Accepted KiCad/Konnect routing tool or engineer | New checkpoint, explicitly identified remaining connections, approved maximum iterations/time/vias, whitelist for ripup. Any source hash drift, failure, or need to relax constraints = BLOCKED |
| 7. GND fill and G4 | KiCad native full DRC + engineer | Keep GND out of ordinary *trace* autorouting; add required ground stitching/returns; refill actual zones; save/reload; zero unconnected and native DRC errors; full G4 reviews including SI/PI, high-current thermal and manufacturing constraints |

**Do not require zero unconnected or full-board DRC in G3 placement**. G3 remains placement-only after real Konnect save and position readback. Only stage 7 calls final native full-board DRC.

## Practical use

1. Use existing `pcb.fab_preview` / `pcb.fab_confirm` then apply approved settings via actual accepted KiCad/Konnect writer, read back effective rules. Use existing `pcb.routing_preflight` and route policy (full inventory with actual hashed board, XML netlist, stackup, rule, protected-object inputs).
2. Export a *saved* KiCad PCB to DSN; create an independently audited `netclass-map.json`. A JSON file with plausible names is not proof of actual KiCad NetClass membership; the operator must verify the effective native assignment before invoking Freerouting.
3. Create a stage plan config and run `routing_seven_stage.py plan`. It reuses the existing full-net constraint validator and refuses a NetClass that mixes protected/GND and ordinary nets.
4. Perform critical net native routing; save/reload and capture protection/hash evidence. Re-export DSN **after** these edits, rebind all hashes and plan again before Freerouting.
5. Invoke `freerouting_adapter.py` with exact source hashes, exclusions, verified JAR and bounded runs; the adapter generates SES only and does not import or approve.
6. Import SES into *another* saved KiCad candidate via accepted Konnect commands, save/reload. Use `audit-import` on actual before/after board hashes; repair anything blocked. Do not overwrite the original PCB to make a check pass.
7. Refill GND and save again. Run full native KiCad DRC, capture machine-readable JSON; use `audit-final` on checkpoint/final board and DRC. **Success still means G4 engineer approval pending, not Gerber-ready.**

### Plan sample (`route-plan-config.json`)

```json
{
  "schema_version": 1,
  "stage": "plan",
  "routing_request": "routing-request.json",
  "dsn": {"file":"route/board.dsn","sha256":"<actual 64-hex source SHA>"},
  "netclass_map": {"file":"route/netclass-map.json","sha256":"<actual 64-hex map SHA>"}
}
```

The referenced native map is:

```json
{
  "schema_version": 1,
  "board_sha256": "<routing-request inputs.board.sha256>",
  "dsn_sha256": "<actual DSN SHA>",
  "net_to_class": {
    "GND": "GND",
    "USB_D+": "DIFF_CRITICAL",
    "GPIO1": "SIGNAL"
  }
}
```

`net_to_class` must include **every** classified net and actual NetClasses from the specific project. Protected and ordinary nets may not share a Freerouting class. Do not hand-author an unverified map for production routing.

### Review sample (`route-import-config.json`)

```json
{
  "schema_version": 1,
  "stage": "import",
  "before_board": {"file":"checkpoints/pre-freerouting.kicad_pcb","sha256":"<source hash>"},
  "after_board": {"file":"candidates/imported.kicad_pcb","sha256":"<candidate hash>"},
  "networks": {
    "GPIO1": {
      "minimum_width_mm": 0.20,
      "allowed_layers": ["F.Cu","B.Cu"],
      "min_via_diameter_mm": 0.30,
      "min_via_drill_mm": 0.20
    }
  },
  "protected_nets": ["GND","USB_D+"],
  "gnd_nets": ["GND"],
  "protected_object_uuids": ["<actual saved locked object UUID>"],
  "max_new_vias": 10
}
```

For the final audit, use `"stage":"final"` and add `"zone_refill_completed":true` plus `"native_drc_json":{"file":"reports/final-drc.json","sha256":"<actual DRC JSON hash>"}`. The final board must have a genuinely filled GND zone and the report must contain `violations` and `unconnected_items` arrays. This read-only audit does not authenticate the DRC tool or calculate current/thermal, differential timing, characteristic impedance, return path or engineer acceptance by itself. **Never treat user-supplied boolean evidence as a substitute for an actual native operation.**

### Commands

```bash
python scripts/routing_seven_stage.py plan PROJECT --config route-plan-config.json
python scripts/freerouting_adapter.py --dsn route/board.dsn \
  --expected-dsn-sha256 ACTUAL_DSN_SHA --jar approved/freerouting-2.5.0.jar \
  --expected-jar-sha256 APPROVED_JAR_SHA \
  --exclude-netclasses GND,DIFF_CRITICAL,RF_CRITICAL,POWER_CRITICAL \
  --netclass-map route/netclass-map.json \
  --expected-netclass-map-sha256 APPROVED_NATIVE_MAP_SHA \
  --output-dir NEW_CANDIDATE --passes 20
# After reviewing preview, repeat the same command with --apply.
# Import SES via accepted KiCad/Konnect operation into isolated candidate.
python scripts/routing_seven_stage.py audit-import PROJECT --config route-import-config.json
# Then approved bounded repair, native KiCad zone fill and actual full DRC.
python scripts/routing_seven_stage.py audit-final PROJECT --config route-final-config.json
```

If the approved Freerouting `.rules` is present, pass `--rules-file FILE --expected-rules-sha256 HASH`; a silently autodiscovered adjacent rules file is blocked. Use actual available NetClass names: examples are **not** automatic categories.

The same plan/audit interfaces are registered as `workflow.py --task pcb.routing_seven_plan`, `pcb.routing_import_audit`, and `pcb.routing_final_audit` with `--routing-stage-config`. The `pcb.freerouting_candidate` task calls only the offline Freerouting adapter; the accepted Konnect native import remains a separately discovered and authorized operation.

## Freerouting 2.5.0 fanout and optimization safety

Native KiCad 10.0.8 + Freerouting 2.5.0 regression showed that even
with GND correctly assigned to the effective GND NetClass and -inc GND
specified, the router's initial SMD fanout stage could still add GND
copper. The approved R10 ordinary-net CLI adapter therefore explicitly
sets --router.fanout.enabled=false and --router.optimizer.enabled=false.
Only the constrained ordinary autorouter pass remains active. This
may reduce routing completion on very dense boards; never re-enable
fanout or optimizer without a separate version-pinned native protected-
object test. If a design cannot finish with these protections, return
BLOCKED/engineer handoff instead of silently routing GND.

The real KiCad SES import must still prove no newly added/removed GND
tracks/vias or protected copper in the saved and reloaded board.

## Mandatory native NetClass membership proof (R10 protected-GND fix)

A DSN file can declare a class called GND without placing the actual GND net
in that class. In particular, headless KiCad 10 SWIG LoadBoard() loads the
PCB but not the separate .kicad_pro net settings; a naive ExportSpecctraDSN()
may emit a GND declaration yet put GND in kicad_default. Freerouting -inc GND
only applies to the effective imported class. R10 now inspects the direct
membership inside the real DSN network/class blocks, not a regex for the
class name alone. A GND net assigned to a non-excluded class is BLOCKED.

Before using the adapter with --apply, independently read actual KiCad
NetClass membership from a project-aware editor and supply the complete
source/DSN-bound map:

~~~json
{
  "schema_version": 1,
  "board_sha256": "actual saved KiCad board SHA-256",
  "dsn_sha256": "actual exported DSN SHA-256",
  "net_to_class": {"GND": "GND", "GPIO": "SIGNAL"}
}
~~~

Pass the map and its SHA-256 via --netclass-map and
--expected-netclass-map-sha256. Every DSN class member must match the native
map exactly and the DSN hash must match; the adapter does not infer or repair
the project rules and must reject mismatch. Use native project-aware Konnect
DSN export and independent readback. An isolated native test can explicitly
restore .kicad_pro settings into a disposable headless board before its
genuine KiCad ExportSpecctraDSN() call, but this is not authorization to write
the user's live PCB through pcbnew.

After SES import, compare saved board tracks, vias and protected copper,
including GND, against the original. A clean DSN map and a successful SES
generation **alone** never close G4.

## Important limitations and test gate

- Freerouting's `-is prioritized` does **not** guarantee a user-defined P0/P1/P2 fixed net order. Route critical nets first with separate verified actions and protect their copper before exporting ordinary-only DSN.
- `-inc` excludes **NetClasses**, not raw net names; class existence alone does not guarantee net membership.
- Freerouting `automatic_neckdown` and optimizer behavior are not an approved substitute for a per-pad source-backed local power escape with bounded length/thermal check.
- The `routing_seven_stage.py` parser checks newly added ordinary straight-segment width, H/V/45, allowed layers, via budget/diameter, protected nets and UUIDs; other native/custom/thermal/SI rules still need independent signoff.
- Do not claim acceptance from software fixtures alone. Promote default autoexecution only after Windows KiCad 10.0.8, accepted Konnect tools, Freerouting 2.5.0 and diverse representative 2/4-layer boards pass actual save/reload/DRC and geometry audits.
- A generated SES or zero-violation JSON alone never authorizes manufacturing or bypasses G4. Final state remains `EXPORTED_NOT_RELEASED` pending all production-release requirements.

Reference: [Freerouting 2.5.0 CLI](https://github.com/freerouting/freerouting/blob/v2.5.0/docs/command_line_arguments.md), [Freerouting 2.5.0 settings](https://github.com/freerouting/freerouting/blob/v2.5.0/docs/settings.md), [KiCad PCB Editor rules](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).
