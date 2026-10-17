#!/usr/bin/env python3
"""Check the current interpreter and KiCad CLI without changing project files."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--require',choices=['core','pdf','pcb','all'],default='core')
    a=ap.parse_args()
    mods={n:importlib.util.find_spec(n) is not None for n in ['pcbnew','fitz','PIL']}
    cli=shutil.which(os.environ.get('KICAD_CLI','kicad-cli'))
    version=None
    if cli:
        try:
            p=subprocess.run([cli,'version'],capture_output=True,text=True,timeout=15)
            if p.returncode==0:version=p.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):pass
    ok={'core':True,'pdf':mods['fitz'],'pcb':mods['pcbnew'] and bool(version),'all':all(mods.values()) and bool(version)}[a.require]
    print(json.dumps({'python':sys.executable,'python_version':sys.version.split()[0],'modules':mods,'kicad_cli':cli,'kicad_version':version,'requested_profile':a.require,'ready':bool(ok)},indent=2))
    return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
