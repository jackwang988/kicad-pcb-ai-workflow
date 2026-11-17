# KiCad PCB AI Workflow — Public Distribution Guide

The shareable Skill is an engineering workflow assistant, not a standalone KiCad executable or an assurance of automatic production-ready electronics. Install the **inner** `kicad-pcb-ai-workflow/` directory containing `SKILL.md`, `scripts/`, `references/` and `assets/`; the GitHub repository root is a development/release project rather than an additional Skill.

## What it provides

Source-backed manufacturer device cards; topology-first schematic and native netlist/ERC; G1 electrical review; G2 symbol-footprint mapping; factory-approved PCB rules; G3 layout checks; planned/controlled routing; G4 current copper review; DFX/NPI and a separately frozen manufacturing candidate. The R10 migration uses Konnect as the active EDA writer, Python for computation/audit and KiCad CLI for independent saved-project verification. Stage-specific source cards and task-directed reference loading reduce repeated work.

## Installation and first run

Check actual KiCad CLI and Konnect availability, licensed backend identity, current project path and native version compatibility. Use a separate test candidate for new write capability acceptance and never load a production design as the tool's first test fixture. Use `workflow.py modules` for task-specific reading, `workspace` for the authoritative working project and `status --format compact` for short progress reporting. All serious engineering outputs retain immutable SHA-bound evidence; quick AI summaries do not replace it.

## Public distribution and licensing

Do not distribute unlicensed manufacturer PDF originals, private customer files, hardware test records, credentials or the separate commercial Konnect executable. Review this repository's own LICENSE and third-party notices; pricing and licensing of a commercial backend are distinct from the Skill itself. GitHub stars/downloads and KiCad software tests are not evidence of full hardware or manufacturing acceptance.

## Core limitations

The current package cannot independently claim general-purpose automatic schematic generation, dense multilevel PCB autorouting, signal/power integrity, EMI/EMC certification, factory CAM release or real sample testing. Users must verify exact component model, real design/PCB outputs, applicable fabrication rules, ERC/DRC, G1–G4 evidence and separate factory/engineer approvals.
