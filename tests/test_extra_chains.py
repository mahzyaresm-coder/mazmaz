"""Synthetic native/SPL protocol fixtures; never published as live samples."""
from datetime import datetime,timezone
import unittest
from extra_chains import solana_kind,sample_solana,SYSTEM,SPL,COMPUTE,SOLANA_MINTS,sample_xrp,sample_stellar,sample_blockcypher
from chain_fees import collect
from networks import canonical_network

class ExtraChainTests(unittest.TestCase):
    def test_exchange_aliases_require_unambiguous_labels(self):
        self.assertEqual(canonical_network('bitpin','BNB','BNB Smart Chain BSC (BEP20)','bitpin:BNB'),'bsc')
        self.assertEqual(canonical_network('bitpin','BNB','BNB Beacon Chain','bitpin:BNB'),'bitpin:BNB')
        self.assertEqual(canonical_network('bitpin','AVAX','آوالانچ (سی چین)','bitpin:AVAX'),'avalanche-c')
    def test_solana_checked_token_native_and_batch(self):
        tx={'meta':{'err':None},'transaction':{'message':{'instructions':[{'programId':SPL,'parsed':{'type':'transferChecked','info':{'mint':SOLANA_MINTS['USDT'],'tokenAmount':{'amount':'100'}}}}]}}}
        self.assertEqual(solana_kind(tx,{'USDT':None}),'USDT')
        self.assertIsNone(solana_kind(tx,{'USDC':None}))
        tx['transaction']['message']['instructions'].append({'programId':SYSTEM,'parsed':{'type':'transfer','info':{'lamports':100}}})
        self.assertIsNone(solana_kind(tx,{'USDT':None,'SOL':None}))
    def test_solana_actual_lamport_fee_includes_priority(self):
        tx={'meta':{'err':None,'fee':6000},'transaction':{'signatures':['2'*88],'message':{'instructions':[{'programId':COMPUTE},{'programId':SYSTEM,'parsed':{'type':'transfer','info':{'lamports':100}}}]}}}
        class Fake:
            def rpc(self,method,params):
                if method=='getSlot':return 100
                return {'blockTime':int(datetime.now(timezone.utc).timestamp()),'transactions':[tx]}
        result=sample_solana({'SOL':None},Fake())['SOL']
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['fee'],'0.000006')
    def test_xrp_fee_is_drops_and_issued_currency_payment_excluded(self):
        stamp=int(datetime.now(timezone.utc).timestamp())-946684800
        tx={'hash':'a'*64,'TransactionType':'Payment','Amount':'1000000','Fee':'12','metaData':{'TransactionResult':'tesSUCCESS'}}
        class Fake:
            def request(self,path='',payload=None):return {'result':{'status':'success','validated':True,'ledger':{'ledger_index':str(100 if payload['params'][0]['ledger_index']=='validated' else payload['params'][0]['ledger_index']),'close_time':stamp,'transactions':[tx]}}}
        self.assertEqual(sample_xrp(Fake())['XRP'][0]['fee'],'0.000012')
        tx['Amount']={'currency':'USD','value':'1'}
        self.assertEqual(sample_xrp(Fake())['XRP'],[])
    def test_stellar_stroops_and_successful_simple_native_payment(self):
        class Fake:
            def request(self,path):
                if '/operations' in path:return {'_embedded':{'records':[{'type':'payment','asset_type':'native','transaction_successful':True}]}}
                return {'_embedded':{'records':[{'successful':True,'operation_count':1,'hash':'a'*64,'created_at':datetime.now(timezone.utc).isoformat(),'fee_charged':'100','ledger':100}]}}
        self.assertEqual(sample_stellar(Fake())['XLM'][0]['fee'],'0.00001')
    def test_utxo_native_fee_and_change_not_batch(self):
        stamp=datetime.now(timezone.utc).isoformat()
        class Fake:
            def request(self,path=''):
                if not path:return {'height':100}
                if path.startswith('/blocks'):return {'height':int(path.split('/')[2].split('?')[0]),'hash':'b'*64,'time':stamp,'txids':['a'*64]}
                return {'hash':'a'*64,'block_hash':'b'*64,'block_height':100,'fees':1000,'inputs':[{'addresses':['sender'],'prev_hash':'c'*64}],'outputs':[{'addresses':['recipient'],'value':1},{'addresses':['sender'],'value':1}]}
        self.assertEqual(sample_blockcypher('LTC',Fake())['LTC'][0]['fee'],'0.00001')
    def test_unsupported_stock_mint_remains_explicit(self):
        result=collect([dict(asset='TSLAX',network='solana')])
        self.assertEqual(result[0]['reason'],'verified_token_identity_missing')
    def test_arbitrum_parent_chain_gas_included_once(self):
        from chain_fees import evm_sample
        tx={'hash':'0x'+'a'*64,'to':'0x'+'1'*40,'input':'0x','value':'0x1','type':'0x2','blockHash':'0x'+'b'*64,'blockNumber':'0x64'}
        receipt={'transactionHash':tx['hash'],'blockHash':tx['blockHash'],'blockNumber':tx['blockNumber'],
            'status':'0x1','gasUsed':hex(21500),'gasUsedForL1':hex(500),'effectiveGasPrice':hex(1000000000)}
        result=evm_sample(tx,receipt,'ETH','ETH',datetime.now(timezone.utc).isoformat(),'https://arbiscan.io/tx/','arbitrum')
        self.assertEqual(result['fee'],'0.0000215')
        receipt.pop('gasUsedForL1')
        with self.assertRaises(KeyError):evm_sample(tx,receipt,'ETH','ETH',datetime.now(timezone.utc).isoformat(),'https://arbiscan.io/tx/','arbitrum')
