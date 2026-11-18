# Freerouting-primary routing candidate: staged engineering contract (R10 preview)

**Status:** implementation proposal plus partial CLI fail-closed guards; no end-to-end acceptance or default promotion yet. **Do not treat the current branch as a production-qualified router.**

## Decision: deterministic autorouter, AI planner, independent KiCad authority

For ordinary nets, prefer a *qualified* Freerouting 2.5.0 DSN/SES candidate over building an LLM-operated multi-net A* copper engine. Keep Konnect as the sole active KiCad writer and read-back tool, with native KiCad checks as the final authority. The offline grid A* remains a bounded research/diagnostic candidate only; it is **not** a production fallback. For critical traces, Konnect executes an approved native trace operation or the user routes manually with review.

The Freerouting **DSN** route is preferred to the experimental JSON/API route until equivalent, source-bound E2E evidence exists. The presence of a plugin or an SES file is not evidence of a conforming board.

## Seven-stage routing orchestration

1. **Whole-board net inventory**: classify every real XML/KiCad net; bind net names, pin/pad endpoints, actual NetClass assignment and protected nets. Unknown names are BLOCKED. Use the full-net request gate from `constraint-routing.md`.
2. **Rule and GND strategy**: apply confirmed fabricator stackup, copper width/spacing, drill/via geometry, layer restrictions, board edge, keepouts, and the actual effective KiCad rules. Prepare continuous GND zones for final refill; exclude dedicated GND NetClasses from *trace* autorouting, but do not suppress GND short returns/stitching or electrical connectivity verification. Dedicated NetClasses must be proven from KiCad and the exported DSN; a class named GND does not prove the GND net belongs to it.
3. **Critical-first geometry**: protect fixed footprints, locked existing tracks, antenna/analog/RF, high-speed differential, length-sensitive, switching loops, Kelvin and high-current branches. Route special signals in native KiCad/Konnect with their own engineering acceptance. NetClass `-inc` exclusions are mandatory for the ordinary-nets pass and must be reviewed against the actual KiCad net membership.
4. **Ordinary candidate**: export DSN from the real, saved KiCad PCB into an isolated checkpoint. Bind exact DSN SHA, optional reviewed Freerouting `.rules` SHA and verified 2.5.0 JAR SHA. Run bounded `-mp`/timeout, `-inc` excluded classes, and a fresh output directory. The adapter rejects an unapproved adjacent `.rules`; it never imports the SES itself.
5. **Isolated import and read-back**: use only approved Konnect capabilities / KiCad editor to import `.ses` into a separate candidate, save, reload and diff nets, footprints, traces, vias, zones and protected object UUIDs. A success exit code/SES alone cannot satisfy this stage. Keep source SHA and a non-overwriting evidence directory.
6. **Electrical repair and copper**: repair remaining ordinary airwires with a bounded, accepted native tool; do not silently relax net/fab rules. Size power trunks from actual copper thickness, voltage drop, temperature rise and the user's reference width **plus 0.254 mm**, rounding *up*. Permit scoped pad-escape neckdown only with named net/pad/region/layer, maximum length, verified thermal/current/drop and native rule scope. Freerouting 2.5.0 `-inc`/DSN rules are **not** proof it can enforce this segmented local neckdown automatically. Fill all authorized GND zones; confirm actual pad-to-zone connectivity and return continuity.
7. **G4 gate and release**: complete native KiCad DRC after fill, all required-net connectivity, native netlist parity, saved/reloaded geometry, rule-hit audit, controlled impedance / differential skew / timing / power/thermal/creepage review as applicable. **Any unsupported / stale / missing rule, loss of copper protection, or DRC blocker means BLOCKED**, not a silently accepted SES. Manufacturing remains EXPORTED_NOT_RELEASED until the separately required release gates.

## Rule placement and actual capability boundaries

| Requirement | Best enforcement point | Freerouting 2.5.0 treatment |
|---|---|---|
| Trace width / spacing / NetClass / layer limits / via | KiCad Board Setup, approved native effective rules, DSN, reviewed `.rules` | Can consume supported Specctra/FreeRouting rules; verify final actual widths/clearances and layers |
| GND plane and reference return | KiCad zone policy + protected NetClasses + post-fill check | Exclude trace-routed GND NetClass by `-inc`; `-inc` acts on **classes, not names** |
| H/V/45 general signal shape | Final geometry analyzer and approved router-specific option | Do not claim strict 45-degree output solely from DSN; inspect actual SES-imported tracks |
| Power trunk +0.254 mm | External power-width gate, approved netclass and KiCad native geometry audit | Do not assume `.rules` applies arbitrary per-segment electrical sizing |
| Fine pitch scoped neckdown | KiCad custom rules + native pad/track geometric & thermal audit | Use approved Konnect intervention; no automatic local variable-width guarantee |
| USB/MIPI/RF controlled impedance and length/skew | KiCad design rules and dedicated SI/PI review | Treat as protected/critical initially; route separately |
| Component courtyard, keepout, locked copper | KiCad actual object geometry and protected-object diff | Not every assembly/courtyard or custom-rule condition survives DSN translation |
| Full manufacturing/thermal/signal-integrity signoff | Native KiCad + electrical analysis + engineer gate | Not delivered by router DRC, even if it exists |

**Version distinction:** In the Freerouting *v2.5.0* CLI docs, the supported input is DSN/SES/FreeRouting `.rules`, and `-inc` excludes NetClasses; later **master** docs also describe direct KiCad `.kicad_pro`/`.kicad_dru` input and neck-width behavior. Do **not** use later master features as a claim about tested 2.5.0 capabilities.

## Minimal gated external CLI example (not an authorization to release)

```bash
python scripts/freerouting_adapter.py \
  --dsn path/to/approved-board.dsn \
  --expected-dsn-sha256 <actual-reviewed-64-hex-sha256> \
  --exclude-netclasses GND,RF,DIFF,POWER_CRITICAL \
  --jar path/to/verified-freerouting-2.5.0.jar \
  --expected-jar-sha256 <trusted-jar-hash> \
  --output-dir path/to/new-candidate
# Inspect preview. Run same command with --apply only after source/protection review.
```

If the DSN contains `approved-board.rules`, explicitly pass `--rules-file` and `--expected-rules-sha256` or remove that uncontrolled sidecar from the clean, isolated export directory. Never alter an original export to make a hash check pass.

## Promotion gate

Run version-pinned Windows KiCad 10.0.8 + Konnect + Freerouting 2.5.0 integration on multiple independently reviewed boards (including 2/4-layer ordinary nets, existing locked copper, GND plane, narrow-pitch pad escape, mixed power, and high-speed protected groups). Compare before/after unmapped nets, route completion, DRC, preserved object UUIDs, width/clearance, layer usage, vias, differential/thermal constraints, time and manual intervention. Only promote Freerouting to automatic default for the **accepted scope**; retain explicit fallback BLOCKED for unsupported designs.

**Sources**: [Freerouting v2.5.0 CLI](https://github.com/freerouting/freerouting/blob/v2.5.0/docs/command_line_arguments.md), [KiCad integration](https://github.com/freerouting/freerouting/blob/master/integrations/KiCad/README.md), [KiCad PCB design rules](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html).
