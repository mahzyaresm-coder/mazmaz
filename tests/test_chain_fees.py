"""Synthetic protocol fixtures; these are never published as live chain samples."""
from datetime import datetime,timezone
from decimal import Decimal
import unittest
from chain_fees import (USDT_TRON,TRANSFER_TOPIC,tron_hex,tron_kind,tron_sample,
    evm_candidate,evm_sample,summarize,collect,sample_tron,sample_evm,now)

HASH='a'*64
RECIPIENT='0'*24+'1'*40
AMOUNT='0'*63+'1'
DATA='a9059cbb'+RECIPIENT+AMOUNT
STAMP=int(datetime.now(timezone.utc).timestamp()*1000)

def tron_tx():
    return {'txID':HASH,'ret':[{'contractRet':'SUCCESS'}],'raw_data':{'contract':[{
        'type':'TriggerSmartContract','parameter':{'value':{'contract_address':tron_hex(USDT_TRON),'data':DATA}}}]}}

def tron_receipt(fee=1234567):
    return {'id':HASH,'blockNumber':100,'blockTimeStamp':STAMP,'fee':fee,'receipt':{'result':'SUCCESS'},
        'log':[{'address':tron_hex(USDT_TRON)[2:],'topics':[TRANSFER_TOPIC,'0'*64,RECIPIENT],'data':AMOUNT}]}

class ChainFeeTests(unittest.TestCase):
    def test_tron_real_fee_in_sun_and_token_identity(self):
        tx=tron_tx();receipt=tron_receipt()
        self.assertEqual(tron_kind(tx),'USDT')
        self.assertEqual(tron_sample(tx,receipt,'USDT')['fee'],'1.234567')
        tx['raw_data']['contract'][0]['parameter']['value']['contract_address']='41'+'2'*40
        self.assertIsNone(tron_kind(tx))
    def test_swap_revert_batch_and_unemitted_transfer_are_not_samples(self):
        tx=tron_tx();tx['raw_data']['contract'][0]['parameter']['value']['data']='deadbeef'+DATA[8:]
        self.assertIsNone(tron_kind(tx))
        tx=tron_tx();tx['ret'][0]['contractRet']='REVERT'
        self.assertIsNone(tron_kind(tx))
        tx=tron_tx();tx['raw_data']['contract']*=2
        self.assertIsNone(tron_kind(tx))
        receipt=tron_receipt();receipt['log']=[]
        self.assertIsNone(tron_sample(tron_tx(),receipt,'USDT'))
        receipt=tron_receipt();receipt['receipt']['result']='OUT_OF_ENERGY'
        self.assertIsNone(tron_sample(tron_tx(),receipt,'USDT'))
    def test_tron_successful_resource_funded_transaction_preserves_zero(self):
        receipt=tron_receipt();receipt.pop('fee')
        self.assertEqual(tron_sample(tron_tx(),receipt,'USDT')['fee'],'0')
        receipt.pop('receipt')
        self.assertIsNone(tron_sample(tron_tx(),receipt,'USDT'))
    def test_mean_uses_actual_count_including_zero(self):
        samples=[]
        for index,units in enumerate([0,1000000,2000000]):
            sample=tron_sample(tron_tx(),tron_receipt(units),'USDT');sample['txid']=str(index)*64;samples.append(sample)
        result=summarize('USDT','tron','TRX',6,samples,now())
        self.assertEqual(Decimal(result['average_fee']),Decimal('1'))
        self.assertEqual(result['sample_count'],3)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['zero_fee_count'],1)
        self.assertIsNone(summarize('USDT','tron','TRX',6,[],now())['average_fee'])
        with self.assertRaises(ValueError):summarize('USDT','tron','TRX',6,[samples[0]]*2,now())
    def test_evm_actual_gas_not_gas_limit_or_max_fee(self):
        tx={'hash':'0x'+HASH,'to':'0x'+'1'*40,'value':'0x1','input':'0x','type':'0x2',
            'blockHash':'0x'+'2'*64,'blockNumber':'0x64','gas':'0xffff','maxFeePerGas':'0xffffff'}
        receipt={'transactionHash':tx['hash'],'blockHash':tx['blockHash'],'blockNumber':tx['blockNumber'],
            'status':'0x1','gasUsed':hex(21000),'effectiveGasPrice':hex(1000000000)}
        self.assertEqual(evm_candidate(tx,{'ETH':None},'ETH'),'ETH')
        result=evm_sample(tx,receipt,'ETH','ETH',now(),'https://etherscan.io/tx/')
        self.assertEqual(Decimal(result['fee']),Decimal('0.000021'))
        receipt['gasUsed']=hex(50000)
        self.assertIsNone(evm_sample(tx,receipt,'ETH','ETH',now(),'https://etherscan.io/tx/'))
        receipt['gasUsed']=hex(21000);receipt.pop('effectiveGasPrice')
        with self.assertRaises(ValueError):evm_sample(tx,receipt,'ETH','ETH',now(),'https://etherscan.io/tx/')
    def test_errors_preserve_timestamp_and_unsupported_is_not_zero(self):
        old={'asset':'USDT','network':'tron','average_fee':'1.2','sample_count':10,'updated_at':now(),'samples':[]}
        rows=[{'asset':'USDT','network':'tron'},{'asset':'USDT','network':'ton'}]
        def offline(targets):raise OSError('offline')
        result=collect(rows,[old],{'tron':offline})
        tron=next(r for r in result if r['network']=='tron')
        self.assertEqual(tron['status'],'error');self.assertEqual(tron['average_fee'],'1.2')
        self.assertEqual(tron['updated_at'],old['updated_at'])
        other=next(r for r in result if r['network']=='ton')
        self.assertEqual(other['status'],'unsupported');self.assertIsNone(other['average_fee'])
    def test_tron_sampling_stops_at_ten_and_checks_block(self):
        transactions=[]
        receipts={}
        for i in range(12):
            tx=tron_tx();tx['txID']=f'{i:064x}';transactions.append(tx)
            receipt=tron_receipt();receipt['id']=tx['txID'];receipts[tx['txID']]=receipt
        class Fake:
            def request(self,path,payload):
                if path.endswith('getnowblock'):return {'block_header':{'raw_data':{'number':100,'timestamp':STAMP}},'transactions':transactions}
                return receipts[payload['value']]
        sampled=sample_tron(['USDT'],Fake())
        self.assertEqual(len(sampled['USDT']),10)
        self.assertEqual(len({s['txid'] for s in sampled['USDT']}),10)
    def test_no_unverified_evm_token_or_rollup_fee(self):
        rows=[{'asset':'UNKNOWN','network':'ethereum'},{'asset':'USDT','network':'optimism'}]
        result=collect(rows)
        self.assertTrue(all(r['status']=='unsupported' for r in result))
    def test_bitcoin_batch_and_coinbase_excluded_and_satoshi_units(self):
        from chain_fees import sample_bitcoin
        class Fake:
            def request(self,path):
                if path=='/api/blocks':return [{'id':HASH,'timestamp':STAMP//1000,'height':100,'tx_count':12}]
                result=[]
                for i in range(10):
                    result.append({'txid':f'{i:064x}','fee':1000,'vin':[{'prevout':{'scriptpubkey_address':'sender'}}],
                        'vout':[{'value':1,'scriptpubkey_address':'recipient'},{'value':10,'scriptpubkey_address':'sender'}],
                        'status':{'confirmed':True,'block_hash':HASH}})
                result.append({'vin':[{'is_coinbase':True}],'vout':[]})
                result.append({'vin':[{'prevout':{'scriptpubkey_address':'sender'}}],
                    'vout':[{'value':1,'scriptpubkey_address':'one'},{'value':2,'scriptpubkey_address':'two'}]})
                return result
        samples=sample_bitcoin(Fake())['BTC']
        self.assertEqual(len(samples),10)
        self.assertEqual(samples[0]['fee'],'0.00001')
    def test_erc20_receipt_must_include_matching_transfer_log(self):
        token='0x'+'1'*40
        tx={'hash':'0x'+HASH,'to':token,'value':'0x0','input':'0x'+DATA,'type':'0x2',
            'blockHash':'0x'+'2'*64,'blockNumber':'0x64'}
        receipt={'transactionHash':tx['hash'],'blockHash':tx['blockHash'],'blockNumber':tx['blockNumber'],
            'status':'0x1','gasUsed':hex(60000),'effectiveGasPrice':hex(1000000000),
            'logs':[{'address':token,'topics':['0x'+TRANSFER_TOPIC,'0x'+'0'*64,'0x'+RECIPIENT],'data':'0x'+AMOUNT}]}
        self.assertEqual(evm_candidate(tx,{'USDT':token},'ETH'),'USDT')
        result=evm_sample(tx,receipt,'USDT','ETH',now(),'https://etherscan.io/tx/')
        self.assertEqual(Decimal(result['fee']),Decimal('0.00006'))
        receipt['logs'][0]['topics'][2]='0x'+'2'*64
        self.assertIsNone(evm_sample(tx,receipt,'USDT','ETH',now(),'https://etherscan.io/tx/'))
    def test_full_sample_and_no_new_samples_keep_previous_statistic(self):
        samples=[]
        for index in range(10):
            sample=tron_sample(tron_tx(),tron_receipt(1000000),'USDT');sample['txid']=f'{index:064x}';samples.append(sample)
        full=summarize('USDT','tron','TRX',6,samples,now())
        self.assertEqual(full['status'],'ok')
        rows=[dict(asset='USDT',network='tron')]
        result=collect(rows,[full],{'tron':lambda _: {'USDT':[]}})[0]
        self.assertEqual(result['status'],'error')
        self.assertEqual(result['updated_at'],full['updated_at'])
        self.assertEqual(result['samples'],samples)
    def test_screenshot_fee_conversion_does_not_charge_consumed_energy(self):
        receipt=tron_receipt(348600)
        receipt['receipt'].update(energy_usage_total=130279,energy_fee=0,net_fee=348600)
        sample=tron_sample(tron_tx(),receipt,'USDT')
        self.assertEqual(sample['fee'],'0.3486')
        self.assertEqual(sample['energy_fee'],'0')
        self.assertEqual(sample['bandwidth_fee'],'0.3486')
        self.assertEqual(sample['energy_consumed'],130279)
        receipt.pop('fee');receipt['receipt']['energy_fee']=1000000
        with self.assertRaises(ValueError):tron_sample(tron_tx(),receipt,'USDT')
    def test_mean_exposes_total_and_spread_without_excluding_high_fees(self):
        # Hypothetical distribution, NOT the website's actual 10 transactions.
        samples=[]
        for index,units in enumerate([348600]*9+[24473100]):
            sample=tron_sample(tron_tx(),tron_receipt(units),'USDT');sample['txid']=f'{index:064x}';samples.append(sample)
        result=summarize('USDT','tron','TRX',6,samples,now())
        self.assertEqual(Decimal(result['average_fee']),Decimal('2.76105'))
        self.assertEqual(result['total_fee'],'27.6105')
        self.assertEqual(result['minimum_fee'],'0.3486')
        self.assertEqual(result['maximum_fee'],'24.4731')
        self.assertEqual(result['median_fee'],'0.3486')
