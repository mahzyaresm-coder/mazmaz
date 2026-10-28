"""Read-only samples of actual fees from comparable confirmed transfers.

Supported: native BTC; native TRX and verified USDT TRC20; native and
verified ERC20 tokens on Ethereum/BSC. No broadcasting or wallet access.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from urllib.error import HTTPError, URLError

TARGET=10
MAX_AGE_SECONDS=86400
USDT_TRON='TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
TRANSFER_TOPIC='ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
EVM={
 'ethereum':dict(url='https://ethereum-rpc.publicnode.com',chain_id=1,unit='ETH',asset='ETH',explorer='https://etherscan.io/tx/'),
 'bsc':dict(url='https://bsc-rpc.publicnode.com',chain_id=56,unit='BNB',asset='BNB',explorer='https://bscscan.com/tx/'),
}

def now():return datetime.now(timezone.utc).isoformat()

def timestamp(milliseconds):
    if type(milliseconds) is not int or milliseconds<=0:raise ValueError('Invalid chain timestamp')
    dt=datetime.fromtimestamp(milliseconds/1000,timezone.utc)
    age=(datetime.now(timezone.utc)-dt).total_seconds()
    if age < -60 or age>MAX_AGE_SECONDS:raise ValueError('Chain sample timestamp out of range')
    return dt.isoformat()

def integer(value):
    if type(value) is not int or value<0:raise ValueError('Invalid fee integer')
    return value

def hexint(value):
    if not isinstance(value,str) or not re.fullmatch(r'0x[0-9a-fA-F]+',value):raise ValueError('Invalid RPC integer')
    return int(value,16)

def txhash(value):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}',value):raise ValueError('Invalid transaction hash')
    return value.lower()

def money(units,decimals):
    with localcontext() as ctx:
        ctx.prec=80
        return format(Decimal(units)/(10**decimals),'f')

class Client:
    """Per-provider pacing, TLS verification and bounded read-only requests."""
    def __init__(self,base,pace=0.65):self.base=base;self.last=0;self.pace=pace
    def request(self,path='',payload=None):
        delay=self.pace-(time.monotonic()-self.last)
        if delay>0:time.sleep(delay)
        headers={'Accept':'application/json','User-Agent':'MazmazFeeMonitor/0.2'}
        if self.base=='https://api.trongrid.io' and os.environ.get('TRONGRID_API_KEY'):
            headers['TRON-PRO-API-KEY']=os.environ['TRONGRID_API_KEY']
        body=None if payload is None else json.dumps(payload).encode()
        if body is not None:headers['Content-Type']='application/json'
        request=urllib.request.Request(self.base+path,data=body,headers=headers)
        self.last=time.monotonic()
        with urllib.request.urlopen(request,timeout=15) as response:
            data=response.read(12_000_001)
            if len(data)>12_000_000:raise ValueError('Oversize chain response')
            return json.loads(data)
    def rpc(self,method,params):
        response=self.request(payload={'jsonrpc':'2.0','id':1,'method':method,'params':params})
        if response.get('error') or 'result' not in response:raise ValueError('RPC error')
        return response['result']


def tron_hex(address):
    if re.fullmatch(r'41[0-9a-fA-F]{40}',address or ''):return address.lower()
    alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    value=0
    for char in address:value=value*58+alphabet.index(char)
    raw=value.to_bytes((value.bit_length()+7)//8,'big')
    if len(raw)!=25 or raw[0]!=65 or hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4]!=raw[-4:]:
        raise ValueError('Invalid Tron address')
    return raw[:-4].hex()


def tron_kind(tx):
    contracts=tx.get('raw_data',{}).get('contract',[])
    ret=tx.get('ret',[])
    if len(contracts)!=1 or len(ret)!=1 or ret[0].get('contractRet')!='SUCCESS':return None
    contract=contracts[0];value=contract.get('parameter',{}).get('value',{})
    if contract.get('type')=='TransferContract' and type(value.get('amount')) is int and value['amount']>0:
        return 'TRX'
    if contract.get('type')!='TriggerSmartContract' or value.get('call_value',0)!=0:return None
    if tron_hex(value.get('contract_address',''))!=tron_hex(USDT_TRON):return None
    data=value.get('data','').lower()
    if not re.fullmatch(r'a9059cbb[0-9a-f]{128}',data) or int(data[-64:],16)<=0:return None
    return 'USDT'


def tron_sample(tx,info,asset):
    ident=txhash(tx['txID'])
    if info.get('id')!=ident or not info.get('blockNumber'):return None
    receipt=info.get('receipt')
    if not isinstance(receipt,dict) or receipt.get('result','SUCCESS')!='SUCCESS':return None
    if info.get('result','SUCESS') not in ['SUCESS','SUCCESS']:return None
    if asset=='USDT':
        value=tx['raw_data']['contract'][0]['parameter']['value'];data=value['data'].lower()
        contract=tron_hex(USDT_TRON)[2:]
        if not any(log.get('address','').lower()==contract and len(log.get('topics',[]))==3 and log['topics'][0]==TRANSFER_TOPIC
                   and log['topics'][2].lower()==data[8:72] and log.get('data','').lower()==data[-64:] for log in info.get('log',[])):
            return None
    # TransactionInfo is protobuf JSON: the omitted scalar `fee` defaults to zero.
    # Accept that default only for this fully identified successful confirmed receipt.
    units=integer(info.get('fee',0))
    energy_paid=integer(receipt.get('energy_fee',0))
    bandwidth_paid=integer(receipt.get('net_fee',0))
    if units < energy_paid+bandwidth_paid:
        raise ValueError('Inconsistent Tron paid fee components')
    return dict(txid=ident,fee=money(units,6),fee_base_units=units,
        energy_fee=money(energy_paid,6),bandwidth_fee=money(bandwidth_paid,6),
        other_fee=money(units-energy_paid-bandwidth_paid,6),
        energy_consumed=integer(receipt.get('energy_usage_total',0)),
        block_number=integer(info['blockNumber']),timestamp=timestamp(info['blockTimeStamp']),
        url='https://tronscan.org/#/transaction/'+ident)


def sample_tron(assets,client=None):
    client=client or Client('https://api.trongrid.io',pace=1.1)
    found={asset:[] for asset in assets};seen=set();reads=0;deadline=time.monotonic()+180
    block=client.request('/walletsolidity/getnowblock',{})
    head=integer(block['block_header']['raw_data']['number'])
    timestamp(block['block_header']['raw_data']['timestamp'])
    for offset in range(8):
        if offset:block=client.request('/walletsolidity/getblockbynum',{'num':head-offset})
        if block['block_header']['raw_data']['number']!=head-offset:raise ValueError('Wrong Tron block')
        for tx in reversed(block.get('transactions',[])):
            asset=tron_kind(tx)
            if asset not in found or len(found[asset])>=TARGET:continue
            ident=txhash(tx['txID'])
            if ident in seen:continue
            seen.add(ident)
            reads+=1
            if reads>80 or time.monotonic()>deadline:return found
            info=client.request('/walletsolidity/gettransactioninfobyid',{'value':ident})
            if info.get('blockNumber')!=head-offset:raise ValueError('Wrong Tron receipt block')
            sample=tron_sample(tx,info,asset)
            if sample:found[asset].append(sample)
        if all(len(v)>=TARGET for v in found.values()):break
    return found


def evm_candidate(tx,targets,native):
    if tx.get('type','0x0') not in ['0x0','0x1','0x2']:return None
    if not tx.get('to') or hexint(tx.get('value','0x0'))<0:return None
    data=tx.get('input','').lower();address=tx['to'].lower()
    if data in ['','0x'] and hexint(tx.get('value','0x0'))>0 and native in targets:return native
    if hexint(tx.get('value','0x0'))!=0 or not re.fullmatch(r'0xa9059cbb[0-9a-f]{128}',data):return None
    if int(data[-64:],16)<=0:return None
    for asset,contract in targets.items():
        if contract and contract.lower()==address:return asset
    return None


def evm_sample(tx,receipt,asset,native,stamp,explorer):
    ident=txhash(tx['hash'])
    if not receipt or receipt.get('transactionHash','').lower()!=ident or hexint(receipt['status'])!=1:return None
    if receipt.get('blockHash')!=tx.get('blockHash') or receipt.get('blockNumber')!=tx.get('blockNumber'):
        raise ValueError('Receipt does not match block')
    gas=hexint(receipt['gasUsed'])
    if asset==native:
        if gas!=21000:return None  # no contract execution / batch transfers
    else:
        data=tx['input'].lower()
        if not any(log.get('address','').lower()==tx['to'].lower() and len(log.get('topics',[]))==3
                   and log['topics'][0].lower()=='0x'+TRANSFER_TOPIC
                   and log['topics'][2].lower()=='0x'+data[10:74] and log.get('data','').lower()=='0x'+data[-64:] for log in receipt.get('logs',[])):
            return None
    price=receipt.get('effectiveGasPrice')
    if price is None:
        if tx.get('type','0x0') not in ['0x0','0x1']:raise ValueError('Actual gas price missing')
        price=tx['gasPrice']
    units=gas*hexint(price)
    return dict(txid=ident,fee=money(units,18),fee_base_units=units,
        block_number=hexint(receipt['blockNumber']),timestamp=stamp,url=explorer+ident)


def sample_evm(network,targets,client=None):
    config=EVM[network];client=client or Client(config['url'])
    if hexint(client.rpc('eth_chainId',[]))!=config['chain_id']:raise ValueError('Wrong chain ID')
    if network=='ethereum':
        block=client.rpc('eth_getBlockByNumber',['finalized',True]);head=hexint(block['number'])
    else:
        head=hexint(client.rpc('eth_blockNumber',[]))-20
        block=client.rpc('eth_getBlockByNumber',[hex(head),True])
    found={asset:[] for asset in targets};seen=set();reads=0;deadline=time.monotonic()+180
    for offset in range(8):
        if offset:block=client.rpc('eth_getBlockByNumber',[hex(head-offset),True])
        if not block or hexint(block['number'])!=head-offset:raise ValueError('Wrong EVM block')
        stamp=timestamp(hexint(block['timestamp'])*1000)
        for tx in reversed(block.get('transactions',[])):
            asset=evm_candidate(tx,targets,config['asset'])
            if asset not in found or len(found[asset])>=TARGET:continue
            ident=txhash(tx['hash'])
            if ident in seen:continue
            seen.add(ident);reads+=1
            if reads>80 or time.monotonic()>deadline:return found
            receipt=client.rpc('eth_getTransactionReceipt',[ident])
            sample=evm_sample(tx,receipt,asset,config['asset'],stamp,config['explorer'])
            if sample:found[asset].append(sample)
        if all(len(v)>=TARGET for v in found.values()):break
    return found


def sample_bitcoin(client=None):
    client=client or Client('https://mempool.space',pace=0.35)
    blocks=client.request('/api/blocks');found=[];seen=set()
    for block in blocks[:3]:
        ident=txhash(block['id']);stamp=timestamp(integer(block['timestamp'])*1000)
        count=integer(block['tx_count'])
        transactions=[]
        last_page=((max(count,1)-1)//25)*25
        for page in range(last_page,max(-1,last_page-50),-25):
            transactions.extend(reversed(client.request('/api/block/'+ident+'/txs/'+str(page))))
        for tx in transactions:
            inputs=tx.get('vin',[]);outputs=tx.get('vout',[])
            if not 1<=len(inputs)<=2 or not 1<=len(outputs)<=2 or any(i.get('is_coinbase') for i in inputs):continue
            if any(not o.get('scriptpubkey_address') or o.get('value',0)<=0 for o in outputs):continue
            owners={i.get('prevout',{}).get('scriptpubkey_address') for i in inputs}
            if None in owners or len(owners)!=1:continue
            recipients={o.get('scriptpubkey_address') for o in outputs if o.get('value',0)>0}-owners
            if len(recipients)!=1 or None in recipients:continue
            status=tx.get('status',{})
            if status.get('confirmed') is not True or status.get('block_hash')!=ident:continue
            transaction=txhash(tx['txid'])
            if transaction in seen:continue
            seen.add(transaction);units=integer(tx['fee'])
            found.append(dict(txid=transaction,fee=money(units,8),fee_base_units=units,
                block_number=integer(block['height']),timestamp=stamp,url='https://mempool.space/tx/'+transaction))
            if len(found)>=TARGET:return {'BTC':found}
    return {'BTC':found}


def summarize(asset,network,unit,decimals,samples,attempt):
    samples=sorted(samples,key=lambda s:(s['block_number'],s['timestamp']),reverse=True)[:TARGET]
    ids=[s['txid'] for s in samples]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate fee samples')
    count=len(samples)
    average=None
    total=minimum=maximum=median=None
    if count:
        with localcontext() as ctx:
            ctx.prec=80
            values=sorted(integer(s['fee_base_units']) for s in samples)
            total=money(sum(values),decimals)
            minimum=money(values[0],decimals);maximum=money(values[-1],decimals)
            midpoint=Decimal(values[count//2]) if count%2 else (Decimal(values[count//2-1])+Decimal(values[count//2]))/2
            median=format(midpoint/(10**decimals),'f')
            average=format((Decimal(sum(values))/count/(10**decimals)).quantize(Decimal(1).scaleb(-decimals-4)),'f')
    newest=max((s['timestamp'] for s in samples),default=None)
    stale=newest and (datetime.now(timezone.utc)-datetime.fromisoformat(newest)).total_seconds()>3600
    return dict(asset=asset,network=network,status='stale' if stale else 'ok' if count==TARGET else 'partial' if count else 'unavailable',
        fee_currency=unit,average_fee=average,total_fee=total,minimum_fee=minimum,maximum_fee=maximum,median_fee=median,sample_count=count,target_count=TARGET,
        zero_fee_count=sum(s['fee_base_units']==0 for s in samples),samples=samples,
        sampled_from=min((s['timestamp'] for s in samples),default=None),sampled_to=max((s['timestamp'] for s in samples),default=None),
        updated_at=attempt if count else None,last_attempt=attempt,
        method='recent_confirmed_simple_transfers',max_sample_age_seconds=MAX_AGE_SECONDS)


def collect(rows,previous=(),samplers=None):
    """An unavailable chain never blocks publishing exchange fees."""
    groups={};unavailable=[];old={(r['asset'],r['network']):r for r in previous}
    pairs=sorted({(r['asset'],r['network']) for r in rows});attempt=now()
    for asset,network in pairs:
        contract=None
        supported=(network=='tron' and asset in ['USDT','TRX']) or (network=='bitcoin' and asset=='BTC')
        if network in EVM:
            if asset==EVM[network]['asset']:supported=True
            else:
                addresses={r['contract_address'].lower() for r in rows if r['asset']==asset and r['network']==network
                    and isinstance(r.get('contract_address'),str) and re.fullmatch('0x[0-9a-fA-F]{40}',r['contract_address'])}
                if len(addresses)==1:contract=next(iter(addresses));supported=True
        if supported:groups.setdefault(network,{})[asset]=contract
        else:unavailable.append(dict(asset=asset,network=network,status='unsupported',sample_count=0,
            target_count=TARGET,average_fee=None,samples=[],updated_at=None,last_attempt=attempt,
            reason='verified_token_identity_missing' if network in EVM else 'sampler_not_available'))
    def sample_group(item):
        network,targets=item
        unit,decimals=(EVM[network]['unit'],18) if network in EVM else (None,None)
        if network=='tron':unit,decimals='TRX',6
        elif network=='bitcoin':unit,decimals='BTC',8
        try:
            if samplers and network in samplers:sampled=samplers[network](targets)
            elif network=='tron':sampled=sample_tron(targets)
            elif network=='bitcoin':sampled=sample_bitcoin()
            else:sampled=sample_evm(network,targets)
            result=[summarize(asset,network,unit,decimals,sampled.get(asset,[]),attempt) for asset in targets]
            # No new valid samples must not erase a previous mean or make it fresh.
            for index,entry in enumerate(result):
                key=(entry['asset'],network)
                if not entry['sample_count'] and old.get(key,{}).get('sample_count'):
                    result[index]={**old[key],'status':'error','last_attempt':attempt,'error':'no_valid_recent_samples'}
            logging.info('Blockchain %s: %s',network,{r['asset']:r['sample_count'] for r in result})
            return result
        except Exception as exc:
            error='http_'+str(exc.code) if isinstance(exc,HTTPError) else 'network_unavailable' if isinstance(exc,URLError) else 'invalid_provider_response'
            logging.warning('Blockchain %s unavailable (%s)',network,error)
            return [{**old.get((asset,network),dict(asset=asset,network=network,fee_currency=unit,
                sample_count=0,target_count=TARGET,average_fee=None,samples=[],updated_at=None)),
                'status':'error','last_attempt':attempt,'error':error} for asset in targets]
    if groups:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(sample_group,groups.items()):unavailable.extend(result)
    return sorted(unavailable,key=lambda r:(r['asset'],r['network']))
