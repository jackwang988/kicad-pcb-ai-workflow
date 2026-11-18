#!/usr/bin/env python3
"""Preview SPICE netlist export; optionally run an independently installed ngspice.

KiCad's internal ngspice library is NOT assumed to be an external executable.
"""
import argparse
import json
import shutil
from pathlib import Path
from npi_common import TARGET_VERSION, environment, run, cli_native_ready

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('schematic',type=Path); p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--kicad-cli'); p.add_argument('--variant'); p.add_argument('--apply',action='store_true')
    p.add_argument('--run-ngspice',action='store_true',help='Only run a user-reviewed complete SPICE testbench')
    a=p.parse_args(); env=environment(a.kicad_cli)
    if a.output_dir.exists(): p.error('Output directory already exists; overwriting is prohibited')
    command=[env['kicad_cli'] or 'kicad-cli','sch','export','netlist','--format','spice','--output',str(a.output_dir/'circuit.cir')]
    if a.variant: command+=['--variant',a.variant]
    command+=[str(a.schematic)]
    if not a.apply:
        print(json.dumps({'preview':True,'command':command,'ngspice_requested':a.run_ngspice},ensure_ascii=False)); return 0
    if not cli_native_ready(env, a.kicad_cli): p.error('Stable compatible KiCad CLI required; KiCad 11+ needs accepted native CLI-only validation')
    if a.run_ngspice and not shutil.which('ngspice'): p.error('External ngspice executable not found')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    result=run(command); print(json.dumps(result,ensure_ascii=False))
    if result['returncode']: return 2
    if a.run_ngspice:
        result=run([shutil.which('ngspice'),'-b','-o',str(a.output_dir/'ngspice.log'),str(a.output_dir/'circuit.cir')])
        print(json.dumps(result,ensure_ascii=False)); return 0 if result['returncode']==0 else 2
    return 0

if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__': raise SystemExit(main())
