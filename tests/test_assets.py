import unittest
from assets import REQUESTED_ASSETS,selected_rows

class SelectedAssetsTests(unittest.TestCase):
    def test_exact_symbols_and_all_networks(self):
        rows=[dict(asset=a,network=n) for a,n in [('BTC','bitcoin'),('BTC','bsc'),('SHIBAI','ethereum'),('AMZN','ethereum'),('AMZNX','solana'),('TON','ton'),('TRON','tron')]]
        selected=selected_rows(rows)
        self.assertEqual([(r['asset'],r['network']) for r in selected],[('BTC','bitcoin'),('BTC','bsc'),('AMZNX','solana'),('TRX','tron')])
        self.assertEqual(len(REQUESTED_ASSETS),len(set(REQUESTED_ASSETS)))
    def test_scaled_shib_is_converted_once_and_input_unchanged(self):
        row=dict(asset='1K_SHIB',asset_scale='1000',fee_currency='1K_SHIB',fee='300.000000000000000000001',minimum='500')
        result=selected_rows([row])[0]
        self.assertEqual(result['asset'],'SHIB')
        self.assertEqual(result['fee'],'300000.000000000000000001000')
        self.assertEqual(result['minimum'],'500000')
        self.assertEqual(result['fee_currency'],'SHIB')
        self.assertEqual(selected_rows([result]),[result])
        self.assertEqual(row['asset'],'1K_SHIB')
    def test_unknown_shib_unit_rejected(self):
        with self.assertRaises(ValueError):selected_rows([dict(asset='1K_SHIB',asset_scale='1')])
