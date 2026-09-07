"""Version 1 of the supplied query contract. No executable text fields exist."""
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator


class Intent(str, Enum):
    TABLE = 'table'
    METRIC = 'metric'
    CHART = 'chart'
    CLARIFY = 'clarify'


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


class QueryPlanV1(ContractModel):
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
