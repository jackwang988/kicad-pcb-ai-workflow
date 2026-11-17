# R10 Cache-First Device Knowledge: Node 03 and G1

Node 03 first queries the persistent verified registry using manufacturer + exact MPN + package and selected document kinds. A true cache hit reuses source cards, extracted text and original provenance; absent/stale materials require targeted official-source review. `AMBIGUOUS` and invalid cache entries block rather than silently selecting a similar component.

G1 (node 06) reads the same project-frozen bundle prepared at node 03. The static review packet includes a concise device-knowledge brief and referenced cached extraction, avoiding redundant downloads and full-PDF context. When figures, note qualifiers, operating modes or mismatches matter, consult the frozen original source at its exact locator.

This changes source reuse, not project engineering acceptance. Current schematic/netlist/ERC, engineer review, source hashes and all gates remain mandatory. Offline tests cannot establish an independent true-hardware or manufacturing certificate.
