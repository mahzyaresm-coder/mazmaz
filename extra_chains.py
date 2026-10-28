"""Additional read-only native chain and canonical SPL token fee samplers."""
from datetime import datetime
import re
import time
from chain_fees import Client,RPCError,TARGET,integer,txhash,timestamp,money

# Source reviewed: solana-labs/token-list, mainnet chainId=101, matching
# coingeckoId tether / usd-coin. No unverified ticker-only token lookup.
SOLANA_MINTS={
 'USDT':'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
 'USDC':'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
}
SYSTEM='11111111111111111111111111111111'
COMPUTE='ComputeBudget111111111111111111111111111111'
SPL='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'


def solana_kind(transaction,targets):
    meta=transaction.get('meta')
    if not meta or meta.get('err') is not None:return None
    instructions=transaction['transaction']['message'].get('instructions',[])
    actions=[i for i in instructions if i.get('programId')!=COMPUTE]
    if len(actions)!=1:return None
    instruction=actions[0];parsed=instruction.get('parsed',{});info=parsed.get('info',{})
    if instruction.get('programId')==SYSTEM and parsed.get('type')=='transfer':
        return 'SOL' if 'SOL' in targets and type(info.get('lamports')) is int and info['lamports']>0 else None
    if instruction.get('programId')==SPL and parsed.get('type')=='transferChecked':
        amount=info.get('tokenAmount',{}).get('amount','')
        if not isinstance(amount,str) or not amount.isdigit() or int(amount)<=0:return None
        return next((asset for asset in targets if SOLANA_MINTS.get(asset)==info.get('mint')),None)
    return None


def sample_solana(targets,client=None):
    client=client or Client('https://api.mainnet-beta.solana.com',pace=1,max_bytes=32_000_000)
    slot=integer(client.rpc('getSlot',[{'commitment':'finalized'}]));found={a:[] for a in targets};seen=set()
    deadline=time.monotonic()+180
    for offset in range(5):
        try:
            block=client.rpc('getBlock',[slot-offset,{'commitment':'finalized','encoding':'jsonParsed',
                'transactionDetails':'full','maxSupportedTransactionVersion':0,'rewards':False}])
        except RPCError as exc:
            if exc.code in [-32004,-32007,-32009]:continue
            raise
        if block is None:continue
        stamp=timestamp(integer(block['blockTime'])*1000)
        for tx in reversed(block.get('transactions',[])):
            asset=solana_kind(tx,targets)
            if asset not in found or len(found[asset])>=TARGET:continue
            signature=tx['transaction']['signatures'][0]
            if not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{80,90}',signature):raise ValueError('Invalid Solana signature')
            if signature in seen:continue
            seen.add(signature);fee=integer(tx['meta']['fee'])
            found[asset].append(dict(txid=signature,fee=money(fee,9),fee_base_units=fee,
                block_number=slot-offset,timestamp=stamp,url='https://solscan.io/tx/'+signature))
        if all(len(v)>=TARGET for v in found.values()) or time.monotonic()>deadline:break
    return found


def decimal_integer(value):
    if not isinstance(value,str) or not value.isdigit():raise ValueError('Expected decimal integer')
    return int(value)


def sample_xrp(client=None):
    client=client or Client('https://xrplcluster.com',pace=1)
    found=[];seen=set();head=None
    for offset in range(4):
        payload=client.request(payload={'method':'ledger','params':[{'ledger_index':'validated' if head is None else head-offset,
            'transactions':True,'expand':True}]})['result']
        if payload.get('status')!='success' or payload.get('validated') is not True:raise ValueError('Unvalidated XRP ledger')
        ledger=payload['ledger'];height=decimal_integer(str(ledger['ledger_index']))
        if head is None:head=height
        if height!=head-offset:raise ValueError('Wrong XRP ledger')
        stamp=timestamp((integer(ledger['close_time'])+946684800)*1000)
        for entry in reversed(ledger.get('transactions',[])):
            tx=entry.get('tx_json',entry);meta=entry.get('metaData',entry.get('meta',{}))
            amount=tx.get('Amount',tx.get('DeliverMax'))
            if tx.get('TransactionType')!='Payment' or not isinstance(amount,str):continue
            if not amount.isdigit() or int(amount)<=0 or tx.get('Paths') or tx.get('Flags',0)&0x20000:continue
            if isinstance(tx.get('SendMax'),dict) or tx.get('Signers'):continue
            if meta.get('TransactionResult')!='tesSUCCESS':continue
            ident=txhash(entry.get('hash',tx.get('hash')))
            if ident in seen:continue
            seen.add(ident);fee=decimal_integer(tx['Fee'])
            found.append(dict(txid=ident,fee=money(fee,6),fee_base_units=fee,block_number=height,
                timestamp=stamp,url='https://xrpscan.com/tx/'+ident))
            if len(found)>=TARGET:return {'XRP':found}
    return {'XRP':found}


def sample_stellar(client=None):
    client=client or Client('https://horizon.stellar.org',pace=0.4)
    page=client.request('/transactions?order=desc&limit=50');found=[];seen=set();reads=0
    for tx in page['_embedded']['records']:
        if tx.get('successful') is not True or tx.get('operation_count')!=1:continue
        ident=txhash(tx['hash'])
        if ident in seen:continue
        seen.add(ident);reads+=1
        if reads>35:break
        ops=client.request('/transactions/'+ident+'/operations')['_embedded']['records']
        if len(ops)!=1 or ops[0].get('type')!='payment' or ops[0].get('asset_type')!='native':continue
        if ops[0].get('transaction_successful') is not True:continue
        closed=datetime.fromisoformat(tx['created_at'].replace('Z','+00:00'))
        stamp=timestamp(int(closed.timestamp()*1000));fee=decimal_integer(tx['fee_charged'])
        found.append(dict(txid=ident,fee=money(fee,7),fee_base_units=fee,block_number=integer(tx['ledger']),
            timestamp=stamp,url='https://stellar.expert/explorer/public/tx/'+ident))
        if len(found)>=TARGET:break
    return {'XLM':found}


def sample_blockcypher(asset,client=None):
    chain={'LTC':'ltc','DOGE':'doge'}[asset]
    client=client or Client('https://api.blockcypher.com/v1/'+chain+'/main',pace=1)
    tip=client.request();head=integer(tip['height']);found=[];seen=set();reads=0;deadline=time.monotonic()+180
    for offset in range(2):
        block=client.request('/blocks/'+str(head-offset)+'?limit=1&txstart=0')
        count=integer(block.get('n_tx',len(block.get('txids',[]))))
        if count>len(block.get('txids',[])):
            block=client.request('/blocks/'+str(head-offset)+'?limit=100&txstart='+str(max(0,count-100)))
        if block['height']!=head-offset:raise ValueError('Wrong UTXO block')
        closed=datetime.fromisoformat(block['time'].replace('Z','+00:00'));stamp=timestamp(int(closed.timestamp()*1000))
        for ident in reversed(block.get('txids',[])):
            ident=txhash(ident)
            if ident in seen:continue
            seen.add(ident);reads+=1
            if reads>30 or time.monotonic()>deadline:return {asset:found}
            tx=client.request('/txs/'+ident)
            if tx.get('hash')!=ident or tx.get('block_hash')!=block['hash'] or tx.get('block_height')!=head-offset:continue
            inputs=tx.get('inputs',[]);outputs=tx.get('outputs',[])
            if not 1<=len(inputs)<=2 or not 1<=len(outputs)<=2:continue
            if any(len(i.get('addresses',[]))!=1 or i.get('prev_hash')=='0'*64 for i in inputs):continue
            owners={i['addresses'][0] for i in inputs}
            if len(owners)!=1 or any(len(o.get('addresses',[]))!=1 or o.get('value',0)<=0 for o in outputs):continue
            recipients={o['addresses'][0] for o in outputs}-owners
            if len(recipients)!=1:continue
            fee=integer(tx['fees'])
            found.append(dict(txid=ident,fee=money(fee,8),fee_base_units=fee,block_number=head-offset,
                timestamp=stamp,url='https://live.blockcypher.com/'+chain+'/tx/'+ident+'/'))
            if len(found)>=TARGET:return {asset:found}
    return {asset:found}
