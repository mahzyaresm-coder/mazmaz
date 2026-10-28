"""User-selected assets; never use substring matching for token identities."""
from decimal import Decimal, localcontext
from networks import canonical_network

REQUESTED_ASSETS = (
 'BTC','ETH','USDT','BNB','DOGE','SHIB','IRR','XRP','LTC','BCH','TRX','ADA',
 'XLM','SOL','USDC','POL','GRAM','UNI','SAND','MANA','LINK','XAUT','PAXG','FIL',
 'ATOM','ARB','OP','AVAX','NOT','HMSTR','DOGS','DAI','TRUMP','S','TSLAX','AAPLX',
 'NVDAX','COINX','CRCLX','METAX','GOOGLX','HOODX','AMZNX',
)


def selected_rows(rows):
    result=[]
    for original in rows:
        source=original['asset'].upper()
        symbol={'TRON':'TRX','1K_SHIB':'SHIB'}.get(source,source)
        if symbol not in REQUESTED_ASSETS:continue
        row=dict(original)
        row['network']=canonical_network(row.get('exchange'),row.get('network_raw'),row.get('network_label'),row.get('network'))
        if source=='1K_SHIB':
            if str(row.get('asset_scale'))!='1000':
                raise ValueError('Unverified SHIB unit scale')
            row['source_asset']=source
            for field in ('fee','minimum'):
                if row.get(field) is not None:
                    number=Decimal(row[field])
                    with localcontext() as context:
                        context.prec=max(50,len(number.as_tuple().digits)+20)
                        row[field]=format(number*1000,'f')
            if row.get('fee_currency','').upper()==source:row['fee_currency']='SHIB'
            row['asset_scale']='1'
        row['asset']=symbol
        if row.get('fee_currency','').upper()=='TRON':row['fee_currency']='TRX'
        result.append(row)
    return result
