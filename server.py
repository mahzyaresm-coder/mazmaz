"""Local fee comparison app. No third-party dependencies or account credentials."""
import argparse
from assets import selected_rows, REQUESTED_ASSETS
import json
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCHANGES = [dict(id=k, name=v) for k, v in [('nobitex','نوبیتکس'),('wallex','والکس'),('tabdeal','تبدیل'),('bitpin','بیت‌پین')]]

def load_snapshot(path):
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    return validate_rows(rows['rows'] if isinstance(rows,dict) else rows)

def validate_rows(rows):
    if not isinstance(rows, list):
        raise ValueError('Snapshot must be a list')
    seen = set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('Invalid row')
        key = tuple(row.get(k) for k in ('exchange', 'asset', 'network'))
        if key[0] not in {x['id'] for x in EXCHANGES} or not all(isinstance(x,str) and x.strip() for x in key):
            raise ValueError('Invalid exchange, asset or network')
        if key in seen:
            raise ValueError('Duplicate exchange/asset/network')
        seen.add(key)
        for field in ('fee', 'minimum'):
            value = row.get(field)
            if value is not None:
                try:
                    number = Decimal(value) if isinstance(value, str) else Decimal('NaN')
                    if not number.is_finite() or number < 0:
                        raise ValueError('Amounts must be nonnegative decimal strings')
                except InvalidOperation as exc:
                    raise ValueError('Invalid amount') from exc
        if row.get('withdrawal_enabled') is not None and type(row['withdrawal_enabled']) is not bool:
            raise ValueError('Invalid withdrawal status')
        if not isinstance(row.get('source'),str) or not row['source'].startswith('https://'):
            raise ValueError('HTTPS source required')
        stamp = datetime.fromisoformat(row['updated_at'].replace('Z','+00:00'))
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            raise ValueError('Timestamp must be timezone-aware and not in the future')
        if row.get('fee') is not None and not row.get('fee_currency'):
            raise ValueError('Fee currency required')
    return rows

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?',1)[0]
        if route in ['/api/fees','/fees.json']:
            try:
                path = Path(os.environ.get('FEE_DATA_FILE', str(ROOT/'data'/'fees.json')))
                document = json.loads(path.read_text()) if path.exists() else {}
                sources = document.get('sources',{}) if isinstance(document,dict) else {}
                rows = selected_rows(validate_rows(document.get('rows',[]) if isinstance(document,dict) else document))
                self.send_payload(200, json.dumps({'exchanges': EXCHANGES, 'requested_assets': REQUESTED_ASSETS, 'rows': rows, 'sources': sources, 'blockchain_fees': document.get('blockchain_fees',[]) if isinstance(document,dict) else [], 'stale_after_seconds': 3600}, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except (ValueError, KeyError, TypeError, OSError):
                self.send_payload(503, b'{"error":"invalid_or_unavailable_snapshot"}', 'application/json')
        elif route in ('/', '/app.js', '/style.css'):
            file = ROOT/'web'/({'/':'index.html'}.get(route,route[1:]))
            self.send_payload(200,file.read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[route])
        else:
            self.send_payload(404,b'Not found','text/plain')

    def send_payload(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org")
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--no-collector',action='store_true',help='Serve existing snapshot only')
    parser.add_argument('--interval',type=int,default=900)
    args = parser.parse_args()
    if args.interval < 60: parser.error('Minimum interval is 60 seconds')
    stop = threading.Event()
    if not args.no_collector:
        from collector import worker
        data_path = Path(os.environ.get('FEE_DATA_FILE', str(ROOT/'data'/'fees.json')))
        threading.Thread(target=worker,args=(data_path,args.interval,stop),daemon=True).start()
    try:
        ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
    finally:
        stop.set()
