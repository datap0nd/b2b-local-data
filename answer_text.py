"""Deterministic answer text: a short business title, a factual sentence, and up to three verified metrics.

Everything here is derived from the executed result's complete-population metadata (counts, per-currency totals,
groups). Nothing is estimated from the displayed preview and no model call is involved."""
import re
from decimal import Decimal

LABELS={'opportunity_no':'Opportunity no.','opportunity_name':'Opportunity','end_customer':'Customer','opportunity_owner':'Owner','stage':'Stage','stage_group':'Stage group',
        'close_date':'Close date','close_month':'Close month','created_date':'Created','last_modified_date':'Last modified','product_code':'Product code','pet_name':'Product',
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
    if kind=='rows': items=['Total amount by owner','How many opportunities per stage group?','Amount by close month']
    elif not dims: items=['Break the total down by owner','Break the total down by stage group','Show the matching opportunities']
    else:
        other='stage group' if 'stage_group' not in dims else 'owner'
        items=['Show the opportunities behind that result',f'Show the same values by {other}','Show those values as a table' if presentation=='chart' else 'Chart those values as a bar chart']
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
    parts=[]
    for f in filters or []:
        value=f['value']
        if isinstance(value,list): value=', '.join(str(v) for v in value) if f['operator']!='between' else f"{value[0]} and {value[1]}"
        parts.append(f"{label(f['field']).lower()} {OPS.get(f['operator'],f['operator'])} {value if value is not None else 'empty'}")
    return ('; '.join(parts)) if parts else ''


def compose_answer(table):
    """Title, sentence, and metrics for a result payload (rows or aggregate)."""
    metadata=table.get('metadata') or {}
    complete=metadata.get('complete') or {}
    currency=metadata.get('currency') or {}
    code=currency.get('code')
    filters=filters_phrase(table.get('filters'))
    unit='product rows' if table.get('grain')=='opportunity_sku' else 'opportunities'
    metrics=[]
    if table.get('result_kind')=='rows':
        title='Opportunity products' if table.get('grain')=='opportunity_sku' else 'Opportunities'
        total=table.get('total_rows',0)
        if total==0:
            sentence='No '+unit+' match'+(f' ({filters})' if filters else '')+'.'
            return {'title':title,'sentence':sentence,'metrics':[]}
        opportunities=complete.get('opportunities')
        by_currency=complete.get('by_currency') or {}
        sentence=f'{count(total)} {unit} match'+(f' where {filters}' if filters else '')
        if table.get('grain')=='opportunity_sku' and opportunities: sentence+=f' across {count(opportunities)} opportunities'
        if code and by_currency.get(code,{}).get('amount') is not None:
            sentence+=f', totalling {money(by_currency[code]["amount"],code)}'
        elif len(by_currency)>1:
            sentence+=', in '+' and '.join(f'{money(v["amount"],k)}' for k,v in by_currency.items() if v.get('amount') is not None)
        sentence+='.'
        if table.get('truncated'): sentence+=f' The first {count(len(table.get("rows",[])))} rows are shown.'
        if not metadata.get('explicit_columns'):
            metrics.append({'label':'Opportunities' if table.get('grain')=='opportunity' else 'Product rows','value':count(total),'raw':total})
            if code and by_currency.get(code,{}).get('amount') is not None:
                metrics.append({'label':'Total amount','value':money(by_currency[code]['amount'],code),'raw':by_currency[code]['amount'],'currency':code})
            elif len(by_currency)>1:
                metrics.append({'label':'Amount by currency','value':'; '.join(f'{money(v["amount"],k)}' for k,v in by_currency.items() if v.get('amount') is not None),'raw':None,'note':'Several currencies match; totals are not combined.'})
            if table.get('grain')=='opportunity_sku' and opportunities:
                metrics.append({'label':'Opportunities','value':count(opportunities),'raw':opportunities})
            elif complete.get('quantity') is not None:
                metrics.append({'label':'Total quantity','value':money(complete['quantity'],None,None),'raw':complete['quantity']})
        return {'title':title,'sentence':sentence,'metrics':metrics[:3]}
    # Aggregates
    measures=[c for c in table.get('columns',[]) if c in MEASURE_LABELS]
    dimensions=[c for c in table.get('columns',[]) if c not in MEASURE_LABELS]
    if not dimensions:
        title=MEASURE_TITLES.get(measures[0],'Totals') if len(measures)==1 else 'Totals'
        row=(table.get('rows') or [{}])[0]
        parts=[]
        for m in measures:
            value=row.get(m)
            if value is None: text='not available'
            elif m=='amount': text=money(value,code) if code else money(value,None)
            elif m=='deal_size': text=money(value,'USD')
            else: text=money(value,None,None)
            parts.append(f'{MEASURE_LABELS[m].lower()} {text}')
            metrics.append({'label':MEASURE_TITLES.get(m,MEASURE_LABELS[m]),'value':text,'raw':value,'currency':code if m=='amount' else ('USD' if m=='deal_size' else None)})
        sentence='Across '+count(complete.get('opportunities') or 0)+' matching opportunities'+(f' where {filters}' if filters else '')+': '+', '.join(parts)+'.'
        return {'title':title,'sentence':sentence,'metrics':metrics[:3]}
    title=' and '.join(MEASURE_LABELS[m] for m in measures)+' by '+' and '.join(label(d) for d in dimensions)
    groups=table.get('total_rows',0)
    rows=table.get('rows') or []
    sentence=f'{count(groups)} {"group" if groups==1 else "groups"}'+(f' where {filters}' if filters else '')+f' across {count(complete.get("opportunities") or 0)} opportunities.'
    lead=measures[0] if measures else None
    if lead and rows:
        best=max((r for r in rows if r.get(lead) is not None),key=lambda r:Decimal(str(r[lead])),default=None)
        if best is not None:
            value=best[lead]
            text=money(value,code) if lead=='amount' else money(value,'USD') if lead=='deal_size' else money(value,None,None)
            name=' / '.join(display(d,best.get(d)) for d in dimensions)
            sentence+=f' Largest {MEASURE_LABELS[lead].lower()}: {name} with {text}.'
            metrics.append({'label':f'Largest {MEASURE_LABELS[lead].lower()}','value':f'{name}: {text}','raw':value})
    metrics.insert(0,{'label':'Groups','value':count(groups),'raw':groups})
    if lead in ('quantity','opportunity_count','sku_count') or (lead=='amount' and code) or lead=='deal_size':
        total=Decimal(0);any_value=False
        for r in rows:
            if r.get(lead) is not None: total+=Decimal(str(r[lead]));any_value=True
        if any_value and not table.get('truncated'):
            metrics.append({'label':MEASURE_TITLES.get(lead,lead),'value':money(total,code) if lead=='amount' else money(total,'USD') if lead=='deal_size' else money(total,None,None),'raw':str(total)})
    return {'title':title,'sentence':sentence,'metrics':metrics[:3]}
