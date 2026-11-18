#!/usr/bin/env python3
"""Native KiCad/Freerouting 2.5.0 roundtrip acceptance: ISOLATED fixture only.

Runs on a disposable KiCad project (never the user's live working project).
Separately proves exact real KiCad DSN export, real Freerouting SES generation,
KiCad native SES import, saved/reloaded track changes, and GND exclusion.
Full G4 engineering approval remains a distinct manual/native integration gate.
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
OUT = Path(os.environ.get("FREEROUTING_NATIVE_REPORT", "/tmp/freerouting-kicad-native-evidence.json"))
JAR = Path(os.environ.get("FREEROUTING_JAR", "/tmp/freerouting-2.5.0.jar"))
EXPECTED_JAR_SHA = "f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, timeout=480):
    process = subprocess.run([str(x) for x in command], capture_output=True, text=True,
                             timeout=timeout, check=False)
    return {"returncode": process.returncode,
            "stdout_tail": process.stdout[-4000:], "stderr_tail": process.stderr[-4000:]}


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def load_project_netclasses_for_native_export(board, net_settings, pcbnew):
    """Mirror actual .kicad_pro rules in a headless SWIG board before DSN export.

    LoadBoard() alone does NOT load .kicad_pro NET_SETTINGS. A declaration for
    GND can be emitted without its net being assigned to that DSN class.
    """
    native = board.GetDesignSettings().m_NetSettings
    for cls in net_settings["classes"]:
        name = cls["name"]
        nc = native.GetDefaultNetclass() if name == "Default" else pcbnew.NETCLASS(name)
        for key, setter in (
            ("clearance", "SetClearance"),
            ("track_width", "SetTrackWidth"),
            ("via_diameter", "SetViaDiameter"),
            ("via_drill", "SetViaDrill"),
        ):
            if isinstance(cls.get(key), (int, float)):
                getattr(nc, setter)(pcbnew.FromMM(float(cls[key])))
        if name != "Default":
            if isinstance(cls.get("priority"), int):
                nc.SetPriority(cls["priority"])
            native.SetNetclass(name, nc)
    for entry in net_settings["netclass_patterns"]:
        native.SetNetclassPatternAssignment(entry["pattern"], entry["netclass"])
    if hasattr(native, "ClearAllCaches"):
        native.ClearAllCaches()
    board.SynchronizeNetsAndNetClasses(False)


def main():
    evidence = {"status": "BLOCKED", "scope": "isolated_real_tool_roundtrip_not_production",
                "manufacturing_authorized": False, "g4_approved": False,
                "steps": {}, "limitations": [
                    "Linux/headless native roundtrip is not Windows/Konnect GUI acceptance",
                    "Native DRC and G4 review are separate from successful SES import",
                    "Fixture is intentionally used to validate real tool interoperability, not to certify ampacity/SI/PI",
                ]}
    try:
        import pcbnew
        cli = shutil.which("kicad-cli")
        require(cli, "REAL_KICAD_CLI_MISSING")
        version = run([cli, "version"])
        require(version["returncode"] == 0, "KICAD_VERSION_FAILED")
        pcb_version = str(pcbnew.GetBuildVersion())
        require(version["stdout_tail"].strip().startswith("10.") and "10." in pcb_version,
                "REQUIRES_REAL_KICAD_10")
        evidence["steps"]["tool_versions"] = {
            "kicad_cli": version["stdout_tail"].strip(), "pcbnew": pcb_version,
            "java": run(["java", "-version"]) }
        require(JAR.is_file() and sha(JAR) == EXPECTED_JAR_SHA, "FREEROUTING_JAR_PIN_MISMATCH")
        evidence["steps"]["freerouting_jar_sha256"] = sha(JAR)
        with tempfile.TemporaryDirectory(prefix="freerouting-kicad-native-") as td:
            project = Path(td) / "fixture"
            shutil.copytree(ROOT / "development/fixtures/npi-demo", project)
            pro = project / "npi-demo.kicad_pro"
            settings = json.loads(pro.read_text(encoding="utf-8"))
            ns = settings.setdefault("net_settings", {})
            ns["meta"] = {"version": 5}
            ns["classes"] = [
                {"name": "Default", "priority": 2147483647, "track_width": 0.2, "clearance": 0.2,
                 "via_diameter": 0.5, "via_drill": 0.25},
                {"name": "GND", "priority": -2, "track_width": 0.2, "clearance": 0.2},
                {"name": "SIGNAL", "priority": -1, "track_width": 0.3, "clearance": 0.2}
            ]
            ns["netclass_patterns"] = [
                {"pattern": "GND", "netclass": "GND"},
                {"pattern": "+3V3", "netclass": "SIGNAL"}
            ]
            pro.write_text(json.dumps(settings), encoding="utf-8")
            pcbfile = project / "npi-demo.kicad_pcb"
            board = pcbnew.LoadBoard(str(pcbfile))
            tracks_before = list(board.GetTracks())
            for track in tracks_before:
                board.Remove(track)
            pcbnew.SaveBoard(str(pcbfile), board)
            assert not list(pcbnew.LoadBoard(str(pcbfile)).GetTracks())
            board = pcbnew.LoadBoard(str(pcbfile))
            # Restore project net settings: raw pcbnew.LoadBoard never loads .kicad_pro.
            load_project_netclasses_for_native_export(board, ns, pcbnew)
            dsn = project / "native-export.dsn"
            exported = pcbnew.ExportSpecctraDSN(board, str(dsn))
            require(bool(exported) and dsn.is_file() and dsn.stat().st_size > 0,
                    "REAL_KICAD_DSN_EXPORT_FAILED")
            dsntxt = dsn.read_text(encoding="utf-8", errors="replace")
            require("(pcb" in dsntxt and "GND" in dsntxt and "+3V3" in dsntxt,
                    "DSN_NETS_MISSING")
            # Import our production DSN preflight: declarations alone are insufficient.
            sys.path.insert(0, str(ROOT / "kicad-pcb-ai-workflow" / "scripts"))
            from freerouting_adapter import specctra_netclass_members
            members = specctra_netclass_members(dsn)
            evidence["steps"]["dsn"] = {
                "sha256": sha(dsn), "bytes": dsn.stat().st_size,
                "gnd_effective_class": members.get("GND"),
                "signal_effective_class": members.get("+3V3"),
            }
            require(members.get("GND") == "GND",
                    "GND_EFFECTIVE_NETCLASS_MISMATCH")
            require(members.get("+3V3") == "SIGNAL",
                    "SIGNAL_EFFECTIVE_NETCLASS_MISMATCH")
            ses = project / "freerouting-candidate.ses"
            command = ["java", "-jar", str(JAR),
                       "-de", str(dsn), "-do", str(ses),
                       "-inc", "GND", "-mp", "25", "-mt", "1",
                       "--router.fanout.enabled=false",
                       "--router.optimizer.enabled=false",
                       "--gui.enabled=false", "-da"]
            result = run(command, timeout=600)
            evidence["steps"]["freerouting"] = result
            require(result["returncode"] == 0 and ses.is_file() and ses.stat().st_size > 0,
                    "FREEROUTING_2_5_0_SES_NOT_GENERATED")
            evidence["steps"]["ses"] = {"sha256": sha(ses), "bytes": ses.stat().st_size}
            target = project / "ses-imported.kicad_pcb"
            shutil.copy2(pcbfile, target)
            imported = pcbnew.LoadBoard(str(target))
            ok = pcbnew.ImportSpecctraSES(imported, str(ses))
            require(bool(ok), "KICAD_NATIVE_SES_IMPORT_RETURNED_FALSE")
            pcbnew.SaveBoard(str(target), imported)
            saved = pcbnew.LoadBoard(str(target))
            routed = list(saved.GetTracks())
            require(routed, "SES_IMPORT_ADDED_NO_REAL_COPPER")
            counts = {}
            for track in routed:
                name = str(track.GetNetname())
                counts[name] = counts.get(name, 0) + 1
            require(counts.get("+3V3", 0) > 0, "SIGNAL_UNROUTED_AFTER_IMPORT")
            evidence["steps"]["imported_track_counts"] = counts
            require(counts.get("GND", 0) == 0, "GND_AUTOROUTED_DESPITE_EXCLUSION")
            evidence["steps"]["imported_saved_board"] = {
                "sha256": sha(target), "tracks": len(routed), "per_net": counts,
                "source_sha256": sha(pcbfile)}
            # This route-only fixture predates design approvals and must not be
            # mistaken for a full G4-passed PCB or a real engineer signoff.
            drc_report = project / "native-drc.json"
            drc = run([cli, "pcb", "drc", "--format", "json",
                       "--output", str(drc_report), str(target)], timeout=240)
            evidence["steps"]["native_drc"] = drc
            if drc_report.is_file():
                data = json.loads(drc_report.read_text(encoding="utf-8"))
                evidence["steps"]["native_drc"]["violation_count"] = len(data.get("violations", []))
                evidence["steps"]["native_drc"]["unconnected_count"] = len(data.get("unconnected_items", []))
                evidence["steps"]["native_drc"]["report_sha256"] = sha(drc_report)
            evidence["status"] = "REAL_NATIVE_DSN_SES_ROUNDTRIP_PASSED_NOT_G4"
    except Exception as exc:
        evidence["reason"] = str(exc)
        evidence["traceback_tail"] = traceback.format_exc()[-6500:]
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"].startswith("REAL_NATIVE_") else 2


if __name__ == "__main__":
    sys.exit(main())
