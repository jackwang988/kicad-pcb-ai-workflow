# Optional Six-Group Human Stage Confirmation

Collaboration can use **dialogue** (brief checkpoints in conversation) or **formal_engineering** (immutable recorded review evidence). This selection controls workflow pace, not ERC/DRC, G1–G4 or manufacturer/prod release authority. Actual authorized hardware engineers remain responsible for sign-off.

In formal mode, use `workflow.py stage-prepare PROJECT --bundle BUNDLE --group GROUP --evidence PATH` to generate a new immutable packet. It binds the source project's exact input hashes and previous group packet; status is `ENGINEER_REVIEW_PENDING`. An authorized engineer then supplies an actual review file containing role, name, date, decision, reason and this packet's SHA. Use `stage-confirm` only after that separate real review. Changed source, project version, file hash, tool rules, dependencies or previous stage invalidates affected evidence; create a new packet rather than overriding past approvals.

Dialogue-mode acknowledgement cannot stand in for a formal engineering signature. `stage-check` validates existing approval records; it must never convert missing/changed evidence to PASS.
