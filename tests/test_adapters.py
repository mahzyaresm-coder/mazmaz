from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
from adapters import parse_tabdeal_api,parse_wallex,parse_nobitex,parse_bitpin
from collector import now
from server import validate_rows

FIXTURES=Path(__file__).parent/'fixtures'
class AdapterTests(unittest.TestCase):
    def test_tabdeal_live_hides_invisible_networks(self):
        rows=parse_tabdeal_api((FIXTURES/'tabdeal-api.json').read_text(),now())
        validate_rows(rows)
        usdt={r['network']:r for r in rows if r['asset']=='USDT'}
        self.assertEqual(len(usdt),4)
        self.assertEqual(usdt['tron']['minimum'],'5.5')
        self.assertEqual(usdt['bsc']['fee'],'1.1')
        self.assertIsNone(usdt['tron']['withdrawal_enabled'])
    def test_wallex_network_state_and_minimum_match_page(self):
        rows=parse_wallex((FIXTURES/'wallex.json').read_text(),now())
        validate_rows(rows)
        usdt={r['network']:r for r in rows if r['asset']=='USDT'}
        self.assertEqual(usdt['bsc']['fee'],'0.8')
        self.assertEqual(usdt['bsc']['minimum'],'5.0')
        self.assertFalse(usdt['tron']['withdrawal_enabled'])
        self.assertTrue(usdt['bsc']['withdrawal_enabled'])
        self.assertFalse(any(r['asset']=='TMN' for r in rows))
    def test_nobitex_flight_preserves_source_time(self):
        rows=parse_nobitex((FIXTURES/'nobitex.html').read_text(),now())
        validate_rows(rows)
        usdt={r['network']:r for r in rows if r['asset']=='USDT'}
        self.assertEqual(usdt['bsc']['fee'],'0.7')
        self.assertFalse(usdt['arbitrum']['withdrawal_enabled'])
        self.assertFalse(any(r['asset']=='IRT' for r in rows))
        self.assertNotEqual(usdt['bsc']['updated_at'],usdt['bsc']['fetched_at'])
    def test_changed_schemas_rejected(self):
        for parser in [parse_tabdeal_api,parse_wallex,parse_nobitex,parse_bitpin]:
            with self.subTest(parser=parser.__name__):
                with self.assertRaises((ValueError,KeyError,TypeError)):parser('{}',now())

    def test_bitpin_uses_network_fee_and_maintenance(self):
        rows=parse_bitpin((FIXTURES/'bitpin.json').read_text(),now())
        validate_rows(rows)
        lookup={r['network']:r for r in rows}
        self.assertEqual(lookup['bitcoin']['fee'],'0.00008000')
        self.assertNotEqual(lookup['bitcoin']['fee'],'0.003000000000000000')
        self.assertFalse(lookup['bitcoin-lightning']['withdrawal_enabled'])

    def test_bitpin_pagination_complete_and_external_next_rejected(self):
        from collector import fetch_bitpin_pages,SourceError
        sample=json.loads((FIXTURES/'bitpin.json').read_text())
        first={**sample,'results':sample['results'][:1],'next':'https://api.bitpin.ir/v1/mkt/network_settings/?page=2'}
        second={**sample,'results':sample['results'][1:],'next':None}
        full=fetch_bitpin_pages(lambda u:json.dumps(second if 'page=2' in u else first))
        self.assertEqual(len(json.loads(full)['results']),2)
        with self.assertRaises(SourceError):
            fetch_bitpin_pages(lambda u:json.dumps({**first,'next':'https://example.com/'}))
        with self.assertRaises(SourceError):
            fetch_bitpin_pages(lambda u:json.dumps({**sample,'count':3}))
