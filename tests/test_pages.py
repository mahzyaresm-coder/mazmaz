import functools
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from build_pages import build
from collector import now

class PagesTests(unittest.TestCase):
    def test_static_project_subpath_and_precise_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshot=root/'snapshot.json'
            row=dict(exchange='wallex',asset='USDT',network='tron',fee='2.500000000001',fee_currency='USDT',minimum=None,withdrawal_enabled=False,source='https://api.wallex.ir/v1/currencies',updated_at=now())
            snapshot.write_text(json.dumps({'rows':[row],'sources':{'wallex':{'status':'error','last_success':now()}}}))
            build(root/'mazmaz',snapshot)
            with ThreadingHTTPServer(('127.0.0.1',0),functools.partial(SimpleHTTPRequestHandler,directory=str(root))) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base='http://127.0.0.1:'+str(server.server_port)+'/mazmaz/'
                try:
                    for name in ['','app.js','style.css','fees.json']:
                        with urllib.request.urlopen(base+name) as r:
                            content=r.read();self.assertEqual(r.status,200)
                            if name=='fees.json':
                                data=json.loads(content)
                                self.assertEqual(data['rows'][0]['fee'],'2.500000000001')
                                self.assertEqual(data['sources']['wallex']['status'],'error')
                            if name=='':self.assertIn(b'./app.js',content)
                finally:server.shutdown();thread.join()
    def test_empty_snapshot_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshot=root/'snapshot.json';snapshot.write_text('{"rows":[]}')
            with self.assertRaises(ValueError):build(root/'site',snapshot)
            self.assertFalse((root/'site'/'fees.json').exists())
