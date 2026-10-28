import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import create_app

class ApplicationTests(unittest.TestCase):
    def test_routes_and_corrupt_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fees.json'
            with patch.dict(os.environ,{'FEE_DATA_FILE':str(path)}):app=create_app(run_collector=False)
            def request(route,method='GET'):
                headers=[]
                body=b''.join(app({'PATH_INFO':route,'REQUEST_METHOD':method},lambda status,h:headers.append((status,h))))
                return headers[0][0],body
            status,body=request('/api/fees')
            self.assertEqual(status,'200 OK');self.assertEqual(len(json.loads(body)['exchanges']),4)
            self.assertEqual(request('/healthz')[0],'200 OK')
            self.assertIn('هزینه'.encode(),request('/')[1])
            self.assertEqual(request('/','HEAD')[1],b'')
            self.assertEqual(request('/','POST')[0],'405 Method Not Allowed')
            self.assertEqual(request('/../../etc/passwd')[0],'404 Not Found')
            path.write_text('{')
            self.assertEqual(request('/api/fees')[0],'503 Service Unavailable')
