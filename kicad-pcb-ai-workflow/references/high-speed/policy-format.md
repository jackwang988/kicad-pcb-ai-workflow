# High-Speed and PI Evidence: Policy Schema and Boundaries

The policy is a finite, source-backed engineering contract (`schema_version=1`) and must describe the *actual* project/board revision, interface and frequency/edge conditions, approved stack-up/copper/dielectric parameters, reference planes, impedance/timing constraints, power rail ripple/transient limits, scope and sources. Missing required constraints remain `NEEDS_EVIDENCE`/BLOCKED; a bus-name heuristic must not silently invent a default target.

## Policy and evidence

- **Policy facts:** Source identity/issuer, version, actual board/net names, exact applicable protocol/PHY and manufacturer conditions; current input SHA and allowed analysis type.
- **Budget:** When applicable, provide target characteristic/differential impedance and tolerance, diff P/N pairing, setup/hold or skew time budget, propagation delay based on real stack-up, via and reference-layer constraints, crosstalk or attenuation budget.
- **PDN:** Supply and transient current, allowable ripple, decoupling ESR/ESL/C effective under bias/temperature, target frequency range and validated solver/model conditions.
- **Evidence:** Save source hashes, board/solver/tool version, input/output fingerprint, calculated result and stated limitations. External simulation or test evidence must be independently obtained; a path string alone cannot prove that it exists or is valid.

A deterministic Python screening result cannot replace a 2D/3D field solve, accurate complex geometry, actual stack-up read-back, hardware EMI/EMC tests or engineer approval. Tools perform only the explicitly implemented predicates described by the policy and their independent review reports. For detailed rule list see [high-speed/rules.json](rules.json), and for sources see [source registry](source_registry.json).
