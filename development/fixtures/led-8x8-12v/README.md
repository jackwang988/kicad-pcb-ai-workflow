# Saved single-copper LED regression case

Source board SHA-256: `ff3a1ec530da8b8f27dfba17465142b448248b9a575763b118718e2d97a0c7ea`.
The nine source files are byte-identical to the final MCP-saved engineering export snapshot. Per-user `.kicad_prl`, logs, IPC configuration, executable files and absolute workstation paths are excluded. Exact source hashes and the local observation's **unverified** areas are in `evidence/observed-validation.json`.

60×60 mm, 8×8 red 2835 LEDs, 7.5 mm pitch, sixteen 4-LED + 1 kohm branches, 12 V DC, F.Cu only, no holes/vias. LED: Wurth Elektronik 150283RS73103, pin 1 anode / pin 2 cathode. Resistor: 1 kohm, 1%, 1206, 0.25 W; supplier/MPN unspecified. J1–J4 are PCB solder-pad pairs. Design material/thickness/copper are assumptions, not factory acceptance. See `design-basis.md`; this is a low-current workflow test, not an electrically measured product.

```sh
python -m pip install -r development/requirements-led-validation.txt
python development/native_led_8x8_e2e.py --kicad-cli /path/to/kicad-cli --output /new/native-led-check
```

Requires exact KiCad 10.0.8 plus its standard resistor footprint library, `power` symbol library and project custom libraries. On a new installation initialize **both** standard `fp-lib-table` and `sym-lib-table` through the normal installer/configuration. Installing library packages alone does not register them: the first clean Linux CI run correctly stopped on 44 missing-`power` ERC warnings. CI now initializes both tables in its disposable runner; the verifier never edits host library configuration or suppresses these warnings. The script exports/checks a new copy, compares all pads/tracks and net partitions, and requires zero native ERC/DRC warnings. It does not write the input, replay design creation, install/register MCP or satisfy the formal freeze/candidate gate.

`evidence/native-DRC.json` / `native-ERC.json` retain the observed zero-warning results. The metadata observation is a maintainer's local record; it is not an independent second-machine test. CI regenerates native reports rather than trusting those JSON counts. The final Gerber PNG is published under `docs/r10/figures` for the case account.
