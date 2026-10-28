import json
import tempfile
import unittest
from pathlib import Path
from server import load_snapshot

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'fees.json'
        self.row = dict(exchange='nobitex',asset='USDT',network='TRC20',fee='1.25',fee_currency='USDT',minimum=None,withdrawal_enabled=False,source='https://example.com/fees',updated_at='2026-01-01T00:00:00Z')
    def write(self,rows):
        self.path.write_text(json.dumps(rows))
    def test_missing_is_empty(self):
        self.assertEqual(load_snapshot(self.path),[])
    def test_retains_precision_and_unknown(self):
        self.write([self.row]); row = load_snapshot(self.path)[0]
        self.assertEqual(row['fee'],'1.25'); self.assertIsNone(row['minimum']); self.assertFalse(row['withdrawal_enabled'])
    def test_rejects_invalid_amounts(self):
        for value in ['NaN','Infinity','-1',1.25]:
            with self.subTest(value=value):
                self.write([{**self.row,'fee':value}])
                with self.assertRaises(ValueError): load_snapshot(self.path)
    def test_rejects_duplicates(self):
        self.write([self.row,self.row])
        with self.assertRaises(ValueError): load_snapshot(self.path)
    def test_rejects_untraceable_data(self):
        self.write([{**self.row,'source':'http://example.com'}])
        with self.assertRaises(ValueError): load_snapshot(self.path)

if __name__ == '__main__': unittest.main()
