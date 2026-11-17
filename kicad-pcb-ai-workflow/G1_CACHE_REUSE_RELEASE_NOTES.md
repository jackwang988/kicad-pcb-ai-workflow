# G1 Cache-First Schematic Review Update

Objective: reuse officially verified manufacturer cards from the current project device bundle instead of downloading and extracting the same datasheet again. The stage-specific brief includes exact part and package, manufacturer revision, source SHA, applicability, cited requirement and locator. `static_review.py` uses matching cached source text where possible; original PDF/figures remain available on demand. `static_review_gate.py` rechecks project and source evidence hashes before considering the packet.

If required card data are absent, version-incompatible or tampered, G1 is blocked and returns to node 03 for source-backed repair. A valid cached statement does not validate a new circuit; actual pin/net topology, native ERC, visual analysis and engineer sign-off are required. Offline fixture tests cover the software reuse contract only.
