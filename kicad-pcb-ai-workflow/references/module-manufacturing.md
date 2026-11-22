# DFX/NPI and Manufacturing Candidate

For a user-requested **engineering export**, read [export lessons](engineering-export-lessons.md): verify a current source snapshot and actual files, identify unresolved procurement/process evidence, and retain `EXPORTED_NOT_RELEASED`. This limited export check does not assert the formal freeze handoff, engineer signatures or factory release gates below have passed. A completed example export must not be described as a complete formal NPI run.

Before any formal manufacturing export, independently validate current G1–G4, netlist/board version, board-house stack-up, effective rules, BOM/CPL variants, pad/polarity, test points, mechanical outline, fabrication/assembly process limits and applicable SI/PI or safety findings. `mass_production_review.py` and `static_review_gate.py` must consume full evidence even if the agent sees a short summary.

Freeze a **new isolated candidate** with the documented Konnect zone-fill/save receipt and independent KiCad CLI reload/DRC. `manufacturing_export.py` may create Gerber, Excellon drill, BOM, CPL and drawings only after relevant gates; bind hashes to exactly the saved source candidate. A successful export means `EXPORTED_NOT_RELEASED`, never automatic factory approval. Real factory CAM, engineering query (EQ), panel/assembly review and production authorization require actual external evidence and human sign-off.

See [DFX/NPI details](dfx-npi.md), [latest workflow](latest-complete-workflow.md) and [stage approvals](stage-approvals.md).
