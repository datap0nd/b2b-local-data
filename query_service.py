"""The one path every question takes: plan with the model, validate, merge, execute, describe, save, and record.

A reply that is not an executable plan (invalid JSON, a schema violation, or a deterministic validation error)
gets exactly one recorded correction attempt: the model sees the unchanged conversation, its rejected reply, and
the validation feedback, never any expected answer. Transport and data failures are not corrected.

Every data answer carries version-2 result metadata (currency of the complete population, verified source
freshness, complete-result metrics, structured warnings, available views) and a deterministic answer text. The
bounded answer, with its Summary/Detailed variant where one applies, is saved with the turn so reopening the
conversation restores the original tables and charts without SQL or model calls."""
import threading
from time import monotonic

from answer_text import compose_answer
from app_config import AppError
from answer_text import default_suggestions
from query_engine import QUERY_FIELDS, PlanRejected, merge_plan, supported_suggestions, validate_execution
from query_models import ResultKind

RESULT_CONTRACT_VERSION=2


def describe_result(plan,table):
    """A readable record of what was shown, kept in the conversation history for the user and the model."""
    layout='opportunity summary' if plan.grain.value=='opportunity' else 'opportunity/SKU detail'
    if plan.result_kind==ResultKind.ROWS: kind='Table'
    else: kind={'table':'Grouped values','chart':f"{plan.chart_type or ''} chart".strip().capitalize(),'cards':'Totals'}[plan.presentation.value]
    parts=[f"{kind} ({layout}): {table['total_rows']:,} rows" + (f", showing {len(table['rows']):,}" if table['truncated'] else '')]
    if plan.filters:
        parts.append('filters: '+'; '.join(f"{f.field} {f.operator.value} {f.value!r}" for f in plan.filters))
    if plan.result_kind==ResultKind.AGGREGATE and plan.group_by:
        parts.append('grouped by '+', '.join(plan.group_by))
    elif plan.result_kind==ResultKind.ROWS and plan.columns.mode.value!='default':
        parts.append(f"columns ({plan.columns.mode.value}): "+', '.join(plan.columns.fields))
    if plan.measures:
        parts.append('measures: '+', '.join(m.value for m in plan.measures))
    if plan.sort:
        parts.append('sorted by '+', '.join(f"{s.field} {s.direction}" for s in plan.sort))
    if plan.limit:
        parts.append(f'limit {plan.limit}')
    if table.get('totals') and table['totals'].get('amount') is not None:
        parts.append(f"total amount {table['totals']['amount']}")
    return ' · '.join(parts)+'.'


def excerpt(text,limit=300):
    text='' if text is None else ' '.join(str(text).split())
    return text[:limit]


def attach_freshness(table,views,snapshot_at):
    """Result metadata gets the verified freshness and the fingerprint of the snapshot actually used."""
    metadata=table.setdefault('metadata',{})
    metadata['freshness']=dict(getattr(views,'freshness',None) or {'status':'unavailable','reason':'No verified update time for this source.'})
    metadata['fingerprint']=getattr(views,'fingerprint',None)
    metadata['loaded_at']=snapshot_at
    table['snapshot_at']=snapshot_at
    return table


class QueryService:
    """Ordinary questions and acceptance-test steps share this planner/validation/merge/execution path.

    Callers supply the conversation store and the data snapshot, so tests can use an isolated
    conversation and a pinned snapshot while exercising exactly the production logic."""
    MAX_ATTEMPTS=2   # the first generation plus one recorded correction

    def __init__(self,planner,executor):
        self.planner,self.executor=planner,executor
        # One model call at a time; the same lock protects ordinary and test questions.
        self.lane=threading.Lock()

    def _generate(self,question,history,previous,view,correction,effective_date):
        """Normalize any planner (generate-capable or plan-only) into one outcome dictionary."""
        started=monotonic()
        # A real generate() method (not a mock's auto-attribute) means the planner can be asked for a correction.
        if callable(getattr(type(self.planner),'generate',None)):
            outcome=self.planner.generate(question,history,previous,view,correction=correction,effective_date=effective_date)
            outcome.setdefault('seconds',round(monotonic()-started,3))
            return outcome
        # Plan-only planners (scripted or mocked) cannot be corrected; a rejection is final.
        try: plan=self.planner.plan(question,history,previous,view)
        except PlanRejected as rejected:
            return {'plan':None,'content':None,'error':str(rejected),'settings':None,'fallback_events':[],'seconds':round(monotonic()-started,3),'prompt_digest':None,'excerpt':None}
        return {'plan':plan,'content':None,'error':None,'settings':None,'fallback_events':[],'seconds':round(monotonic()-started,3),'prompt_digest':None,'excerpt':None}

    def answer_payload(self,plan,views,snapshot_at):
        """Execute a validated plan and build the complete answer: primary table, its variant, and the answer text."""
        table=attach_freshness(self.executor.execute(views,plan),views,snapshot_at)
        variants={}
        if plan.result_kind==ResultKind.ROWS:
            other='detail' if table['view']=='summary' else 'summary'
            try:
                variants[other]=attach_freshness(self.executor.variant(views,plan,other),views,snapshot_at)
            except AppError as error:
                variants[other]={'error':str(error)}
        answer=compose_answer(table)
        return {'table':table,'variants':variants,'answer':answer,'contract_version':RESULT_CONTRACT_VERSION}

    def execute_and_save(self,store,owner,session_id,question,plan,views,snapshot_at,model_reply=None,rerun_of=None):
        """Run a plan, record the turn, and save the bounded answer with its provenance. Returns the answer payload."""
        payload=self.answer_payload(plan,views,snapshot_at)
        table=payload['table']
        response=describe_result(plan,table)
        turn_id=store.append(owner,session_id,question,response,plan,model_reply=model_reply,kind='data')
        saved={'table':store.bounded(table),'variants':{k:(store.bounded(v) if 'rows' in v else v) for k,v in payload['variants'].items()},'answer':payload['answer'],'contract_version':RESULT_CONTRACT_VERSION,'rerun_of':rerun_of}
        try:
            store.save_result(owner,session_id,turn_id,'data',plan,table['metadata'].get('fingerprint'),table['metadata'].get('freshness'),saved)
        except AppError:
            pass   # an oversized answer is still shown; it simply cannot be restored later
        return payload|{'turn_id':turn_id,'plan':plan.model_dump(mode='json'),'session_id':session_id,'rerun_of':rerun_of}

    def ask(self,store,owner,session_id,question,view,views,snapshot_at,effective_date=None):
        question=question.strip()
        if not question: raise AppError('Enter a question.')
        history,previous=store.context(owner,session_id)
        attempts=[]
        correction=None
        plan=incoming=None
        outcome=None
        for attempt in range(1,self.MAX_ATTEMPTS+1):
            outcome=self._generate(question,history,previous,view,correction,effective_date)
            record={'attempt':attempt,'seconds':outcome.get('seconds'),'reply_excerpt':outcome.get('excerpt'),'corrected':correction is not None}
            try:
                if outcome['plan'] is None: raise PlanRejected(outcome['error'] or 'The model reply was not a plan.')
                incoming=outcome['plan']
                if set(incoming.remove_filters)-QUERY_FIELDS:
                    raise PlanRejected('Unknown field in remove_filters: '+', '.join(sorted(set(incoming.remove_filters)-QUERY_FIELDS))+'.')
                candidate=merge_plan(previous,incoming)
                if candidate.result_kind!=ResultKind.CLARIFY: validate_execution(candidate)
            except PlanRejected as rejected:
                record.update(status='rejected',error=str(rejected))
                attempts.append(record)
                # Only a reply we can show back can be corrected; plan-only planners return no text.
                if attempt<self.MAX_ATTEMPTS and outcome.get('content') is not None:
                    correction={'rejected':outcome['content'],'feedback':str(rejected)}
                    continue
                raise AppError(str(rejected)+(' The model did not produce a valid plan after one correction attempt.' if attempt>1 else ''))
            record.update(status='accepted')
            attempts.append(record)
            plan=candidate
            break
        diagnostics={'attempts':attempts,'recovered':len(attempts)>1,'settings':outcome.get('settings'),'fallback_events':list(outcome.get('fallback_events') or []),
                     'prompt_digest':outcome.get('prompt_digest'),'effective_date':effective_date.isoformat() if effective_date else None}
        returned=incoming.model_dump(mode='json')
        if plan.result_kind==ResultKind.CLARIFY:
            suggestions=supported_suggestions(plan.suggestions)
            turn_id=store.append(owner,session_id,question,plan.clarification,model_reply=returned,kind='clarify')
            return {'kind':'clarify','question':plan.clarification,'suggestions':suggestions,'session_id':session_id,'turn_id':turn_id,'returned_plan':returned,'diagnostics':diagnostics}
        payload=self.execute_and_save(store,owner,session_id,question,plan,views,snapshot_at,model_reply=returned)
        return {'kind':'table','suggestions':supported_suggestions(plan.suggestions) or default_suggestions(payload['table']),'returned_plan':returned,'diagnostics':diagnostics}|payload
