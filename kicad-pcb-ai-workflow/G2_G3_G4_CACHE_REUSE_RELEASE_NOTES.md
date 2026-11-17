# G2/G3/G4 Stage-Specific Manufacturer Knowledge Reuse

This extension reuses node 03 project-frozen manufacturer evidence at the symbol/footprint gate G2, placement gate G3 and final PCB gate G4. G2 loads pinout/pad/land-pattern knowledge and checks current resource identity; G3 loads layout, oscillator, RF, decoupling and return-loop rules against the current board and its actual core components; G4 loads reference-plane, critical-net and fanout constraints and binds the current saved board/native findings. Source hash changes or missing current-stage categories block the relevant gate.

Separate native design and human engineering approval remain mandatory. Knowledge reuse never automatically proves electrical correctness, safe routing, actual copper fill, factory capability or PCB production acceptance. Tests for this stage were software fixture tests; live end-to-end KiCad/Konnect acceptance is separate.
