#!/usr/bin/env python3
"""Real KiCad 10.0.8 integration evidence. Never treats CI smoke as factory approval."""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kicad-pcb-ai-workflow/scripts"))
from npi_common import environment, runtime_inventory, sha256, load_board
from environment_start import setup, check
from manufacturing_export import commands

def execute(argv, ok=(0,)):
    result = subprocess.run(list(map(str, argv)), text=True, capture_output=True, timeout=240)
    print("COMMAND", json.dumps(list(map(str, argv)), ensure_ascii=False))
    print("EXIT", result.returncode, "STDERR", result.stderr[-1200:], flush=True)
    if result.returncode not in ok:
        raise RuntimeError("Native KiCad command failed: " + str(argv) + ": " + result.stderr[-1500:])
    return result

def hashed_tree(base):
    return {str(p.relative_to(base)): sha256(p) for p in base.rglob("*") if p.is_file()}

def candidates():
    # First use an explicit repository-owned complete fixture.
    ours = ROOT / "development/fixtures/npi-demo"
    yield ours, "npi-demo"
    for base in (Path("/usr/share/kicad/demos"), Path("/usr/share/kicad/samples")):
        if not base.exists():
            continue
        found = 0
        for schematic in sorted(base.rglob("*.kicad_sch")):
            stem = schematic.stem
            if all((schematic.parent / (stem + suffix)).is_file()
                   for suffix in (".kicad_pcb", ".kicad_pro")):
                yield schematic.parent, stem
                found += 1
                if found >= 14:
                    break

def validate(temp):
    checks = {"mode": "ACTUAL_NATIVE_CLI_PCBNEW", "production_authorized": False,
              "factory_cam_approval": False, "verified_version": "10.0.8",
              "steps": {}, "status": "BLOCKED"}
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("Missing real kicad-cli binary")
    version = execute([cli, "version"]).stdout.strip()
    if version != "10.0.8":
        raise RuntimeError("Must test exact stable KiCad 10.0.8, found " + version)
    import pcbnew
    pcbversion = str(pcbnew.GetBuildVersion())
    if "10.0.8" not in pcbversion:
        raise RuntimeError("pcbnew version mismatch: " + pcbversion)
    env = environment(cli)
    if not env.get("version_pair_compatible"):
        raise RuntimeError("Skill rejects real KiCad 10.0.8 pair: " + str(env))
    inventory = runtime_inventory(ROOT / "kicad-pcb-ai-workflow")
    checks["steps"]["tool_identity"] = {"cli": cli, "cli_version": version,
        "pcbnew_version": pcbversion, "inventory_script_count": len(inventory)}

    failures = []
    selected = None
    for index, (src, name) in enumerate(candidates()):
        state_dir = temp / ("smoke-" + str(index))
        try:
            if not src.is_dir():
                continue
            result = setup(src, name + ".kicad_sch", name + ".kicad_pcb",
                           name + ".kicad_pro", state_dir, cli, apply=True)
            if result.get("status") != "ENVIRONMENT_READY":
                raise RuntimeError(result.get("reason", str(result.get("status"))))
            assert result.get("production_authorized") is False
            assert check(state_dir / "startup-state.json", cli)["status"] == "ENVIRONMENT_READY"
            selected = (src, name, state_dir)
            break
        except Exception as exc:
            failures.append({"project": str(src / name), "error": str(exc)[:500]})
            print("SMOKE_CANDIDATE_REJECTED", name, str(exc)[:500], flush=True)
    checks["attempted_fixtures"] = failures
    if selected is None:
        raise RuntimeError("No native KiCad 10.0.8 project passed Skill setup; see attempted_fixtures")
    src, name, state_dir = selected
    checks["steps"]["native_project_smoke"] = {"project": str(src / name),
        "status": "ENVIRONMENT_READY",
        "generated_outputs": hashed_tree(state_dir)}
    original = hashed_tree(src)
    board_path = src / (name + ".kicad_pcb")
    loaded = pcbnew.LoadBoard(str(board_path))
    if loaded is None:
        raise RuntimeError("Actual pcbnew.LoadBoard returned None")
    footprints = list(loaded.GetFootprints())
    if not footprints:
        raise RuntimeError("Native test board has no footprint")
    checked = load_board(board_path, require_native=True)
    if checked.get("engine") != "pcbnew.LoadBoard":
        raise RuntimeError("Skill board loader failed to prove pcbnew engine")
    checks["steps"]["pcbnew_geometry"] = {"footprints": len(footprints),
        "native_engine": checked["engine"],
        "copper_layers": checked.get("copper_layers")}
    saved = temp / "refill-save-reload.kicad_pcb"
    filler = pcbnew.ZONE_FILLER(loaded)
    filler.Fill(loaded.Zones())
    pcbnew.SaveBoard(str(saved), loaded)
    reloaded = pcbnew.LoadBoard(str(saved))
    if reloaded is None or len(list(reloaded.GetFootprints())) != len(footprints):
        raise RuntimeError("ZoneFill/SaveBoard/reload failed")
    checks["steps"]["zone_fill_save_reload"] = {"status": "NATIVE_API_CALLS_OK",
        "zones_in_fixture": len(list(loaded.Zones())),
        "saved_sha256": sha256(saved),
        "note": "When zones_in_fixture=0 this does NOT prove real copper-zone fill quality"}

    # Native manufacturing *CLI interfaces* only: bypassing NPI approval is NOT allowed.
    cfg = {"inputs": {"board": name + ".kicad_pcb", "schematic": name + ".kicad_sch"},
           "variants": ["default"], "bom_fields": {},
           "delivery_export": {"schema_version": 1, "origin": "absolute",
             "gerber_layers": ["F.Cu", "B.Cu", "F.Mask", "B.Mask", "Edge.Cuts"],
             "assembly_layers": ["F.Fab", "B.Fab", "Edge.Cuts"],
             "bom_fields": ["Reference", "Value"], "variant": "default",
             "gerber_dir": "gerbers", "drill_dir": "drill",
             "position_file": "positions.csv", "bom_file": "bom.csv",
             "assembly_file": "assembly.pdf"}}
    output = temp / "manufacturing-cli-only"
    output.mkdir()
    native_outputs = []
    for cmd in commands(src, cfg, output, cli):
        target = Path(cmd[cmd.index("--output") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        execute(cmd)
        if not target.is_dir() and (not target.is_file() or target.stat().st_size == 0):
            raise RuntimeError("Missing/empty manufacturing CLI file " + str(target))
        native_outputs.append(cmd[1:4])
    products = hashed_tree(output)
    if not products or not any(p.endswith(".gbr") or p.endswith(".gtl") for p in products):
        raise RuntimeError("No Gerber files produced")
    if not any(p.endswith(".drl") for p in products):
        raise RuntimeError("No drill file produced")
    if original != hashed_tree(src):
        raise RuntimeError("Native tests modified the original demonstration project")
    checks["steps"]["manufacturing_cli_interfaces"] = {
        "status": "OUTPUT_FILES_PRESENT_NOT_APPROVED_FOR_PRODUCTION",
        "invocations": native_outputs, "outputs_sha256": products}
    checks["status"] = "NATIVE_TOOLCHAIN_SMOKE_PASSED"
    return checks

def main():
    reportfile = Path(os.environ.get("KICAD_NATIVE_REPORT", "/tmp/native-kicad-1008.json"))
    reportfile.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "BLOCKED", "production_authorized": False}
    with tempfile.TemporaryDirectory(prefix="kicad-1008-") as dirname:
        try:
            report = validate(Path(dirname))
        except Exception as exc:
            report["failure"] = str(exc)
            report["traceback"] = traceback.format_exc()[-6500:]
        finally:
            reportfile.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print("NATIVE_VERIFY_SUMMARY", json.dumps({k: v for k, v in report.items() if k != "steps"}, ensure_ascii=False), flush=True)
    return 0 if report.get("status") == "NATIVE_TOOLCHAIN_SMOKE_PASSED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
