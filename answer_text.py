"""Deterministic answer text: a business title, scope, and every explicitly requested scalar metric.

Everything here is derived from the executed result's complete-population metadata (counts, per-currency totals,
groups). Nothing is estimated from the displayed preview and no model call is involved."""
import re
from decimal import Decimal

LABELS={'opportunity_no':'Opportunity no.','opportunity_name':'Opportunity','end_customer':'Customer','opportunity_owner':'Owner','stage':'Stage','stage_group':'Opportunity status',
        'close_date':'Close date','close_month':'Closing month','created_date':'Created','last_modified_date':'Last modified','product_code':'Product code','pet_name':'Product',
        'quantity':'Quantity','opportunity_amount':'Amount','sku_amount':'Amount','amount':'Amount','deal_size':'Deal size (USD)','sku_count':'Product count','opportunity_count':'Opportunity count',
        'opp_amount_converted_currency':'Currency','amount_converted_currency':'Currency','type':'Type','first_channel':'First channel','probability':'Probability','gscm_product_group_new':'Product group',
        'has_quality_warning':'Data quality','has_amount_discrepancy':'Amount check','subsidiary_subsidiary_code':'Subsidiary','biz_focus':'Business focus','business_location':'Location','division':'Division'}
MEASURE_TITLES={'amount':'Total amount','quantity':'Total quantity','sku_count':'Product count','opportunity_count':'Opportunity count','deal_size':'Total deal size (USD)'}
MEASURE_LABELS={'amount':'Amount','quantity':'Quantity','sku_count':'Product count','opportunity_count':'Opportunity count','deal_size':'Deal size (USD)'}
OPS={'eq':'is','ne':'is not','gt':'over','ge':'at least','lt':'under','le':'at most','contains':'contains','in':'is one of','between':'between'}


MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']


def display(field,value):
    """Group value as shown to readers: ISO dates become '2 Feb 2026' (months 'Feb 2026'); nulls read 'Unknown'."""
    if value is None: return 'Unknown'
    text=str(value)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}(T.*)?',text):
        year,month,day=int(text[:4]),int(text[5:7]),int(text[8:10])
        if 1<=month<=12: return f'{MONTHS[month-1]} {year}' if str(field).endswith('month') else f'{day} {MONTHS[month-1]} {year}'
    return text


def default_suggestions(table):
    """Deterministic follow-ups for a data answer (no model call): questions this contract can always answer."""
    kind=table.get('result_kind');presentation=table.get('presentation');filters=table.get('filters') or []
    dims=[c for c in table.get('columns',[]) if c not in MEASURE_LABELS] if kind=='aggregate' else []
    if kind=='rows': items=['Total amount by owner','How many opportunities per status?','Amount by closing month']
    elif not dims: items=['Break the total down by owner','Break the total down by opportunity status','Break the total down by closing month']
    else:
        alternatives=[name for field,name in [('opportunity_owner','owner'),('stage_group','opportunity status'),('close_month','closing month'),('end_customer','customer')] if field not in dims]
        items=[f'Show the same values by {name}' for name in alternatives[:2]]+['Show those values as a table' if presentation=='chart' else 'Chart those values as a bar chart']
    if filters: items[-1]=f'Remove the {label(filters[-1].get("field")).lower()} restriction'
    return items[:3]


def label(field):
    return LABELS.get(field) or str(field).replace('_',' ').capitalize()


def money(value,code=None,decimals=2):
    """Exact decimal text with thousands separators and a fixed number of places (display only; values stay untouched)."""
    if value is None: return None
    number=Decimal(str(value))
    quantized=number.quantize(Decimal(1).scaleb(-decimals)) if decimals is not None else number.normalize()
    text=f'{quantized:,f}' if decimals is not None else (format(quantized,'f') if quantized!=0 else '0')
    return f'{text} {code}' if code else text


def count(value):
    return f'{int(value):,}' if value is not None else None


def filters_phrase(filters):
    """Readable scope, with the source date field kept explicit."""
    parts=[]
    for f in filters or []:
        field,value,op=f['field'],f['value'],f['operator']
        if field in ('close_month','close_date','created_date') and op=='between' and isinstance(value,list):
            start,end=map(str,value)
            verb='Created' if field=='created_date' else 'Closing'
            if start.endswith('-01-01') and end==start[:4]+'-12-31': parts.append(f'{verb} in {start[:4]}')
            else: parts.append(f'{verb} {display(field,start)} – {display(field,end)}')
        elif field in ('stage','stage_group') and op=='eq' and value in ('Open','Won','Lost'):
            parts.append(f'{value} opportunities')
        else:
            shown=(', '.join(display(field,v) for v in value) if isinstance(value,list) else display(field,value))
            parts.append(f'{label(field)} {OPS.get(op,op)} {shown}')
    return ' · '.join(parts)


def compose_answer(table):
    """One title, scope, optional insight and primary values; no repeated fact layers.

    Group headline totals never sum overlapping memberships. Extrema come from
    complete server metadata or a known-complete returned result, never a preview.
    """
    metadata=table.get('metadata') or {}
    complete=metadata.get('complete') or {}
    currency=metadata.get('currency') or {}
    code=currency.get('code')
    filters=list(table.get('filters') or [])
    metrics=[]
    sentence=''
    measures=[c for c in table.get('columns',[]) if c in MEASURE_LABELS]
    dimensions=[c for c in table.get('columns',[]) if c not in MEASURE_LABELS]
    if table.get('result_kind')=='rows':
        title='Opportunity products' if table.get('grain')=='opportunity_sku' else 'Opportunities'
    elif not dimensions:
        title=MEASURE_TITLES.get(measures[0],'Totals') if len(measures)==1 else 'Totals'
        if measures==['opportunity_count']:
            title='Opportunities'
            status=next((f for f in filters if f['field'] in ('stage','stage_group') and f['operator']=='eq' and f['value'] in ('Open','Won','Lost')),None)
            if status:
                title=f"{status['value']} opportunities"
                filters.remove(status)
        row=(table.get('rows') or [{}])[0]
        for m in measures:
            value=row.get(m)
            unit='USD' if m=='deal_size' else code if m=='amount' else None
            text='Not available' if value is None else count(value) if m in ('opportunity_count','sku_count') else money(value,unit,2 if m in ('amount','deal_size') else None)
            metrics.append({'label':MEASURE_TITLES.get(m,MEASURE_LABELS[m]),'value':text,'raw':value,'currency':unit})
    else:
        title=' and '.join(MEASURE_LABELS[m] for m in measures)+' by '+' and '.join(label(d) for d in dimensions)
        lead=measures[0] if measures else None
        best=(complete.get('largest') or {}).get(lead)
        if best is None and not table.get('truncated') and lead:
            best=max((r for r in table.get('rows',[]) if r.get(lead) is not None),key=lambda r:Decimal(str(r[lead])),default=None)
        if best and lead and not (lead=='amount' and currency.get('mixed')):
            value=money(best[lead],'USD' if lead=='deal_size' else code if lead=='amount' else None,2 if lead in ('amount','deal_size') else None)
            name=' / '.join(display(d,best.get(d)) for d in dimensions)
            sentence=f'Largest {MEASURE_LABELS[lead].lower()}: {name} with {value}.'
    return {'title':title,'context':filters_phrase(filters),'sentence':sentence,'metrics':metrics}
