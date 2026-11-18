#!/usr/bin/env python3
"""REAL KiCad 10 isolated GND first-fill → via → refill → full native DRC.

Fixture-only acceptance test: never edits a user's live EDA PCB, and
does not grant final engineering G4 or manufacturing authorization.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kicad-pcb-ai-workflow" / "scripts"))
from routing_seven_stage import board_snapshot, ground_audit, ground_filled_layers, sha

OUTPUT = Path(os.environ.get("NATIVE_GND_REPORT", "/tmp/r10-native-ground-fill-evidence.json"))


def run(command):
    p = subprocess.run([str(x) for x in command], capture_output=True,
                       text=True, errors="replace", timeout=240, check=False)
    return {"returncode": p.returncode, "stdout_tail": p.stdout[-2000:],
            "stderr_tail": p.stderr[-2000:]}


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def main():
    evidence = {"status": "BLOCKED", "g4_approved": False,
                "manufacturing_authorized": False,
                "scope": "isolated_two_layer_native_ground_plane_gate"}
    try:
        import pcbnew
        cli = shutil.which("kicad-cli")
        require(cli is not None and "10." in str(pcbnew.GetBuildVersion()),
                "REAL_KICAD_10_REQUIRED")
        with tempfile.TemporaryDirectory(prefix="r10-native-ground-") as td:
            folder = Path(td)
            initial = ROOT / "development/fixtures/npi-demo/npi-demo.kicad_pcb"
            pre = folder / "routed.kicad_pcb"
            shutil.copy2(initial, pre)
            board = pcbnew.LoadBoard(str(pre))
            require(board is not None, "REAL_KICAD_BOARD_LOAD_FAILED")
            require(int(board.GetNetcodeFromNetname("GND")) == 2,
                    "GROUND_NET_CODE_NOT_FOUND")
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                zone = pcbnew.ZONE(board)
                zone.SetLayer(layer)
                zone.SetNetCode(2)
                polygon = pcbnew.SHAPE_POLY_SET()
                polygon.NewOutline()
                for x, y in ((1, 1), (29, 1), (29, 19), (1, 19)):
                    polygon.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
                zone.SetOutline(polygon)
                board.Add(zone)
            fill = pcbnew.ZONE_FILLER(board)
            require(fill.Fill(board.Zones()) is not False,
                    "NATIVE_GND_INITIAL_FILL_FAILED")
            first = folder / "initial-filled.kicad_pcb"
            pcbnew.SaveBoard(str(first), board)
            first_loaded = board_snapshot(first)
            evidence["first_filled_ground_layers"] = sorted(
                ground_filled_layers(first_loaded, "GND"))
            # Approved geometry is a named, reviewed location inside the
            # native fixture. This is not generic automatic via placement.
            board = pcbnew.LoadBoard(str(first))
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(5), pcbnew.FromMM(15)))
            via.SetWidth(pcbnew.FromMM(0.6))
            via.SetDrill(pcbnew.FromMM(0.3))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNetCode(2)
            board.Add(via)
            stitched = folder / "stitch-saved.kicad_pcb"
            pcbnew.SaveBoard(str(stitched), board)
            after_vias = [x for x in board_snapshot(stitched)['vias']
                          if x['net'] == "GND"]
            require(len(after_vias) == 1 and after_vias[0]['id'],
                    "REAL_STITCH_VIA_MISSING_OR_AMBIGUOUS")
            approved_uuid = after_vias[0]['id']
            # Refill *again* after adding the GND via. Only this snapshot
            # can advance to the actual native G4 DRC call.
            board = pcbnew.LoadBoard(str(stitched))
            require(pcbnew.ZONE_FILLER(board).Fill(board.Zones()) is not False,
                    "NATIVE_GND_SECOND_FILL_FAILED")
            final = folder / "after-stitch-refill.kicad_pcb"
            pcbnew.SaveBoard(str(final), board)
            binds = lambda p: {"file":p.name, "sha256":sha(p)}
            config = {
                "schema_version":1, "stage":"ground",
                "pre_ground_board":binds(pre),
                "first_filled_board":binds(first),
                "stitched_board":binds(stitched),
                "final_refilled_board":binds(final),
                "gnd_zone_layers":{"GND":["F.Cu","B.Cu"]},
                "copper_layer_stack":["F.Cu","B.Cu"],
                "approved_stitching_vias":[{
                    "uuid":approved_uuid, "net":"GND", "at_mm":[5,15],
                    "layers":["F.Cu","B.Cu"],
                    "ground_contact_layers":["F.Cu","B.Cu"],
                    "min_diameter_mm":0.6, "min_drill_mm":0.3,
                    "purpose":"Approved 2-layer GND plane interconnection in isolated fixture"}],
            }
            configpath = folder / "ground-config.json"
            configpath.write_text(json.dumps(config,indent=2),encoding="utf-8")
            ground = ground_audit(folder, configpath.name)
            require(ground["status"] ==
                    "GROUND_FILLED_STITCHING_AUDITED_READY_FOR_NATIVE_DRC",
                    "PRE_DRC_GND_GATE_DID_NOT_PASS")
            evidence["ground_gate"] = ground
            drc_file = folder / "post-ground-drc.json"
            drc = run([cli, "pcb", "drc", "--refill-zones",
                       "--save-board", "--format", "json",
                       "--output", drc_file, final])
            require(drc_file.is_file() and drc_file.stat().st_size > 0,
                    "NATIVE_POSTGROUND_DRC_NOT_GENERATED")
            data = json.loads(drc_file.read_text(encoding="utf-8"))
            require(isinstance(data.get("violations"), list) and
                    isinstance(data.get("unconnected_items"), list),
                    "NATIVE_DRC_REPORT_INVALID")
            evidence["postground_native_drc"] = {
                "command_result":drc,
                "board_sha256":sha(final), "report_sha256":sha(drc_file),
                "violation_count":len(data["violations"]),
                "unconnected_count":len(data["unconnected_items"]),
            }
            evidence["status"] = "REAL_GND_FIRST_FILL_STITCH_REFILL_AND_DRC_COMPLETED_NOT_G4"
    except Exception as error:
        evidence["reason"] = str(error)
        evidence["traceback"] = traceback.format_exc()[-5500:]
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n",
                          encoding="utf-8")
        print(json.dumps(evidence,indent=2,ensure_ascii=False))
    return 0 if evidence["status"].startswith("REAL_GND_") else 2


if __name__ == "__main__":
    sys.exit(main())
