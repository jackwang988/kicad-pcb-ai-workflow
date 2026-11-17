# Konnect-EDA Historical Local Fixture Evidence

This file summarizes **bounded historical records**, not universal acceptance of every discovered MCP tool. The sampled environment was Windows x64, KiCad 10.0.8 and a specific locally installed Konnect-EDA release. Reported tool counts vary with backend build and loaded toolsets; only the **actual currently discovered schemas** are relevant.

Small representative tests included connection, a limited part move/rotation, selected schematic symbol/field/net actions, simplified schematic-to-PCB synchronization, single-net routing rejection/acceptance cases and controlled export candidates. Complex hierarchical schematics, fully automated multilevel routing, sophisticated custom pad/zone geometry, SI/PI and industrial DFX/NPI require separate accepted fixtures and current-project native checks.

The R10 policy is dynamic discovery + L0–L3 risk + scope-bound acceptance. Do not move an acceptance record across executable SHA, KiCad version, input schema, object type or operation range without evidence. See [Konnect migration](konnect-capability-migration.md).
