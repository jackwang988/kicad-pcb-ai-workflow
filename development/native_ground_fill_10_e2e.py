#!/usr/bin/env python3
"""Real KiCad 10 fixture: GND first pour -> approved via -> refill -> final DRC.

This isolated native test uses the supported KiCad CLI --refill-zones --
save-board workflow. It deliberately avoids KiCad 10 headless pcbnew
SWIG ZONE_FILLER writes, which can segfault on Ubuntu/Windows.
This is NOT general product G4 or manufacturing authorization.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kicad-pcb-ai-workflow" / "scripts"))
from routing_seven_stage import ground_audit, ground_defined_layers, ground_filled_layers, board_snapshot, sha
OUTPUT = Path(os.environ.get("NATIVE_GND_REPORT",
                             "/tmp/r10-native-ground-fill-evidence.json"))
UUID = "00000000-0000-4000-8000-000000000123"


def run(cmd):
    p = subprocess.run([str(v) for v in cmd], capture_output=True, text=True,
                       timeout=240, errors="replace", check=False)
    return {"returncode": p.returncode,
            "stdout_tail": p.stdout[-1800:],
            "stderr_tail": p.stderr[-1800:]}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def add_items(board_file, items):
    source = board_file.read_text(encoding="utf-8")
    stripped = source.rstrip()
    require(stripped.startswith("(kicad_pcb") and stripped.endswith(")"),
            "NATIVE_SOURCE_BOARD_INVALID")
    board_file.write_text(stripped[:-1] + "\n" +
                          "\n".join(items) + "\n)\n", encoding="utf-8")


def zone(layer):
    return f'''(zone (net 2) (net_name "GND") (layer "{layer}")
      (uuid "{'00000000-0000-4000-8000-000000000010' if layer=="F.Cu" else '00000000-0000-4000-8000-000000000011'}")
      (hatch edge 0.5)
      (connect_pads (clearance 0.25))
      (min_thickness 0.2)
      (fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3))
      (polygon (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19))))'''


def refill_first_then_drc(cli, board, out):
    # KiCad fills zones BEFORE the integrated diagnostic check, then saves.
    # These first two checks are fill operations, not final G4 acceptance.
    result = run([cli, "pcb", "drc", "--refill-zones", "--save-board",
                  "--format", "json", "--output", out, board])
    require(out.is_file() and out.stat().st_size > 0 and
            result["returncode"] == 0, "NATIVE_KICAD_CLI_REFILL_FAILED")
    return result


def main():
    evidence = {"status": "BLOCKED", "g4_approved": False,
                "manufacturing_authorized": False,
                "scope": "isolated_two_layer_GND_real_kicad_cli"}
    try:
        cli = shutil.which("kicad-cli")
        require(cli, "REAL_KICAD_CLI_MISSING")
        version = run([cli, "version"])
        require(version["returncode"] == 0
                and version["stdout_tail"].strip().startswith("10."),
                "REAL_KICAD_10_REQUIRED")
        with tempfile.TemporaryDirectory(prefix="r10-native-ground-") as td:
            folder = Path(td)
            original = ROOT / "development/fixtures/npi-demo/npi-demo.kicad_pcb"
            pre = folder / "routed.kicad_pcb"
            shutil.copy2(original, pre)
            first = folder / "first-fill.kicad_pcb"
            shutil.copy2(pre, first)
            add_items(first, [zone("F.Cu"), zone("B.Cu")])
            first_receipt = refill_first_then_drc(
                cli, first, folder / "first-pour-diagnostic.json")
            evidence["first_native_fill"] = first_receipt
            first_snapshot = board_snapshot(first)
            require({"F.Cu","B.Cu"} <= ground_defined_layers(first_snapshot, "GND"),
                    "GROUND_FIRST_FILL_ZONES_MISSING")
            evidence["first_filled_layers"] = sorted(
                ground_filled_layers(first_snapshot, "GND"))

            # A single approved GND stitching via for this specific 2-layer
            # test fixture; never create uncontrolled grids in real projects.
            stitched = folder / "stitch-saved.kicad_pcb"
            shutil.copy2(first, stitched)
            add_items(stitched, [
                '(via (at 5 15) (size 0.6) (drill 0.3) '
                '(layers "F.Cu" "B.Cu") (net 2) '
                f'(uuid "{UUID}"))'
            ])
            st = board_snapshot(stitched)
            require(any(v['id'] == UUID and v['net'] == 'GND'
                        for v in st['vias']), "NATIVE_GND_STITCH_MISSING")
            final = folder / "final-refill.kicad_pcb"
            shutil.copy2(stitched, final)
            second_receipt = refill_first_then_drc(
                cli, final, folder / "refill-diagnostic.json")
            evidence["post_via_native_refill"] = second_receipt

            bindings = lambda p: {"file": p.name, "sha256": sha(p)}
            cfg = {
                "schema_version": 1, "stage": "ground",
                "pre_ground_board": bindings(pre),
                "first_filled_board": bindings(first),
                "stitched_board": bindings(stitched),
                "final_refilled_board": bindings(final),
                "copper_layer_stack": ["F.Cu","B.Cu"],
                "gnd_zone_layers": {"GND":["F.Cu","B.Cu"]},
                "approved_stitching_vias": [{
                    "uuid": UUID, "net":"GND", "at_mm":[5,15],
                    "layers":["F.Cu","B.Cu"],
                    "ground_contact_layers":["F.Cu","B.Cu"],
                    "min_diameter_mm":0.6,"min_drill_mm":0.3,
                    "purpose":"Reviewed two-layer GND plane contact"}]
            }
            conf = folder / "ground.json"
            conf.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            receipt = ground_audit(folder, conf.name)
            require(receipt["status"] ==
                    "GROUND_FILLED_STITCHING_AUDITED_READY_FOR_NATIVE_DRC",
                    "GROUND_GEOMETRY_PRE_DRC_GATE_BLOCKED")
            evidence["ground_pre_drc_gate"] = receipt

            # FINAL DRC is run only after actual first fill, GND via insertion,
            # second refill and passing the ground stage checkpoint gate.
            drc = folder / "final-postground-drc.json"
            final_cmd = run([cli,"pcb","drc","--refill-zones","--save-board",
                             "--format","json","--output",drc,final])
            require(drc.is_file() and final_cmd["returncode"] == 0,
                    "NATIVE_FINAL_DRC_TOOL_FAILED")
            data = json.loads(drc.read_text(encoding="utf-8"))
            require(isinstance(data.get("violations"),list)
                    and isinstance(data.get("unconnected_items"),list),
                    "NATIVE_FINAL_DRC_JSON_INVALID")
            evidence["native_postground_drc"] = {
                "exit_code": final_cmd["returncode"],
                "saved_board_sha256": sha(final),
                "report_sha256": sha(drc),
                "violations": len(data["violations"]),
                "unconnected_items": len(data["unconnected_items"]),
                "status": "NATIVE_DRC_EXECUTED_NOT_AUTOMATICALLY_CLEAN",
            }
            evidence["status"] = "REAL_GND_FIRST_FILL_STITCH_REFILL_DRC_EXECUTED_NOT_G4"
    except Exception as exc:
        evidence["reason"] = str(exc)
        evidence["traceback"] = traceback.format_exc()[-4800:]
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+"\n",
                          encoding="utf-8")
        print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0 if evidence["status"].startswith("REAL_GND_") else 2


if __name__ == "__main__":
    sys.exit(main())
