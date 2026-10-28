"""Periodic public-source collection; fail closed on unknown source schemas."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
from adapters import parse_tabdeal_api, parse_wallex, parse_nobitex, parse_bitpin
from server import validate_rows, EXCHANGES
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
TABDEAL_API = 'https://api-web.tabdeal.org/treasury/currency_transaction_fees/'
SOURCES = {
    'efex': ('https://efex.pro/fa/fees', 'کارمزد برداشت'),
    'wallex': ('https://wallex.ir/commission', 'واریز و برداشت'),
    'bitpin': ('https://bitpin.ir/fee/', 'کارمزد برداشت رمزارز'),
    'nobitex': ('https://nobitex.ir/pricing/?q=', 'واریز و برداشت'),
    'tabdeal': ('https://tabdeal.org/commissions/cryptofee', 'کارمزد برداشت ارز دیجیتال'),
}
# Only explicitly verified aliases. Unknown identifiers remain exchange-scoped.
NETWORKS = {'BTC':'bitcoin', 'ETH':'ethereum', 'TRX':'tron', 'BSC':'bsc',
            'AVAXC':'avalanche-c', 'ARBITRUM':'arbitrum', 'OPTIMISM':'optimism',
            'SOL':'solana', 'LTC':'litecoin', 'BCH':'bitcoin-cash', 'XRP':'xrp',
            'DOGE':'dogecoin', 'ADA':'cardano', 'ATOM':'cosmos'}

class SourceError(ValueError):
    pass

class NuxtData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('id') == '__NUXT_DATA__'
    def handle_endtag(self, tag):
        if tag == 'script': self.active = False
    def handle_data(self, data):
        if self.active: self.parts.append(data)

def now():
    return datetime.now(timezone.utc).isoformat()

def amount(value):
    if value is None: return None
    if isinstance(value, bool): raise SourceError('Boolean amount')
    d = Decimal(str(value))
    if not d.is_finite() or d < 0: raise SourceError('Invalid amount')
    return str(d)

def parse_tabdeal(html, fetched_at):
    parser = NuxtData()
    parser.feed(html)
    if not parser.parts: raise SourceError('Nuxt fee payload missing; source format changed')
    pool = json.loads(''.join(parser.parts), parse_float=Decimal)
    def ref(index):
        if type(index) is not int or not 0 <= index < len(pool):
            raise SourceError('Invalid Nuxt reference')
        return pool[index]
    root = ref(0)
    if root != ['ShallowReactive', 1]: raise SourceError('Unknown Nuxt root')
    metadata = ref(1)
    source_time = datetime.fromtimestamp(float(ref(metadata['prerenderedAt'])) / 1000, timezone.utc)
    if source_time > datetime.fromisoformat(fetched_at): raise SourceError('Future source timestamp')
    data = ref(metadata['data'])
    if data[0] != 'ShallowReactive': raise SourceError('Unknown Nuxt data wrapper')
    pages = ref(data[1])
    page = ref(pages['/commissions/cryptofee'])
    currencies = ref(page['currencies'])
    rows = []
    seen = set()
    for index in currencies:
        currency = ref(index)
        asset = ref(currency['symbol'])
        if not isinstance(asset,str) or not asset: raise SourceError('Missing asset')
        if asset.lower() == 'irt': continue
        for network_index in ref(currency['transaction_fees']):
            network = ref(network_index)
            if ref(network['visible']) is not True: continue
            raw = ref(network['network_type'])
            label = ref(network['network_type_name'])
            if not isinstance(raw,str) or not raw or not isinstance(label,str):
                raise SourceError('Missing network identifier')
            normalized = NETWORKS.get(raw.upper(), 'tabdeal:' + raw)
            key = (asset, normalized)
            if key in seen: raise SourceError('Duplicate asset/network')
            seen.add(key)
            rows.append(dict(exchange='tabdeal',asset=asset,network=normalized,
                network_raw=raw,network_label=label,
                fee=amount(ref(network['transaction_fee'])),fee_currency=asset,
                minimum=amount(Decimal(str(ref(network['min_withdraw']))) - Decimal(str(ref(network['transaction_fee'])))),
                # "visible" does not prove withdrawals are enabled.
                withdrawal_enabled=None, source=SOURCES['tabdeal'][0],
                updated_at=source_time.isoformat(), fetched_at=fetched_at))
    if not rows or not any(r['fee'] is not None for r in rows):
        raise SourceError('No withdrawal fees; refusing to replace previous data')
    return rows

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent':'MazmazFeeMonitor/0.1', 'Accept':'application/json, text/html'})
    with urllib.request.urlopen(request,timeout=25) as response:
        if not any(t in response.headers.get('Content-Type','') for t in ['text/html','application/json']):
            raise SourceError('Unexpected content type')
        body = response.read(8_000_001)
        if len(body) > 8_000_000: raise SourceError('Source exceeds size limit')
        return body.decode('utf-8')

def fetch_bitpin_pages(fetcher):
    url = 'https://api.bitpin.ir/v1/mkt/network_settings/?page=1'
    items=[]
    seen=set()
    expected=None
    while url:
        from urllib.parse import urlsplit
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.netloc!='api.bitpin.ir' or parsed.path!='/v1/mkt/network_settings/':
            raise SourceError('Unexpected pagination destination')
        if url in seen or len(seen)>=100:raise SourceError('Invalid pagination cycle')
        seen.add(url)
        page=json.loads(fetcher(url))
        if type(page.get('count')) is not int or not isinstance(page.get('results'),list):
            raise SourceError('Invalid pagination schema')
        if expected is None:expected=page['count']
        if page['count']!=expected:raise SourceError('Source count changed during collection; retry next cycle')
        items.extend(page['results'])
        url=page['next']
    if len(items)!=expected:raise SourceError('Incomplete Bitpin collection')
    return json.dumps({'results':items})

def collect_one(exchange, fetcher=fetch):
    attempted = now()
    try:
        endpoint = {'tabdeal':TABDEAL_API, 'wallex':'https://api.wallex.ir/v1/currencies'}.get(exchange,SOURCES[exchange][0])
        text = fetch_bitpin_pages(fetcher) if exchange == 'bitpin' else fetcher(endpoint)
        parser = {'tabdeal':parse_tabdeal_api, 'wallex':parse_wallex, 'nobitex':parse_nobitex, 'bitpin':parse_bitpin}.get(exchange)
        if parser is None:
            raise SourceError('Parser not verified: source requires inspection of withdrawal tab')
        rows = parser(text,now())
        if not rows or not any(r['fee'] is not None for r in rows):
            raise SourceError('No withdrawal fees; refusing to replace previous data')
        validate_rows(rows)
        stale = any((datetime.now(timezone.utc) - datetime.fromisoformat(r['updated_at'])).total_seconds() > 3600 for r in rows)
        return exchange,rows,dict(status='stale' if stale else 'ok',last_attempt=attempted,last_success=now(),count=len(rows))
    except Exception as exc:
        # Store controlled diagnostics, never arbitrary response bodies or secrets.
        if isinstance(exc,urllib.error.HTTPError): error = 'http_' + str(exc.code)
        elif isinstance(exc,urllib.error.URLError): error = 'network_unavailable'
        elif isinstance(exc,SourceError): error = str(exc)
        else: error = 'source_schema_invalid'
        return exchange,None,dict(status='error',last_attempt=attempted,error=error)

def atomic_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.fees-', dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,ensure_ascii=False,allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def run_once(path, fetcher=fetch):
    # One atomic document keeps source status consistent with its fee rows.
    previous = json.loads(path.read_text()) if path.exists() else {'rows':[], 'sources':{}}
    if isinstance(previous,list): previous = {'rows':previous,'sources':{}}
    rows = previous['rows']
    statuses = previous.get('sources',{})
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda exchange: collect_one(exchange,fetcher),[e['id'] for e in EXCHANGES]))
    for exchange, fresh, status in results:
        old_status = statuses.get(exchange,{})
        statuses[exchange] = {**old_status,**status,'source':SOURCES[exchange][0],'tab':SOURCES[exchange][1]}
        if fresh is not None:
            rows = [r for r in rows if r['exchange'] != exchange] + fresh
            statuses[exchange].pop('error',None)
        logging.info('%s: %s',exchange,status['status'])
    result = dict(rows=rows,sources=statuses,checked_at=now())
    atomic_json(path,result)
    return result

def worker(path, interval, stop):
    while not stop.is_set():
        try: run_once(path)
        except Exception: logging.exception('Collection cycle failed; previous snapshot preserved')
        stop.wait(interval)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--interval',type=int,default=900)
    parser.add_argument('--data',type=Path,default=ROOT/'data'/'fees.json')
    args = parser.parse_args()
    if args.interval < 60: parser.error('Minimum interval is 60 seconds')
    logging.basicConfig(level=logging.INFO)
    if args.once:
        result = run_once(args.data)
        raise SystemExit(0 if all(s['status']=='ok' for s in result['sources'].values()) else 1)
    worker(args.data,args.interval,threading.Event())
