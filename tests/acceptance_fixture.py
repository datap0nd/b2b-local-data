"""Invented, deterministic source and a scripted planner that answers every suite prompt with the authored plan."""
from datetime import date
from decimal import Decimal
import json
import random

from acceptance_suite import STEPS, STEP_INDEX, render_prompt
from data_layer import RAW_COLUMNS
from query_engine import PlanRejected, parse_plan
from reference_evaluator import STAGE_MEMBERS

OWNERS=['Ann Ahl','Bo Berg','Cy Chen','Di Dorn','Ed Ekre','Fay Falk','Gil Gray','Hal Hurd','Ivy Iles','Jo Jung']
CUSTOMERS=['Northwind Traders','Southgate Foods','Eastbridge Labs','Westfield Motors','Central Grid','Harbor Steel','Summit Retail','Valley Clinics']
PRODUCTS=['P-100','P-200','P-300','P-400','P-500','P-600']
TYPES=['New Business','Existing Business','Renewal']
STAGES=[s for members in STAGE_MEMBERS.values() for s in members]
# Recognizable clarification wording for the suite's predicates (the scripted "model" answers like a good model would).
CLARIFICATIONS={'T34':'Probability-weighted revenue is not available: there is no weighted calculation in this data contract. I can show the total amount by owner or the probability per opportunity instead.',
                'C2':'A probability-weighted revenue is not supported here. I can give the ordinary total amount of those opportunities, or list their probabilities.',
                'T35':'Do you mean the whole opportunities that contain this product (all their products counted), or only the product rows for it (its own quantity and amount)?',
                'C4':'Should I count the entire opportunities containing that product, or only that product\'s own rows within the currency?',
                'T36':'I cannot run SQL statements; questions are answered through the validated query contract. Describe what the query should return, for example the opportunities in a stage or the amount by owner.'}
SUGGESTIONS={'T34':['Show the total amount by opportunity owner','Show the opportunities with a probability of at least 75%'],
             'C2':['What is the total amount of those opportunities?'],'T35':['Show the whole opportunities containing the product','Show only the rows for the product'],
             'C4':['Count only the product rows','Count the whole opportunities'],'T36':['Show every opportunity as a summary table']}


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
                    'biz_focus':'Focus','business_location':'Berlin','division':'Div','sales_type_detail':'Detail','quantity':str(qty),'opp_amount_converted':str(amount),
                    'amount_converted_currency':'EUR','opp_amount_converted_currency':'EUR','probability':probability,'close_date':close_date,'close_month':close_month,
                    'created_date':created,'last_modified_date':modified,'first_channel':'Partner' if n%2 else 'Direct','age':str(n%90),'comment':f'Note {n}',
                    'deal_size_on_pricing_date_usd':str(n*100),'rollout_period_from':'2026-Q1','rollout_period_to':'2026-Q4'})
        if n%11==0: parent+=Decimal('5')          # parent-amount discrepancy
        if n%13==0: lines.append(dict(lines[0],pet_name='Renamed unit'))   # repeated raw row with a conflicting product name -> quality warning
        for line in lines: line['amount_converted']=str(parent)
        records.extend(lines)
    records.append(dict.fromkeys(RAW_COLUMNS)|{'opportunity_no':'','product_code':'P-100','quantity':'1','amount_converted':'1'})
    return records


def authored_plan(step,witnesses):
    """The version-2 plan a perfectly behaving model would return for a step, with refine follow-ups in conversations."""
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
    if e['intent']=='clarify':
        return {'result_kind':'clarify','clarification':CLARIFICATIONS.get(sid,'Which calculation or scope do you mean?'),'suggestions':SUGGESTIONS.get(sid,[]),'context_action':'refine' if step['conversation'] else 'replace'}
    grain='opportunity_sku' if e['grain']=='sku' else 'opportunity'
    if e['intent']=='table':
        plan={'result_kind':'rows','presentation':'table','grain':grain,'filters':filters(e['filters'])}
        if e['columns']: plan['columns']={'mode':'only','fields':list(e['columns'])}
        elif e.get('include'): plan['columns']={'mode':'include','fields':list(e['include'])}
        if e['sort']: plan['sort']=[{'field':f,'direction':'asc' if a else 'desc'} for f,a in e['sort']]
        if e['limit']: plan['limit']=e['limit']
    else:
        group=['opp_amount_converted_currency' if g=='currency' else g for g in e['group']]
        plan={'result_kind':'aggregate','presentation':'chart' if e['intent']=='chart' else ('table' if group else 'cards'),'grain':grain,'filters':filters(e['filters']),'group_by':group,'measures':list(e['measures'])}
        if e['chart_type']: plan['chart_type']=e['chart_type']
        if e['sort']: plan['sort']=[{'field':f,'direction':'asc' if a else 'desc'} for f,a in e['sort']]
    refinements={'A2':{'context_action':'refine','filters':[{'field':'opportunity_owner','operator':'eq','value':w('owner_b')}]},
                 'A3':{'context_action':'refine','filters':[{'field':'stage','operator':'eq','value':'Won'}]},
                 'A4':{'context_action':'refine','remove_filters':['opportunity_owner']},'A5':{'context_action':'refine','grain':'opportunity_sku'},'A6':{'context_action':'refine','grain':'opportunity'},
                 'B2':{'context_action':'refine','result_kind':'aggregate','presentation':'chart','chart_type':'bar','group_by':['stage_group'],'measures':['amount']},'B3':{'context_action':'refine','measures':['quantity']},
                 'B4':{'context_action':'refine','presentation':'table'},'B5':{'context_action':'refine','result_kind':'rows','grain':'opportunity_sku','filters':[{'field':'stage','operator':'eq','value':'Won'}]},
                 'B6':{'context_action':'replace','result_kind':'rows','grain':'opportunity'},'C3':{'context_action':'refine','result_kind':'aggregate','presentation':'cards','measures':['amount']},
                 'C5':{'context_action':'refine','grain':'opportunity_sku','filters':[{'field':'product_code','operator':'eq','value':w('product')}]},'C6':{'context_action':'refine','remove_filters':['product_code']},
                 'D2':{'context_action':'refine','presentation':'table'},'D3':{'context_action':'refine','result_kind':'rows','grain':'opportunity'},
                 'E2':{'context_action':'refine','remove_filters':['type']},'E3':{'context_action':'refine','filters':[{'field':'opportunity_owner','operator':'eq','value':w('owner_a')}]},'E4':{'context_action':'replace','result_kind':'rows','grain':'opportunity'}}
    return refinements.get(sid,plan)


class ScriptedPlanner:
    """Answers each rendered prompt with a scripted plan; overrides let tests inject wrong or failing answers.

    rejections={'T05': ['first invalid reply', ...]} makes the first generation(s) for a step return replies that are
    not plans; the correction attempt then returns the scripted plan (or the next rejection if more are listed)."""
    def __init__(self,witnesses,overrides=None,fail_on=(),rejections=None):
        self.witnesses=witnesses;self.overrides=overrides or {};self.fail_on=set(fail_on);self.rejections={k:list(v) for k,v in (rejections or {}).items()}
        self.calls=[];self.generations=[];self.corrections=[]
        self.prompts={render_prompt(s,witnesses):s for s in STEPS if all(k in witnesses for k in s['witnesses'])}
    def prompt_digest(self,effective_date=None):return 'sha256:scripted-planner'
    def scripted(self,step,view):
        values=self.overrides.get(step['id'])
        return values if values is not None else authored_plan(step,self.witnesses)
    def plan(self,question,history,previous=None,view='auto'):
        self.calls.append(question)
        step=self.prompts.get(question)
        if step is None: raise AssertionError('Unscripted prompt: '+question)
        if step['id'] in self.fail_on: raise RuntimeError('model unavailable')
        plan=parse_plan(self.scripted(step,view))
        if view!='auto' and plan.result_kind.value!='clarify': plan.grain='opportunity' if view=='summary' else 'opportunity_sku'
        return plan
    def generate(self,question,history,previous=None,view='auto',correction=None,effective_date=None):
        self.calls.append(question)
        step=self.prompts.get(question)
        if step is None: raise AssertionError('Unscripted prompt: '+question)
        if step['id'] in self.fail_on: raise RuntimeError('model unavailable')
        self.generations.append({'step':step['id'],'question':question,'history':list(history),'correction':correction,'effective_date':effective_date})
        if correction is not None: self.corrections.append({'step':step['id'],'question':question,'history':list(history),'correction':correction})
        outcome={'plan':None,'content':None,'error':None,'settings':{'provider':'scripted','model':'scripted','stream':False,'temperature':0,'max_tokens':0,'structured_output':'none'},
                 'fallback_events':[],'seconds':0.0,'prompt_digest':self.prompt_digest(effective_date),'excerpt':None}
        pending=self.rejections.get(step['id'])
        if pending:
            reply=pending.pop(0)
            outcome['content']=reply;outcome['excerpt']=reply[:300]
            try: parse_plan(reply)
            except PlanRejected as rejected: outcome['error']=str(rejected);return outcome
            outcome['plan']=parse_plan(reply);return outcome
        values=self.scripted(step,view)
        outcome['content']=json.dumps(values,default=str);outcome['excerpt']=outcome['content'][:300]
        plan=parse_plan(values)
        if view!='auto' and plan.result_kind.value!='clarify': plan.grain='opportunity' if view=='summary' else 'opportunity_sku'
        outcome['plan']=plan
        return outcome
