"""Authored live scenarios. Matrices vary semantic dimensions, not random wording.

The legacy suite remains available to regression tests. Live runs use this catalog,
including every legacy case, grouped into 200 independently isolated scenarios.
"""
from copy import deepcopy
from collections import Counter
from decimal import Decimal
from acceptance_suite import STEPS as LEGACY, step, table, metric, chart, F, CLARIFY, SUMMARY_DEFAULT, DETAIL_DEFAULT

VERSION = '4.0.0'
TARGETS = {'continuity': 40, 'filters': 35, 'calculations': 35, 'charts': 35,
           'tables': 25, 'ambiguity': 15, 'presentation': 15}
SCENARIOS = []


def add(category, title, turns, actions=()):
    number = len(SCENARIOS) + 1
    sid = f'S{number:03d}'
    copied = deepcopy(turns)
    for n, turn in enumerate(copied, 1):
        if not turn['id']:
            turn['id'] = f'{sid}T{n}'
        turn.update(scenario_id=sid, category=category, turn_number=n,
                    conversation=sid, ui_actions=list(actions) if n == len(copied) else [])
        # The model must choose grain itself, as in the ordinary composer.
        turn['view'] = 'auto'
        if not turn['behavior']:
            turn['behavior'] = str(turn['expect'])
    SCENARIOS.append({'id': sid, 'number': number, 'category': category, 'title': title,
                      'steps': copied, 'actions': list(actions)})


def turn(prompt, expect, needs=(), actions=()):
    import re
    return step('', prompt, prompt, expect, witnesses=tuple(dict.fromkeys(re.findall(r'\{(\w+)\}', prompt))), needs=needs)


# Keep the full existing audited cases and their explicit browser checks.
groups = {}
seen = set()
for s in LEGACY:
    if s['conversation']:
        groups.setdefault(s['conversation'], []).append(s)
    else:
        identity = (s['prompt'], repr(s['expect']))
        if identity in seen: continue  # formerly forced-layout duplicates now use the same Auto path
        seen.add(identity)
        intent = s['expect']['intent']
        category = ('ambiguity' if intent == 'clarify' else 'charts' if intent == 'chart' else
                    'calculations' if intent == 'metric' or s['id'] in ('T23', 'T24', 'T33') else
                    'tables' if s['id'] in ('T01', 'T02', 'T03', 'T04', 'T25', 'T37', 'T38', 'T39') else 'filters')
        add(category, s['title'], [s])
for key, turns in groups.items():
    add('continuity', f'Conversation {key}: {turns[0]["title"]}', turns)

scopes = [
    ('Open opportunities', [F('stage', 'group', 'Open')]),
    ('Won opportunities', [F('stage', 'group', 'Won')]),
    ('Lost opportunities', [F('stage', 'group', 'Lost')]),
    ('opportunities owned by {owner_a}', [F('opportunity_owner', 'eq', '{owner_a}')]),
    ("opportunities of type '{type}'", [F('type', 'eq', '{type}')]),
    ('opportunities closing in 2026', [F('close_date', 'year', 2026)]),
    ('whole opportunities containing product {product}', [F('product_code', 'eq', '{product}')]),
]
for name, filters in scopes:
    initial = turn('Show all ' + name + '.', table(filters=filters))
    for label, follow, expected, last, last_expected in [
        ('count', 'How many distinct opportunities are those?', metric('opportunity', filters, measures=['opportunity_count']), 'Show those opportunities again.', table(filters=filters)),
        ('group', 'Break their opportunity count down by stage group.', metric('opportunity', filters, ['stage_group'], ['opportunity_count']), 'Show the same counts as a bar chart.', chart('bar', 'opportunity', filters, ['stage_group'], ['opportunity_count'])),
        ('quantity', 'What is their total quantity?', metric('opportunity', filters, measures=['quantity']), 'Now show the quantities by opportunity owner.', metric('opportunity', filters, ['opportunity_owner'], ['quantity'])),
        ('columns', 'Show those with only opportunity number and stage.', table(filters=filters, columns=['stage']), 'Start over: show every opportunity.', table()),
        ('limit', 'Show only the first 5 of those sorted by opportunity number ascending.', table(filters=filters, sort=[('opportunity_no', True)], limit=5), 'Remove the row limit and keep the same population.', table(filters=filters, sort=[('opportunity_no', True)])),
    ]:
        add('continuity', name + ': ' + label, [initial, turn(follow, expected), turn(last, last_expected)])


def remaining(category):
    return TARGETS[category] - sum(s['category'] == category for s in SCENARIOS)


filter_cases = []
for field, label in [('close_date', 'close date'), ('close_month', 'close month'), ('created_date', 'created date'), ('last_modified_date', 'last modification date')]:
    for description, op, value in [('before 1 January 2026', 'lt', '2026-01-01'), ('on or after 1 January 2026', 'ge', '2026-01-01'), ('missing', 'eq', None)]:
        filter_cases.append(turn(f'Show opportunities with {label} {description}.', table(filters=[F(field, op, value)])))
for label, field, value in [('probability', 'probability', Decimal('0.5')), ('quantity', 'quantity', 10), ('age', 'age', 30)]:
    for op, wording in [('gt', 'greater than'), ('le', 'at most'), ('eq', 'equal to')]:
        threshold = '50%' if field == 'probability' else str(value)
        filter_cases.append(turn(f'Show opportunities with {label} {wording} {threshold}.', table(filters=[F(field, op, value)])))
filter_cases += [turn('Show Open opportunities owned by {owner_a}.', table(filters=[F('stage', 'group', 'Open'), F('opportunity_owner', 'eq', '{owner_a}')]))]
for t in filter_cases[:remaining('filters')]: add('filters', t['title'], [t])

calc_cases = []
for grain, noun in [('opportunity', 'whole opportunities'), ('sku', 'opportunity/product rows')]:
    for field, label in [('stage_group', 'stage group'), ('opportunity_owner', 'owner'), ('type', 'opportunity type'), ('first_channel', 'first channel')]:
        for measure, words in [('opportunity_count', 'distinct opportunity count'), ('quantity', 'total quantity'), ('sku_count', 'opportunity/product pair count')]:
            calc_cases.append(turn(f'For {noun}, show {words} by {label}.', metric(grain, group=[field], measures=[measure])))
for measure, words in [('amount', 'amount'), ('deal_size', 'deal size in USD'), ('quantity', 'quantity'), ('opportunity_count', 'distinct opportunity count')]:
    for stage in ['Open', 'Won', 'Lost']:
        calc_cases.append(turn(f'For whole {stage} opportunities, show total {words}.', metric('opportunity', [F('stage', 'group', stage)], measures=[measure]), needs=('single_currency',) if measure == 'amount' else ()))
for t in calc_cases[:remaining('calculations')]: add('calculations', t['title'], [t])

chart_cases = []
for kind in ['bar', 'line', 'area']:
    for field, label in [('stage_group', 'stage group'), ('opportunity_owner', 'owner'), ('close_date', 'close date'), ('created_date', 'created date')]:
        for measure, words in [('opportunity_count', 'distinct opportunity count'), ('quantity', 'total quantity'), ('sku_count', 'product pair count')]:
            chart_cases.append(turn(f'Create a {kind} chart of {words} by {label} at whole-opportunity grain.', chart(kind, 'opportunity', group=[field], measures=[measure])))
for t in chart_cases[:remaining('charts')]: add('charts', t['title'], [t], ['chart-data', 'resize'])

table_cases = []
for grain, fields, label in [
    ('opportunity', ['subsidiary_subsidiary_code', 'division', 'business_location'], 'subsidiary code, division and business location'),
    ('opportunity', ['biz_focus', 'sales_type_detail', 'type'], 'business focus, sales type detail and opportunity type'),
    ('opportunity', ['first_channel', 'end_customer', 'opportunity_owner'], 'first channel, end customer and owner'),
    ('opportunity', ['age', 'comment', 'deal_size_on_pricing_date_usd'], 'age, comment and deal size in USD'),
    ('opportunity', ['created_date', 'last_modified_date', 'close_month', 'close_date'], 'created date, last modification date, close month and close date'),
    ('sku', ['pet_name', 'gscm_product_group_new', 'product_code'], 'product name, product group and product code'),
    ('sku', ['quantity', 'sku_amount', 'amount_converted_currency'], 'quantity, product amount and its currency'),
    ('opportunity', ['opportunity_amount', 'opp_amount_converted_currency', 'sku_count'], 'opportunity amount, its currency and product pair count'),
]:
    noun = 'whole opportunities' if grain == 'opportunity' else 'opportunity/product rows'
    defaults = SUMMARY_DEFAULT if grain == 'opportunity' else DETAIL_DEFAULT
    extra = [f for f in fields if f not in defaults]
    table_cases.append(turn(f'Show all {noun}, including {label}.', table(grain, include=extra or None)))
for grain, noun in [('opportunity', 'opportunities'), ('sku', 'opportunity/product rows')]:
    for column, label in [('stage', 'stage'), ('opportunity_owner', 'owner'), ('close_date', 'close date'), ('quantity', 'quantity'), ('age', 'age')]:
        for asc, direction in [(True, 'ascending'), (False, 'descending')]:
            table_cases.append(turn(f'Show all {noun} sorted by {label} {direction}.', table(grain, sort=[(column, asc)])))
for t in table_cases[:remaining('tables')]: add('tables', t['title'], [t], ['explore', 'sort', 'paginate', 'export'])

# Every clarification must explain the unsupported/ambiguous request; unknown
# language is explicitly reviewable, never accepted merely for returning clarify.
unsupported = ['average opportunity amount', 'median deal size', 'probability-weighted pipeline',
               'next quarter sales forecast', 'win rate', 'year over year growth percentage',
               'standard deviation of amounts', 'moving average of quantity', 'conversion rate',
               'ratio of Won to Lost value', 'cumulative running total', 'SQL query execution',
               'predicted closing dates', 'percentage share of revenue', 'pipeline coverage ratio']
for term in unsupported[:remaining('ambiguity')]:
    t = turn(f'Calculate {term} from the opportunities.', deepcopy(CLARIFY))
    t['clarification_subject'] = term
    add('ambiguity', term, [t])

presentation_cases = [
    ('Reopen summary', 'Show all opportunities.', table(), ['reopen', 'explore']),
    ('Reopen products', 'Show all opportunity/product rows.', table('sku'), ['reopen', 'explore']),
    ('Narrow summary', 'Show all opportunities including their comment.', table(include=['comment']), ['resize', 'explore']),
    ('Narrow products', 'Show all product rows including their comment.', table('sku', include=['comment']), ['resize', 'explore']),
    ('Empty layout', 'Show opportunity {nonexistent}.', table(filters=[F('opportunity_no', 'eq', '{nonexistent}')]), ['resize']),
    ('Scalar layout', 'Count all distinct opportunities.', metric('opportunity', measures=['opportunity_count']), ['resize', 'supporting']),
    ('Grouped supporting', 'Count distinct opportunities by stage group.', metric('opportunity', group=['stage_group'], measures=['opportunity_count']), ['supporting']),
    ('Chart reopen', 'Chart total quantity by stage group as a bar chart.', chart('bar', 'opportunity', group=['stage_group'], measures=['quantity']), ['reopen', 'chart-data']),
    ('Long conversation scroll', 'Show all opportunities.', table(), ['scrollback']),
    ('Owner label layout', 'Chart distinct opportunity counts by owner as a bar chart.', chart('bar', 'opportunity', group=['opportunity_owner'], measures=['opportunity_count']), ['resize', 'chart-data']),
    ('Customer labels', 'Show distinct opportunity counts by end customer.', metric('opportunity', group=['end_customer'], measures=['opportunity_count']), ['resize', 'explore']),
    ('Quality review', 'Show opportunities with quality warnings.', table(filters=[F('has_quality_warning', 'eq', True)]), ['quality']),
    ('Discrepancy review', 'Show opportunities with amount discrepancies.', table(filters=[F('has_amount_discrepancy', 'eq', True)]), ['quality']),
    ('Product supporting', 'Show total quantity by product code at product row grain.', metric('sku', group=['product_code'], measures=['quantity']), ['supporting']),
    ('Date chart layout', 'Show a line chart of opportunity counts by close date.', chart('line', 'opportunity', group=['close_date'], measures=['opportunity_count']), ['resize', 'chart-data']),
]
for title, prompt, expected, actions in presentation_cases:
    turns = [turn(prompt, expected)]
    if 'scrollback' in actions:
        turns += [turn('How many distinct opportunities are those?', metric('opportunity', measures=['opportunity_count']))]
    add('presentation', title, turns, actions)

assert Counter(s['category'] for s in SCENARIOS) == TARGETS
STEPS = [t for s in SCENARIOS for t in s['steps']]
assert len({s['id'] for s in STEPS}) == len(STEPS)


def manifest():
    from acceptance_suite import BROWSER_CHECKS
    return {'suite_version': VERSION, 'scenario_count': len(SCENARIOS), 'steps': STEPS,
            'scenarios': [{k: v for k, v in s.items() if k != 'steps'} | {'step_ids': [t['id'] for t in s['steps']]} for s in SCENARIOS],
            'browser_checks': BROWSER_CHECKS}
