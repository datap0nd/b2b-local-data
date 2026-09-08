"""Runs the versioned acceptance suite against one frozen snapshot and writes the Markdown report.

The server owns the suite, the step order, and the expected results. Step requests are idempotent and
carry no prompts, plans, SQL, or paths. Run state lives under B2B_DATA_DIR/acceptance, separate from
ordinary conversation history. Every run retains a lossless copy of its raw snapshot so a failure can be
replayed diagnostically; replay runs never qualify for delivery."""
from datetime import date, datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic, sleep
from urllib.parse import urlsplit
import uuid

from acceptance_suite import BROWSER_CHECKS, DETAIL_DEFAULT, STEPS, SUMMARY_DEFAULT, SUITE_VERSION, blocked_reason, check_clarification, match_plan, reference_spec, render_prompt, select_witnesses
from app_config import APP_VERSION, ROOT, AppError
from data_layer import OPPORTUNITY_COLUMNS, RAW_COLUMNS, SKU_COLUMNS, SOURCE_FIELDS, build_canonical_views
from history_store import HistoryStore
from query_engine import CALCULATION_VERSION, result_digest
from reference_evaluator import DIGEST_VERSION, EVALUATOR_VERSION, FINGERPRINT_FIELDS, FINGERPRINT_VERSION, ReferenceSource, compare, compare_grains, evaluate, evaluate_supporting
from reference_evaluator import OPPORTUNITY_COLUMNS as REFERENCE_OPPORTUNITY_COLUMNS, SKU_COLUMNS as REFERENCE_SKU_COLUMNS

REPORT_VERSION = 'report-3'
MAX_RUNS_LISTED = 50
# Everything that must stay identical across the three qualifying runs.
IDENTITY_KEYS = ('source_fingerprint', 'app_revision', 'suite_version', 'evaluator_version', 'digest_version', 'calculation_version', 'source_contract_verified', 'rules_digest', 'model_config', 'prompt_digest', 'effective_date')
STEP_STATES = ('pass', 'fail', 'error', 'review', 'blocked', 'not_applicable', 'pending')
EXECUTED_STATES = ('pass', 'fail', 'error', 'review')


def replace_evidence(temporary, destination):
    """Keep replacement atomic while tolerating short Windows scanner/file locks.

    Retry only the rename, never the query or model call. A persistent denial
    leaves the previous destination and recoverable temporary file intact.
    """
    delays = (.05, .1, .2, .4, .8, 1., 1.)
    for attempt in range(len(delays) + 1):
        try:
            temporary.replace(destination)
            return
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == len(delays):
                raise
            sleep(delays[attempt])


def compare_supporting(expected, outcome):
    """Validate raw supporting tables against authored, independent expectations.

    This runs before the API's 25-row public preview. Every supporting cell is
    checked, including rows after the primary result's limit. Identical primary
    totals cannot conceal missing evidence, wrong membership, or another snapshot.
    """
    supporting = outcome.get('supporting') or {}
    views = supporting.get('views') or {}
    primary = outcome['table']
    primary_meta = primary.get('metadata') or {}
    checks = {'contract': supporting.get('version') == 1 and supporting.get('available') is True,
              'default_view': supporting.get('default_view') == 'summary',
              'views': set(views) == {'summary', 'detail'}}
    comparisons = {}
    for view, wanted in expected.items():
        actual = views.get(view)
        if not isinstance(actual, dict) or 'rows' not in actual:
            comparisons[view] = {'ok': False, 'checks': {'available': False},
                                 'differences': [{'kind': 'supporting_view_missing', 'view': view}], 'counts': {}}
            continue
        result = compare(wanted, actual)
        metadata = actual.get('metadata') or {}
        evidence = metadata.get('evidence') or {}
        result['checks']['complete_raw_rows'] = actual.get('truncated') is False and len(actual['rows']) == wanted['total']
        result['checks']['view'] = actual.get('view') == view
        result['checks']['scope'] = (evidence.get('role') == 'supporting'
                                    and evidence.get('source_grain') == wanted['source_grain']
                                    and evidence.get('data_scope') == wanted['data_scope']
                                    and (actual.get('views') or {}).get('scope_label') == ('All products in matching opportunities' if wanted['data_scope'] == 'all_products' else 'Matching products only'))
        result['checks']['default_columns'] = evidence.get('default_columns') == (SUMMARY_DEFAULT if view == 'summary' else DETAIL_DEFAULT)
        result['checks']['answer_identity'] = evidence.get('source_result_digest') == primary.get('result_digest')
        result['checks']['snapshot_identity'] = all(key in metadata and key in primary_meta and metadata[key] == primary_meta[key]
                                                   for key in ('fingerprint', 'freshness', 'data_contract_version', 'calculation_version'))
        result['ok'] = all(result['checks'].values())
        comparisons[view] = result
    return {'ok': all(checks.values()) and all(item['ok'] for item in comparisons.values()),
            'checks': checks, 'views': comparisons}


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
    """Model identity and the settings the planner will send, without any credential or authorization header."""
    endpoint = settings.get('LLM_API_URL') or settings.get('AI_BASE_URL') or ''
    parsed = urlsplit(endpoint)
    provider = settings.get('AI_PROVIDER', 'openai_compatible')
    return {'provider': provider, 'model': settings.get('LLM_MODEL_NAME') or settings.get('AI_MODEL') or '', 'endpoint_host': parsed.hostname or '',
            'endpoint_port': parsed.port, 'temperature': 0, 'max_tokens': 3000 if provider == 'ollama' else 5000,
            'structured_output': 'json_schema' if provider == 'ollama' else 'none',
            'stream': bool(settings.flag('B2B_LLM_STREAM', True)) if provider == 'openai_compatible' else False,
            'timeout_seconds': settings.number('AI_TIMEOUT_SECONDS', 120, high=900)}


def jsonable(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f') if value != 0 else '0'
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if value is not None and not isinstance(value, (str, int, float, bool)):
        try:
            if value != value:   # pandas/numpy NaN
                return None
        except Exception:
            pass
        item = getattr(value, 'item', None)
        return item() if callable(item) else str(value)
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
    def __init__(self, settings, repository, service, data_dir, *, live=False):
        self.settings, self.repository, self.service = settings, repository, service
        self.live = live
        self.steps, self.suite_version, self.scenarios = STEPS, SUITE_VERSION, []
        if live:
            from live_scenarios import STEPS as live_steps, SCENARIOS, VERSION
            self.steps, self.suite_version, self.scenarios = live_steps, VERSION, SCENARIOS
        self.artifacts = settings.home / 'test-results'
        self.root = Path(data_dir) / 'acceptance'
        (self.root / 'runs').mkdir(parents=True, exist_ok=True)
        (self.root / 'snapshots').mkdir(parents=True, exist_ok=True)
        self.history = HistoryStore(self.root / 'test_history.sqlite3')
        self.snapshots = {}
        self._cached_runs = {}
        self.lock = threading.Lock()

    # ----- persistence -----
    def _path(self, run_id):
        if not isinstance(run_id, str) or not run_id.isalnum() or len(run_id) != 32:
            raise AppError('Unknown test run.')
        return self.root / 'runs' / (run_id + '.json')

    def _snapshot_path(self, run_id):
        return self.root / 'snapshots' / (self._path(run_id).stem + '.json.gz')

    def _save(self, run):
        path = self._path(run['id'])
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(jsonable(run), ensure_ascii=False, indent=None if self.live else 1), encoding='utf-8')
        replace_evidence(temporary, path)
        if self.live:
            self._cached_runs[run['id']] = run
            while len(self._cached_runs) > 3: self._cached_runs.pop(next(iter(self._cached_runs)))

    def _save_snapshot(self, run_id, records, source, source_name, relation):
        """Lossless local copy of the raw records (trimmed of nothing) so the run can be replayed."""
        payload = {'run_id': run_id, 'saved_at': now(), 'source': source, 'source_name': source_name, 'relation': relation, 'columns': RAW_COLUMNS,
                   'records': [[jsonable(record.get(c)) for c in RAW_COLUMNS] for record in records]}
        with gzip.open(self._snapshot_path(run_id), 'wt', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False)

    def load_snapshot(self, run_id):
        path = self._snapshot_path(run_id)
        if not path.exists():
            raise AppError('No retained snapshot exists for that run.')
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            payload = json.load(stream)
        records = [dict(zip(payload['columns'], row)) for row in payload['records']]
        return records, payload

    def _load(self, owner, run_id):
        path = self._path(run_id)
        if not path.exists():
            raise AppError('Unknown test run.')
        run = self._cached_runs.get(run_id) if self.live else None
        if run is None:
            run = json.loads(path.read_text(encoding='utf-8'))
            journal = self.artifacts / run_id / 'scenarios.json'
            if self.live and journal.exists(): run['scenarios'] = json.loads(journal.read_text(encoding='utf-8'))
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
    def start(self, owner, only_failed_from=None, replay_from=None):
        with self.lock:
            if any(r['status'] == 'running' for r in self.snapshots.values()):
                raise AppError('A test run is already in progress. Cancel it or wait for it to finish.')
            started = monotonic()
            relation = self.settings.get('B2B_RAW_TABLE') or 'bi_reporting.b2b_project_segmented'
            if replay_from:
                self._load(owner, replay_from)
                records, payload = self.load_snapshot(replay_from)
                import pandas as pd
                raw = pd.DataFrame(records, columns=RAW_COLUMNS, dtype=object)
                source, source_name, relation = payload['source'], payload['source_name'], payload.get('relation') or relation
            else:
                raw, source, source_name = self.repository.load_raw()
                records = raw.to_dict('records')
            views = build_canonical_views(raw)
            views.source, views.source_name = source, source_name
            reference = ReferenceSource(records)
            witnesses, coverage, notes = select_witnesses(reference, records)
            summary = reference.summary()
            run_id = uuid.uuid4().hex
            effective = today()
            planner = getattr(self.service, 'planner', None)
            prompt_digest = planner.prompt_digest(effective) if planner is not None and callable(getattr(planner, 'prompt_digest', None)) else 'unavailable'
            app_sku, app_opportunity = views.sku.to_dict('records'), views.opportunity.to_dict('records')
            run = {'id': run_id, 'owner': owner, 'status': 'running', 'started_at': now(), 'finished_at': None, 'scope': 'full', 'report_version': REPORT_VERSION,
                   'identity': {'app_version': APP_VERSION, 'app_revision': app_revision(), 'suite_version': SUITE_VERSION, 'evaluator_version': EVALUATOR_VERSION,
                                'digest_version': DIGEST_VERSION, 'calculation_version':CALCULATION_VERSION, 'source_contract_verified':source!='postgres' or self.settings.flag('B2B_SOURCE_CONTRACT_VERIFIED',False), 'fingerprint_version': FINGERPRINT_VERSION, 'rules_digest': hashlib.sha256(self.settings.rules.encode()).hexdigest(),
                                'model_config': model_config(self.settings), 'prompt_digest': prompt_digest, 'effective_date': effective.isoformat(), 'source_fingerprint': summary['fingerprint']},
                   'snapshot': {'timestamp': now(), 'source': source, 'source_name': source_name, 'relation': relation,
                                'raw_rows': summary['raw_rows'], 'excluded_rows': summary['excluded_rows'], 'opportunities': summary['opportunities'],
                                'opportunity_sku_pairs': summary['opportunity_sku_pairs'], 'currencies': summary['currencies'],
                                'fingerprints': {'raw': summary['fingerprint'], 'reference_sku': summary['sku_digest'], 'reference_opportunity': summary['opportunity_digest'],
                                                 'app_sku': result_digest(app_sku, SKU_COLUMNS), 'app_opportunity': result_digest(app_opportunity, OPPORTUNITY_COLUMNS)},
                                'normalization_warnings': self._normalization_warnings(views, summary), 'load_seconds': round(monotonic() - started, 3), 'retained_snapshot': None},
                   'planner': {'settings': None, 'fallback_events': [], 'prompt_digest': prompt_digest, 'corrections': 0, 'recovered_steps': []},
                   'witnesses': witnesses, 'coverage': coverage, 'notes': list(notes), 'steps': [], 'browser': [], 'next_step': 0, 'qualified': None, 'unqualified_reasons': []}
            run['identity']['suite_version'] = self.suite_version
            if self.live:
                run['scenarios'] = [{k: v for k, v in s.items() if k != 'steps'} | {'step_ids': [t['id'] for t in s['steps']], 'png': None, 'ui': None, 'visual_review': 'pending'} for s in self.scenarios]
            # Canonical parity is a global prerequisite: the app grains must equal the reference grains key by key.
            parity = {'sku': compare_grains(reference.sku, app_sku, ['opportunity_no', 'product_code'], REFERENCE_SKU_COLUMNS, source=reference),
                      'opportunity': compare_grains(reference.opportunity, app_opportunity, ['opportunity_no'], REFERENCE_OPPORTUNITY_COLUMNS, source=reference)}
            parity['ok'] = parity['sku']['ok'] and parity['opportunity']['ok']
            run['snapshot']['parity'] = jsonable(parity)
            run['snapshot']['canonical_parity'] = parity['ok']
            if not parity['ok']:
                run['notes'].append('Canonical parity failed: the application grains differ from the independent reference grains (see the parity diagnostics). Individual assertions are still recorded, but the run is unqualified.')
            try:
                self._save_snapshot(run_id, records, source, source_name, relation)
                run['snapshot']['retained_snapshot'] = self._snapshot_path(run_id).name
            except OSError as error:
                run['notes'].append(f'The raw snapshot could not be retained for replay: {error}')
            selected = None
            if replay_from:
                run['scope'] = 'replay of ' + replay_from
                run['notes'].append('Replay of a retained snapshot for diagnosis: never a qualifying run.')
            if only_failed_from:
                previous = self._load(owner, only_failed_from)
                selected = {s['id'] for s in previous['steps'] if s['status'] in ('fail', 'error', 'review', 'blocked')}
                run['scope'] = 'failed-only from ' + only_failed_from
                run['notes'].append('Failed-case-only rerun: useful for diagnosis, never a complete pass.')
            for step in self.steps:
                record = {'id': step['id'], 'title': step['title'], 'conversation': step['conversation'], 'view': step['view'], 'status': 'pending',
                          'prompt': None, 'browser_checks': step['browser_checks'], 'expected': step['behavior'], 'interpretation': None, 'data': None,
                          'returned_plan': None, 'effective_plan': None, 'clarification': None, 'seconds': None, 'error': None, 'warnings': [],
                          'attempts': [], 'recovered': False, 'planner_settings': None, 'fallback_events': []}
                for key in ('scenario_id', 'category', 'turn_number', 'ui_actions'):
                    if key in step: record[key] = step[key]
                reason = blocked_reason(step, witnesses, coverage)
                if selected is not None and step['id'] not in selected:
                    record['status'], record['error'] = 'not_applicable', 'Not part of this failed-case-only rerun.'
                elif reason:
                    record['status'], record['error'] = ('not_applicable' if self.live else 'blocked'), reason
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

    def counts(self, run):
        steps, browser = run['steps'], run['browser']
        by_state = {state: sum(1 for s in steps if s['status'] == state) for state in STEP_STATES}
        return {'passed': by_state['pass'], 'failed': by_state['fail'] + by_state['error'], 'errors': by_state['error'], 'review': by_state['review'],
                'blocked': by_state['blocked'] + by_state['not_applicable'], 'not_applicable': by_state['not_applicable'], 'remaining': by_state['pending'], 'by_state': by_state,
                'total': len(steps), 'accounted': sum(by_state.values()) == len(steps),
                'browser_passed': sum(1 for b in browser if b['status'] == 'pass'), 'browser_failed': sum(1 for b in browser if b['status'] == 'fail'),
                'browser_blocked': sum(1 for b in browser if b['status'] == 'blocked'), 'browser_remaining': sum(1 for b in browser if b['status'] == 'pending')}

    def status(self, owner, run_id):
        run = self._load(owner, run_id)
        if self.live:
            keys = ('id','title','scenario_id','category','turn_number','prompt','status','error','browser_checks','ui_actions','expected','interpretation','recovered')
            steps = [{k: s.get(k) for k in keys} | {'data_ok': (s.get('data') or {}).get('ok')} for s in run['steps']]
            snapshot = {k: v for k, v in run['snapshot'].items() if k not in ('parity', 'normalization_warnings')}
            return {'run': {k: run[k] for k in ('id','status','scenarios','started_at','finished_at')} | {'snapshot': snapshot, 'steps': steps},
                    'counts': self.counts(run), 'next_step': run['next_step'] if run['status'] == 'running' and run['next_step'] < len(run['steps']) else None,
                    'total_steps': len(run['steps']), 'complete': self.is_complete(run), 'full_pass': self.is_full_pass(run)}
        return {'run': {k: v for k, v in run.items() if k != 'steps'} | {'steps': [{k: v for k, v in s.items() if k not in ('data',)} | {'data_ok': (s['data'] or {}).get('ok')} for s in run['steps']]},
                'counts': self.counts(run), 'next_step': run['next_step'] if run['status'] == 'running' and run['next_step'] < len(run['steps']) else None, 'total_steps': len(run['steps']), 'complete': self.is_complete(run),
                'full_pass': self.is_full_pass(run), 'qualified': self.is_full_pass(run), 'unqualified_reasons': self.unqualified_reasons(run)}

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
        if index < 0 or index >= len(run['steps']): raise AppError('Unknown step index.')
        snapshot = self.snapshots.get(run_id)
        if run['status'] != 'running' or snapshot is None:
            raise AppError(f"This test run is {run['status']}; start a new run.")
        if index < run['next_step']:
            return {'step': run['steps'][index], 'status': self.status(owner, run_id), 'payload': self.payload(owner, run_id, run['steps'][index]['id'])}
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
            return {'step': run['steps'][index], 'status': self.status(owner, run_id), 'table': snapshot.get('tables', {}).get(run['steps'][index]['id']), 'payload': self.payload(owner, run_id, run['steps'][index]['id'])}
        finally:
            snapshot['lock'].release()

    def _execute(self, owner, run, index, snapshot):
        step, record = self.steps[index], run['steps'][index]
        conversation = step['conversation']
        if conversation:
            session = snapshot['sessions'].get(conversation)
            if session is None:
                session = snapshot['sessions'][conversation] = self.history.create(owner)
        else:
            session = self.history.create(owner)
        record['session'] = session
        started = monotonic()
        effective_date = date.fromisoformat(run['identity']['effective_date'])
        try:
            outcome = self.service.ask(self.history, owner, session, record['prompt'], step['view'], snapshot['views'], run['snapshot']['timestamp'], effective_date=effective_date)
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
        record['turn_id'] = outcome.get('turn_id')
        # Keep the public payload exactly as ordinary /api/ask returns it.
        from query_service import public_answer_payload
        if self.live:
            folder = self.artifacts / run['id'] / 'payloads'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (record['id'] + '.json')).write_text(json.dumps(jsonable(public_answer_payload(outcome))), encoding='utf-8')
        record['returned_plan'] = outcome.get('returned_plan')
        self._record_diagnostics(run, record, outcome.get('diagnostics') or {})
        ok, problems, variant = match_plan(outcome, step, run['witnesses'])
        record['interpretation'] = {'ok': ok, 'problems': problems, 'variant': jsonable({k: v for k, v in variant.items() if k != 'columns'})}
        if outcome['kind'] == 'clarify':
            record['clarification'] = outcome['question']
            record['suggestions'] = list(outcome.get('suggestions') or [])
            record['effective_plan'] = None
            if not ok:
                record['data'] = {'ok': False, 'checks': {'no_execution': False}, 'differences': [], 'counts': {}}
                record['status'] = 'fail'
                self._block_followups(run, index, 'An unexpected clarification left the conversation without the expected plan.')
                return
            verdict, semantic_problems = check_clarification(step, outcome)
            if step.get('clarification_subject') and verdict == 'pass':
                # New unsupported calculations require human semantic review,
                # until an explicit language predicate has been authored.
                verdict = 'review'
                semantic_problems.append('Review that the response explains why ' + step['clarification_subject'] + ' is unavailable.')
            record['interpretation']['clarification_check'] = {'verdict': verdict, 'problems': semantic_problems}
            record['interpretation']['problems'] = list(semantic_problems)
            record['interpretation']['ok'] = verdict == 'pass'
            record['data'] = {'ok': True, 'checks': {'no_execution': True}, 'differences': [], 'counts': {}}
            record['status'] = verdict
            if verdict == 'fail':
                self._block_followups(run, index, 'An earlier clarification of this conversation failed its check.')
            return
        table = outcome['table']
        snapshot['tables'] = {step['id']: table}
        record['effective_plan'] = outcome['plan']
        record['warnings'] = table.get('warnings', [])
        if step['expect']['intent'] == 'clarify':
            record['data'] = {'ok': False, 'checks': {'no_execution': False}, 'differences': [{'kind': 'executed', 'total_rows': table['total_rows']}], 'counts': {}}
            record['status'] = 'fail'
            record['result'] = self._result_summary(table, None)
            self._block_followups(run, index, 'A query executed where a clarification was expected.')
            return
        spec = reference_spec(step, variant, run['witnesses'])
        expected = evaluate(snapshot['reference'], spec)
        comparison = compare(expected, table)
        supporting_expected = None
        if spec['intent'] in ('metric', 'chart'):
            supporting_expected = evaluate_supporting(snapshot['reference'], spec)
            comparison['supporting'] = compare_supporting(supporting_expected, outcome)
            comparison['checks']['supporting_rows'] = comparison['supporting']['ok']
            comparison['ok'] = comparison['ok'] and comparison['checks']['supporting_rows']
        if step['expect']['intent'] == 'chart':
            chart = table.get('chart') or {}
            comparison['checks']['chart_spec'] = chart.get('type') == step['expect']['chart_type'] and set(chart.get('measures', [])) == set(spec['measures']) and list(chart.get('dimensions', [])) == list(spec['group'])
            comparison['ok'] = comparison['ok'] and comparison['checks']['chart_spec']
        record['data'] = jsonable(comparison)
        record['reference_spec'] = jsonable(spec)
        record['result'] = self._result_summary(table, expected)
        if supporting_expected is not None:
            views = (outcome.get('supporting') or {}).get('views') or {}
            record['result']['supporting'] = {view: self._result_summary(views[view], wanted)
                                               for view, wanted in supporting_expected.items()
                                               if isinstance(views.get(view), dict) and 'rows' in views[view]}
        record['status'] = 'pass' if ok and comparison['ok'] else 'fail'
        if record['status'] != 'pass':
            self._block_followups(run, index, 'An earlier turn of this conversation failed its interpretation or data check.')

    def _record_diagnostics(self, run, record, diagnostics):
        record['attempts'] = list(diagnostics.get('attempts') or [])
        record['recovered'] = bool(diagnostics.get('recovered'))
        record['planner_settings'] = diagnostics.get('settings')
        record['fallback_events'] = list(diagnostics.get('fallback_events') or [])
        planner = run['planner']
        if planner['settings'] is None and diagnostics.get('settings'):
            planner['settings'] = diagnostics['settings']
        for event in record['fallback_events']:
            if event not in planner['fallback_events']:
                planner['fallback_events'].append(event)
        if record['recovered']:
            planner['corrections'] += 1
            planner['recovered_steps'].append(record['id'])
        if diagnostics.get('prompt_digest') and planner.get('prompt_digest') in (None, 'unavailable'):
            planner['prompt_digest'] = diagnostics['prompt_digest']

    def _result_summary(self, table, expected):
        summary = {'columns': table['columns'], 'total_rows': table['total_rows'], 'preview_rows': len(table['rows']), 'truncated': table['truncated'],
                   'result_digest': table.get('result_digest'), 'totals': table.get('totals'), 'chart': table.get('chart'), 'rows': table['rows'][:10],
                   'rows_checked': len(table['rows'])}
        if expected is not None:
            summary['expected'] = {'total_rows': expected['total'], 'digest': expected['digest'], 'totals': jsonable(expected['totals']), 'rows': jsonable(expected['rows'][:10]), 'columns': expected['columns']}
        return summary

    def _block_followups(self, run, index, reason):
        conversation = self.steps[index]['conversation']
        if not conversation:
            return
        for later in range(index + 1, len(self.steps)):
            if self.steps[later]['conversation'] == conversation and run['steps'][later]['status'] == 'pending':
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
        if any(not s.get('png') or s.get('ui') is None for s in run.get('scenarios', [])):
            return False
        return all(s['status'] != 'pending' for s in run['steps']) and all(b['status'] != 'pending' for b in run['browser'])

    def unqualified_reasons(self, run):
        reasons = []
        for scenario in run.get('scenarios', []):
            if not scenario.get('png') or not scenario.get('ui') or scenario['ui'].get('status') != 'pass' or scenario.get('visual_review') != 'pass':
                reasons.append('Scenario evidence or visual review incomplete: ' + scenario['id'])
        if run['snapshot'].get('source')=='postgres' and not run.get('identity',{}).get('source_contract_verified',False):
            reasons.append('live source amount/currency mapping and extraction grain have not been independently verified; confirm them before setting B2B_SOURCE_CONTRACT_VERIFIED=true')
        if not run['snapshot'].get('canonical_parity', False):
            reasons.append('canonical parity failed (application grains differ from the reference grains)')
        if run['scope'] != 'full':
            reasons.append(f"scope is {run['scope']}, not a full run")
        if run['status'] != 'complete':
            reasons.append(f"run status is {run['status']}")
        failing = [s['id'] for s in run['steps'] if s['status'] != 'pass']
        if failing:
            reasons.append(f"{len(failing)} step(s) not passing: {', '.join(failing[:12])}{'…' if len(failing) > 12 else ''}")
        checks = [str(b['id']) for b in run['browser'] if b['status'] != 'pass']
        if checks:
            reasons.append(f"{len(checks)} browser check(s) not passing: {', '.join(checks)}")
        return reasons

    def is_full_pass(self, run):
        return not self.unqualified_reasons(run)

    def payload(self, owner, run_id, step_id):
        record = self.detail(owner, run_id, step_id)
        if record is None: raise AppError('Unknown test step.')
        path = self.artifacts / run_id / 'payloads' / (record['id'] + '.json')
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def test_session(self, owner, run_id, session_id, turn_id):
        run = self._load(owner, run_id)
        if not any(s.get('session') == session_id and s.get('turn_id') == turn_id for s in run['steps']):
            raise AppError('Unknown test answer.')
        return self.history

    def save_evidence(self, owner, run_id, scenario_id, png):
        from evidence import validate_png
        run = self._load(owner, run_id)
        scenario = next((s for s in run.get('scenarios', []) if s['id'] == scenario_id), None)
        if scenario is None: raise AppError('Unknown scenario.')
        if any(s['status'] == 'pending' for s in run['steps'] if s.get('scenario_id') == scenario_id):
            raise AppError('Scenario has unfinished prompts.')
        width, height = validate_png(png)
        folder = self.artifacts / run_id
        folder.mkdir(parents=True, exist_ok=True)
        filename = f"{scenario['number']:03d}-{scenario_id}.png"
        temporary = folder / (filename + '.tmp')
        temporary.write_bytes(png)
        replace_evidence(temporary, folder / filename)
        scenario['png'] = {'file': filename, 'bytes': len(png), 'width': width, 'height': height, 'sha256': hashlib.sha256(png).hexdigest()}
        self._finish_if_complete(run, run_id)
        self._save_scenarios(run)
        # The run JSON is durable after every image. Materialize the larger
        # review bundle at completion, not 200 times during capture.
        if self.is_complete(run): self.write_review_files(owner, run_id)
        return self.status(owner, run_id)

    def record_scenario(self, owner, run_id, scenario_id, observation):
        run = self._load(owner, run_id)
        scenario = next((s for s in run.get('scenarios', []) if s['id'] == scenario_id), None)
        if scenario is None: raise AppError('Unknown scenario.')
        scenario['ui'] = observation
        self._finish_if_complete(run, run_id)
        self._save_scenarios(run)
        return self.status(owner, run_id)

    def _save_scenarios(self, run):
        folder = self.artifacts / run['id']
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / 'scenarios.tmp'
        temp.write_text(json.dumps(jsonable(run['scenarios'])), encoding='utf-8')
        replace_evidence(temp, folder / 'scenarios.json')
        self._cached_runs[run['id']] = run
        if run['status'] == 'complete': self._save(run)

    def review(self, owner, run_id, start=0, size=10):
        run = self._load(owner, run_id)
        scenarios = run.get('scenarios', [])[start:start + size]
        ids = {s['id'] for s in scenarios}
        steps = []
        for s in run['steps']:
            if s.get('scenario_id') not in ids: continue
            compact = {k: s.get(k) for k in ('id','scenario_id','turn_number','prompt','status','expected','interpretation','returned_plan','effective_plan','clarification','error','recovered','result')}
            data = s.get('data') or {}
            compact['data'] = {k: data.get(k) for k in ('ok','checks','counts','differences')}
            steps.append(compact)
        return {'run_id': run_id, 'identity': run['identity'], 'counts': self.counts(run),
                'scenario_count': len(run.get('scenarios', [])), 'scenarios': scenarios,
                'steps': steps,
                'visual_review': 'Pending human review; automated checks do not establish visual correctness.'}

    def write_review_files(self, owner, run_id):
        folder = self.artifacts / run_id
        (folder / 'manifest.json').write_text(json.dumps(jsonable(self.review(owner, run_id, 0, 200)), indent=2), encoding='utf-8')
        (folder / 'report.md').write_text(self.report(owner, run_id), encoding='utf-8')

    def _finish_if_complete(self, run, run_id):
        if run['status'] == 'running' and self.is_complete(run):
            run['status'], run['finished_at'] = 'complete', now()
            run['qualified'] = self.is_full_pass(run)
            run['unqualified_reasons'] = self.unqualified_reasons(run)
            self.snapshots.pop(run_id, None)

    # ----- qualification and comparison -----
    def identity_of(self, run):
        return {k: run['identity'].get(k) for k in IDENTITY_KEYS}

    def qualification(self, owner):
        """Three consecutive complete full passes with identical identity; older-format runs never count."""
        runs = [r for r in self.list_runs(owner) if r['scope'] == 'full' and r['status'] not in ('running',)]
        streak, reason = 0, 'No complete run yet.'
        latest_identity = None
        for run in runs:
            identity = self.identity_of(run)
            if identity.get('suite_version') != self.suite_version:
                reason = 'The latest completed run uses a different suite version; run the current suite.'
                break
            if run.get('report_version') != REPORT_VERSION or any(identity.get(k) is None for k in IDENTITY_KEYS):
                reason = 'An earlier run was produced by an older suite, evaluator, or report version and does not count toward this release sequence.'
                break
            if latest_identity is None:
                latest_identity = identity
            if identity != latest_identity:
                reason = 'An earlier run used a different source, app revision, suite, evaluator, rules, model configuration, prompt, or effective date; the sequence restarted.'
                break
            if not self.is_full_pass(run):
                reason = f"Run {run['id'][:8]} is {run['status']} with {sum(1 for s in run['steps'] if s['status'] != 'pass')} steps and {sum(1 for b in run['browser'] if b['status'] != 'pass')} browser checks not passing."
                break
            streak += 1
            if streak >= 3:
                reason = 'Three consecutive complete passes with matching source, app revision, suite, evaluator, rules, model configuration, prompt, and effective date.'
                break
        return {'ready': streak >= 3, 'streak': min(streak, 3), 'required': 3, 'reason': reason, 'identity': latest_identity}

    def comparison(self, owner, run):
        """Compare with the previous run over mutually executed cases only; other cases are new or lost coverage."""
        previous = next((r for r in self.list_runs(owner) if r['id'] != run['id'] and r['started_at'] < run['started_at']), None)
        if previous is None:
            return None
        before = {s['id']: s for s in previous['steps']}
        outcome = {'previous_run': previous['id'], 'previous_started_at': previous['started_at'], 'previous_report_version': previous.get('report_version', 'report-1'),
                   'newly_failing': [], 'fixed': [], 'inconsistent': [], 'changed_results': [], 'latency': [], 'changes': {}, 'new_coverage': [], 'lost_coverage': [], 'compared': 0}
        for step in run['steps']:
            old = before.get(step['id'])
            if not old:
                continue
            executed_now, executed_before = step['status'] in EXECUTED_STATES, old['status'] in EXECUTED_STATES
            if executed_now and not executed_before:
                outcome['new_coverage'].append(step['id'])
                continue
            if executed_before and not executed_now:
                outcome['lost_coverage'].append(step['id'])
                continue
            if not (executed_now and executed_before):
                continue
            outcome['compared'] += 1
            if step['status'] in ('fail', 'error') and old['status'] == 'pass':
                outcome['newly_failing'].append(step['id'])
            elif step['status'] == 'pass' and old['status'] in ('fail', 'error', 'review'):
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
        outcome['same_sequence'] = self.identity_of(run) == self.identity_of(previous) and run['scope'] == 'full' and previous['scope'] == 'full' and previous.get('report_version') == REPORT_VERSION
        return outcome

    # ----- report -----
    def report(self, owner, run_id):
        run = self._load(owner, run_id)
        identity, snapshot = run['identity'], run['snapshot']
        model = identity['model_config']
        lines = [f"# B2B acceptance test run {run['id']}", '',
                 f"Suite {identity['suite_version']} · app {identity['app_revision']} · evaluator {identity['evaluator_version']} · digest {identity.get('digest_version', DIGEST_VERSION)} · report {run.get('report_version', 'report-1')} · status **{run['status']}** · scope {run['scope']}", '',
                 '## Run identity and source', '',
                 md_table(['Item', 'Value'], [['Run id', run['id']], ['Started', run['started_at']], ['Finished', run.get('finished_at') or 'not finished'], ['Effective date (frozen for every prompt)', identity['effective_date']],
                          ['App version / revision', f"{identity['app_version']} / {identity['app_revision']}"], ['Suite version', identity['suite_version']], ['Evaluator / digest / fingerprint versions', f"{identity['evaluator_version']} / {identity.get('digest_version', '')} / {identity['fingerprint_version']}"],
                          ['Business-rule digest', identity['rules_digest']], ['Planner prompt digest', identity.get('prompt_digest', '')],
                          ['Model', f"{model['provider']} · {model['model']} · {model['endpoint_host']}:{model['endpoint_port']}"],
                          ['Configured model settings', f"temperature {model['temperature']}, max tokens {model['max_tokens']}, structured output {model['structured_output']}, streaming {model.get('stream')}, timeout {model.get('timeout_seconds')} s"],
                          ['Actual request settings (first accepted reply)', json.dumps(run.get('planner', {}).get('settings'), ensure_ascii=False) if run.get('planner', {}).get('settings') else 'not observed'],
                          ['Provider fallback events', '; '.join(run.get('planner', {}).get('fallback_events') or []) or 'none'],
                          ['Correction attempts used', f"{run.get('planner', {}).get('corrections', 0)} (recovered steps: {', '.join(run.get('planner', {}).get('recovered_steps') or []) or 'none'})"],
                          ['Source', f"{snapshot['source']} · {snapshot['source_name']} (configured relation {snapshot['relation']})"], ['Snapshot timestamp', snapshot['timestamp']],
                          ['Retained snapshot', snapshot.get('retained_snapshot') or 'not retained'],
                          ['Raw rows / excluded', f"{snapshot['raw_rows']} / {snapshot['excluded_rows']}"], ['Distinct opportunities', snapshot['opportunities']], ['Distinct opportunity/SKU pairs', snapshot['opportunity_sku_pairs']],
                          ['Currency distribution (SKU rows)', ', '.join(f'{k}: {v}' for k, v in snapshot['currencies'].items()) or 'none'],
                          ['Raw fingerprint', snapshot['fingerprints']['raw']], ['Reference grain digests', f"sku {snapshot['fingerprints']['reference_sku']} · opportunity {snapshot['fingerprints']['reference_opportunity']}"],
                          ['App grain digests', f"sku {snapshot['fingerprints']['app_sku']} · opportunity {snapshot['fingerprints']['app_opportunity']}"], ['Canonical parity (app = reference)', 'yes' if snapshot.get('canonical_parity') else '**NO — run unqualified**'],
                          ['Run completeness', 'complete' if self.is_complete(run) else 'partial']]), '']
        if snapshot['normalization_warnings']:
            lines += ['Normalization warnings:', ''] + [f'- {md(w)}' for w in snapshot['normalization_warnings']] + ['']
        if run['notes']:
            lines += ['Notes:', ''] + [f'- {md(n)}' for n in run['notes']] + ['']
        lines += self._parity_section(snapshot.get('parity'))
        lines += ['Substituted witnesses:', '', md_table(['Placeholder', 'Value'], [[k, v] for k, v in run['witnesses'].items()]), '']
        # Scorecard and status accounting
        steps = run['steps']
        counts = self.counts(run)
        interp = {'pass': sum(1 for s in steps if (s.get('interpretation') or {}).get('ok')), 'fail': sum(1 for s in steps if s.get('interpretation') and not s['interpretation'].get('ok'))}
        data = {'pass': sum(1 for s in steps if (s.get('data') or {}).get('ok')), 'fail': sum(1 for s in steps if s.get('data') and not s['data'].get('ok'))}
        browser = {'pass': counts['browser_passed'], 'fail': counts['browser_failed']}
        blocked_steps = [s for s in steps if s['status'] in ('blocked', 'not_applicable')]
        pending = [s for s in steps if s['status'] == 'pending']
        blocked_checks = [b for b in run['browser'] if b['status'] in ('blocked', 'pending')]
        qualification = self.qualification(owner)
        lines += ['## Scorecard', '', md_table(['Dimension', 'Passed', 'Failed', 'Review', 'Blocked or not run'],
                  [['Interpretation', interp['pass'], interp['fail'], counts['review'], len(blocked_steps) + len(pending)], ['Data correctness', data['pass'], data['fail'], '', len(blocked_steps) + len(pending)],
                   ['Browser presentation', browser['pass'], browser['fail'], '', len(blocked_checks)]]), '',
                  md_table(['Step state', 'Count'], [[state, counts['by_state'][state]] for state in STEP_STATES] + [['total accounted', f"{sum(counts['by_state'].values())} of {counts['total']}"]]), '',
                  'Full pass: **' + ('yes' if self.is_full_pass(run) else 'no') + '**. Delivery gate: ' + ('**Ready for review**' if qualification['ready'] else f"{qualification['streak']} of 3 consecutive passes") + ' — ' + md(qualification['reason']), '']
        lines += ['### Step status accounting', '', md_table(['Step', 'Title', 'Conversation', 'Status', 'Interpretation', 'Data', 'Attempts', 'Reason'],
                  [[s['id'], s['title'], s['conversation'] or '', s['status'], 'pass' if (s.get('interpretation') or {}).get('ok') else ('fail' if s.get('interpretation') else ''),
                    'pass' if (s.get('data') or {}).get('ok') else ('fail' if s.get('data') else ''), self._attempts_label(s), s.get('error') or ('; '.join((s.get('interpretation') or {}).get('problems') or []))] for s in steps]), '']
        failed = [s for s in steps if s['status'] in ('fail', 'error', 'review')]
        if failed or blocked_steps or pending or blocked_checks or browser['fail']:
            lines += ['### Failed, review, and blocked checks', '']
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
        lines += ['## Browser checks', '', 'Checks run against the production renderer; expected values are recomputed in the browser from the payload, independently of the renderer.', '']
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
            lines += [md_table(['Item', 'Value'], [['Previous run', f"{comparison['previous_run']} started {comparison['previous_started_at']} ({comparison['previous_report_version']})"],
                      ['Mutually executed cases compared', comparison['compared']], ['New coverage (executed now, not before)', ', '.join(comparison['new_coverage']) or 'none'],
                      ['Lost coverage (executed before, not now)', ', '.join(comparison['lost_coverage']) or 'none'], ['Newly failing', ', '.join(comparison['newly_failing']) or 'none'],
                      ['Fixed', ', '.join(comparison['fixed']) or 'none'], ['Inconsistent', ', '.join(comparison['inconsistent']) or 'none'], ['Result changes (digest)', ', '.join(comparison['changed_results']) or 'none'],
                      ['Latency differences (>= 1 s)', '; '.join(comparison['latency']) or 'none'], ['Source, prompt, rule, app, evaluator, or model-setting changes', json.dumps(comparison['changes'], ensure_ascii=False) if comparison['changes'] else 'none'],
                      ['Eligible for the same three-pass sequence', 'yes' if comparison['same_sequence'] else 'no']]), '']
        # Release decision and coverage limitations
        lines += ['## Release decision', '',
                  f"This run is **{'qualified' if self.is_full_pass(run) else 'not qualified'}**" + ('' if self.is_full_pass(run) else ': ' + md('; '.join(self.unqualified_reasons(run)))) + '.',
                  f"Delivery requires three consecutive qualified full runs with identical identity ({', '.join(IDENTITY_KEYS)}); this run is number {qualification['streak']} of 3 in the current sequence." if self.is_full_pass(run) else 'Replay, partial, and failed-case reruns are diagnostic only.', '',
                  '### Coverage limitations', '']
        limitations = [f"{s['id']} {s['title']}: {s.get('error')}" for s in blocked_steps]
        limitations += [f"Step {s['id']} was recovered by one correction attempt (first reply rejected)." for s in steps if s.get('recovered')]
        limitations += [f"Step {s['id']} needs manual review of its clarification wording." for s in steps if s['status'] == 'review']
        limitations.append('Conditions absent from the live source (mixed currencies, more than 30 chart groups, malformed values) are covered by development fixtures and synthetic browser checks only; they are not live-source coverage.')
        lines += [f'- {md(item)}' for item in limitations] + ['']
        lines += ['## Review instructions', '',
                  'Recompute every expected value from the local CSV with the reference rules below and compare with the per-case expected counts, totals, digests, and rows. The accepted $0.44 CSV-versus-SQL difference applies to the CSV source comparison only, never to application-versus-evaluator comparisons of the same snapshot.', '',
                  f"- Fingerprint {identity['fingerprint_version']}: for each raw row, trim spaces from every value and turn blanks into null; JSON-encode the {len(FINGERPRINT_FIELDS)} values in the order below; SHA-256 each row; sort the hex digests; SHA-256 the newline-joined list. Duplicate rows keep their multiplicity and row order does not matter.",
                  '- Fingerprint field order: ' + ', '.join(FINGERPRINT_FIELDS) + '.',
                  f"- Result digest {DIGEST_VERSION}: for each complete result row, turn each cell into a typed token (n:<exact decimal without trailing zeros> for numbers, d:<ISO date> for dates, b:true/b:false for flags, s:<text> for text and identifiers, null for null), JSON-encode the tokens in result column order, SHA-256 each row, sort, SHA-256 the newline-joined list.",
                  '- Text is trimmed of spaces (empty becomes null); numbers must match `^[+-]?[0-9]+(\\.[0-9]+)?$`; probability accepts an optional `%` and is divided by 100; dates are day-first `D/M/YYYY` with one- or two-digit day and month, or ISO `YYYY-MM-DD` text from typed database columns, and must be valid calendar dates; invalid values become null.',
                  '- Rows without opportunity number or product code are excluded. SKU rows sum quantity and additive opp_amount_converted per opportunity/product. Repeated amount_converted is the independent exported opportunity total, retained once for comparison with the line sum using the 0.01 rule. Currency validity is checked before amount aggregation. Channel memberships are preserved; Multiple channels is an explicit group, not an arbitrary selection. Other conflicting metadata is explained in quality details.',
                  '- Agreement with the reference calculator tests implementation, not source semantics. Live PostgreSQL qualification also requires independent verification of the amount/currency mapping and extraction grain (B2B_SOURCE_CONTRACT_VERIFIED).',
                  '- Stage groups: Won = Won, Rollout Started, Rollout Finished; Open = Identified, Qualified, Negotiation; Lost = Dropped, Lost.',
                  '- Filters apply after grain reduction; a product-level filter at opportunity grain selects whole opportunities. deal_size counts once per opportunity.', '',
                  'CSV header mapping (canonical field ← SQL column ← accepted export headers), generated from the data specification:', '',
                  md_table(['Canonical field', 'SQL column', 'Export header examples'], header_mapping()), '']
        return '\n'.join(lines) + '\n'

    def _attempts_label(self, step):
        attempts = step.get('attempts') or []
        if not attempts:
            return ''
        if step.get('recovered'):
            return f'{len(attempts)} (recovered)'
        return f'{len(attempts)}' + (' (first attempt)' if len(attempts) == 1 else '')

    def _parity_section(self, parity):
        if not parity:
            return []
        lines = ['### Canonical parity diagnostics', '']
        for grain in ('sku', 'opportunity'):
            part = parity.get(grain) or {}
            counts = part.get('counts') or {}
            lines += [f"{grain} grain: **{'match' if part.get('ok') else 'MISMATCH'}** — " + md(json.dumps(counts, ensure_ascii=False)), '']
            if part.get('examples'):
                lines += [f'First {len(part["examples"])} differences with raw-row context:', '', '```json', json.dumps(part['examples'], ensure_ascii=False, indent=1)[:12000], '```', '']
        return lines

    def _step_section(self, s):
        lines = [f"### {s['id']} {md(s['title'])} — **{s['status']}**", '',
                 md_table(['Item', 'Value'], [['Prompt', s.get('prompt') or '(not rendered)'], ['Layout selection', s['view']], ['Conversation', s['conversation'] or 'fresh conversation'],
                          ['Expected behavior', s.get('expected') or ''], ['Duration', f"{s['seconds']} s" if s.get('seconds') is not None else ''], ['Error', s.get('error') or ''],
                          ['Model attempts', self._attempts_label(s) or 'none'], ['Request settings', json.dumps(s.get('planner_settings'), ensure_ascii=False) if s.get('planner_settings') else ''],
                          ['Fallback events', '; '.join(s.get('fallback_events') or []) or 'none']]), '']
        for attempt in s.get('attempts') or []:
            lines += [f"Attempt {attempt.get('attempt')}: **{attempt.get('status')}**" + (' (correction)' if attempt.get('corrected') else '') + (f" in {attempt.get('seconds')} s" if attempt.get('seconds') is not None else '') + (' — ' + md(attempt.get('error')) if attempt.get('error') else ''), '']
            if attempt.get('reply_excerpt'):
                lines += ['```', str(attempt['reply_excerpt'])[:300].replace('```', "'''"), '```', '']
        if s.get('returned_plan') is not None:
            lines += ['Returned plan (Qwen, final attempt):', '', '```json', json.dumps(s['returned_plan'], ensure_ascii=False), '```', '']
        if s.get('clarification'):
            lines += [f"Clarification: {md(s['clarification'])}", '']
            if s.get('suggestions'):
                lines += ['Suggestions: ' + md('; '.join(s['suggestions'])), '']
        if s.get('effective_plan') is not None:
            lines += ['Effective merged plan:', '', '```json', json.dumps(s['effective_plan'], ensure_ascii=False), '```', '']
        interp = s.get('interpretation')
        if interp:
            lines += [f"Interpretation: **{'pass' if interp.get('ok') else ('review' if s['status'] == 'review' else 'fail')}**" + (' — ' + md('; '.join(interp.get('problems', []))) if interp.get('problems') else ''), '']
            if interp.get('variant', {}).get('note'):
                lines += [md(interp['variant']['note']), '']
        data, result = s.get('data'), s.get('result')
        if data:
            checks = ', '.join(f"{k}={'ok' if v else 'FAIL'}" for k, v in data.get('checks', {}).items())
            lines += [f"Data: **{'pass' if data.get('ok') else 'fail'}** — {md(checks)}", '']
            if data.get('scope'):
                scope = data['scope']
                lines += [f"Scope: {scope.get('preview_cells')} preview cells in {scope.get('preview_rows')} preview rows compared one by one; the complete result of {scope.get('complete_rows')} rows verified by {', '.join(scope.get('complete_verified_by', []))}.", '']
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
        if data and data.get('supporting'):
            evidence = data['supporting']
            checks = ', '.join(f"{key}={'ok' if value else 'FAIL'}" for key, value in evidence.get('checks', {}).items())
            lines += [f"Supporting rows: **{'pass' if evidence.get('ok') else 'fail'}** — {md(checks)}. Independently checked from the authored question's complete matching population.", '']
            for view, comparison in evidence.get('views', {}).items():
                checks = ', '.join(f"{key}={'ok' if value else 'FAIL'}" for key, value in comparison.get('checks', {}).items())
                summary = (result or {}).get('supporting', {}).get(view, {})
                wanted = summary.get('expected') or {}
                lines += [f"{view.capitalize()}: **{'pass' if comparison.get('ok') else 'fail'}** — {md(checks)}", '',
                          md_table(['Supporting evidence', 'Expected', 'Actual'], [
                              ['Complete row count', wanted.get('total_rows', ''), summary.get('total_rows', '')],
                              ['Full-result digest', wanted.get('digest', ''), summary.get('result_digest', '')],
                              ['Complete totals', json.dumps(wanted.get('totals'), ensure_ascii=False), json.dumps(summary.get('totals'), ensure_ascii=False)],
                              ['Rows checked cell by cell', wanted.get('total_rows', ''), summary.get('rows_checked', '')]]), '']
                if comparison.get('differences'):
                    lines += ['Supporting-row differences (first 20):', '', '```json', json.dumps(comparison['differences'], ensure_ascii=False, indent=1)[:8000], '```', '']
        if data and data.get('counts'):
            lines += ['Comparison counts: `' + json.dumps(data['counts'], ensure_ascii=False) + '`', '']
        if s.get('warnings'):
            lines += ['Warnings: ' + md('; '.join(s['warnings'])), '']
        return lines


EXPORT_HEADER_EXAMPLES = {
    'opportunity_no': 'Opportunity No.', 'product_code': 'Product Code', 'subsidiary_subsidiary_code': 'Subsidiary: Subsidiary Code / Subsidiary Code', 'opportunity_name': 'Opportunity Name',
    'end_customer': 'End Customer', 'gscm_product_group_new': 'GSCM Product Group (New)', 'pet_name': 'PET Name', 'stage': 'Stage', 'opportunity_owner': 'Opportunity Owner',
    'biz_focus': 'Biz Focus', 'business_location': 'Business Location', 'division': 'Division', 'sales_type_detail': 'Sales Type Detail', 'type': 'Type',
    'amount_converted_currency': 'Amount (converted) Currency', 'opp_amount_converted_currency': 'Opportunity Amount (converted) Currency', 'rollout_period_to': 'Rollout Period To',
    'rollout_period_from': 'Rollout Period From', 'first_channel': '1st Channel', 'comment': 'Comment / Comments', 'quantity': 'Quantity', 'amount_converted': 'Amount (converted)',
    'opp_amount_converted': 'Opportunity Amount (converted)', 'probability': 'Probability (%)', 'age': 'Age', 'deal_size_on_pricing_date_usd': 'Deal Size on Pricing Date (USD)',
    'close_month': 'Close Month', 'close_date': 'Close Date', 'created_date': 'Created Date', 'last_modified_date': 'Last Modified Date',
}


def header_mapping():
    """Canonical field, SQL column, and accepted export headers, generated from the data specification."""
    return [(name, column, EXPORT_HEADER_EXAMPLES.get(name, '')) for name, column, _ in SOURCE_FIELDS]


HEADER_MAPPING = header_mapping()
