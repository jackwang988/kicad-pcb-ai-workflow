# Environment Setup and Daily Operation

## Prerequisites

Use a real KiCad installation and `kicad-cli` compatible with the target project; a separately licensed, locally enrolled Konnect MCP executable and accessible KiCad editor are required **only** for live operations. Python standard-library scripts work in an isolated interpreter; source PDF text extraction may need `pdftotext`. Do not install a random `pcbnew` wheel from PyPI as a substitute for KiCad's matching legacy Python binding. During the single-writer migration, old `pcbnew` can be optional for certain read-only audits, but it is not an authorized board writer.

## First installation and smoke tests

Confirm actual OS, install path, CLI version, KiCad application version, executable SHA-256, Konnect backend build and license. For stable KiCad 10.x, run native smoke on a real independent, nonempty project candidate and check schematic XML/PDF, ERC/DRC, PCB reload and manufacturing command availability as required by the task. For KiCad 11+ do not assume old SWIG `pcbnew` is available: the CLI-only smoke may permit bounded source tasks, not automatically PCB write/freeze/manufacturing approval. KiCad 9 has separate limited compatibility status unless independently validated. Future release numbers alone do not prove compatibility.

```bash
# Read-only environment diagnosis without creating an engineering project.
python scripts/workflow.py run /project --task environment.doctor
# Setup requires a real independent project and, for mutations, explicit --apply.
python scripts/workflow.py run /project --task environment.setup --cli-only
# See actual supported arguments for the installed version.
python scripts/environment_start.py --help
```

## Daily work (minimum necessary calls)

For routine MCP availability, try one supported protocol ping or lightweight read; for real KiCad project connection try a single `open_project` query with the expected board path. Stop on success. Do not automatically relaunch software, install a plugin, open new test boards, discover all 200+ tools, screenshot the desktop or run DRC for a connection ping. If connection fails, inspect the returned failure class, then perform one targeted diagnostic before attempting a change.

When editing, read the workspace index and ensure `01_WORKING` is the authorized project. Konnect operation acceptance is stored separately from an environment smoke, and a saved current project needs its own native validation. Re-run setup after changes in CLI executable, service build, connection credentials/target board, project schema or rules that invalidate relevant prior evidence. Never copy another user's startup-state file or human approval record.

## Debugging and cross-platform notes

Use actual local KiCad and Python paths for Windows PowerShell, Linux or macOS. Do not invent platform directories; check installed binaries using `--version`/`--help` and the user-provided installation. Different interpreters, nightly/RC versions and mixed KiCad libraries require explicit separate testing. Commands and export/report schemas may differ between releases. If a required capability is absent, state the exact scope of the block rather than pretending that an offline mock passed real native validation.

Related: [environment module](module-environment.md), [Konnect backend](konnect-backend.md), [workspace policy](workspace-and-token-policy.md), [KiCad-native verification](static-ai-review.md).
