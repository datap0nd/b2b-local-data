"""Runs the versioned acceptance suite against one frozen snapshot and writes the Markdown report.

The server owns the suite, the step order, and the expected results. Step requests are idempotent and
carry no prompts, plans, SQL, or paths. Run state lives under B2B_DATA_DIR/acceptance, separate from
ordinary conversation history."""
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic
from urllib.parse import urlsplit
import uuid

from acceptance_suite import BROWSER_CHECKS, STEPS, SUITE_VERSION, blocked_reason, match_plan, reference_spec, render_prompt, select_witnesses
from app_config import APP_VERSION, ROOT, AppError
from data_layer import OPPORTUNITY_COLUMNS, SKU_COLUMNS, build_canonical_views
from history_store import HistoryStore
from query_engine import result_digest
from reference_evaluator import EVALUATOR_VERSION, FINGERPRINT_VERSION, ReferenceSource, compare, evaluate

MAX_RUNS_LISTED = 50
IDENTITY_KEYS = ('source_fingerprint', 'app_revision', 'suite_version', 'rules_digest', 'model_config', 'effective_date')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def today():
    return date.today()


def app_revision():
    try:
        commit = json.loads((ROOT / '.release.json').read_text(encoding='utf-8-sig')).get('commit')
    except (OSError, ValueError, AttributeError):
        commit = None
    return f'{APP_VERSION}+{commit[:12]}' if isinstance(commit, str) and commit else f'{APP_VERSION}+source-checkout'


def model_config(settings):
    """Model identity and settings without any credential or authorization header."""
    endpoint = settings.get('LLM_API_URL') or settings.get('AI_BASE_URL') or ''
    parsed = urlsplit(endpoint)
    provider = settings.get('AI_PROVIDER', 'openai_compatible')
    return {'provider': provider, 'model': settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or '', 'endpoint_host': parsed.hostname or '',
            'endpoint_port': parsed.port, 'temperature': 0, 'max_tokens': 3000 if provider == 'ollama' else 5000, 'structured_output': 'json_schema' if provider == 'ollama' else 'json_object'}


def jsonable(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f') if value != 0 else '0'
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return value


def md(text):
    """Escape a value for a Markdown table cell."""
    text = '' if text is None else str(text)
    return text.replace('\\', '\\\\').replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('`', '\\`')


def md_table(columns, rows):
    lines = ['| ' + ' | '.join(md(c) for c in columns) + ' |', '|' + '---|' * len(columns)]
    for row in rows:
        lines.append('| ' + ' | '.join(md(row.get(c) if isinstance(row, dict) else row[i]) for i, c in enumerate(columns)) + ' |')
    return '\n'.join(lines)


class AcceptanceRunner:
    def __init__(self, settings, repository, service, data_dir):
        self.settings, self.repository, self.service = settings, repository, service
        self.root = Path(data_dir) / 'acceptance'
        (self.root / 'runs').mkdir(parents=True, exist_ok=True)
        self.history = HistoryStore(self.root / 'test_history.sqlite3')
        self.snapshots = {}
        self.lock = threading.Lock()

    # ----- persistence -----
    def _path(self, run_id):
        if not isinstance(run_id, str) or not run_id.isalnum() or len(run_id) != 32:
            raise AppError('Unknown test run.')
        return self.root / 'runs' / (run_id + '.json')

    def _save(self, run):
        path = self._path(run['id'])
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(jsonable(run), ensure_ascii=False, indent=1), encoding='utf-8')
        temporary.replace(path)

    def _load(self, owner, run_id):
        path = self._path(run_id)
        if not path.exists():
            raise AppError('Unknown test run.')
        run = json.loads(path.read_text(encoding='utf-8'))
        if run['owner'] != owner:
            raise AppError('Unknown test run.')
        if run['status'] == 'running' and run_id not in self.snapshots:
            run['status'] = 'interrupted'
            run['finished_at'] = run.get('finished_at') or now()
            run['notes'].append('The application restarted while this run was in progress; its frozen snapshot is gone and the report is partial.')
            self._save(run)
        return run

    def list_runs(self, owner):
        runs = []
        for path in sorted(self.root.glob('runs/*.json'), reverse=True):
            try:
                run = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if run.get('owner') == owner:
                runs.append(run)
        runs.sort(key=lambda r: r['started_at'], reverse=True)
        return runs[:MAX_RUNS_LISTED]

    # ----- lifecycle -----
    def start(self, owner, only_failed_from=None):
        with self.lock:
            if any(r['status'] == 'running' for r in self.snapshots.values()):
                raise AppError('A test run is already in progress. Cancel it or wait for it to finish.')
            started = monotonic()
            raw, source, source_name = self.repository.load_raw()
            views = build_canonical_views(raw)
            views.source, views.source_name = source, source_name
            records = raw.to_dict('records')
            reference = ReferenceSource(records)
            witnesses, coverage, notes = select_witnesses(reference, records)
            summary = reference.summary()
            run_id = uuid.uuid4().hex
            run = {'id': run_id, 'owner': owner, 'status': 'running', 'started_at': now(), 'finished_at': None, 'scope': 'full',
                   'identity': {'app_version': APP_VERSION, 'app_revision': app_revision(), 'suite_version': SUITE_VERSION, 'evaluator_version': EVALUATOR_VERSION,
                                'fingerprint_version': FINGERPRINT_VERSION, 'rules_digest': hashlib.sha256(self.settings.rules.encode()).hexdigest(),
                                'model_config': model_config(self.settings), 'effective_date': today().isoformat(), 'source_fingerprint': summary['fingerprint']},
                   'snapshot': {'timestamp': now(), 'source': source, 'source_name': source_name, 'relation': self.settings.get('B2B_RAW_TABLE') or 'bi_reporting.b2b_project',
                                'raw_rows': summary['raw_rows'], 'excluded_rows': summary['excluded_rows'], 'opportunities': summary['opportunities'],
                                'opportunity_sku_pairs': summary['opportunity_sku_pairs'], 'currencies': summary['currencies'],
                                'fingerprints': {'raw': summary['fingerprint'], 'reference_sku': summary['sku_digest'], 'reference_opportunity': summary['opportunity_digest'],
                                                 'app_sku': result_digest(views.sku.to_dict('records'), SKU_COLUMNS), 'app_opportunity': result_digest(views.opportunity.to_dict('records'), OPPORTUNITY_COLUMNS)},
                                'normalization_warnings': self._normalization_warnings(views, summary), 'load_seconds': round(monotonic() - started, 3)},
                   'witnesses': witnesses, 'coverage': coverage, 'notes': list(notes), 'steps': [], 'browser': [], 'next_step': 0}
            parity = run['snapshot']['fingerprints']['app_sku'] == summary['sku_digest'] and run['snapshot']['fingerprints']['app_opportunity'] == summary['opportunity_digest']
            run['snapshot']['canonical_parity'] = parity
            if not parity:
                run['notes'].append('The application canonical grains differ from the independent reference grains; every data check inherits this defect.')
            selected = None
            if only_failed_from:
                previous = self._load(owner, only_failed_from)
                selected = {s['id'] for s in previous['steps'] if s['status'] in ('fail', 'error', 'blocked')}
                run['scope'] = 'failed-only from ' + only_failed_from
                run['notes'].append('Failed-case-only rerun: useful for diagnosis, never a complete pass.')
            for step in STEPS:
                record = {'id': step['id'], 'title': step['title'], 'conversation': step['conversation'], 'view': step['view'], 'status': 'pending',
                          'prompt': None, 'browser_checks': step['browser_checks'], 'expected': step['behavior'], 'interpretation': None, 'data': None,
                          'returned_plan': None, 'effective_plan': None, 'clarification': None, 'seconds': None, 'error': None, 'warnings': []}
                reason = blocked_reason(step, witnesses, coverage)
                if selected is not None and step['id'] not in selected:
                    record['status'], record['error'] = 'skipped', 'Not part of this failed-case-only rerun.'
                elif reason:
                    record['status'], record['error'] = 'blocked', reason
                else:
                    try:
                        record['prompt'] = render_prompt(step, witnesses)
                    except KeyError as missing:
                        record['status'], record['error'] = 'blocked', f'Blocked coverage: no {missing.args[0]} example exists in the frozen source.'
                run['steps'].append(record)
            for check in BROWSER_CHECKS:
                run['browser'].append({'id': check['id'], 'title': check['title'], 'step': check['step'], 'status': 'pending', 'expected': None, 'observed': None, 'notes': None})
            self.snapshots[run_id] = {'views': views, 'reference': reference, 'sessions': {}, 'status': 'running', 'lock': threading.Lock()}
            self._save(run)
            return self.status(owner, run_id)

    def _normalization_warnings(self, views, summary):
        warnings = []
        if summary['excluded_rows']:
            warnings.append(f"{summary['excluded_rows']} raw rows without an opportunity number or product code were excluded.")
        nulls = {c: int(views.opportunity[c].isna().sum()) for c in ('close_date', 'close_month', 'created_date', 'last_modified_date', 'probability', 'opportunity_amount', 'quantity')}
        for column, count in nulls.items():
            if count:
                warnings.append(f'{count} opportunities have no parsed {column}.')
        if len(summary['currencies']) > 1:
            warnings.append('Several SKU currencies are present: ' + ', '.join(f'{k} ({v})' for k, v in summary['currencies'].items()) + '.')
        return warnings

    def status(self, owner, run_id):
        run = self._load(owner, run_id)
        counts = {'passed': sum(1 for s in run['steps'] if s['status'] == 'pass'), 'failed': sum(1 for s in run['steps'] if s['status'] in ('fail', 'error')),
                  'blocked': sum(1 for s in run['steps'] if s['status'] in ('blocked', 'skipped')), 'remaining': sum(1 for s in run['steps'] if s['status'] == 'pending'),
                  'browser_passed': sum(1 for b in run['browser'] if b['status'] == 'pass'), 'browser_failed': sum(1 for b in run['browser'] if b['status'] == 'fail'),
                  'browser_blocked': sum(1 for b in run['browser'] if b['status'] == 'blocked'), 'browser_remaining': sum(1 for b in run['browser'] if b['status'] == 'pending')}
        return {'run': {k: v for k, v in run.items() if k != 'steps'} | {'steps': [{k: v for k, v in s.items() if k not in ('data',)} | {'data_ok': (s['data'] or {}).get('ok')} for s in run['steps']]},
                'counts': counts, 'next_step': run['next_step'] if run['status'] == 'running' else None, 'total_steps': len(run['steps']), 'complete': self.is_complete(run), 'full_pass': self.is_full_pass(run)}

    def detail(self, owner, run_id, step_id):
        run = self._load(owner, run_id)
        return next((s for s in run['steps'] if s['id'] == step_id), None)

    def cancel(self, owner, run_id):
        run = self._load(owner, run_id)
        if run['status'] == 'running':
            run['status'], run['finished_at'] = 'cancelled', now()
            run['notes'].append('Cancelled by the user; remaining steps and checks were not executed.')
            for step in run['steps']:
                if step['status'] == 'pending':
                    step['status'], step['error'] = 'blocked', 'Run cancelled before this step.'
            for check in run['browser']:
                if check['status'] == 'pending':
                    check['status'], check['notes'] = 'blocked', 'Run cancelled before this check.'
            self.snapshots.pop(run_id, None)
            self._save(run)
        return self.status(owner, run_id)

    # ----- execution -----
    def step(self, owner, run_id, index):
        run = self._load(owner, run_id)
        snapshot = self.snapshots.get(run_id)
        if run['status'] != 'running' or snapshot is None:
            raise AppError(f"This test run is {run['status']}; start a new run.")
        if index < run['next_step']:
            return {'step': run['steps'][index], 'status': self.status(owner, run_id)}
        if index != run['next_step']:
            raise AppError('Steps run in order; request the next step.')
        if not snapshot['lock'].acquire(blocking=False):
            raise AppError('This step is already running.')
        try:
            record = run['steps'][index]
            if record['status'] == 'pending':
                if not self.service.lane.acquire(blocking=False):
                    raise AppError('A question is running. Try again when it finishes.')
                try:
                    self._execute(owner, run, index, snapshot)
                finally:
                    self.service.lane.release()
            run['next_step'] = index + 1
            self._finish_if_complete(run, run_id)
            self._save(run)
            # The complete production result of this step stays in memory only, for the browser checks.
            return {'step': run['steps'][index], 'status': self.status(owner, run_id), 'table': snapshot.get('tables', {}).get(run['steps'][index]['id'])}
        finally:
            snapshot['lock'].release()

    def _execute(self, owner, run, index, snapshot):
        step, record = STEPS[index], run['steps'][index]
        conversation = step['conversation']
        if conversation:
            session = snapshot['sessions'].get(conversation)
            if session is None:
                session = snapshot['sessions'][conversation] = self.history.create(owner)
        else:
            session = self.history.create(owner)
        record['session'] = session
        started = monotonic()
        try:
            outcome = self.service.ask(self.history, owner, session, record['prompt'], step['view'], snapshot['views'], run['snapshot']['timestamp'])
        except AppError as error:
            record.update(status='error', error=str(error), seconds=round(monotonic() - started, 3))
            record['interpretation'] = {'ok': False, 'problems': ['the question failed: ' + str(error)]}
            self._block_followups(run, index, 'An earlier turn of this conversation failed.')
            return
        except Exception:
            record.update(status='error', error='The question failed unexpectedly.', seconds=round(monotonic() - started, 3))
            record['interpretation'] = {'ok': False, 'problems': ['the question failed unexpectedly']}
            self._block_followups(run, index, 'An earlier turn of this conversation failed.')
            return
        record['seconds'] = round(monotonic() - started, 3)
        record['returned_plan'] = outcome.get('returned_plan')
        ok, problems, variant = match_plan(outcome, step, run['witnesses'])
        record['interpretation'] = {'ok': ok, 'problems': problems, 'variant': jsonable({k: v for k, v in variant.items() if k != 'columns'})}
        if outcome['kind'] == 'clarify':
            record['clarification'] = outcome['question']
            record['effective_plan'] = None
            record['data'] = {'ok': True, 'checks': {'no_execution': True}, 'differences': [], 'counts': {}} if ok else {'ok': False, 'checks': {'no_execution': False}, 'differences': [], 'counts': {}}
            record['status'] = 'pass' if ok else 'fail'
            if not ok:
                self._block_followups(run, index, 'An unexpected clarification left the conversation without the expected plan.')
            return
        table = outcome['table']
        snapshot['tables'] = {step['id']: table}
        record['effective_plan'] = outcome['plan']
        record['warnings'] = table.get('warnings', [])
        if step['expect']['intent'] == 'clarify':
            record['data'] = {'ok': False, 'checks': {'no_execution': False}, 'differences': [{'kind': 'executed', 'total_rows': table['total_rows']}], 'counts': {}}
            record['status'] = 'fail'
            record['result'] = self._result_summary(table, None)
            return
        spec = reference_spec(step, variant, run['witnesses'])
        expected = evaluate(snapshot['reference'], spec)
        comparison = compare(expected, table)
        if step['expect']['intent'] == 'chart':
            chart = table.get('chart') or {}
            comparison['checks']['chart_spec'] = chart.get('type') == step['expect']['chart_type'] and set(chart.get('measures', [])) == set(spec['measures']) and list(chart.get('dimensions', [])) == list(spec['group'])
            comparison['ok'] = comparison['ok'] and comparison['checks']['chart_spec']
        record['data'] = jsonable(comparison)
        record['reference_spec'] = jsonable(spec)
        record['result'] = self._result_summary(table, expected)
        record['status'] = 'pass' if ok and comparison['ok'] else 'fail'

    def _result_summary(self, table, expected):
        summary = {'columns': table['columns'], 'total_rows': table['total_rows'], 'preview_rows': len(table['rows']), 'truncated': table['truncated'],
                   'result_digest': table.get('result_digest'), 'totals': table.get('totals'), 'chart': table.get('chart'), 'rows': table['rows'][:10],
                   'rows_checked': len(table['rows'])}
        if expected is not None:
            summary['expected'] = {'total_rows': expected['total'], 'digest': expected['digest'], 'totals': jsonable(expected['totals']), 'rows': jsonable(expected['rows'][:10]), 'columns': expected['columns']}
        return summary

    def _block_followups(self, run, index, reason):
        conversation = STEPS[index]['conversation']
        if not conversation:
            return
        for later in range(index + 1, len(STEPS)):
            if STEPS[later]['conversation'] == conversation and run['steps'][later]['status'] == 'pending':
                run['steps'][later]['status'], run['steps'][later]['error'] = 'blocked', reason

    def record_browser(self, owner, run_id, check_id, status, expected=None, observed=None, notes=None):
        run = self._load(owner, run_id)
        check = next((c for c in run['browser'] if c['id'] == check_id), None)
        if check is None or status not in ('pass', 'fail', 'blocked'):
            raise AppError('Unknown browser check or status.')
        if run['status'] != 'running':
            raise AppError(f"This test run is {run['status']}.")
        check.update(status=status, expected=expected, observed=observed, notes=notes, recorded_at=now())
        self._finish_if_complete(run, run_id)
        self._save(run)
        return self.status(owner, run_id)

    def is_complete(self, run):
        if run['status'] in ('cancelled', 'interrupted'):
            return False
        return all(s['status'] != 'pending' for s in run['steps']) and all(b['status'] != 'pending' for b in run['browser'])

    def is_full_pass(self, run):
        return run['status'] == 'complete' and run['scope'] == 'full' and all(s['status'] == 'pass' for s in run['steps']) and all(b['status'] == 'pass' for b in run['browser']) and run['snapshot'].get('canonical_parity', False)

    def _finish_if_complete(self, run, run_id):
        if run['status'] == 'running' and self.is_complete(run):
            run['status'], run['finished_at'] = 'complete', now()
            self.snapshots.pop(run_id, None)

    # ----- qualification and comparison -----
    def identity_of(self, run):
        return {k: run['identity'][k] for k in IDENTITY_KEYS}

    def qualification(self, owner):
        runs = [r for r in self.list_runs(owner) if r['scope'] == 'full' and r['status'] not in ('running',)]
        streak, reason = 0, 'No complete run yet.'
        latest_identity = None
        for run in runs:
            identity = self.identity_of(run)
            if latest_identity is None:
                latest_identity = identity
            if identity != latest_identity:
                reason = 'An earlier run used a different source, app revision, suite, rules, model configuration, or effective date; the sequence restarted.'
                break
            if not self.is_full_pass(run):
                reason = f"Run {run['id'][:8]} is {run['status']} with {sum(1 for s in run['steps'] if s['status'] != 'pass')} steps and {sum(1 for b in run['browser'] if b['status'] != 'pass')} browser checks not passing."
                break
            streak += 1
            if streak >= 3:
                reason = 'Three consecutive complete passes with matching source, app revision, suite, rules, model configuration, and effective date.'
                break
        return {'ready': streak >= 3, 'streak': min(streak, 3), 'required': 3, 'reason': reason, 'identity': latest_identity}

    def comparison(self, owner, run):
        previous = next((r for r in self.list_runs(owner) if r['id'] != run['id'] and r['started_at'] < run['started_at']), None)
        if previous is None:
            return None
        before = {s['id']: s for s in previous['steps']}
        outcome = {'previous_run': previous['id'], 'previous_started_at': previous['started_at'], 'newly_failing': [], 'fixed': [], 'inconsistent': [], 'changed_results': [], 'latency': [], 'changes': {}}
        for step in run['steps']:
            old = before.get(step['id'])
            if not old:
                continue
            if step['status'] in ('fail', 'error') and old['status'] == 'pass':
                outcome['newly_failing'].append(step['id'])
            elif step['status'] == 'pass' and old['status'] in ('fail', 'error'):
                outcome['fixed'].append(step['id'])
            elif step['status'] != old['status']:
                outcome['inconsistent'].append(f"{step['id']}: {old['status']} -> {step['status']}")
            new_digest, old_digest = (step.get('result') or {}).get('result_digest'), (old.get('result') or {}).get('result_digest')
            if new_digest != old_digest and (new_digest or old_digest):
                outcome['changed_results'].append(step['id'])
            if step.get('seconds') is not None and old.get('seconds') is not None and abs(step['seconds'] - old['seconds']) >= 1:
                outcome['latency'].append(f"{step['id']}: {old['seconds']}s -> {step['seconds']}s")
            if step.get('prompt') != old.get('prompt'):
                outcome['changes'].setdefault('prompts', []).append(step['id'])
        for key in IDENTITY_KEYS:
            if run['identity'].get(key) != previous['identity'].get(key):
                outcome['changes'][key] = {'previous': previous['identity'].get(key), 'current': run['identity'].get(key)}
        outcome['same_sequence'] = self.identity_of(run) == self.identity_of(previous) and run['scope'] == 'full' and previous['scope'] == 'full'
        return outcome

    # ----- report -----
    def report(self, owner, run_id):
        run = self._load(owner, run_id)
        identity, snapshot = run['identity'], run['snapshot']
        lines = [f"# B2B acceptance test run {run['id']}", '',
                 f"Suite {identity['suite_version']} · app {identity['app_revision']} · evaluator {identity['evaluator_version']} · status **{run['status']}** · scope {run['scope']}", '',
                 '## Run identity and source', '',
                 md_table(['Item', 'Value'], [['Run id', run['id']], ['Started', run['started_at']], ['Finished', run.get('finished_at') or 'not finished'], ['Effective date', identity['effective_date']],
                          ['App version / revision', f"{identity['app_version']} / {identity['app_revision']}"], ['Suite version', identity['suite_version']], ['Evaluator / fingerprint versions', f"{identity['evaluator_version']} / {identity['fingerprint_version']}"],
                          ['Business-rule digest', identity['rules_digest']], ['Model', f"{identity['model_config']['provider']} · {identity['model_config']['model']} · {identity['model_config']['endpoint_host']}:{identity['model_config']['endpoint_port']}"],
                          ['Model settings', f"temperature {identity['model_config']['temperature']}, max tokens {identity['model_config']['max_tokens']}, {identity['model_config']['structured_output']}"],
                          ['Source', f"{snapshot['source']} · {snapshot['source_name']} (configured relation {snapshot['relation']})"], ['Snapshot timestamp', snapshot['timestamp']],
                          ['Raw rows / excluded', f"{snapshot['raw_rows']} / {snapshot['excluded_rows']}"], ['Distinct opportunities', snapshot['opportunities']], ['Distinct opportunity/SKU pairs', snapshot['opportunity_sku_pairs']],
                          ['Currency distribution (SKU rows)', ', '.join(f'{k}: {v}' for k, v in snapshot['currencies'].items()) or 'none'],
                          ['Raw fingerprint', snapshot['fingerprints']['raw']], ['Reference grain digests', f"sku {snapshot['fingerprints']['reference_sku']} · opportunity {snapshot['fingerprints']['reference_opportunity']}"],
                          ['App grain digests', f"sku {snapshot['fingerprints']['app_sku']} · opportunity {snapshot['fingerprints']['app_opportunity']}"], ['Canonical parity (app = reference)', 'yes' if snapshot.get('canonical_parity') else '**NO**'],
                          ['Run completeness', 'complete' if self.is_complete(run) else 'partial']]), '']
        if snapshot['normalization_warnings']:
            lines += ['Normalization warnings:', ''] + [f'- {md(w)}' for w in snapshot['normalization_warnings']] + ['']
        if run['notes']:
            lines += ['Notes:', ''] + [f'- {md(n)}' for n in run['notes']] + ['']
        lines += ['Substituted witnesses:', '', md_table(['Placeholder', 'Value'], [[k, v] for k, v in run['witnesses'].items()]), '']
        # Scorecard
        steps = run['steps']
        interp = {'pass': sum(1 for s in steps if (s.get('interpretation') or {}).get('ok')), 'fail': sum(1 for s in steps if s.get('interpretation') and not s['interpretation'].get('ok'))}
        data = {'pass': sum(1 for s in steps if (s.get('data') or {}).get('ok')), 'fail': sum(1 for s in steps if s.get('data') and not s['data'].get('ok'))}
        browser = {'pass': sum(1 for b in run['browser'] if b['status'] == 'pass'), 'fail': sum(1 for b in run['browser'] if b['status'] == 'fail')}
        blocked_steps = [s for s in steps if s['status'] in ('blocked', 'skipped')]
        pending = [s for s in steps if s['status'] == 'pending']
        blocked_checks = [b for b in run['browser'] if b['status'] in ('blocked', 'pending')]
        qualification = self.qualification(owner)
        lines += ['## Scorecard', '', md_table(['Dimension', 'Passed', 'Failed', 'Blocked or not run'],
                  [['Interpretation', interp['pass'], interp['fail'], len(blocked_steps) + len(pending)], ['Data correctness', data['pass'], data['fail'], len(blocked_steps) + len(pending)],
                   ['Browser presentation', browser['pass'], browser['fail'], len(blocked_checks)]]), '',
                  'Full pass: **' + ('yes' if self.is_full_pass(run) else 'no') + '**. Delivery gate: ' + ('**Ready for review**' if qualification['ready'] else f"{qualification['streak']} of 3 consecutive passes") + ' — ' + md(qualification['reason']), '']
        failed = [s for s in steps if s['status'] in ('fail', 'error')]
        if failed or blocked_steps or pending or blocked_checks or browser['fail']:
            lines += ['### Failed and blocked checks', '']
            for s in failed:
                problems = (s.get('interpretation') or {}).get('problems') or []
                lines.append(f"- **{s['id']} {md(s['title'])}: {s['status']}** — {md('; '.join(problems) or s.get('error') or 'data mismatch')}; prevents qualification.")
            for s in blocked_steps + pending:
                lines.append(f"- **{s['id']} {md(s['title'])}: {s['status']}** — {md(s.get('error') or 'not executed')}; prevents qualification.")
            for b in run['browser']:
                if b['status'] != 'pass':
                    lines.append(f"- **Browser check {b['id']} {md(b['title'])}: {b['status']}** — {md(b.get('notes') or 'not recorded')}; prevents qualification.")
            lines.append('')
        # Per-case evidence
        lines += ['## Per-case evidence', '']
        for s in steps:
            lines += self._step_section(s)
        lines += ['## Browser checks', '']
        for b in run['browser']:
            lines += [f"### Browser check {b['id']}: {md(b['title'])} — **{b['status']}** (step {b['step']})", '']
            if b.get('notes'):
                lines += [md(b['notes']), '']
            if b.get('expected') is not None or b.get('observed') is not None:
                lines += ['```json', json.dumps({'expected': b.get('expected'), 'observed': b.get('observed')}, ensure_ascii=False, indent=1)[:6000], '```', '']
        # Comparison
        comparison = self.comparison(owner, run)
        lines += ['## Comparison with the previous run', '']
        if comparison is None:
            lines += ['No earlier run exists for this user.', '']
        else:
            lines += [md_table(['Item', 'Value'], [['Previous run', f"{comparison['previous_run']} started {comparison['previous_started_at']}"], ['Newly failing', ', '.join(comparison['newly_failing']) or 'none'],
                      ['Fixed', ', '.join(comparison['fixed']) or 'none'], ['Inconsistent', ', '.join(comparison['inconsistent']) or 'none'], ['Result changes (digest)', ', '.join(comparison['changed_results']) or 'none'],
                      ['Latency differences (>= 1 s)', '; '.join(comparison['latency']) or 'none'], ['Source, prompt, rule, app, or model-setting changes', json.dumps(comparison['changes'], ensure_ascii=False) if comparison['changes'] else 'none'],
                      ['Eligible for the same three-pass sequence', 'yes' if comparison['same_sequence'] else 'no']]), '']
        lines += ['## Review instructions', '',
                  'Recompute every expected value from the local CSV with the reference rules below and compare with the per-case expected counts, totals, digests, and rows.', '',
                  f"- Fingerprint {identity['fingerprint_version']}: for each raw row, trim spaces from every value and turn blanks into null; JSON-encode the 30 values in the order below; SHA-256 each row; sort the hex digests; SHA-256 the newline-joined list. Duplicate rows keep their multiplicity and row order does not matter.",
                  '- Result digest digest1: for each complete result row, normalize each cell (exact decimals without trailing zeros, ISO dates, null, true/false), JSON-encode the cells in result column order, SHA-256 each row, sort, SHA-256 the newline-joined list.',
                  '- Text is trimmed of spaces (empty becomes null); numbers must match `^[+-]?[0-9]+(\\.[0-9]+)?$`; probability accepts an optional `%` and is divided by 100; dates are day-first `D/M/YYYY` with one- or two-digit day and month and must be valid calendar dates; invalid values become null.',
                  '- Rows without opportunity number or product code are excluded. SKU rows sum quantity and amount_converted per opportunity/product; other columns use MIN (last_modified_date MAX). Opportunity rows sum SKU quantity and amount; parent amounts are compared with the 0.01 rule.',
                  '- Stage groups: Won = Won, Rollout Started, Rollout Finished; Open = Identified, Qualified, Negotiation; Lost = Dropped, Lost.',
                  '- Filters apply after grain reduction; a product-level filter at opportunity grain selects whole opportunities. deal_size counts once per opportunity.', '',
                  'CSV header mapping (canonical field ← accepted export headers):', '',
                  md_table(['Canonical field', 'SQL column', 'Export header examples'], [[f, c, h] for f, c, h in HEADER_MAPPING]), '']
        return '\n'.join(lines) + '\n'

    def _step_section(self, s):
        lines = [f"### {s['id']} {md(s['title'])} — **{s['status']}**", '',
                 md_table(['Item', 'Value'], [['Prompt', s.get('prompt') or '(not rendered)'], ['Layout selection', s['view']], ['Conversation', s['conversation'] or 'fresh conversation'],
                          ['Expected behavior', s.get('expected') or ''], ['Duration', f"{s['seconds']} s" if s.get('seconds') is not None else ''], ['Error', s.get('error') or '']]), '']
        if s.get('returned_plan') is not None:
            lines += ['Returned plan (Qwen):', '', '```json', json.dumps(s['returned_plan'], ensure_ascii=False), '```', '']
        if s.get('clarification'):
            lines += [f"Clarification: {md(s['clarification'])}", '']
        if s.get('effective_plan') is not None:
            lines += ['Effective merged plan:', '', '```json', json.dumps(s['effective_plan'], ensure_ascii=False), '```', '']
        interp = s.get('interpretation')
        if interp:
            lines += [f"Interpretation: **{'pass' if interp.get('ok') else 'fail'}**" + (' — ' + md('; '.join(interp.get('problems', []))) if interp.get('problems') else ''), '']
            if interp.get('variant', {}).get('note'):
                lines += [md(interp['variant']['note']), '']
        data, result = s.get('data'), s.get('result')
        if data:
            checks = ', '.join(f"{k}={'ok' if v else 'FAIL'}" for k, v in data.get('checks', {}).items())
            lines += [f"Data: **{'pass' if data.get('ok') else 'fail'}** — {md(checks)}", '']
        if result:
            expected = result.get('expected') or {}
            lines += [md_table(['Measure', 'Expected', 'Actual'], [['Complete row count', expected.get('total_rows', ''), result['total_rows']], ['Full-result digest', expected.get('digest', ''), result.get('result_digest')],
                      ['Totals (complete result)', json.dumps(expected.get('totals'), ensure_ascii=False) if expected.get('totals') else '', json.dumps(result.get('totals'), ensure_ascii=False) if result.get('totals') else ''],
                      ['Rows checked cell by cell', expected.get('total_rows', '') if expected else '', f"{result['rows_checked']} preview rows (complete result verified by count, totals, and digest)"]]), '']
            if result.get('chart'):
                lines += ['Chart specification: `' + json.dumps(result['chart'], ensure_ascii=False) + '`', '']
            if result['rows']:
                label = 'All result rows' if result['total_rows'] <= 10 else f"First 10 of {result['total_rows']} rows (report preview; {result['rows_checked']} rows were checked)"
                lines += [label + ':', '', md_table(result['columns'], result['rows']), '']
            if expected.get('rows') and (data and not data.get('ok')):
                lines += ['Expected rows (first 10):', '', md_table(expected['columns'], expected['rows']), '']
        if data and data.get('differences'):
            lines += ['Keyed differences (first 20):', '', '```json', json.dumps(data['differences'], ensure_ascii=False, indent=1)[:8000], '```', '']
        if data and data.get('counts'):
            lines += ['Comparison counts: `' + json.dumps(data['counts'], ensure_ascii=False) + '`', '']
        if s.get('warnings'):
            lines += ['Warnings: ' + md('; '.join(s['warnings'])), '']
        return lines


HEADER_MAPPING = [
    ('opportunity_no', 'opportunity_no', 'Opportunity No.'), ('product_code', 'product_code', 'Product Code'), ('subsidiary_subsidiary_code', 'subsidiary_subsidiary_code', 'Subsidiary: Subsidiary Code'),
    ('opportunity_name', 'opportunity_name', 'Opportunity Name'), ('end_customer', 'end_customer', 'End Customer'), ('gscm_product_group_new', 'gscm_product_group_new', 'GSCM Product Group (New)'),
    ('pet_name', 'pet_name', 'PET Name'), ('stage', 'stage', 'Stage'), ('opportunity_owner', 'opportunity_owner', 'Opportunity Owner'), ('biz_focus', 'biz_focus', 'Biz Focus'),
    ('business_location', 'business_location', 'Business Location'), ('division', 'division', 'Division'), ('sales_type_detail', 'sales_type_detail', 'Sales Type Detail'), ('type', 'type', 'Type'),
    ('amount_converted_currency', 'amount_converted_currency', 'Amount (converted) Currency'), ('opp_amount_converted_currency', 'opp_amount_converted_currency', 'Opportunity Amount (converted) Currency'),
    ('rollout_period_to', 'rollout_period_to', 'Rollout Period To'), ('rollout_period_from', 'rollout_period_from', 'Rollout Period From'), ('first_channel', '1st_channel', '1st Channel'),
    ('comment', 'comment', 'Comment'), ('quantity', 'quantity', 'Quantity'), ('amount_converted', 'amount_converted', 'Amount (converted)'), ('opp_amount_converted', 'opp_amount_converted', 'Opportunity Amount (converted)'),
    ('probability', 'probability', 'Probability (%)'), ('age', 'age', 'Age'), ('deal_size_on_pricing_date_usd', 'deal_size_on_pricing_date_usd', 'Deal Size on Pricing Date (USD)'),
    ('close_month', 'close_month', 'Close Month'), ('close_date', 'close_date', 'Close Date'), ('created_date', 'created_date', 'Created Date'), ('last_modified_date', 'last_modified_date', 'Last Modified Date'),
]
