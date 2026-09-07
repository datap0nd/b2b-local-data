"""The query contract: version 2 (normalized) and version 1 (kept for saved plans and existing callers).

Version 2 separates what version 1 overloaded in `intent` and `dimensions`:

- result_kind: rows (one row per opportunity or opportunity/SKU pair) versus aggregate (grouped or overall measures).
- presentation: table, chart, or cards; a "table" of an aggregate keeps its grouping, it never means "underlying rows".
- columns: default (the established columns), include (defaults plus the named fields), or only (exactly the named
  fields plus the business keys) for row results.
- group_by: the grouping dimensions of an aggregate.

Grain, filters, measures, sorting, limits, refinement semantics, and the canonical financial rules are unchanged.
No executable text fields exist in either version."""
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

PLAN_VERSION = 2


class Intent(str, Enum):
    TABLE = 'table'
    METRIC = 'metric'
    CHART = 'chart'
    CLARIFY = 'clarify'


class ResultKind(str, Enum):
    ROWS = 'rows'
    AGGREGATE = 'aggregate'
    CLARIFY = 'clarify'


class Presentation(str, Enum):
    TABLE = 'table'
    CHART = 'chart'
    CARDS = 'cards'


class ColumnMode(str, Enum):
    DEFAULT = 'default'
    INCLUDE = 'include'
    ONLY = 'only'


class ContextAction(str, Enum):
    REPLACE = 'replace'
    REFINE = 'refine'


class Grain(str, Enum):
    OPPORTUNITY = 'opportunity'
    OPPORTUNITY_SKU = 'opportunity_sku'


class FilterOperator(str, Enum):
    EQ = 'eq'
    NE = 'ne'
    GT = 'gt'
    GE = 'ge'
    LT = 'lt'
    LE = 'le'
    CONTAINS = 'contains'
    IN = 'in'
    BETWEEN = 'between'


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True, allow_inf_nan=False)


Scalar = StrictStr | StrictInt | StrictFloat | StrictBool | None


class FilterClause(ContractModel):
    field: str = Field(min_length=1,max_length=80)
    operator: FilterOperator
    value: Scalar | list[Scalar]

    @model_validator(mode='after')
    def validate_value_shape(self):
        if self.operator in (FilterOperator.IN,FilterOperator.BETWEEN):
            if not isinstance(self.value,list) or not 1 <= len(self.value) <= 100:
                raise ValueError('in/between requires a nonempty list of at most 100 values')
        elif isinstance(self.value,list):
            raise ValueError('this operator requires a scalar')
        if self.operator == FilterOperator.BETWEEN and len(self.value) != 2:
            raise ValueError('between requires exactly two values')
        values = self.value if isinstance(self.value,list) else [self.value]
        if any(isinstance(x,str) and len(x)>500 for x in values):
            raise ValueError('filter text is too long')
        return self


class SortClause(ContractModel):
    field: str = Field(min_length=1,max_length=80)
    direction: Literal['asc','desc'] = 'desc'


class Measure(str, Enum):
    AMOUNT = 'amount'
    QUANTITY = 'quantity'
    SKU_COUNT = 'sku_count'
    OPPORTUNITY_COUNT = 'opportunity_count'
    # Added in 0.4: sum of deal_size_on_pricing_date_usd, counted once per opportunity.
    DEAL_SIZE = 'deal_size'


class ColumnSelection(ContractModel):
    """Which columns a row result shows: the defaults, the defaults plus named fields, or exactly the named fields."""
    mode: ColumnMode = ColumnMode.DEFAULT
    fields: list[StrictStr] = Field(default_factory=list,max_length=10)

    @model_validator(mode='after')
    def validate_fields(self):
        if len(set(self.fields)) != len(self.fields):
            raise ValueError('duplicate fields are not allowed')
        if self.mode == ColumnMode.DEFAULT and self.fields:
            raise ValueError('default columns take no field list')
        if self.mode != ColumnMode.DEFAULT and not self.fields:
            raise ValueError(f'{self.mode.value} columns need at least one field')
        return self


class QueryPlanV1(ContractModel):
    """Version 1, kept for saved plans and existing callers; parse_plan adapts it to version 2."""
    version: Literal[1] = 1
    intent: Intent = Intent.TABLE
    context_action: ContextAction = ContextAction.REPLACE
    grain: Grain = Grain.OPPORTUNITY
    filters: list[FilterClause] = Field(default_factory=list,max_length=20)
    remove_filters: list[StrictStr] = Field(default_factory=list,max_length=20)
    dimensions: list[StrictStr] = Field(default_factory=list,max_length=10)
    measures: list[Measure] = Field(default_factory=list,max_length=5)
    sort: list[SortClause] = Field(default_factory=list,max_length=3)
    limit: StrictInt | None = Field(default=None,ge=1,le=1000)
    chart_type: Literal['bar','line','area','scatter'] | None = None
    clarification: StrictStr | None = Field(default=None,max_length=300)
    suggestions: list[StrictStr] = Field(default_factory=list,max_length=3)

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and 'version' in value and type(value['version']) is not int:
            raise ValueError('version must be the integer 1')
        return value

    @model_validator(mode='after')
    def validate_intent(self):
        if self.intent == Intent.CLARIFY and not (self.clarification or '').strip():
            raise ValueError('clarify needs a question')
        if self.intent == Intent.CHART and self.chart_type is None:
            raise ValueError('chart needs chart_type')
        if any(len(s)>300 for s in self.suggestions):
            raise ValueError('suggestion is too long')
        for values in (self.dimensions,self.measures,self.remove_filters):
            if len(set(values)) != len(values):
                raise ValueError('duplicate fields are not allowed')
        return self


class QueryPlanV2(ContractModel):
    # Set by the version-1 adapter: which fields the caller actually provided, and its raw dimensions list.
    _provided: set | None = PrivateAttr(default=None)
    _v1_dimensions: list | None = PrivateAttr(default=None)
    version: Literal[2] = 2
    result_kind: ResultKind = ResultKind.ROWS
    presentation: Presentation = Presentation.TABLE
    context_action: ContextAction = ContextAction.REPLACE
    grain: Grain = Grain.OPPORTUNITY
    filters: list[FilterClause] = Field(default_factory=list,max_length=20)
    remove_filters: list[StrictStr] = Field(default_factory=list,max_length=20)
    columns: ColumnSelection = Field(default_factory=ColumnSelection)
    group_by: list[StrictStr] = Field(default_factory=list,max_length=10)
    measures: list[Measure] = Field(default_factory=list,max_length=5)
    sort: list[SortClause] = Field(default_factory=list,max_length=3)
    limit: StrictInt | None = Field(default=None,ge=1,le=1000)
    chart_type: Literal['bar','line','area','scatter'] | None = None
    clarification: StrictStr | None = Field(default=None,max_length=300)
    suggestions: list[StrictStr] = Field(default_factory=list,max_length=3)

    @model_validator(mode='before')
    @classmethod
    def exact_version(cls,value):
        if isinstance(value,dict) and 'version' in value and type(value['version']) is not int:
            raise ValueError('version must be the integer 2')
        return value

    @model_validator(mode='after')
    def validate_shape(self):
        if self.result_kind == ResultKind.CLARIFY and not (self.clarification or '').strip():
            raise ValueError('clarify needs a question')
        if self.presentation == Presentation.CHART and self.chart_type is None:
            raise ValueError('a chart presentation needs chart_type')
        if self.result_kind == ResultKind.ROWS and self.presentation != Presentation.TABLE:
            raise ValueError('row results are presented as a table; use result_kind aggregate for charts and cards')
        if self.result_kind == ResultKind.AGGREGATE and self.columns.mode != ColumnMode.DEFAULT:
            raise ValueError('columns apply to row results; aggregates use group_by and measures')
        if self.result_kind == ResultKind.ROWS and self.group_by:
            raise ValueError('group_by applies to aggregates; use columns for row results')
        if any(len(s)>300 for s in self.suggestions):
            raise ValueError('suggestion is too long')
        for values in (self.group_by,self.measures,self.remove_filters):
            if len(set(values)) != len(values):
                raise ValueError('duplicate fields are not allowed')
        return self

    # ----- derived views kept for history descriptions and older code paths -----
    @property
    def intent(self):
        if self.result_kind == ResultKind.CLARIFY: return Intent.CLARIFY
        if self.result_kind == ResultKind.ROWS: return Intent.TABLE
        return Intent.CHART if self.presentation == Presentation.CHART else Intent.METRIC

    @property
    def dimensions(self):
        """Grouping dimensions of an aggregate, or the explicitly named columns of a row result."""
        if self.result_kind == ResultKind.AGGREGATE: return list(self.group_by)
        return list(self.columns.fields) if self.columns.mode != ColumnMode.DEFAULT else []

    def legacy_dict(self):
        """A version-1-shaped dictionary (intent/dimensions) for readers that still speak the old vocabulary."""
        return {'version':1,'intent':self.intent.value,'context_action':self.context_action.value,'grain':self.grain.value,
                'filters':[f.model_dump(mode='json') for f in self.filters],'remove_filters':list(self.remove_filters),'dimensions':self.dimensions,
                'measures':[m.value for m in self.measures],'sort':[s.model_dump(mode='json') for s in self.sort],'limit':self.limit,
                'chart_type':self.chart_type,'clarification':self.clarification,'suggestions':list(self.suggestions),
                'columns_mode':self.columns.mode.value,'presentation':self.presentation.value,'result_kind':self.result_kind.value}


def adapt_v1(plan):
    """Translate a version-1 plan into the normalized contract without changing what it asks for."""
    if plan.intent == Intent.CLARIFY:
        return QueryPlanV2(result_kind=ResultKind.CLARIFY,presentation=Presentation.TABLE,context_action=plan.context_action,grain=plan.grain,
                           clarification=plan.clarification,suggestions=list(plan.suggestions),remove_filters=list(plan.remove_filters))
    common=dict(context_action=plan.context_action,grain=plan.grain,filters=list(plan.filters),remove_filters=list(plan.remove_filters),
                measures=list(plan.measures),sort=list(plan.sort),limit=plan.limit,suggestions=list(plan.suggestions))
    if plan.intent == Intent.TABLE:
        columns=ColumnSelection(mode=ColumnMode.ONLY,fields=list(plan.dimensions)) if plan.dimensions else ColumnSelection()
        return QueryPlanV2(result_kind=ResultKind.ROWS,presentation=Presentation.TABLE,columns=columns,**common)
    presentation=Presentation.CHART if plan.intent == Intent.CHART else (Presentation.TABLE if plan.dimensions else Presentation.CARDS)
    return QueryPlanV2(result_kind=ResultKind.AGGREGATE,presentation=presentation,group_by=list(plan.dimensions),chart_type=plan.chart_type,**common)
