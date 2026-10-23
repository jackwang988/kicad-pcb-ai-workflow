#!/usr/bin/env python3
"""Optional Freerouting 2.5.0 CLI adapter (not bundled). DSN -> SES only.

This is an independent, opt-in tool. It DOES NOT change the KiCad board, import
SES, perform KiCad DRC, or claim that a routed board is electrically valid.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

VERSION = "2.5.0"
MAX_LOG = 100000


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_jar(path):
    """Reject unknown jar builds. Distribution name alone is not sufficient."""
    if not path.is_file() or path.suffix.lower() != ".jar":
        return False, "JAR_NOT_FOUND"
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if "META-INF/MANIFEST.MF" not in names:
                return False, "MANIFEST_MISSING"
            manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
            poms = [n for n in names if n.endswith("/pom.properties") and "freerouting" in n.lower()]
            parts = [manifest] + [archive.read(n).decode("utf-8", "replace") for n in poms]
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False, "INVALID_JAR"
    identity = "\n".join(parts)
    if not re.search(r"freerouting", identity, re.I):
        return False, "UNRECOGNIZED_PRODUCT"
    version_found = any(re.search(r"(?m)^(?:Implementation-Version|Bundle-Version|version)\s*[:=]\s*2\.5\.0\s*$", t, re.I) for t in parts)
    if not version_found:
        return False, "VERSION_2_5_0_NOT_PROVEN"
    return True, "VERIFIED_METADATA_2_5_0"


def process(args, timeout):
    return subprocess.run(args, shell=False, capture_output=True, text=True,
                          errors="replace", timeout=timeout, check=False)


def main():
    p = argparse.ArgumentParser(description="Optional Freerouting v2.5.0 DSN-to-SES adapter")
    p.add_argument("--dsn", type=Path, required=True, help="KiCad PCB Editor exported Specctra .dsn")
    p.add_argument("--jar", type=Path, help="Verified local Freerouting 2.5.0 jar")
    p.add_argument("--java", default="java")
    p.add_argument("--output-dir", type=Path, required=True, help="New, nonexisting route result directory")
    p.add_argument("--passes", type=int, default=10)
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--expected-jar-sha256", help="Optional external checksum of the approved JAR")
    p.add_argument("--apply", action="store_true", help="Execute router, otherwise preview only")
    a = p.parse_args()
    if a.dsn.suffix.lower() != ".dsn" or not a.dsn.is_file() or not a.dsn.stat().st_size:
        p.error("DSN must be an existing nonempty .dsn export")
    if not (1 <= a.passes <= 1000 and 0 <= a.threads <= 128 and 10 <= a.timeout <= 86400):
        p.error("Invalid passes/threads/timeout bounds")
    dsn = a.dsn.resolve()
    dest = a.output_dir.resolve()
    if dest.exists():
        p.error("Output directory must not exist (never overwrite previous evidence)")
    if dest == dsn.parent or dest in dsn.parents:
        p.error("Output directory cannot be the DSN source directory or its ancestor")
    base = {"adapter": "freerouting-cli", "requested_version": VERSION, "dsn": str(dsn),
            "dsn_sha256": sha256(dsn), "output_directory": str(dest)}
    if a.jar is None or not a.jar.is_file():
        print(json.dumps({**base, "status": "MANUAL_ROUTING_FALLBACK",
                          "reason": "Freerouting jar not configured; use KiCad interactive routing."}, indent=2))
        return 0
    jar = a.jar.resolve()
    ok, reason = inspect_jar(jar)
    if not ok:
        print(json.dumps({**base, "status": "MANUAL_ROUTING_FALLBACK", "reason": reason}, indent=2))
        return 0
    digest = sha256(jar)
    if a.expected_jar_sha256 and digest.lower() != a.expected_jar_sha256.lower():
        print(json.dumps({**base, "status": "BLOCKED", "reason": "JAR_CHECKSUM_MISMATCH"}, indent=2))
        return 2
    java_executable = shutil.which(a.java)
    if not java_executable:
        print(json.dumps({**base, "status": "MANUAL_ROUTING_FALLBACK", "reason": "JAVA_NOT_FOUND"}, indent=2))
        return 0
    try:
        java_check = process([java_executable, "-version"], 15)
    except (OSError, subprocess.TimeoutExpired):
        java_check = None
    if java_check is None or java_check.returncode:
        print(json.dumps({**base, "status": "MANUAL_ROUTING_FALLBACK", "reason": "JAVA_UNUSABLE"}, indent=2))
        return 0
    ses = dest / (dsn.stem + ".ses")
    command = [java_executable, "-jar", str(jar), "-de", str(dsn),
               "-do", str(ses), "-mp", str(a.passes), "-mt", str(a.threads),
               "--gui.enabled=false", "-da"]
    report = {**base, "jar": str(jar), "jar_sha256": digest,
              "jar_identity": reason, "java": java_executable, "command": command,
              "ses": str(ses), "note": "KiCad SES import, DRC and engineering review are mandatory."}
    if not a.apply:
        print(json.dumps({**report, "status": "PREVIEW_NOT_EXECUTED"}, indent=2))
        return 0
    # External tools run ONLY on explicit --apply; outputs are isolated.
    dest.mkdir(parents=True, exist_ok=False)
    try:
        result = process(command, a.timeout)
        report["exit_code"] = result.returncode
        report["stdout_tail"] = result.stdout[-MAX_LOG:]
        report["stderr_tail"] = result.stderr[-MAX_LOG:]
        successful = result.returncode == 0 and ses.is_file() and ses.stat().st_size > 0
    except subprocess.TimeoutExpired as exc:
        report["reason"] = "ROUTER_TIMEOUT"
        report["error"] = str(exc)
        successful = False
    except OSError as exc:
        report["reason"] = "ROUTER_EXECUTION_FAILED"
        report["error"] = str(exc)
        successful = False
    if successful:
        report["ses_sha256"] = sha256(ses)
        report["status"] = "SES_GENERATED_NOT_IMPORTED_OR_APPROVED"
    else:
        report["status"] = "ROUTING_FAILED"
    (dest / "freerouting-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "result": str(dest / "freerouting-result.json")}, indent=2))
    return 0 if successful else 2


if __name__ == "__main__":
    sys.exit(main())
