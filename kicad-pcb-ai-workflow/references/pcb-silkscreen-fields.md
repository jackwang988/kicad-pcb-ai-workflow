# Placed-field and silkscreen repair (case-tested, 2026-11-21)

Read this when final DRC reports `silk_over_copper`, `silk_overlap`, or `footprint_symbol_field_mismatch`. These are different checks: repairing artwork alone does not synchronize component metadata.

## Discover the actual writer

Stock Konnect 0.13.0 and the inspected official 0.14.1 expose `edit_component` for **value only**. Their `update_pcb_from_schematic` may report a no-op while custom fields remain missing. `update_footprints_from_library` preserves instance field positions/styles; refreshing a library is not a placed-reference repair. Inspect the running input schema instead of inferring capability from the tool name.

The Windows LED case required the **open-source** 0.13.0 companion tool `set_placed_footprint_fields`. Its source, exact base archive hashes, license and preparation command are in the repository's [companion extension](https://github.com/jackwang988/kicad-pcb-ai-workflow/tree/main/development/konnect-field-extension). It is not bundled into the installed Skill or the commercial 0.14.1 binary. Never patch/reverse-engineer the commercial binary or automatically switch backends. Missing field capability means report the specific unsupported operation; do not use direct pcbnew/file writes as a hidden fallback.

## Repair loop

1. Bind the current live board, executable/build, KiCad version and discovered schema. Preserve a saved checkpoint and all original DRC evidence. Compare footprint UUIDs, positions, pad geometry/nets, tracks, vias, zones, rules and exclusions.
2. Resolve every warning to its actual owner/UUID. Distinguish a footprint reference, a footprint line, a board note, and an exposed pad. Plan using **native pad/mask/graphic/text geometry**, including neighboring connectors. Reserve a separate reference-text area when first placing footprints; a body/courtyard reserve alone is insufficient.
3. Prefer visible, readable instance references outside mask openings. Keep orientation/placement of the physical part and its polarity marks. Font size and stroke must satisfy the actual project/factory constraints; the example used 0.8 mm / 0.12 mm, not a universal default. Search local text positions; connector-adjacent references may need inward offsets rather than a uniform grid. Move colliding board notes separately by exact observed UUID and preserve their contents.
4. Synchronize all intended schematic fields, **including Datasheet and Description**, not just MPN/manufacturer/package/specification. KiCad can report only the first mismatch per footprint: a constant warning count can conceal a newly exposed next mismatch. Compare every final value against the authoritative schematic. PCB solder-pad features and purchasable parts have different BOM roles.
5. The companion tool uses a dry-run revision bound to current typed footprints and requested changes. Apply only that revision, update parent footprints in one undo commit, preserve every non-field protobuf member, and verify fresh readback of all fields. Its tested scope assumes the four mandatory fields exist; other structures require separate acceptance. Start with one footprint, save, check native geometry and complete DRC, then expand to the reviewed set. A timeout/unconfirmed readback stops further edits until actual state is inspected.
6. After saving, independently audit the **saved file**, not just an MCP success reply. Check complete ERC/DRC including schematic parity and unconnected items. Confirm reference readability in a real native render and verify geometry/net/rule/exclusion preservation. Do not hide references, delete schematic fields, disable categories or add exclusions to manufacture a clean result.

## Saved project settings can be stale

Some Konnect design-rule tools edit the project file while KiCad retains cached Board Setup values. A later `save_project` can overwrite those values. Read effective saved rules **after the last GUI/MCP save**. Reconcile cached state before more design edits; if live reload is unavailable, bind engineering exports to the verified immutable snapshot and require renewed checks after any later save. Reapplying values once does not prove future GUI saves are safe, and library refresh is not a rule-cache fix.

## What the example proves

The [published case and detailed account](https://github.com/jackwang988/kicad-pcb-ai-workflow/blob/main/docs/r10/07-led-e2e-and-silkscreen.md) records 135 mask/silk warnings, 64 silk overlaps and 80 field mismatches reduced to zero; 84 references and 376 field values were checked. All 205 tracks, 168 pads, part placements and filled GND copper were preserved. D5/D61 needed special offsets around side power pads. Those reference names/coordinates are example-specific and must not become general placement rules.

This is one native Windows/KiCad 10.0.8 case, not universal field-tool acceptance or hardware approval. Use explicit local enrollment for a self-built executable; a different binary hash/schema requires relevant first-use checks. See [capability migration](konnect-capability-migration.md).
