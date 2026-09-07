"""Invented, deterministic source and a scripted planner that answers every suite prompt with the authored plan."""
from datetime import date
from decimal import Decimal
import random

from acceptance_suite import STEPS, STEP_INDEX, render_prompt
from data_layer import RAW_COLUMNS
from query_engine import parse_plan
from reference_evaluator import STAGE_MEMBERS

OWNERS=['Ann Ahl','Bo Berg','Cy Chen','Di Dorn','Ed Ekre','Fay Falk','Gil Gray','Hal Hurd','Ivy Iles','Jo Jung']
CUSTOMERS=['Northwind Traders','Southgate Foods','Eastbridge Labs','Westfield Motors','Central Grid','Harbor Steel','Summit Retail','Valley Clinics']
PRODUCTS=['P-100','P-200','P-300','P-400','P-500','P-600']
TYPES=['New Business','Existing Business','Renewal']
STAGES=[s for members in STAGE_MEMBERS.values() for s in members]


def synthetic_records(seed=7,opportunities=60,years=None):
    """Sixty opportunities with duplicates, nulls, single-digit dates, quality conflicts, and a parent mismatch.

    years spreads close months over that many years ending in 2026 (more than 30 chart groups with three)."""
    rng=random.Random(seed);records=[]
    for n in range(1,opportunities+1):
        opp=f'OPP-{n:04d}';owner=OWNERS[n%len(OWNERS)];customer=CUSTOMERS[n%len(CUSTOMERS)];stage=STAGES[n%len(STAGES)]
        products=rng.sample(PRODUCTS,rng.choice([1,2,3]))
        year=(2026-((n//12)%years)) if years else (2026 if n%3 else 2025)
        close_date=f'{(n%28)+1}/{(n%12)+1}/{year}' if n%2 else f'{(n%28)+1:02d}/{(n%12)+1:02d}/{year}'
        close_month=f'1/{(n%12)+1}/{year}';created=f'{(n%27)+1}/{(n%6)+1}/{year-1 if n%5 else year}';modified=f'{(n%9)+1}/{(n%12)+1}/{year}'
        probability=None if n%7==0 else ('75%' if n%4==0 else f'{(n*13)%70+10}%')
        parent=Decimal(0);lines=[]
        for product in products:
            copies=2 if (n%6==0 and product==products[0]) else 1
            for copy in range(copies):
                amount=Decimal(n*10+len(product)*copy+7)+Decimal('0.25')*copy;qty=Decimal((n%5)+1+copy)
                parent+=amount
                lines.append(dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':opp,'product_code':product,'pet_name':product+' unit','gscm_product_group_new':'Group '+product[2],
                    'subsidiary_subsidiary_code':f'{n%3:03d}','opportunity_name':f'Project {n}','end_customer':customer,'stage':stage,'opportunity_owner':owner,'type':TYPES[n%3],
                    'biz_focus':'Focus','business_location':'Berlin','division':'Div','sales_type_detail':'Detail','quantity':str(qty),'amount_converted':str(amount),
                    'amount_converted_currency':'EUR','opp_amount_converted_currency':'EUR','probability':probability,'close_date':close_date,'close_month':close_month,
                    'created_date':created,'last_modified_date':modified,'first_channel':'Partner' if n%2 else 'Direct','age':str(n%90),'comment':f'Note {n}',
                    'deal_size_on_pricing_date_usd':str(n*100),'rollout_period_from':'2026-Q1','rollout_period_to':'2026-Q4'})
        if n%11==0: parent+=Decimal('5')          # parent-amount discrepancy
        if n%13==0: lines.append(dict(lines[0],pet_name='Renamed unit'))   # repeated raw row with a conflicting product name -> quality warning
        for line in lines: line['opp_amount_converted']=str(parent)
        records.extend(lines)
    records.append(dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':'','product_code':'P-100','quantity':'1','amount_converted':'1'})
    return records


def authored_plan(step,witnesses):
    """The plan a perfectly behaving model would return for a step, expressed with refine follow-ups in conversations."""
    e=step['expect'];sid=step['id'];w=lambda k:witnesses[k]
    def filters(specs):
        out=[]
        for f in specs:
            value=f['value'];value=w(value[1:-1]) if isinstance(value,str) and value.startswith('{') else value
            if f['op']=='group': out.append({'field':'stage','operator':'eq','value':value})
            elif f['field']=='currency': out.append({'field':'opp_amount_converted_currency','operator':'eq','value':value})
            elif f['op']=='year': out.append({'field':f['field'],'operator':'between','value':[f'{value}-01-01',f'{value}-12-31']})
            elif f['op'] in ('ge','gt','le','lt'): out.append({'field':f['field'],'operator':f['op'],'value':float(value) if isinstance(value,Decimal) else int(value)})
            else: out.append({'field':f['field'],'operator':f['op'],'value':value})
        return out
    if e['intent']=='clarify': return {'intent':'clarify','clarification':'Which calculation or scope do you mean?','context_action':'refine' if step['conversation'] else 'replace'}
    grain='opportunity_sku' if e['grain']=='sku' else 'opportunity'
    plan={'intent':e['intent'],'grain':grain,'filters':filters(e['filters'])}
    if e['intent']=='table':
        if e['columns']: plan['dimensions']=list(e['columns'])
        if e['sort']: plan['sort']=[{'field':f,'direction':'asc' if a else 'desc'} for f,a in e['sort']]
        if e['limit']: plan['limit']=e['limit']
    else:
        plan['dimensions']=['opp_amount_converted_currency' if g=='currency' else g for g in e['group']];plan['measures']=list(e['measures'])
        if e['chart_type']: plan['chart_type']=e['chart_type']
        if e['sort']: plan['sort']=[{'field':f,'direction':'asc' if a else 'desc'} for f,a in e['sort']]
    refinements={'A2':{'context_action':'refine','filters':[{'field':'opportunity_owner','operator':'eq','value':w('owner_b')}]},
                 'A3':{'context_action':'refine','filters':[{'field':'stage','operator':'eq','value':'Won'}]},
                 'A4':{'context_action':'refine','remove_filters':['opportunity_owner']},'A5':{'context_action':'refine','grain':'opportunity_sku'},'A6':{'context_action':'refine','grain':'opportunity'},
                 'B2':{'context_action':'refine','intent':'chart','chart_type':'bar','dimensions':['stage_group'],'measures':['amount']},'B3':{'context_action':'refine','measures':['quantity']},
                 'B4':{'context_action':'refine','intent':'metric','chart_type':None},'B5':{'context_action':'refine','intent':'table','grain':'opportunity_sku','dimensions':[],'measures':[],'filters':[{'field':'stage','operator':'eq','value':'Won'}]},
                 'B6':{'context_action':'replace','intent':'table','grain':'opportunity'},'C3':{'context_action':'refine','intent':'metric','measures':['amount'],'dimensions':[]},
                 'C5':{'context_action':'refine','grain':'opportunity_sku','filters':[{'field':'product_code','operator':'eq','value':w('product')}]},'C6':{'context_action':'refine','remove_filters':['product_code']}}
    return refinements.get(sid,plan)


class ScriptedPlanner:
    """Answers each rendered prompt with a scripted plan; overrides let tests inject wrong or failing answers."""
    def __init__(self,witnesses,overrides=None,fail_on=()):
        self.witnesses=witnesses;self.overrides=overrides or {};self.fail_on=set(fail_on);self.calls=[]
        self.prompts={render_prompt(s,witnesses):s for s in STEPS if all(k in witnesses for k in s['witnesses'])}
    def plan(self,question,history,previous=None,view='auto'):
        self.calls.append(question)
        step=self.prompts.get(question)
        if step is None: raise AssertionError('Unscripted prompt: '+question)
        if step['id'] in self.fail_on: raise RuntimeError('model unavailable')
        values=self.overrides.get(step['id'])
        plan=parse_plan(values if values is not None else authored_plan(step,self.witnesses))
        if view!='auto' and plan.intent.value!='clarify': plan.grain='opportunity' if view=='summary' else 'opportunity_sku'
        return plan
