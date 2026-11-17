# R10 Workspace Lifecycle and Context Budget Policy

## Purpose and limits

Keep one identifiable working KiCad project and reduce repeated context ingestion without weakening G1–G4 or the final manufacturing controls. `workspace_manager.py` indexes project files and immutable evidence; it does not silently create circuits, invoke Konnect, run KiCad CLI, move historic directories, purge files or grant any engineering approval.

## Canonical project layout

```text
PROJECT_ROOT/
  01_WORKING/                 One actively edited KiCad project
    main.kicad_pro
    main.kicad_sch
    main.kicad_pcb             Optional during schematic-only work
  02_CHECKPOINTS/             Explicit immutable milestone copies
  03_REPORTS/                 Immutable ERC/DRC and G1-G4 evidence
    index/                    References and hashes, not report duplicates
  04_RELEASE/                 Immutable manufacturing candidates
  CURRENT_PROJECT.json        Authoritative project location and revision
```

For an existing project, first make a separate backup and confirm the chosen complete KiCad project and all referenced libraries. Place it under `01_WORKING` deliberately and run workspace initialization. Never infer the authoritative project from the newest modification time. Historical projects outside this convention keep their old non-overwrite safeguards; the new index never authorizes blind replacement.

## When to create a candidate

Create a candidate only for first-time generation, an explicit branch, irreversible/high-risk fixture work, a named engineering checkpoint, or the manufacturing freeze. Within an authorized working session, regular part movement, wiring and component edits operate on the *same* KiCad project. Verify target path, UUID/net/footprint identities and pre/post hashes; use appropriate Konnect risk acceptance and read-back. Build one configuration bundle and reuse it while its source, tool and rule fingerprints remain valid. New review packets are immutable under `03_REPORTS`; store the report hash and project revision in the index.

Manufacturing freeze must not recursively copy `02_CHECKPOINTS`, `03_REPORTS`, `04_RELEASE`, prior candidates, repositories or other historical trees. Confirm that the copied source schematic, PCB, project settings and required relative library assets remain intact. Preserve all historical files; never automatically delete or move them.

## CLI

```bash
python scripts/workflow.py workspace /project --action init --project-file 01_WORKING/main.kicad_pro --apply
python scripts/workflow.py workspace /project --action status
python scripts/workflow.py workspace /project --action checkpoint --label G1-approved --apply
python scripts/workflow.py workspace /project --action register --stage G1 --artifact 03_REPORTS/G1-r1/packet.json --apply
python scripts/workflow.py workspace /project --action index --stage G1
python scripts/workflow.py workspace /project --action inventory --limit 20
python scripts/workflow.py status /project --bundle control-r1 --format compact
```

## AI context rules and measurement

1. Read `SKILL.md` and one selected module. Read full workflow, DFX, high-speed and manufacturing references only when the task requires them. Do not load all toolsets for a simple operation.
2. Keep original source PDFs, netlists, native ERC/DRC output and complete review packets on disk. Provide AI with bounded `checks_summary`, artifact paths, selected current-stage device card excerpts and hashes first. Read full evidence for exact affected nets, pins, source pages, high-risk findings or exceptions.
3. Konnect discovery must remain dynamically complete; a task should load only the necessary toolset. Reuse valid build/schema-bound capability records.
4. `workflow status --format compact` shows counts and the highest-priority missing items. Switch to JSON output for complete debugging.
5. `token_budget.py --input REPORT --limit 6` prioritizes failed/blocked findings and displays total omitted counts; it must never relabel hidden failures as PASS. Gates always process the full original evidence.
6. Only the model host's actual usage statistics can establish saved input/output tokens. File byte/character counts are proxy metrics, not a reliable universal conversion; English is not automatically cheaper for every tokenizer.

## Acceptance and rollback

Ten sequential small edits should keep one working project; checkpoint creation must require an explicit action. Failure, ambiguous source identity, or unsaved conflicting GUI state must block further writes. New instruction or rules revisions may invalidate old bundle hashes; rebuild the affected snapshots rather than replacing signed records. Preserve full audit trails and require genuine KiCad/Konnect end-to-end testing before claiming completed live editing.
