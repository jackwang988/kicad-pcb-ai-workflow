# Engineering export checks learned from the single-copper LED case

Use this for a user-requested Gerber/BOM engineering export from an already routed project. Distinguish an immutable export snapshot from the formal Konnect candidate refill/freeze handoff. Native checks and file hashes do not create missing G1–G4 engineer signatures, factory evidence, or a `freeze_candidate.py` PASS. Keep exports `EXPORTED_NOT_RELEASED`. Formal manufacturing/release still follows [DFX/NPI](dfx-npi.md) and [manufacturing](module-manufacturing.md).

The current generic `manufacturing_export.py` selects every logical copper layer plus front/back mask. It is **not** the accepted single-copper engineering-export path for this two-logical-layer source. Use the discovered MCP `export_gerber` with the reviewed explicit layer list for that limited task; do not claim the formal exporter supports a physical-layer override until separately implemented and tested.

## Bind the exact source

Check the registered working project, current native ERC/DRC (all categories, parity, unconnected), endpoint topology, device/pad polarity, actual rules and saved filled GND geometry. A field-only edit can reuse fill evidence only with a source-bound audit proving copper unchanged; copper/pad/zone edits require refill and renewed connectivity checks. Preserve an independent source snapshot and record hashes before and after every export. Export through the actual discovered MCP schemas; do not edit the active board while packaging results.

## Physical copper count and native metadata differ

KiCad may retain two logical copper layers even when the user requests one physical copper side. Verify absence of backside pads/tracks/zones/vias and select **explicit** output layers for that design. For the tested example these were F.Cu, F.Mask, F.SilkS, Edge.Cuts, plus optional F.Paste for assembly. Do not automatically use that list for other boards.

Inspect `.gbrjob`: the example's automatic job declared two layers, a 60.05 mm graphic size and default 0.2 mm class clearances despite the 60 mm finished profile and stricter custom rules. It was retained as raw evidence, excluded from the single-copper fabrication ZIP, and replaced by explicit delivery instructions—not silently rewritten. Inspect Gerber FileFunction attributes and each ZIP member. An outline's plotting stroke expands its bounding box: verify the **closed machining centerline**, not only rendered extents. A 0.05 mm profile pen around a 60 mm square yields a 60.05 mm graphic bounding box.

An all-SMD board can legitimately produce empty PTH/NPTH drill files. Parse and count actual holes. The example kept the two native files in raw evidence and omitted them from its zero-hole fabrication ZIP. Do not remove real drill data on another design.

## BOM, mask and paste agree with actual objects

Export explicit fields: Reference, `${QUANTITY}`, Value, Footprint, Manufacturer, MPN, Specification, Datasheet and Description. Expand reference ranges and check duplicates, counts and schematic/board membership. Preserve native individual/grouped BOMs. A derived purchasing BOM can exclude integral PCB solder pads while listing them separately; do not invent connector parts, MPNs or supplier IDs.

The example has 84 references: 64 LEDs + 16 resistors + four PCB pad pairs. Purchasing BOM = 80 components; copper/mask = 168 pads/openings; paste = 160 apertures because the eight power solder pads have no paste. The resistor has a specification but no selected manufacturer/MPN: export that fact instead of claiming procurement approval. LED package alone does not determine color/Vf/polarity.

## Validate files, not just successful subprocesses

Check Gerber units, layer functions, closed outline, every copper pad position/bounds, every track endpoint/width, filled regions, mask/paste apertures and drill count against the saved source. Independently parse/render the actual plotted files and visually inspect orientation, pad registration, references and supply polarity. Retain parser warnings with an explicit disposition; never blanket-suppress them. The observed unused RoundRect parameter warning did not change the 168 pad bounds, which were separately checked. This is not factory CAM sign-off.

Build a fresh ZIP, test CRCs and compare every member to the exported bytes. Include file hashes and a source manifest. A later design save invalidates the snapshot's relationship to current source until renewed checks. Missing evidence must remain visible; a readable PNG or nonempty ZIP alone is not manufacturing acceptance.
