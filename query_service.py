"""The one path every question takes: plan with the model, validate, merge, execute, and record."""
import threading

from app_config import AppError
from query_engine import QUERY_FIELDS, merge_plan
from query_models import Intent


def describe_result(plan,table):
    """A readable record of what was shown, kept in the conversation history for the user and the model."""
    layout='opportunity summary' if plan.grain.value=='opportunity' else 'opportunity/SKU detail'
    kind={'table':'Table','metric':'Grouped metrics','chart':f"{plan.chart_type or ''} chart".strip().capitalize()}[plan.intent.value]
    parts=[f"{kind} ({layout}): {table['total_rows']:,} rows" + (f", showing {len(table['rows']):,}" if table['truncated'] else '')]
    if plan.filters:
        parts.append('filters: '+'; '.join(f"{f.field} {f.operator.value} {f.value!r}" for f in plan.filters))
    if plan.dimensions:
        parts.append(('grouped by ' if plan.intent.value!='table' else 'columns: ')+', '.join(plan.dimensions))
    if plan.measures:
        parts.append('measures: '+', '.join(m.value for m in plan.measures))
    if plan.sort:
        parts.append('sorted by '+', '.join(f"{s.field} {s.direction}" for s in plan.sort))
    if plan.limit:
        parts.append(f'limit {plan.limit}')
    if table.get('totals') and table['totals'].get('amount') is not None:
        parts.append(f"total amount {table['totals']['amount']}")
    return ' · '.join(parts)+'.'


class QueryService:
    """Ordinary questions and acceptance-test steps share this planner/validation/merge/execution path.

    Callers supply the conversation store and the data snapshot, so tests can use an isolated
    conversation and a pinned snapshot while exercising exactly the production logic."""
    def __init__(self,planner,executor):
        self.planner,self.executor=planner,executor
        # One model call at a time; the same lock protects ordinary and test questions.
        self.lane=threading.Lock()

    def ask(self,store,owner,session_id,question,view,views,snapshot_at):
        question=question.strip()
        if not question: raise AppError('Enter a question.')
        history,previous=store.context(owner,session_id)
        incoming=self.planner.plan(question,history,previous,view)
        if set(incoming.remove_filters)-QUERY_FIELDS:
            raise AppError('Unknown field in remove_filters.')
        plan=merge_plan(previous,incoming)
        returned=incoming.model_dump(mode='json')
        if plan.intent==Intent.CLARIFY:
            store.append(owner,session_id,question,plan.clarification)
            return {'kind':'clarify','question':plan.clarification,'suggestions':plan.suggestions,'session_id':session_id,'returned_plan':returned}
        table=self.executor.execute(views,plan)
        table['snapshot_at']=snapshot_at
        store.append(owner,session_id,question,describe_result(plan,table),plan)
        return {'kind':'table','table':table,'plan':plan.model_dump(mode='json'),'suggestions':plan.suggestions,'session_id':session_id,'returned_plan':returned}
