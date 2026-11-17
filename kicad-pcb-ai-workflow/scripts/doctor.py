#!/usr/bin/env python3
"""Environment probe; never installs dependencies or changes a KiCad project."""
import argparse
import json
import os
import sys
from pathlib import Path
from npi_common import TARGET_VERSION, environment, pair_compatible, cli_compatible

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kicad-cli')
    p.add_argument('--supply-chain-config',type=Path)
    args=p.parse_args()
    result=environment(args.kicad_cli)
    config=args.supply_chain_config
    result['supply_chain']={'configured': bool(config and config.is_file()),
                            'environment_configured': bool(os.getenv('KICAD_SUPPLY_CHAIN_CONFIG')),
                            'queried':False}
    result['required_ok']=bool(pair_compatible(result) or cli_compatible(result))
    result['verification_scope']='KiCad CLI smoke does not require pcbnew. Konnect dynamic discovery/fixture acceptance is separate. Legacy pcbnew read compatibility is optional. No manufacturing authorization.'
    result['python']=sys.version.split()[0]
    result['optional_note']='ngspice/供应链配置仅检测存在性；不联网、不输出密钥、不自动仿真。'
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['required_ok'] else 2

if __name__ == '__main__':
    # JSON/text CLI protocol is UTF-8 on every platform, including Windows.
    import sys as _stdio_sys
    for _stdio_stream in (_stdio_sys.stdout, _stdio_sys.stderr):
        if hasattr(_stdio_stream, 'reconfigure'):
            _stdio_stream.reconfigure(encoding='utf-8')


if __name__=='__main__': raise SystemExit(main())
