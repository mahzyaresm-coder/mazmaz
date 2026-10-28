"""Only label-confirmed exchange-specific aliases; do not guess unknown chains."""
def canonical_network(exchange, raw, label, existing):
    label=(label or '').upper()
    if exchange=='bitpin':
        if raw=='BNB' and ('BSC' in label or 'BEP20' in label or 'BEP-20' in label):return 'bsc'
        if raw=='AVAX' and ('سی چین' in label or 'C-CHAIN' in label):return 'avalanche-c'
        if raw=='S' and ('سونیک' in label or 'SONIC' in label):return 'sonic'
    return existing
