"""Build the same fee UI as a portable static GitHub Pages artifact."""
import argparse
from assets import selected_rows, REQUESTED_ASSETS
import json
import logging
from pathlib import Path
import shutil
from collector import ROOT, run_once, atomic_json, now
from server import EXCHANGES, validate_rows


def build(output, snapshot, refresh=False):
    seed=ROOT/'data'/'seed.json'
    if not snapshot.exists() and seed.exists():
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(seed,snapshot)
    if refresh:
        run_once(snapshot)
    if not snapshot.exists():raise ValueError('No fee snapshot available')
    document=json.loads(snapshot.read_text())
    rows=selected_rows(validate_rows(document['rows']))
    active={e['id'] for e in EXCHANGES}
    rows=[r for r in rows if r['exchange'] in active]
    if not rows:raise ValueError('No usable fee rows; refusing empty publication')
    sources={k:v for k,v in document.get('sources',{}).items() if k in active}
    output.mkdir(parents=True,exist_ok=True)
    for name in ['index.html','app.js','style.css']:
        shutil.copyfile(ROOT/'web'/name,output/name)
    atomic_json(output/'fees.json',dict(exchanges=EXCHANGES,rows=rows,sources=sources,
        blockchain_fees=document.get('blockchain_fees',[]),requested_assets=REQUESTED_ASSETS,stale_after_seconds=3600,checked_at=document.get('checked_at'),built_at=now()))
    (output/'.nojekyll').write_text('')
    logging.info('Built %d fee rows; source status: %s',len(rows),{k:v.get('status') for k,v in sources.items()})
    return rows

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'_site')
    parser.add_argument('--snapshot',type=Path,default=ROOT/'data'/'fees.json')
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build(args.output,args.snapshot,args.refresh)
