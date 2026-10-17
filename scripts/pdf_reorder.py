#!/usr/bin/env python3
"""Reorder exported PDF pages, writing a NEW file; --info is read-only."""
import argparse
from _runtime import checked_input,new_output

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source');ap.add_argument('output',nargs='?')
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--info',action='store_true');group.add_argument('--order');group.add_argument('--move',nargs=2,type=int,metavar=('FROM','TO'))
    a=ap.parse_args()
    import fitz
    with fitz.open(checked_input(a.source,'.pdf')) as doc:
        n=doc.page_count
        if a.info:
            for i,p in enumerate(doc,1):print(i,tuple(p.rect),len(p.get_text('words')))
            return 0
        if not a.output:ap.error('output is required when reordering')
        dst=new_output(a.source,a.output)
        if a.order:
            try:order=[int(i) for i in a.order.split(',')]
            except ValueError:ap.error('--order requires comma-separated page numbers')
            if sorted(order)!=list(range(1,n+1)):ap.error('--order must be a permutation of all pages')
        else:
            src,to=a.move
            if not(1<=src<=n and 1<=to<=n):ap.error('--move pages out of range')
            order=list(range(1,n+1));order.insert(to-1,order.pop(src-1))
        with fitz.open() as out:
            for i in order:out.insert_pdf(doc,from_page=i-1,to_page=i-1)
            out.save(dst)
        print('Saved',dst,'page order',order)
    return 0
if __name__=='__main__':raise SystemExit(main())
