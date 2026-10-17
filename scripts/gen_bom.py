#!/usr/bin/env python3
"""Export a NEW PCB component CSV grouped by value+footprint. Not a sourcing BOM."""
import argparse
from collections import defaultdict
import csv
from pathlib import Path
from _runtime import checked_input,new_output

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('board');ap.add_argument('--out',required=True)
    a=ap.parse_args();src=checked_input(a.board,'.kicad_pcb');dst=new_output(src,a.out)
    import pcbnew
    board=pcbnew.LoadBoard(src);groups=defaultdict(list)
    for f in board.GetFootprints():
        groups[(str(f.GetValue()),str(f.GetFPID()))].append((str(f.GetReference()),'Bottom' if f.IsFlipped() else 'Top'))
    with Path(dst).open('w',encoding='utf-8-sig',newline='') as out:
        w=csv.writer(out);w.writerow(['Value','Footprint','Quantity','Side','Designators'])
        for (value,footprint),items in sorted(groups.items()):
            w.writerow([value,footprint,len(items),'/'.join(sorted({s for _,s in items})),' '.join(sorted(ref for ref,_ in items))])
    print('Saved',dst,'; verify DNP, assembly variants and manufacturer part numbers separately.')
    return 0
if __name__=='__main__':raise SystemExit(main())
