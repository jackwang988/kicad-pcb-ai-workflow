#!/usr/bin/env python3
"""Refill EXISTING zones to a new board file. No new plane geometry is generated."""
import argparse
from _runtime import checked_input,new_output

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source');ap.add_argument('output');ap.add_argument('--apply',action='store_true')
    a=ap.parse_args();src=checked_input(a.source,'.kicad_pcb');out=new_output(src,a.output)
    if not a.apply:
        print('Preview: refill existing zones from',src,'to',out,'; add --apply to write.');return 0
    import pcbnew
    board=pcbnew.LoadBoard(src)
    if board is None:raise SystemExit('Unable to load board')
    result=pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    if result is False:raise SystemExit('Fill reported failure; no output saved')
    pcbnew.SaveBoard(out,board)
    print('Saved:',out,'; run KiCad DRC and inspect every zone before accepting.')
    return 0
if __name__=='__main__':raise SystemExit(main())
