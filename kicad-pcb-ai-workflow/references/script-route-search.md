# Experimental Offline Grid/A* Routing Search

The Python route-search module is a **candidate path algorithm**, not a KiCad PCB writing backend. It models specified pads/net endpoints, obstacles, board edges/keepouts and inter-layer transitions on a chosen grid, then searches for bounded routes. It requires explicit layer maps, routing widths/clearances, via drill/diameter, coordinates, grid step, allowed-net classes and protected copper. Do not silently infer real manufacturing constraints from a schematic.

Actual path safety requires KiCad native geometry and DRC beyond a grid approximation: arc and pad shape, exact clearance, stack-up, via rules, electrical return, impedance/length/phase, manufacturing tolerances and existing routing. Detected candidate failure, budget limit or unsupported rule must be distinguished from a successful *applied and validated* KiCad route.

The route-plan output can be used by AI to select a validated Konnect operation, but only Konnect writes the active board. Independently read back the actual net/track/via objects, save/reload and run DRC and G4. Do not call the experimental search an autorouter or treat its JSON as native copper.

For exact current arguments, run `python scripts/script_route_search.py --help` and inspect [routing policy](constraint-routing.md).
