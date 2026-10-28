from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from collector import parse_tabdeal,run_once,SourceError,atomic_json,now
from server import load_snapshot

FIXTURE = (Path(__file__).parent/'fixtures'/'tabdeal.html').read_text()

class CollectorTests(unittest.TestCase):
    def setUp(self):
        sampler = patch("chain_fees.collect", return_value=[])
        sampler.start()
        self.addCleanup(sampler.stop)
    def test_authentic_networks_and_minimum_as_rendered(self):
        rows = parse_tabdeal(FIXTURE,now())
        usdt = {r['network']:r for r in rows if r['asset']=='USDT'}
        self.assertEqual(len(usdt),4)
        self.assertEqual(usdt['tron']['fee'],'2.5')
        self.assertEqual(usdt['tron']['minimum'],'5.5')
        self.assertEqual(usdt['ethereum']['fee'],'5')
        self.assertIsNone(usdt['tron']['withdrawal_enabled'])
        self.assertLess(datetime.fromisoformat(usdt['tron']['updated_at']),datetime.now(timezone.utc))
    def test_changed_schema_fails_closed(self):
        with self.assertRaises(SourceError):parse_tabdeal('<h1>کارمزد معاملات صفر</h1>',now())
    def test_partial_failure_preserves_timestamps_and_old_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'fees.json'
            def first(url):
                if 'tabdeal.org' in url:return (Path(__file__).parent/'fixtures'/'tabdeal-api.json').read_text()
                raise urllib.error.URLError('blocked')
            first_result=run_once(path,first)
            self.assertEqual(first_result['sources']['tabdeal']['status'],'ok')
            self.assertEqual(len(load_snapshot(path)),5)
            def fail(url):raise urllib.error.URLError('offline')
            result=run_once(path,fail)
            self.assertEqual(result['rows'],first_result['rows'])
            self.assertEqual(result['sources']['tabdeal']['last_success'],first_result['sources']['tabdeal']['last_success'])
            self.assertEqual(result['sources']['tabdeal']['status'],'error')
    def test_parser_not_invented_for_uninspected_sources(self):
        from collector import collect_one
        _,rows,status=collect_one('efex',lambda u:FIXTURE)
        self.assertIsNone(rows)
        self.assertEqual(status['status'],'error')
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fees.json';atomic_json(p,{'rows':[]})
            self.assertEqual(json.loads(p.read_text()),{'rows':[]})
            self.assertEqual(len(list(Path(d).iterdir())),1)
