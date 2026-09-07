"""The versioned acceptance suite: 54 prompt turns, 12 browser checks, witness selection, and plan matching.

Expectations are authored here, never adopted from model output. The reference result for a step is
computed by reference_evaluator from the authored expectation plus the documented equivalent plan
variant that the model chose (for example a Won stage-group filter versus its member stages).
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from reference_evaluator import STAGE_MEMBERS, r_number

SUITE_VERSION = '2.0.0'
CURRENCY_FIELDS = ('opp_amount_converted_currency', 'amount_converted_currency')
PRODUCT_FIELDS = {'product_code', 'pet_name', 'gscm_product_group_new', 'amount_converted_currency', 'sku_amount', 'exported_opp_amount_value_count'}
# Contract default columns, copied from the published query contract.
SUMMARY_DEFAULT = ['opportunity_no', 'opportunity_name', 'end_customer', 'opportunity_owner', 'stage', 'close_date', 'product_codes', 'product_names',
                   'quantity', 'opportunity_amount', 'sku_count', 'opp_amount_converted_currency', 'has_amount_discrepancy', 'has_quality_warning']
DETAIL_DEFAULT = ['opportunity_no', 'product_code', 'pet_name', 'end_customer', 'opportunity_owner', 'stage', 'quantity', 'sku_amount',
                  'amount_converted_currency', 'has_quality_warning']
AMOUNT_COLUMN = {'opportunity': 'opportunity_amount', 'sku': 'sku_amount'}
ALL_MEASURES = ['amount', 'quantity', 'opportunity_count', 'sku_count']


def step(id, title, prompt, expect, view='auto', conversation=None, witnesses=(), browser=(), needs=(), behavior=''):
    return {'id': id, 'title': title, 'prompt': prompt, 'view': view, 'conversation': conversation, 'expect': expect,
            'witnesses': list(witnesses), 'browser_checks': list(browser), 'needs': list(needs), 'behavior': behavior}


def table(grain='opportunity', filters=(), columns=None, sort=None, limit=None, include=None):
    """A row result. columns=None expects the default columns; columns=[...] an exact 'only' selection (plus keys);
    include=[...] the defaults plus those fields (an additive request such as "with their deal size")."""
    return {'intent': 'table', 'grain': grain, 'filters': list(filters), 'columns': columns, 'include': list(include) if include else None, 'sort': sort, 'limit': limit}


def metric(grain='any', filters=(), group=(), measures=(), intent='metric', chart_type=None, sort=None):
    return {'intent': intent, 'grain': grain, 'filters': list(filters), 'group': list(group), 'measures': list(measures), 'chart_type': chart_type, 'sort': sort, 'limit': None}


def chart(chart_type, grain='any', filters=(), group=(), measures=(), sort=None):
    return metric(grain, filters, group, measures, 'chart', chart_type, sort)


CLARIFY = {'intent': 'clarify'}
F = lambda field, op, value=None: {'field': field, 'op': op, 'value': value}

STEPS = [
    step('T01', 'Full opportunity summary', 'Show every opportunity as a summary table.', table(), view='summary', browser=(1, 3, 4),
         behavior='Opportunity grain, no filters, default columns with the opportunity key, complete count with a 1,000-row preview.'),
    step('T02', 'Full SKU detail', 'Show every opportunity and product row in detail.', table('sku'), view='detail', browser=(2, 5),
         behavior='Opportunity/SKU grain, no filters, default columns with both keys, complete count with a 1,000-row preview.'),
    step('T03', 'Summary with selected columns', 'Show a summary table with only the opportunity number, opportunity owner, stage, close date, quantity, and amount. Limit it to 20 rows.',
         table(columns=['opportunity_owner', 'stage', 'close_date', 'quantity', 'opportunity_amount'], limit=20), view='summary', needs=('twenty_plus',),
         behavior='Exactly the selected columns plus the opportunity key, first 20 rows by opportunity number, complete count reported.'),
    step('T04', 'Detail with selected columns', 'Show a detail table with only the opportunity number, product code, product name, quantity, and amount. Limit it to 20 rows.',
         table('sku', columns=['pet_name', 'quantity', 'sku_amount'], limit=20), view='detail', needs=('twenty_plus',),
         behavior='Exactly the selected columns plus both keys, first 20 rows by keys, complete count reported.'),
    step('T05', 'Overall totals', 'What are the total amount, the total quantity, the number of opportunities, and the number of opportunity/SKU rows across all data?',
         metric(measures=ALL_MEASURES), needs=('single_currency',), browser=(13,), behavior='One ungrouped row with all four measures over the complete source.'),
    step('T06', 'Totals by stage group', 'Show the total amount, total quantity, number of opportunities, and number of opportunity/SKU rows by stage group.',
         metric(group=['stage_group'], measures=ALL_MEASURES), needs=('single_currency',), behavior='One row per stage group (Won, Open, Lost, or none).'),
    step('T07', 'Opportunity counts by owner', 'How many opportunities does each opportunity owner have?', metric(group=['opportunity_owner'], measures=['opportunity_count']),
         behavior='Distinct opportunity counts per owner; a null owner forms its own group.'),
    step('T08', 'Amount by currency', 'Show the total amount by currency.', metric(group=['currency'], measures=['amount']),
         behavior='Amount grouped by the currency column of the chosen grain.'),
    step('T09', 'Won filter', 'Show the Won opportunities.', table(filters=[F('stage', 'group', 'Won')]), view='summary', browser=(15,), behavior='Stage group Won expands to Won, Rollout Started, and Rollout Finished.'),
    step('T10', 'Open filter', 'Show the Open opportunities.', table(filters=[F('stage', 'group', 'Open')]), view='summary', behavior='Stage group Open expands to Identified, Qualified, and Negotiation.'),
    step('T11', 'Lost filter', 'Show the Lost opportunities.', table(filters=[F('stage', 'group', 'Lost')]), view='summary', behavior='Stage group Lost expands to Dropped and Lost.'),
    step('T12', 'Exact owner', 'Show the opportunities owned by {owner_a}.', table(filters=[F('opportunity_owner', 'eq', '{owner_a}')]), view='summary', witnesses=('owner_a',),
         behavior='Exact, case-preserving owner equality.'),
    step('T13', 'Case-insensitive customer search', "Show the opportunities whose end customer name contains '{customer_fragment}'.",
         table(filters=[F('end_customer', 'contains', '{customer_fragment}')]), view='summary', witnesses=('customer_fragment',), behavior='Literal, case-insensitive substring match.'),
    step('T14', 'Opportunity type', "Show the opportunities of type '{type}'.", table(filters=[F('type', 'eq', '{type}')]), view='summary', witnesses=('type',), behavior='Exact type equality.'),
    step('T15', 'Probability at least 75%', 'Show the opportunities with a probability of at least 75%.', table(filters=[F('probability', 'ge', Decimal('0.75'))]), view='summary', needs=('probability_high',),
         behavior='Probability is a fraction; 75% is 0.75. Null probabilities never match.'),
    step('T16', 'Missing probability', 'Show the opportunities that have no probability value.', table(filters=[F('probability', 'eq', None)]), view='summary', needs=('probability_null',),
         behavior='Null equality selects rows without a parsed probability.'),
    step('T17', 'Close date in 2026', 'Show the opportunities with a close date in 2026.', table(filters=[F('close_date', 'year', 2026)]), view='summary', needs=('close_date_2026',),
         behavior='Inclusive 2026-01-01 to 2026-12-31 range on the parsed close date.'),
    step('T18', 'Close month in 2026', 'Show the opportunities with a close month in 2026.', table(filters=[F('close_month', 'year', 2026)]), view='summary', needs=('close_month_2026',),
         behavior='Inclusive 2026 range on the parsed close month.'),
    step('T19', 'Created date in 2026', 'Show the opportunities created in 2026.', table(filters=[F('created_date', 'year', 2026)]), view='summary', needs=('created_date_2026',),
         behavior='Inclusive 2026 range on the parsed created date.'),
    step('T20', 'Last modified in 2026', 'Show the opportunities last modified in 2026.', table(filters=[F('last_modified_date', 'year', 2026)]), view='summary', needs=('last_modified_date_2026',),
         behavior='Inclusive 2026 range on the parsed last modified date (the latest per opportunity).'),
    step('T21', 'Whole opportunities containing a product', 'Show the complete opportunities containing product {product}, including the value of all their products.',
         table(filters=[F('product_code', 'eq', '{product}')]), view='summary', witnesses=('product',), behavior='Opportunity grain: every opportunity with that product, amounts include all of its products.'),
    step('T22', 'Only matching product rows', 'Show only the rows for product {product}, with their quantity and amount.', table('sku', filters=[F('product_code', 'eq', '{product}')]), view='detail', witnesses=('product',),
         behavior='SKU grain: only the matching product rows and their own sums.'),
    step('T23', 'Pair with repeated raw rows', 'Show the detail row for opportunity {dup_opp} and product {dup_sku}.',
         table('sku', filters=[F('opportunity_no', 'eq', '{dup_opp}'), F('product_code', 'eq', '{dup_sku}')]), view='detail', witnesses=('dup_opp', 'dup_sku'),
         behavior='One row; quantity and amount sum the repeated raw lines; source_row_count shows the repetition.'),
    step('T24', 'Complete parent opportunity', 'Show the complete opportunity {dup_opp} as a summary.', table(filters=[F('opportunity_no', 'eq', '{dup_opp}')]), view='summary', witnesses=('dup_opp',),
         behavior='One opportunity row whose amount is the sum of all its SKU amounts.'),
    step('T25', 'Ten largest opportunities', 'Show the 10 largest opportunities by total amount. Break ties by opportunity number.',
         table(sort=[('opportunity_amount', False), ('opportunity_no', True)], limit=10), view='summary', needs=('ten_plus',), behavior='Sort the complete set by amount descending then opportunity number, then keep 10.'),
    step('T26', 'Nonexistent identifier', 'Show opportunity {nonexistent}.', table(filters=[F('opportunity_no', 'eq', '{nonexistent}')]), view='summary', witnesses=('nonexistent',), browser=(14,),
         behavior='A valid query with zero rows, not an error.'),
    step('T27', 'Bar chart by stage group', 'Create a bar chart of the total amount and total quantity by stage group.', chart('bar', group=['stage_group'], measures=['amount', 'quantity']), browser=(6, 10), needs=('single_currency',),
         behavior='Bar chart with one grouping dimension and two measures.'),
    step('T28', 'Line chart by close month', 'Create a line chart of the total amount by close month, earliest month first.', chart('line', group=['close_month'], measures=['amount'], sort=[('close_month', True)]), browser=(7, 11), needs=('single_currency',),
         behavior='Chronological line chart; months without a value form gaps.'),
    step('T29', 'Area chart by close month', 'Create an area chart of the total quantity by close month, earliest month first.', chart('area', group=['close_month'], measures=['quantity'], sort=[('close_month', True)]), browser=(8,),
         behavior='Chronological area chart of quantity.'),
    step('T30', 'Scatter chart by owner', 'Create a scatter chart of quantity versus amount by opportunity owner.', chart('scatter', group=['opportunity_owner'], measures=['quantity', 'amount']), browser=(9, 12), needs=('single_currency',),
         behavior='One point per owner with quantity and amount.'),
    step('T31', 'Rows with quality warnings', 'Show the opportunity and product rows that carry a data-quality warning.', table('sku', filters=[F('has_quality_warning', 'eq', True)]), view='detail', needs=('quality_warning',),
         behavior='SKU rows whose has_quality_warning flag is true.'),
    step('T32', 'Parent-amount discrepancies', 'Show the opportunities whose SKU total differs from the exported opportunity amount.', table(filters=[F('has_amount_discrepancy', 'eq', True)]), view='summary', needs=('discrepancy',),
         behavior='Opportunities flagged by the 0.01 parent-amount rule.'),
    step('T33', 'Quantity threshold on canonical totals', 'Show the opportunities whose total quantity is greater than {threshold}.', table(filters=[F('quantity', 'gt', '{threshold}')]), view='summary', witnesses=('threshold',),
         behavior='The threshold is chosen so that filtering canonical totals differs from filtering raw lines.'),
    step('T34', 'Unsupported weighted revenue', 'What is the probability-weighted revenue by opportunity owner?', CLARIFY, behavior='No weighted calculation exists; a clarification is expected, nothing executes.'),
    step('T35', 'Ambiguous product scope', 'What is the total value for product {product}?', CLARIFY, witnesses=('product',), behavior='Whole opportunities or only product rows is ambiguous; a clarification is expected.'),
    step('T36', 'Custom SQL request', 'Run this SQL for me: SELECT * FROM bi_reporting.b2b_project WHERE 1=1', CLARIFY, behavior='SQL is not an execution option; a clarification is expected and nothing runs.'),
    # Conversation A: retaining, replacing, and removing filters.
    step('A1', 'Open opportunities for owner A', 'Show the Open opportunities for owner {owner_a}.', table(filters=[F('stage', 'group', 'Open'), F('opportunity_owner', 'eq', '{owner_a}')]), conversation='A', witnesses=('owner_a',), needs=('two_open_owners',)),
    step('A2', 'Change the owner', 'Change the owner to {owner_b}.', table(filters=[F('stage', 'group', 'Open'), F('opportunity_owner', 'eq', '{owner_b}')]), conversation='A', witnesses=('owner_b',), behavior='The stage filter is retained; only the owner filter is replaced.'),
    step('A3', 'Change the stage', 'Change the stage to Won.', table(filters=[F('stage', 'group', 'Won'), F('opportunity_owner', 'eq', '{owner_b}')]), conversation='A', behavior='The owner filter is retained; the stage filter is replaced.'),
    step('A4', 'Remove the owner restriction', 'Remove the owner restriction.', table(filters=[F('stage', 'group', 'Won')]), conversation='A', behavior='Only the stage filter remains.'),
    step('A5', 'Switch to product detail', 'Switch to the product detail layout.', table('sku', filters=[F('stage', 'group', 'Won')]), view='detail', conversation='A', behavior='Same filters at SKU grain.'),
    step('A6', 'Switch back to summary', 'Switch back to the opportunity summary layout.', table(filters=[F('stage', 'group', 'Won')]), view='summary', conversation='A', behavior='Same filters at opportunity grain.'),
    # Conversation B: moving between tables and charts.
    step('B1', 'Summary for a selected owner', 'Show a summary of the opportunities owned by {owner_c}.', table(filters=[F('opportunity_owner', 'eq', '{owner_c}')]), view='summary', conversation='B', witnesses=('owner_c',)),
    step('B2', 'Chart amount by stage group', 'Chart its total amount by stage group as a bar chart.', chart('bar', filters=[F('opportunity_owner', 'eq', '{owner_c}')], group=['stage_group'], measures=['amount']), conversation='B', needs=('single_currency',), behavior='The owner filter is retained.'),
    step('B3', 'Change the chart measure', 'Change the chart measure to quantity.', chart('bar', filters=[F('opportunity_owner', 'eq', '{owner_c}')], group=['stage_group'], measures=['quantity']), conversation='B', behavior='Same grouping and filter, quantity only.'),
    step('B4', 'Grouped values as a table', 'Show those exact grouped values as a table instead of a chart.', metric(filters=[F('opportunity_owner', 'eq', '{owner_c}')], group=['stage_group'], measures=['quantity']), conversation='B', behavior='Grouped metric rows equal to the chart values.'),
    step('B5', 'Won product rows behind the result', 'Show the detailed Won product rows behind that result.', table('sku', filters=[F('opportunity_owner', 'eq', '{owner_c}'), F('stage', 'group', 'Won')]), view='detail', conversation='B', behavior='Drill-down keeps the owner and adds the Won stage group at SKU grain.'),
    step('B6', 'Fresh unrestricted summary', 'Start a new question: show a summary of all opportunities without any restriction.', table(), view='summary', conversation='B', behavior='A replace question clears the earlier filters.'),
    # Conversation C: clarification and recovery.
    step('C1', 'Summary filtered to a currency', 'Show a summary of the opportunities in currency {currency}.', table(filters=[F('currency', 'eq', '{currency}')]), view='summary', conversation='C', witnesses=('currency',), browser=(16,)),
    step('C2', 'Unsupported weighted revenue', 'What is the probability-weighted revenue of those opportunities?', CLARIFY, conversation='C', behavior='A clarification that leaves the currency plan active.'),
    step('C3', 'Clarify: ordinary revenue', 'I mean the ordinary, unweighted total amount of those opportunities.', metric(filters=[F('currency', 'eq', '{currency}')], measures=['amount']), conversation='C', behavior='Total amount with the currency filter retained.'),
    step('C4', 'Ambiguous product scope', 'And what is the value of product {product} there?', CLARIFY, conversation='C', witnesses=('product',), behavior='Product scope is ambiguous; a clarification is expected.'),
    step('C5', 'Clarify: only product rows', "Only count that product's own rows, not the whole opportunities.", metric('sku', filters=[F('currency', 'eq', '{currency}'), F('product_code', 'eq', '{product}')], measures=['amount']), conversation='C', behavior='SKU grain amount for the product within the currency.'),
    step('C6', 'Remove the product restriction', 'Remove the product restriction.', metric(filters=[F('currency', 'eq', '{currency}')], measures=['amount']), conversation='C', behavior='Total amount for the currency again.'),
    # Auto-mode versions of the grain-sensitive cases: the model must choose the grain from the wording alone.
    step('T03a', 'Auto: selected opportunity columns', 'Show a table with only the opportunity number, opportunity owner, stage, close date, quantity, and amount. Limit it to 20 rows.',
         table(columns=['opportunity_owner', 'stage', 'close_date', 'quantity', 'opportunity_amount'], limit=20), view='auto', needs=('twenty_plus',),
         behavior='Auto mode: opportunity grain from the wording; exactly the selected columns plus the key, 20 rows.'),
    step('T04a', 'Auto: selected product columns', 'Show a table with only the opportunity number, product code, product name, quantity, and amount. Limit it to 20 rows.',
         table('sku', columns=['pet_name', 'quantity', 'sku_amount'], limit=20), view='auto', needs=('twenty_plus',),
         behavior='Auto mode: product fields imply opportunity/SKU grain; exactly the selected columns plus both keys, no currency column.'),
    step('T21a', 'Auto: whole opportunities containing a product', 'Show the complete opportunities containing product {product}, including the value of all their products.',
         table(filters=[F('product_code', 'eq', '{product}')]), view='auto', witnesses=('product',), behavior='Auto mode: opportunity grain; product filter selects whole opportunities.'),
    step('T22a', 'Auto: only matching product rows', 'Show only the rows for product {product}, with their quantity and amount.', table('sku', filters=[F('product_code', 'eq', '{product}')]), view='auto', witnesses=('product',),
         behavior='Auto mode: opportunity/SKU grain; "with their quantity and amount" keeps the default columns.'),
    step('T31a', 'Auto: rows with quality warnings', 'Show the opportunity and product rows that carry a data-quality warning.', table('sku', filters=[F('has_quality_warning', 'eq', True)]), view='auto', needs=('quality_warning',),
         behavior='Auto mode: "opportunity and product rows" means opportunity/SKU grain.'),
    # Column-selection paraphrases and negative controls.
    step('T37', 'Additive columns', 'Show the opportunities with their deal size.', table(include=['deal_size_on_pricing_date_usd']), view='summary',
         behavior='"With their deal size" keeps the default columns and adds deal_size_on_pricing_date_usd.'),
    step('T38', 'Exact projection paraphrase', 'List just the opportunity number, end customer, and amount for every opportunity.', table(columns=['end_customer', 'opportunity_amount']), view='summary',
         behavior='"Just" is an exact selection: customer and amount plus the key, nothing else.'),
    step('T39', 'Additive negative control', 'Show the opportunities including the first channel and the age.', table(include=['first_channel', 'age']), view='summary',
         behavior='"Including" is additive: defaults plus first_channel and age, not an exclusive projection.'),
    # Conversation D: presentation-only changes versus underlying rows.
    step('D1', 'Quantity by stage group chart', 'Chart the total quantity by stage group as a bar chart.', chart('bar', group=['stage_group'], measures=['quantity']), conversation='D', behavior='Bar chart of quantity by stage group.'),
    step('D2', 'Same values as a table', 'Show the same values as a table.', metric(group=['stage_group'], measures=['quantity']), conversation='D', behavior='Presentation only: the grouped values as a table, grouping and measure unchanged.'),
    step('D3', 'Opportunities behind the values', 'Show the opportunities behind those values.', table(), view='auto', conversation='D', behavior='Underlying rows: every opportunity of the same (unrestricted) population at opportunity grain.'),
    # Conversation E: removing one filter keeps the unrelated ones; a fresh question clears the scope.
    step('E1', 'Open, typed, closing in 2026', "Show the Open opportunities of type '{type}' with a close date in 2026.", table(filters=[F('stage', 'group', 'Open'), F('type', 'eq', '{type}'), F('close_date', 'year', 2026)]), view='summary', conversation='E', witnesses=('type',), needs=('close_date_2026',)),
    step('E2', 'Remove the type restriction', 'Remove the type restriction.', table(filters=[F('stage', 'group', 'Open'), F('close_date', 'year', 2026)]), conversation='E', behavior='The stage and close-date filters stay.'),
    step('E3', 'Add an owner', 'Now only the ones owned by {owner_a}.', table(filters=[F('stage', 'group', 'Open'), F('close_date', 'year', 2026), F('opportunity_owner', 'eq', '{owner_a}')]), conversation='E', witnesses=('owner_a',), behavior='Stage and date filters are retained; the owner filter is added.'),
    step('E4', 'Start over', 'Start over: show every opportunity.', table(), view='summary', conversation='E', behavior='A new unrestricted question clears the previous scope.'),
]
STEP_INDEX = {s['id']: i for i, s in enumerate(STEPS)}

# Browser checks run against the production renderer (the same result view, options, formatting, and handlers
# ordinary answers use); expected values are recomputed independently in the browser from the payload.
BROWSER_CHECKS = [
    {'id': 1, 'title': 'Compact summary table: visible columns, merged key cell, formatted values, hidden fields in row details', 'step': 'T01'},
    {'id': 2, 'title': 'Compact detail table: visible columns, merged product cell, formatted values', 'step': 'T02'},
    {'id': 3, 'title': 'Ascending numeric sort of displayed rows by header click', 'step': 'T01'},
    {'id': 4, 'title': 'Descending sort with nulls last and column selection', 'step': 'T01'},
    {'id': 5, 'title': 'CSV export through the export control: all returned columns, displayed rows in current order', 'step': 'T02'},
    {'id': 6, 'title': 'Horizontal bars: order, proportional lengths, value labels, tooltip', 'step': 'T27'},
    {'id': 7, 'title': 'Line chart: chronological order, missing-value gaps, tooltip', 'step': 'T28'},
    {'id': 8, 'title': 'Area chart: baseline, fill, plotted values', 'step': 'T29'},
    {'id': 9, 'title': 'Scatter chart: point coordinates and tooltip', 'step': 'T30'},
    {'id': 10, 'title': 'Chart-measure change without SQL or Qwen calls', 'step': 'T27'},
    {'id': 11, 'title': '30-group chart limit disclosure and chart stability while the table is sorted', 'step': 'T28'},
    {'id': 12, 'title': 'Redraw after a real resize event: finite coordinates, painted canvas, no browser errors', 'step': 'T30'},
    {'id': 13, 'title': 'Metric cards for an ungrouped metric', 'step': 'T05'},
    {'id': 14, 'title': 'Empty result state with its filter chips', 'step': 'T26'},
    {'id': 15, 'title': 'Filter chips, stage badges, and warnings', 'step': 'T09'},
    {'id': 16, 'title': 'Currency label from the currency filter', 'step': 'C1'},
]

# Clarification meaning is checked with explicit predicates per case (accepted wording variants). A clarification
# whose wording matches none of the variants is marked for review; it never passes automatically.
UNSUPPORTED_TERMS = re.compile(r'\b(average|averages|mean|median|weighted|forecast|predict|prediction|growth|trend|trends|ratio|percentage of|percent of|share of|variance|deviation|moving|cumulative|run rate|coverage|conversion rate|win rate)\b', re.I)
NEGATION = r"(?:not|cannot|can't|can not|unable|isn't|is not|aren't|don't|do not|doesn't|does not|won't|no|unsupported|beyond|outside)"
CLARIFICATION_RULES = {
    'unsupported_calculation': {
        'steps': ('T34', 'C2'),
        'must': [('the calculation is named', r'weight|probabilit'), ('it is declared unavailable', NEGATION + r'\b[^.]{0,80}?(?:support|available|possible|offer|provide|calculat|comput|weight|do|perform)|' + r'(?:support|available|possible|offer|provide|calculat|comput)[^.]{0,40}?' + NEGATION)],
        'suggestions': 'supported'},
    'ambiguous_product_scope': {
        'steps': ('T35', 'C4'),
        'must': [('whole-opportunity alternative', r'whole|entire|complete|full opportunit|all (?:of )?(?:its|their|the) (?:other )?products|opportunit(?:y|ies)[^.]{0,30}(?:total|level|value|amount)|containing'),
                 ('product-rows-only alternative', r"only (?:the|that|those|its|this)? ?(?:product|row|line|sku)|product(?:'s)? own|matching (?:product|row|line|sku)|product (?:rows?|lines?|items?)|(?:sku|line[- ]item) (?:rows?|level|amount|total)|that product alone|itself|just (?:the|that) product")],
        'suggestions': 'supported'},
    'sql_request': {
        'steps': ('T36',),
        'must': [('SQL is named', r'\bsql\b|query|statement|select'), ('execution is declined', NEGATION + r'\b[^.]{0,60}?(?:run|execut|sql|quer|statement|support|possible|able)|(?:run|execut)[^.]{0,30}?' + NEGATION)],
        'suggestions': 'supported'},
}
CLARIFICATION_RULE_BY_STEP = {step: (name, rule) for name, rule in CLARIFICATION_RULES.items() for step in rule['steps']}


def check_clarification(step, outcome):
    """Verdict for a step that expects a clarification: (status, problems).

    pass: every required concept is present and every suggestion is supported; review: the wording matched no
    accepted variant for at least one concept; fail: a suggestion names an unsupported calculation or SQL."""
    text = ' '.join(str(outcome.get('question') or '').split())
    suggestions = list(outcome.get('suggestions') or [])
    problems = []
    unsupported = [sug for sug in suggestions if UNSUPPORTED_TERMS.search(str(sug)) or re.search(r'\b(sql|python|script)\b', str(sug), re.I)]
    if unsupported:
        problems.append('unsupported suggestion(s): ' + '; '.join(str(sug) for sug in unsupported))
    rule = CLARIFICATION_RULE_BY_STEP.get(step['id'])
    if rule is None:
        return ('pass' if not problems else 'fail'), problems
    name, spec = rule
    unmatched = [label for label, pattern in spec['must'] if not re.search(pattern, text, re.I)]
    if unmatched:
        problems.append(f"{name}: wording did not match an accepted variant for " + ', '.join(unmatched) + ' (review the clarification text)')
    if not text:
        problems.append('empty clarification')
    if any(p.startswith('unsupported suggestion') for p in problems) or not text:
        return 'fail', problems
    return ('review' if unmatched else 'pass'), problems
BLOCKED_BY_NEED = {'twenty_plus': 'fewer than 21 opportunities, so a 20-row limit cannot be exercised', 'ten_plus': 'fewer than 10 opportunities',
                   'single_currency': 'the source mixes currencies, so ungrouped amount totals are rejected by the contract',
                   'probability_high': 'no opportunity has a probability of at least 0.75', 'probability_null': 'every opportunity has a probability',
                   'close_date_2026': 'no close date in 2026', 'close_month_2026': 'no close month in 2026', 'created_date_2026': 'no created date in 2026',
                   'last_modified_date_2026': 'no last modified date in 2026', 'quality_warning': 'no row carries a quality warning',
                   'discrepancy': 'no opportunity has a parent-amount discrepancy', 'two_open_owners': 'fewer than two owners with Open opportunities'}


def manifest():
    return {'suite_version': SUITE_VERSION, 'steps': [{'id': s['id'], 'title': s['title'], 'prompt': s['prompt'], 'view': s['view'], 'conversation': s['conversation'],
            'witnesses': s['witnesses'], 'browser_checks': s['browser_checks'], 'expected': s['behavior'] or describe(s['expect'])} for s in STEPS],
            'browser_checks': BROWSER_CHECKS}


def describe(expect):
    if expect['intent'] == 'clarify':
        return 'A clarification question; no query executes.'
    parts = [expect['intent'], 'grain ' + expect['grain']]
    if expect['filters']:
        parts.append('filters ' + ', '.join(f"{f['field']} {f['op']} {f['value']}" for f in expect['filters']))
    if expect.get('group'):
        parts.append('grouped by ' + ', '.join(expect['group']))
    if expect.get('measures'):
        parts.append('measures ' + ', '.join(expect['measures']))
    if expect.get('columns'):
        parts.append('columns ' + ', '.join(expect['columns']))
    return '; '.join(parts)


def select_witnesses(source, records):
    """Pick concrete owners, customers, products, duplicates, and thresholds from the frozen source before any model call."""
    opps, skus = source.opportunity, source.sku
    witnesses, coverage, notes = {}, {}, []
    by_owner_open, by_owner = {}, {}
    for o in opps:
        by_owner[o['opportunity_owner']] = by_owner.get(o['opportunity_owner'], 0) + 1
        if o['stage'] in STAGE_MEMBERS['Open']:
            by_owner_open[o['opportunity_owner']] = by_owner_open.get(o['opportunity_owner'], 0) + 1
    ranked_open = sorted(((n, c) for n, c in by_owner_open.items() if n), key=lambda x: (-x[1], x[0]))
    ranked = sorted(((n, c) for n, c in by_owner.items() if n), key=lambda x: (-x[1], x[0]))
    coverage['two_open_owners'] = len(ranked_open) >= 2
    if ranked_open:
        witnesses['owner_a'] = ranked_open[0][0]
    elif ranked:
        witnesses['owner_a'] = ranked[0][0]
    if len(ranked_open) >= 2:
        witnesses['owner_b'] = ranked_open[1][0]
    elif len(ranked) >= 2:
        witnesses['owner_b'] = ranked[1][0]
    # Owner C: most opportunities spread over several stage groups, so charts have more than one bar.
    groups_by_owner = {}
    for o in opps:
        g = next((g for g, m in STAGE_MEMBERS.items() if o['stage'] in m), None)
        groups_by_owner.setdefault(o['opportunity_owner'], set()).add(g)
    spread = sorted(((n, c) for n, c in by_owner.items() if n), key=lambda x: (-len(groups_by_owner[x[0]]), -x[1], x[0]))
    if spread:
        witnesses['owner_c'] = spread[0][0]
    customers = {}
    for o in opps:
        if o['end_customer']:
            customers[o['end_customer']] = customers.get(o['end_customer'], 0) + 1
    for name, _ in sorted(customers.items(), key=lambda x: (-x[1], x[0])):
        words = [w for w in re.findall(r'[A-Za-z]{3,}', name)]
        if words:
            word = max(words, key=lambda w: (len(w), w))
            witnesses['customer_fragment'] = word.lower() if word != word.lower() else word.upper()
            break
    types = {}
    for o in opps:
        if o['type']:
            types[o['type']] = types.get(o['type'], 0) + 1
    if types:
        witnesses['type'] = sorted(types.items(), key=lambda x: (-x[1], x[0]))[0][0]
    per_product = {}
    for s in skus:
        per_product.setdefault(s['product_code'], set()).add(s['opportunity_no'])
    multi = {o['opportunity_no'] for o in opps if o['sku_count'] >= 2}
    candidates = sorted(per_product.items(), key=lambda x: (-len(x[1] & multi), -len(x[1]), x[0]))
    if candidates:
        witnesses['product'] = candidates[0][0]
        if not candidates[0][1] & multi:
            notes.append('No opportunity containing the selected product has a second product; whole-opportunity and product-only scopes coincide.')
    repeated = sorted((s for s in skus if s['source_row_count'] >= 2), key=lambda s: (-s['source_row_count'], s['opportunity_no'], s['product_code']))
    if repeated:
        witnesses['dup_opp'], witnesses['dup_sku'] = repeated[0]['opportunity_no'], repeated[0]['product_code']
        witnesses['dup_rows'] = repeated[0]['source_row_count']
    else:
        notes.append('No opportunity/SKU pair has repeated raw rows; T23 and T24 are blocked.')
    currencies = {}
    for o in opps:
        if o['opp_amount_converted_currency']:
            currencies[o['opp_amount_converted_currency']] = currencies.get(o['opp_amount_converted_currency'], 0) + 1
    if currencies:
        witnesses['currency'] = sorted(currencies.items(), key=lambda x: (-x[1], x[0]))[0][0]
    sku_currencies = {s['amount_converted_currency'] for s in skus if s['amount_converted_currency']}
    coverage['single_currency'] = len(sku_currencies) <= 1 and len(currencies) <= 1
    # Quantity threshold: an opportunity whose raw lines are each <= t while its canonical total is > t.
    line_max = {}
    for record in records:
        opp, qty = (record.get('opportunity_no') or '').strip(' '), r_number(record.get('quantity'))
        if opp and qty is not None:
            line_max[opp] = max(line_max.get(opp, qty), qty)
    best = None
    for o in opps:
        total, line = o['quantity'], line_max.get(o['opportunity_no'])
        if total is None or line is None or total <= line:
            continue
        t = int(line)
        gain = sum(1 for p in opps if p['quantity'] is not None and p['quantity'] > t) - sum(1 for p in opps if line_max.get(p['opportunity_no']) is not None and line_max[p['opportunity_no']] > t)
        if best is None or (gain, -t) > (best[0], -best[1]):
            best = (gain, t)
    if best:
        witnesses['threshold'] = str(best[1])
        witnesses['threshold_gain'] = best[0]
    else:
        notes.append('No opportunity has a canonical quantity above every one of its raw lines; T33 is blocked.')
    existing = {o['opportunity_no'] for o in opps}
    candidate, n = 'OPP-NONE-0000', 0
    while candidate in existing:
        n += 1
        candidate = f'OPP-NONE-{n:04d}'
    witnesses['nonexistent'] = candidate
    coverage['twenty_plus'] = len(opps) >= 21
    coverage['ten_plus'] = len(opps) >= 10
    coverage['probability_high'] = any(o['probability'] is not None and o['probability'] >= Decimal('0.75') for o in opps)
    coverage['probability_null'] = any(o['probability'] is None for o in opps)
    for field in ('close_date', 'close_month', 'created_date', 'last_modified_date'):
        coverage[field + '_2026'] = any(o[field] is not None and o[field].year == 2026 for o in opps)
        raw_witness = next((str(r.get(field)).strip(' ') for r in records if r.get(field) and re.fullmatch(r'[0-9]/[0-9]{1,2}/2026|[0-9]{1,2}/[0-9]/2026', str(r.get(field)).strip(' '))), None)
        witnesses[field + '_single_digit_witness'] = raw_witness
        if coverage[field + '_2026'] and not raw_witness:
            notes.append(f'No raw {field} value in 2026 uses a single-digit day or month.')
    coverage['quality_warning'] = any(s['has_quality_warning'] for s in skus)
    coverage['discrepancy'] = any(o['has_amount_discrepancy'] for o in opps)
    if len(opps) <= 1000:
        notes.append('The source has at most 1,000 opportunities, so the default preview limit is not exercised by T01.')
    return witnesses, coverage, notes


def render_prompt(step, witnesses):
    text = step['prompt']
    for name in step['witnesses']:
        if name not in witnesses:
            raise KeyError(name)
        text = text.replace('{' + name + '}', str(witnesses[name]))
    return text


def blocked_reason(step, witnesses, coverage):
    for need in step['needs']:
        if not coverage.get(need):
            return 'Blocked coverage: ' + BLOCKED_BY_NEED.get(need, need) + '.'
    for name in step['witnesses']:
        if name not in witnesses:
            return f'Blocked coverage: no {name} example exists in the frozen source.'
    return None


def substitute(value, witnesses):
    if isinstance(value, str) and value.startswith('{') and value.endswith('}'):
        return witnesses[value[1:-1]]
    return value


def as_decimal(value):
    try:
        if isinstance(value, bool) or value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def as_date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def date_range(clauses):
    """Inclusive (lower, upper) covered by a set of comparison clauses on one date field, or None."""
    lower = upper = None
    for c in clauses:
        op, value = c['operator'], c['value']
        if op == 'between':
            lo, hi = as_date(value[0]), as_date(value[1])
            if lo is None or hi is None:
                return None
            lower, upper = lo, hi
        elif op in ('ge', 'gt', 'le', 'lt'):
            d = as_date(value)
            if d is None:
                return None
            if op == 'ge':
                lower = d
            elif op == 'gt':
                lower = date.fromordinal(d.toordinal() + 1)
            elif op == 'le':
                upper = d
            else:
                upper = date.fromordinal(d.toordinal() - 1)
        else:
            return None
    return (lower, upper) if lower and upper else None


def match_filters(expected, clauses, witnesses):
    """Consume plan clauses against the expected filters; report unmatched expectations and leftover clauses."""
    remaining = list(clauses)
    problems, variant = [], {}
    for exp in expected:
        field, op, value = exp['field'], exp['op'], substitute(exp['value'], witnesses)
        taken = None
        if op == 'group':
            members = set(STAGE_MEMBERS[value])
            for c in remaining:
                if c['field'] == 'stage' and ((c['operator'] == 'eq' and c['value'] == value) or (c['operator'] == 'in' and (set(c['value']) == {value} or set(c['value']) == members))):
                    taken = [c]
                elif c['field'] == 'stage_group' and ((c['operator'] == 'eq' and c['value'] == value) or (c['operator'] == 'in' and set(c['value']) == {value})):
                    taken = [c]
                if taken:
                    break
        elif field == 'currency':
            for c in remaining:
                if c['field'] in CURRENCY_FIELDS and ((c['operator'] == 'eq' and c['value'] == value) or (c['operator'] == 'in' and set(c['value']) == {value})):
                    taken = [c]
                    variant['currency_field'] = c['field']
                    break
        elif op == 'year':
            same = [c for c in remaining if c['field'] == field]
            covered = date_range(same)
            if covered == (date(value, 1, 1), date(value, 12, 31)):
                taken = same
        elif op == 'eq':
            for c in remaining:
                if c['field'] != field:
                    continue
                if value is None and ((c['operator'] == 'eq' and c['value'] is None) or (c['operator'] == 'in' and c['value'] == [None])):
                    taken = [c]
                elif value is not None and ((c['operator'] == 'eq' and same_value(c['value'], value)) or (c['operator'] == 'in' and len(c['value']) == 1 and same_value(c['value'][0], value))):
                    taken = [c]
                if taken:
                    break
        elif op == 'contains':
            for c in remaining:
                if c['field'] == field and c['operator'] == 'contains' and isinstance(c['value'], str) and c['value'].casefold() == str(value).casefold():
                    taken = [c]
                    break
        elif op in ('ge', 'gt', 'le', 'lt'):
            for c in remaining:
                if c['field'] == field and c['operator'] == op and as_decimal(c['value']) == as_decimal(value):
                    taken = [c]
                    break
                if c['field'] == field and op == 'ge' and c['operator'] == 'between' and as_decimal(c['value'][0]) == as_decimal(value) and as_decimal(c['value'][1]) == Decimal(1):
                    taken = [c]
                    break
        if taken:
            for c in taken:
                remaining.remove(c)
        else:
            problems.append(f"expected filter {field} {op} {value!r} was not found")
    for c in remaining:
        problems.append(f"unexpected filter {c['field']} {c['operator']} {c['value']!r}")
    return problems, variant


def same_value(actual, expected):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, Decimal) or (isinstance(actual, (int, float)) and not isinstance(actual, bool)):
        return as_decimal(actual) == as_decimal(expected)
    return actual == expected


def column_name(name, grain):
    """Map plan column/measure names to contract column names for comparison."""
    if name == 'amount':
        return AMOUNT_COLUMN[grain]
    return name


def plan_intent(plan):
    """The version-1 intent of a version-2 plan dictionary (rows -> table, aggregate -> metric or chart)."""
    kind = plan.get('result_kind')
    if kind is None:
        return plan.get('intent')
    if kind == 'clarify':
        return 'clarify'
    if kind == 'rows':
        return 'table'
    return 'chart' if plan.get('presentation') == 'chart' else 'metric'


def plan_columns(plan):
    columns = plan.get('columns')
    if isinstance(columns, dict):
        return columns.get('mode', 'default'), list(columns.get('fields') or [])
    dimensions = plan.get('dimensions') or []
    return ('only' if dimensions else 'default'), list(dimensions)


def plan_group_by(plan):
    if 'group_by' in plan:
        return list(plan.get('group_by') or [])
    return list(plan.get('dimensions') or [])


def match_plan(outcome, step, witnesses):
    """Compare the effective plan with the authored expectation. Returns (ok, problems, variant)."""
    expect = step['expect']
    if expect['intent'] == 'clarify':
        if outcome['kind'] == 'clarify':
            return True, [], {}
        return False, ['a clarification was expected but a query executed'], {}
    if outcome['kind'] != 'table':
        return False, ['a query was expected but the model asked a clarification: ' + str(outcome.get('question'))], {}
    plan = outcome['plan']
    problems = []
    grain = 'opportunity' if plan['grain'] == 'opportunity' else 'sku'
    intent = plan_intent(plan)
    if expect['grain'] != 'any' and grain != expect['grain']:
        problems.append(f"grain {plan['grain']} instead of {expect['grain']}")
    if intent != expect['intent']:
        problems.append(f"intent {intent} instead of {expect['intent']}" + (f" (result_kind {plan.get('result_kind')}, presentation {plan.get('presentation')})" if plan.get('result_kind') else ''))
    filter_problems, variant = match_filters(expect['filters'], plan['filters'], witnesses)
    problems.extend(filter_problems)
    variant['grain'] = grain
    if expect['intent'] == 'table':
        keys = {'opportunity_no'} if grain == 'opportunity' else {'opportunity_no', 'product_code'}
        defaults = SUMMARY_DEFAULT if grain == 'opportunity' else DETAIL_DEFAULT
        mode, fields = plan_columns(plan)
        table_measures = [column_name(m, grain) for m in plan['measures'] if m in ('amount', 'quantity')]
        extra_measures = [m for m in plan['measures'] if m not in ('amount', 'quantity')]
        if extra_measures:
            problems.append('unexpected table measures ' + ', '.join(extra_measures))
        named = [column_name(f, grain) for f in fields]
        if expect['columns'] is None and not expect.get('include'):
            extra = [f for f in named + table_measures if f not in defaults and f not in keys]
            if mode == 'only':
                problems.append('default columns were expected but an exact selection was made: ' + ', '.join(fields + plan['measures']))
            elif extra:
                problems.append('default columns were expected but extra columns were included: ' + ', '.join(extra))
            variant['columns'] = list(defaults)
        elif expect.get('include'):
            wanted = {column_name(c, grain) for c in expect['include']}
            if mode == 'only':
                problems.append('an additive request ("with"/"including") was answered with an exact selection: ' + ', '.join(fields))
            elif mode == 'default' or not wanted <= set(named + table_measures):
                problems.append(f"included columns {sorted(set(named + table_measures) - set(defaults))} instead of {sorted(wanted)}")
            variant['columns'] = list(defaults) + [f for f in fields + [m for m in plan['measures'] if m in ('amount', 'quantity')] if column_name(f, grain) not in defaults]
        else:
            expected_set = {column_name(c, grain) for c in expect['columns']} - keys
            if mode != 'only':
                problems.append(f"an exact selection ('only') was expected but columns mode was {mode}")
            if set(named + table_measures) - keys != expected_set:
                problems.append(f"columns {sorted(set(named + table_measures) - keys)} instead of {sorted(expected_set)}")
            # Keep the plan's own spelling of an equivalent amount column so cells compare by name.
            variant['columns'] = list(fields) + [m for m in plan['measures'] if m in ('amount', 'quantity')]
        if expect['sort'] is not None:
            wanted = [(column_name(f, grain), asc) for f, asc in expect['sort']]
            actual = [(column_name(s['field'], grain), s['direction'] == 'asc') for s in plan['sort']]
            if actual != wanted:
                problems.append(f'sort {actual} instead of {wanted}')
            variant['sort'] = [(s['field'], s['direction'] == 'asc') for s in plan['sort']]
        else:
            variant['sort'] = [(s['field'], s['direction'] == 'asc') for s in plan['sort']]
            if plan['sort']:
                variant['note'] = 'Ordering adopted from the plan because the prompt requested none.'
        if expect['limit'] is not None:
            if plan['limit'] != expect['limit']:
                problems.append(f"limit {plan['limit']} instead of {expect['limit']}")
        elif plan['limit'] not in (None, 1000):
            problems.append(f"limit {plan['limit']} was not requested")
        variant['limit'] = plan['limit']
    else:
        expected_group = [('currency', CURRENCY_FIELDS) if g == 'currency' else (g, (g,)) for g in expect['group']]
        dims = plan_group_by(plan)
        if plan.get('result_kind') == 'aggregate' and expect['intent'] == 'metric' and plan.get('presentation') not in ('table', 'cards'):
            problems.append(f"presentation {plan.get('presentation')} instead of table or cards")
        resolved = []
        for name, accepted in expected_group:
            found = next((d for d in dims if d in accepted), None)
            if found is None:
                problems.append(f'missing grouping {name}')
            else:
                dims.remove(found)
                resolved.append(found)
                if name == 'currency':
                    variant['currency_field'] = found
        if dims:
            problems.append('unexpected grouping ' + ', '.join(dims))
        variant['group'] = resolved
        if set(plan['measures']) != set(expect['measures']):
            problems.append(f"measures {sorted(plan['measures'])} instead of {sorted(expect['measures'])}")
        variant['measures'] = list(plan['measures'])
        if expect['intent'] == 'chart' and plan['chart_type'] != expect['chart_type']:
            problems.append(f"chart type {plan['chart_type']} instead of {expect['chart_type']}")
        if expect['sort'] is not None:
            wanted = [(f, asc) for f, asc in expect['sort']]
            actual = [(s['field'], s['direction'] == 'asc') for s in plan['sort']]
            if actual and actual != wanted:
                problems.append(f'sort {actual} instead of {wanted}')
            variant['sort'] = wanted
        else:
            variant['sort'] = [(s['field'], s['direction'] == 'asc') for s in plan['sort']]
        if plan['limit'] not in (None, 1000):
            problems.append(f"limit {plan['limit']} was not requested")
    return not problems, problems, variant


def reference_spec(step, variant, witnesses):
    """Build the evaluator specification from the authored expectation and the accepted plan variant."""
    expect = step['expect']
    grain = variant.get('grain') or (expect['grain'] if expect['grain'] != 'any' else 'opportunity')
    filters = []
    for exp in expect['filters']:
        field, op, value = exp['field'], exp['op'], substitute(exp['value'], witnesses)
        if field == 'currency':
            field = variant.get('currency_field') or 'opp_amount_converted_currency'
        if op == 'group':
            filters.append({'field': 'stage', 'op': 'in', 'value': list(STAGE_MEMBERS[value])})
        elif op == 'year':
            filters.append({'field': field, 'op': 'between', 'value': [date(value, 1, 1), date(value, 12, 31)]})
        elif op in ('ge', 'gt', 'le', 'lt'):
            filters.append({'field': field, 'op': op, 'value': Decimal(str(value))})
        else:
            filters.append({'field': field, 'op': op, 'value': value})
    if expect['intent'] == 'table':
        columns = variant.get('columns') if variant.get('columns') is not None else (expect['columns'] or (SUMMARY_DEFAULT if grain == 'opportunity' else DETAIL_DEFAULT))
        sort = variant.get('sort') or (expect['sort'] and [(column_name(f, grain) if f == 'amount' else f, asc) for f, asc in expect['sort']]) or None
        return {'grain': grain, 'intent': 'table', 'filters': filters, 'columns': list(columns), 'sort': sort or None, 'limit': expect['limit'] or variant.get('limit')}
    group = variant.get('group') or [variant.get('currency_field', 'opp_amount_converted_currency') if g == 'currency' else g for g in expect['group']]
    return {'grain': grain, 'intent': expect['intent'], 'filters': filters, 'group': group, 'measures': list(expect['measures']), 'sort': variant.get('sort') or expect['sort'] or None, 'limit': None}
