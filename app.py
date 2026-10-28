"""WSGI entry point for an always-on, single-worker deployment."""
import atexit
import json
import os
from pathlib import Path
import threading
from collector import worker
from server import ROOT,EXCHANGES,validate_rows

HEADERS=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),
 ('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org")]

def create_app(run_collector=True):
    path=Path(os.environ.get('FEE_DATA_FILE',str(ROOT/'data'/'fees.json')))
    interval=int(os.environ.get('FEE_REFRESH_SECONDS','900'))
    if interval<60:raise ValueError('Minimum refresh interval is 60 seconds')
    stop=threading.Event()
    if run_collector:
        threading.Thread(target=worker,args=(path,interval,stop),daemon=True).start()
        atexit.register(stop.set)
    def application(environ,start_response):
        route=environ.get('PATH_INFO','/')
        status='200 OK';content_type='application/json; charset=utf-8'
        if environ.get('REQUEST_METHOD') not in ['GET','HEAD']:
            status='405 Method Not Allowed';body=b'{"error":"method_not_allowed"}'
        elif route=='/healthz':
            body=b'{"status":"running"}'
        elif route in ['/api/fees','/fees.json']:
            try:
                data=json.loads(path.read_text()) if path.exists() else {}
                rows=validate_rows(data.get('rows',[]) if isinstance(data,dict) else data)
                sources=data.get('sources',{}) if isinstance(data,dict) else {}
                sources={k:v for k,v in sources.items() if k in {e['id'] for e in EXCHANGES}}
                body=json.dumps(dict(exchanges=EXCHANGES,rows=rows,sources=sources,stale_after_seconds=3600),ensure_ascii=False).encode()
            except (ValueError,KeyError,TypeError,OSError):
                status='503 Service Unavailable';body=b'{"error":"invalid_or_unavailable_snapshot"}'
        elif route in ['/','/app.js','/style.css']:
            name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[route]
            content_type={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[route]
            body=(ROOT/'web'/name).read_bytes()
        else:
            status='404 Not Found';body=b'{"error":"not_found"}'
        start_response(status,HEADERS+[('Content-Type',content_type),('Content-Length',str(len(body)))])
        return [b'' if environ.get('REQUEST_METHOD')=='HEAD' else body]
    return application
