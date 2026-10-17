"""Small CLI guards; importing this module does not read or modify project files."""
from pathlib import Path
import os
import sys

def require_apply():
    if '--help' in sys.argv or '-h' in sys.argv:
        return
    if '--apply' not in sys.argv:
        raise SystemExit('This tool writes output. Review the proposed operation, then explicitly add --apply. Source overwrite is not allowed.')
    sys.argv.remove('--apply')

def board_option():
    if '--board' in sys.argv:
        i=sys.argv.index('--board')
        if i+1 >= len(sys.argv):raise SystemExit('--board requires a .kicad_pcb path')
        value=sys.argv[i+1];del sys.argv[i:i+2]
    else:value=os.environ.get('KICAD_BOARD','')
    return checked_input(value,'.kicad_pcb')

def positional_board():
    value=sys.argv[1] if len(sys.argv)>1 and not sys.argv[1].startswith('-') else ''
    return checked_input(value,'.kicad_pcb')

def checked_input(value,suffix=None):
    if not value:raise SystemExit('Specify an input path; for board tools use --board or KICAD_BOARD.')
    p=Path(value).expanduser().resolve()
    if not p.is_file():raise SystemExit('Input file does not exist: '+str(p))
    if suffix and p.suffix.lower()!=suffix:raise SystemExit('Expected '+suffix)
    return str(p)

def new_output(source,destination):
    src=Path(checked_input(source));dst=Path(destination).expanduser().resolve()
    if src==dst:raise SystemExit('Output must differ from source; work on a copy.')
    if dst.exists():raise SystemExit('Output already exists; choose a new output path.')
    if not dst.parent.is_dir():raise SystemExit('Output parent directory must already exist.')
    return str(dst)

def new_output_directory(source,destination):
    src=Path(checked_input(source));dst=Path(destination).expanduser().resolve()
    if dst.exists():raise SystemExit('Output directory must be new; existing content will not be replaced.')
    if dst==src.parent:raise SystemExit('Choose a separate output directory.')
    return str(dst)
