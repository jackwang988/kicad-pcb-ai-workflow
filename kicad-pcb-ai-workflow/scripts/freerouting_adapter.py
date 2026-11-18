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


def specctra_netclasses(path):
    """Inventory declared classes only; membership still needs independent proof."""
    source = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r'\(\s*class\s+(?:"([^"]+)"|([^\s()]+))', source, re.I)
    return {quoted or bare for quoted, bare in matches}


def specctra_netclass_members(path):
    """Read actual Specctra DSN net-to-class membership, not mere declarations."""
    source = path.read_text(encoding="utf-8", errors="strict")
    if len(source) > 32 * 1024 * 1024:
        raise ValueError("DSN_NETCLASS_INVENTORY_TOO_LARGE")
    token_re = re.compile(r'\s+|;[^\n]*|"(?:\\.|[^"\\])*"|[()]|[^\s();]+')
    roots, stack, pos = [], [], 0
    for match in token_re.finditer(source):
        if match.start() != pos:
            raise ValueError("DSN_SYNTAX_UNRECOGNIZED")
        pos = match.end()
        token = match.group()
        if not token.strip() or token.startswith(";"):
            continue
        if token == "(":
            node = []
            if stack:
                stack[-1].append(node)
            else:
                roots.append(node)
            stack.append(node)
        elif token == ")":
            if not stack:
                raise ValueError("DSN_UNBALANCED_PARENTHESES")
            stack.pop()
        else:
            if not stack:
                raise ValueError("DSN_CONTENT_OUTSIDE_ROOT")
            if token.startswith('"'):
                token = token[1:-1].replace(r'\"', '"').replace(r'\\', "\\")
            stack[-1].append(token)
    if pos != len(source) or stack or len(roots) != 1:
        raise ValueError("DSN_INCOMPLETE_SEXPR")
    pcb = roots[0]
    if not pcb or str(pcb[0]).lower() != "pcb":
        raise ValueError("DSN_PCB_ROOT_MISSING")
    networks = [part for part in pcb if isinstance(part, list) and
                part and str(part[0]).lower() == "network"]
    if len(networks) != 1:
        raise ValueError("DSN_NETWORK_SCOPE_MISSING_OR_DUPLICATE")
    members, declared_nets, classes = {}, set(), set()
    for entry in networks[0][1:]:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        kind = str(entry[0]).lower()
        if kind == "net":
            if not isinstance(entry[1], str):
                raise ValueError("DSN_NET_NAME_INVALID")
            declared_nets.add(entry[1])
        if kind != "class":
            continue
        name = entry[1]
        if not isinstance(name, str) or not name or name in classes:
            raise ValueError("DSN_DUPLICATE_OR_INVALID_NETCLASS")
        classes.add(name)
        for net in entry[2:]:
            if isinstance(net, list):
                continue
            if not isinstance(net, str) or not net or net in members:
                raise ValueError("DSN_DUPLICATE_OR_INVALID_NET_MEMBER")
            members[net] = name
    if not members:
        raise ValueError("DSN_NETCLASS_MEMBERSHIP_ABSENT")
    if declared_nets and declared_nets != set(members):
        raise ValueError("DSN_CLASS_NET_INVENTORY_INCOMPLETE")
    return members


def class_exclusions(value):
    """CLI -inc is a CLASS exclusion, not a net-name exclusion."""
    if not value:
        return []
    classes = [x.strip() for x in value.split(",")]
    if (not all(classes) or len(set(classes)) != len(classes) or
            not all(re.fullmatch(r"[A-Za-z0-9_.:+-]+", x) for x in classes)):
        raise ValueError("Invalid or duplicate NetClass names in exclusions")
    return classes


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
    p.add_argument("--exclude-netclasses", default="",
                   help="Comma-separated PROTECTED NetClass names; routed with Freerouting -inc")
    p.add_argument("--expected-dsn-sha256",
                   help="SHA-256 of reviewed KiCad-exported DSN; required for --apply")
    p.add_argument("--netclass-map", type=Path,
                   help="Native net_to_class readback JSON (required for --apply)")
    p.add_argument("--expected-netclass-map-sha256",
                   help="SHA-256 of approved native netclass map (required for --apply)")
    p.add_argument("--rules-file", type=Path,
                   help="Optional approved Freerouting .rules file (never trust implicit sidecar)")
    p.add_argument("--expected-rules-sha256",
                   help="SHA-256 of approved .rules; required for --apply when --rules-file is used")
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
    def blocked(reason, **extra):
        print(json.dumps({**base, "status": "BLOCKED", "reason": reason, **extra}, indent=2))
        return 2

    if a.expected_dsn_sha256:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", a.expected_dsn_sha256):
            return blocked("INVALID_DSN_SHA256")
        if base["dsn_sha256"] != a.expected_dsn_sha256.lower():
            return blocked("DSN_SHA256_MISMATCH")
    elif a.apply:
        return blocked("DSN_HASH_REQUIRED_FOR_EXECUTION")

    try:
        excluded = class_exclusions(a.exclude_netclasses)
    except ValueError:
        return blocked("INVALID_EXCLUDED_NETCLASSES")
    if a.apply and not excluded:
        return blocked("PROTECTED_NETCLASS_EXCLUSIONS_REQUIRED")
    if excluded:
        declared = specctra_netclasses(dsn)
        missing = sorted(set(excluded) - declared)
        if missing:
            return blocked("EXCLUDED_NETCLASS_NOT_IN_DSN", missing_netclasses=missing)
    # A named class does not prove that the expected net belongs to it.
    try:
        actual_map = specctra_netclass_members(dsn)
    except (ValueError, UnicodeError, OSError) as exc:
        return blocked("DSN_NETCLASS_MEMBERSHIP_UNVERIFIABLE", detail=str(exc))
    implicit_rules = dsn.with_suffix(".rules")
    rules = a.rules_file.resolve() if a.rules_file else None
    if implicit_rules.is_file() and rules != implicit_rules.resolve():
        return blocked("UNAPPROVED_ADJACENT_RULES")
    rules_hash = None
    if rules:
        if rules.suffix.lower() != ".rules" or not rules.is_file() or not rules.stat().st_size:
            return blocked("INVALID_RULES_FILE")
        rules_hash = sha256(rules)
        if a.expected_rules_sha256:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", a.expected_rules_sha256):
                return blocked("INVALID_RULES_SHA256")
            if rules_hash != a.expected_rules_sha256.lower():
                return blocked("RULES_SHA256_MISMATCH")
        elif a.apply:
            return blocked("RULES_HASH_REQUIRED_FOR_EXECUTION")

    if "GND" in actual_map and actual_map["GND"] not in excluded:
        return blocked("GND_EFFECTIVE_CLASS_NOT_EXCLUDED",
                       actual_class=actual_map["GND"])
    native_map_sha = None
    if a.netclass_map:
        native_path = a.netclass_map.resolve()
        if not native_path.is_file() or native_path.suffix.lower() != ".json":
            return blocked("NATIVE_NETCLASS_MAP_NOT_FOUND")
        native_map_sha = sha256(native_path)
        if not a.expected_netclass_map_sha256:
            return blocked("NATIVE_NETCLASS_MAP_HASH_REQUIRED")
        if native_map_sha != a.expected_netclass_map_sha256.lower():
            return blocked("NATIVE_NETCLASS_MAP_HASH_MISMATCH")
        try:
            native = json.loads(native_path.read_text(encoding="utf-8"))
            expected_map = native["net_to_class"]
            if not isinstance(expected_map, dict) or not expected_map:
                raise ValueError("missing net_to_class entries")
            if native.get("dsn_sha256") != base["dsn_sha256"]:
                return blocked("NATIVE_NETCLASS_MAP_DSN_HASH_MISMATCH")
            if expected_map != actual_map:
                return blocked("NATIVE_NETCLASS_MAP_MEMBERSHIP_MISMATCH",
                               native_net_count=len(expected_map),
                               exported_net_count=len(actual_map))
        except (KeyError, ValueError, TypeError) as exc:
            return blocked("NATIVE_NETCLASS_MAP_INVALID", detail=str(exc))
    elif a.apply:
        return blocked("NATIVE_NETCLASS_MAP_REQUIRED_FOR_EXECUTION")

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
    if excluded:
        command.extend(["-inc", ",".join(excluded)])
    if rules:
        command.extend(["-dr", str(rules)])
    report = {**base, "excluded_netclasses": excluded,
              "dsn_classes_declared": sorted(specctra_netclasses(dsn)) if excluded else [],
              "rules_file": str(rules) if rules else None, "rules_sha256": rules_hash,
              "effective_dsn_netclasses": actual_map,
              "native_netclass_map_sha256": native_map_sha,
              "class_mapping_limit": "Must match native NetClass readback and protect copper by independent saved KiCad board audit.",
              "jar": str(jar), "jar_sha256": digest,
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


if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__ == "__main__":
    sys.exit(main())
