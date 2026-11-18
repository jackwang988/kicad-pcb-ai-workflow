# Source-Backed Reserve Options, DNP and Testability

Reserve components only for a justified electrical, sourcing, assembly or diagnostic purpose. A 0-ohm link, DNP footprint, alternative selector, jumper or series component is not automatically harmless. Record required/optional status, rationale, reference designator(s), exact default fitted state and value/MPN, alternate variants, mutual exclusion rules and actual switching/protection implications.

## Three-phase review

**Schematic:** Verify topology, normally fitted and DNP states, electrical limits and sources; check whether a 0-ohm replacement would defeat feedback, current limiting, impedance matching, filtering or safety. **Layout:** Confirm actual footprint/pads exist, residual stubs, return loops, sensitive RF/clock/high-speed effects, current ampacity, mechanical/courtyard access and testability. **Production:** Verify selected assembly BOM/CPL, DNP/fitted/MPN consistency, mutually exclusive fitted-count bounds and real engineering disposition. A removed placeholder should not still appear in the schematic, PCB or BOM.

`reserve_review.py` checks bounded structural contracts; it cannot replace source-based electrical safety or SI/EMC assessment. Any omitted safety evidence, invalid alternative, stale board SHA, absent variant proof or mismatch is a blocking or tracked issue by risk class. Do not silently substitute alternative parts or use a zero-ohm resistor as an unreviewed electrical component.

See [engineering rules](engineering-rules.md), [design intent](design-intent.md) and [manufacturing](dfx-npi.md).
