# Native KiCad Symbol Geometry — Read Before Pre-placement

**Primary source:** KiCad native `.kicad_sch` embedded `lib_symbols` and `.kicad_sym` files. They contain actual symbol primitives, pin connection coordinates/directions and field positions. There is no universal stored width/height property for a complete symbol: the Skill calculates a bounding rectangle from the library's graphic primitives. It must **never invent symbol dimensions**.

## Automatic source lookup

1. **Existing/embedded:** load the exact symbol definition from the selected `.kicad_sch` `lib_symbols` cache (honors the current saved symbol revision).
2. **New, not yet cached:** resolve the matching project `sym-lib-table`; otherwise installed `KICAD10_SYMBOL_DIR`/`KICAD9_SYMBOL_DIR`/`KICAD_SYMBOL_DIR`, local project library or standard KiCad install folders. The user may pass an existing `.kicad_sym` explicitly for a custom/private library. No network, downloads or test boards are needed.
3. **Inherited/multi-unit:** resolve `(extends ...)`, select the requested `(unit ...)` and graphics style, include shared unit-0 graphics and pins. If the required native library or a graphic type is unavailable, report which symbol lacks data and do not fabricate a box.

The extractor computes rectangles, circles, polyline extents, 3-point arcs (including extrema), cubic Bezier extrema, pin stems and pin names/numbers. Native KiCad library uses **+Y upward**; the sheet uses **+Y downward**. Instances apply 0/90/180/270-degree rotation and `mirror x|y`; the pin endpoint and outward direction are transformed with the same mapping. Use exact KiCad pin endpoints for wires, never approximate centers.

## Practical read-only commands

```bash
# Query dimensions and pins BEFORE placing Device:R. Looks up the embedded
# definition or the installed/project symbol library automatically.
python scripts/schematic_native_geometry.py symbol /project \
  --schematic 01_WORKING/main.kicad_sch --lib-id Device:R

# Optional offline geometry snapshot of already placed objects. Only the
# worksheet protected-region contract (not a per-symbol bounding list) is needed.
python scripts/schematic_native_geometry.py snapshot /project \
  --schematic 01_WORKING/main.kicad_sch \
  --protected 03_REPORTS/worksheet-regions.json \
  --output /project/03_REPORTS/native-geometry.json
```

One-time worksheet region example (values must come from actual project worksheet or reviewed KiCad SVG; do not copy arbitrary coordinates to production projects):

```json
{
  "*": [
    {"id":"project-title", "kind":"title_block", "bbox_mm":[220,165,292,207]}
  ]
}
```

For the planner, use **`geometry_mode: "native_auto"`** and **`protected_regions_by_page`** instead of `geometry_manifest`, `geometry_sha256`, `render_file` and a caller-authored `geometry` field on each symbol:

```json
{
  "schema_version": 1,
  "geometry_mode": "native_auto",
  "schematic": "01_WORKING/main.kicad_sch",
  "schematic_sha256": "<sha256 of current schematic>",
  "page": "01_WORKING/main.kicad_sch",
  "protected_regions_by_page": {
    "*": [{"id":"project-title", "kind":"title_block", "bbox_mm":[220,165,292,207]}]
  },
  "topology_file": "03_REPORTS/expected-pin-nets.json",
  "topology_sha256": "<sha256 of independently approved topology>",
  "clearance_mm": 1,
  "symbols": [
    {"ref":"R1", "lib_id":"Device:R", "value":"10k", "unit":1,
     "candidate_positions_mm":[[50.8,63.5],[55.88,63.5]],
     "rotations_deg":[0,90,180,270],
     "labels":[{"pin":"1","kind":"local"}]}
  ]
}
```

This is an **illustrative partial request**; supply the normal independent pin-to-net contract, connection list, routing/label settings and real sheet keepouts before planning. Required per-component input is the **KiCad library identifier, net topology, and optional actual displayed Value / placement zones**—not guessed body/pin geometry. An unspecified `value` inherits the native symbol library `Value` property; the `lib_id` itself is always non-rendered lookup metadata.

## What is exact and what is not

| Quantity | Evidence/precision |
|---|---|
| Supported symbol drawing primitives, coordinates, pin endpoints | Native source-derived, geometric calculations |
| `lib_id` (such as `Device:R`) | **Lookup metadata only; never a visible text object and never a source of collision width.** Changing identifier length must not change the placement bounds. |
| Actual displayed `Reference` (`R1`), `Value` (`10k`) and other visible text | Occupancy counts their shown text, with conservative font estimates; hidden properties are not obstacles. If the prospective instance does not declare `value`, inherit the **native KiCad library `Value` field**, never `lib_id` or its suffix. |
| Actual placed instance origin/rotation/mirror | Native `.kicad_sch` |
| Existing Reference/Value text positions, font sizes, visible/hidden flags | Native `.kicad_sch` metadata |
| **Exact glyph outline** of KiCad's rendered font, especially complex Unicode | **Not guaranteed by text-size metadata.** Use conservative bounds and the real KiCad SVG/PDF during post-write review |
| Custom worksheet title-block extent | Must be sourced from the actual `.kicad_wks` / rendered worksheet and configured once; **not inferred from the symbol library** |
| Electrical correctness | **Not determined by geometry.** Native XML netlist/ERC and G1 review remain required |

### Execution contract

- The native extractor and `schematic.preplacement_plan` are read-only. The planner resolves the real symbol library source at run time and hashes every source file.
- `schematic.preplacement_check` validates the request, symbols, source hashes and solver code hashes without rerunning symbol geometry extraction or A* for an unchanged batch.
- A successfully planned anchor is **not** a verified KiCad edit. Konnect must write the exact library ID, unit, orientation, pin/network identity, field/label positions and actual project revision; compare its saved readback with the plan before advancing.
- Unexpected KiCad font/text rendering, unsupported graphic primitive, third-party library drift, concurrent unsaved editor changes or missing worksheet evidence **cannot be silently approved**. Recalculate only affected module/page after a real edit. Unknown A* results remain an advisory and do not assert an impossible sheet.

This module is not a replacement for KiCad's native renderer, custom worksheet parser or an integrated Konnect schematic transactional write-back. Full live end-to-end acceptance must be performed separately on the target Windows/KiCad/Konnect stack before calling schematic generation production-ready.
