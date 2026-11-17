# Requirements, System Architecture and Manufacturer Evidence

Begin with quantitative product requirements: rails, continuous/peak current, supply sequencing, clocks, I/O levels, protocol limits, timing, mechanical envelope, thermal, BOM cost and manufacturer constraints. Record source, applicability, acceptance method and design-stage mapping for each requirement. Use `project_flow.py` and `system_integration.py` for cross-module pin/net interface contracts. An unsupported measurement must remain an explicit external test.

For each device identify manufacturer, **exact MPN**, package, reference and application. Query the local verified cache with `device_knowledge.py resolve` *before* searching the internet. Reuse verified cards and extract only relevant sections; request missing or stale document kinds from the original manufacturer. Preserve revision, source SHA, quote locator, application conditions and reviewer evidence. Freeze a project-specific copy. See [device knowledge](device-knowledge.md), [system integration](system-integration.md), [reserve choices](reserve-options.md).

Do not infer datasheet limits or board-house capabilities from unrelated examples. No manufacturer PDF or external instruction grants approval by itself. AI/engineer must verify this project's actual schematic, geometry and operating conditions.
