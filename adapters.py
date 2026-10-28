"""Verified public withdrawal sources. Amounts are in the row's asset unit."""
from datetime import datetime, timezone
from networks import canonical_network
from decimal import Decimal
from html.parser import HTMLParser
import json
import re

ALIASES = {
 'BTC':'bitcoin','BITCOIN':'bitcoin','BTC_LN':'bitcoin-lightning','BTCLN':'bitcoin-lightning',
 'ETH':'ethereum','ERC20':'ethereum','TRX':'tron','TRC20':'tron',
 'BSC':'bsc','BEP20':'bsc','ARBITRUM':'arbitrum','ARB':'arbitrum',
 'OPTIMISM':'optimism','OP':'optimism','SOL':'solana','SOLANA':'solana',
 'AVAXC':'avalanche-c','LTC':'litecoin','LITECOIN':'litecoin',
 'BCH':'bitcoin-cash','BITCOIN_CASH':'bitcoin-cash','XRP':'xrp','RIPPLE':'xrp',
 'DOGE':'dogecoin','DOGECOIN':'dogecoin','ADA':'cardano','ATOM':'cosmos','COSMOS':'cosmos',
 'MATIC':'polygon','POLYGON':'polygon','TON':'ton','BASE':'base','SUI':'sui',
 'ETC':'ethereum-classic','ETHEREUM_CLASSIC':'ethereum-classic',
 'XLM':'stellar','STELLAR':'stellar','XTZ':'tezos','DASH':'dash',
 'ONE':'harmony','HARMONY':'harmony','SONIC':'sonic','EOS':'eos',
}

def amount(value):
    if value is None: return None
    if isinstance(value,bool): raise ValueError('Boolean amount')
    number=Decimal(str(value))
    if not number.is_finite() or number < 0: raise ValueError('Invalid amount')
    return format(number,'f')

def row(exchange,asset,raw,label,fee,minimum,enabled,source,stamp,fetched,**extra):
    if not all(isinstance(x,str) and x.strip() for x in [asset,raw,label]):
        raise ValueError('Missing currency/network identity')
    return dict(exchange=exchange,asset=asset.upper(),network=canonical_network(exchange,raw,label,ALIASES.get(raw.upper(),exchange+':'+raw)),
                network_raw=raw,network_label=label,fee=amount(fee),fee_currency=asset.upper(),
                minimum=amount(minimum),withdrawal_enabled=enabled,source=source,
                updated_at=stamp,fetched_at=fetched,**extra)

def parse_tabdeal_api(text,fetched):
    data=json.loads(text,parse_float=Decimal)
    result=[]
    for currency in data['currency_transaction_fees']:
        if currency['symbol'].lower()=='irt': continue
        for n in currency['transaction_fees']:
            if n['visible'] is not True: continue
            fee=amount(n['transaction_fee'])
            minimum=None if fee is None or n['min_withdraw'] is None else Decimal(str(n['min_withdraw']))-Decimal(fee)
            result.append(row('tabdeal',currency['symbol'],n['network_type'],n['network_type_name'],
                fee,minimum,None,'https://api-web.tabdeal.org/treasury/currency_transaction_fees/',fetched,fetched))
    return result

def availability(value):
    return {'ENABLE':True,'DISABLE':False}.get(value)

def parse_wallex(text,fetched):
    data=json.loads(text,parse_float=Decimal)
    if data.get('success') is False: raise ValueError('Unsuccessful response')
    result=[]
    for currency in data['result'].values():
        if currency['type']!='CRYPTO': continue
        for n in currency['network']:
            if n.get('type')!='ADDRESS': continue
            fee=amount(n['transaction_fee'])
            minimum=None if fee is None or n['min_withdrawal_value'] is None else Decimal(str(n['min_withdrawal_value']))+Decimal(fee)
            network_enabled=availability(n['withdrawal_availability'])
            enabled=False if availability(currency['withdrawal_availability']) is False else network_enabled
            result.append(row('wallex',currency['key'],n['name'],n['name'],fee,minimum,enabled,
                'https://api.wallex.ir/v1/currencies',fetched,fetched))
    return result

class FlightScripts(HTMLParser):
    def __init__(self):
        super().__init__();self.script=False;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script':self.script=True
    def handle_endtag(self,tag):
        if tag=='script':self.script=False
    def handle_data(self,data):
        if not self.script or not data.startswith('self.__next_f.push('):return
        # Parse a literal JSON argument only; never evaluate source JavaScript.
        literal=data[len('self.__next_f.push('):]
        payload,end=json.JSONDecoder().raw_decode(literal)
        if literal[end:].strip() not in [')',');']:raise ValueError('Unexpected Flight script')
        if payload[0]==1 and isinstance(payload[1],str):self.parts.append(payload[1])

def nobitex_query(html):
    parser=FlightScripts();parser.feed(html)
    for line in ''.join(parser.parts).splitlines():
        if ':' not in line:continue
        _,literal=line.split(':',1)
        if not literal.startswith('['):continue
        try:payload=json.loads(literal,parse_float=Decimal)
        except ValueError:continue
        if not isinstance(payload,list) or len(payload)<4 or not isinstance(payload[3],dict):continue
        for query in payload[3].get('state',{}).get('queries',[]):
            if query.get('queryKey')==['options'] and query['state'].get('status')=='success':return query['state']
    raise ValueError('Nobitex options hydration not found')

def parse_nobitex(html,fetched):
    state=nobitex_query(html)
    stamp=datetime.fromtimestamp(float(state['dataUpdatedAt'])/1000,timezone.utc).isoformat()
    if datetime.fromisoformat(stamp)>datetime.fromisoformat(fetched):raise ValueError('Future source timestamp')
    options=state['data'];config=options['nobitex']
    available=set(config['activeCurrencies'])|set(config.get('xchangeCurrencies',[]))
    # These exclusions match the pricing page's public withdrawal table.
    excluded={'irt','ftm','bnx','pgala','gala'}
    suppressed={'ETH':{'enj','render','usdc','dydx'},
                'BSC':{'ada','atom','avax','bch','doge','near','sol','trx','a','pol'},
                'TRX':{'usdc'},'BNB':{'bnb'}}
    result=[]
    for currency in options['coins']:
        asset=currency['coin']
        if asset not in available or asset in excluded:continue
        for n in currency['networkList'].values():
            raw=n['network']
            if asset in suppressed.get(raw,set()):continue
            enabled=n.get('withdrawEnable')
            if enabled is not None and type(enabled) is not bool:raise ValueError('Invalid withdrawal state')
            clean=lambda x:None if x is None else str(x).replace('_','')
            result.append(row('nobitex',asset,raw,n['name'],clean(n.get('withdrawFee')),
                clean(n.get('withdrawMin')),enabled,'https://nobitex.ir/pricing/?q=',stamp,fetched,
                asset_scale=currency.get('scale','1'),contract_address=n.get('contractAddress')))
    return result

def parse_bitpin(text,fetched):
    data=json.loads(text,parse_float=Decimal)
    result=[]
    for item in data['results']:
        currency=item['currency'];network=item['network']
        if currency.get('for_test') is True:continue
        kind=item['withdraw_commission_type']
        if kind not in ['value','percent']:raise ValueError('Unknown Bitpin commission type')
        enabled=network.get('can_withdraw')
        if type(enabled) is not bool:raise ValueError('Missing Bitpin withdrawal status')
        if item.get('withdraw_under_maintenance') or network.get('withdraw_under_maintenance'):enabled=False
        result.append(row('bitpin',currency['code'],network['code'],network['title_fa'],
            item['withdraw_commission'] if kind=='value' else None,item['min_withdraw'],enabled,
            'https://api.bitpin.ir/v1/mkt/network_settings/',fetched,fetched,
            fee_kind=kind,fee_rate=amount(item['withdraw_commission']) if kind=='percent' else None))
    return result
