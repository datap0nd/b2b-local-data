"""Local settings and release compatibility checks; safe to import before dependencies."""
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import sysconfig
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
APP_VERSION = '0.5.0'
PLAN_VERSION = 1
# Version of the app's canonical data schema (the 30 raw Salesforce columns and their derived grains).
DATA_SCHEMA_VERSION = 2


class AppError(Exception):
    """A diagnostic that can be displayed without secrets or raw query errors."""


def read_env(path):
    values = {}
    if not path.exists():
        return values
    for index, raw in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise AppError(f'Invalid .env entry at line {index}.')
        if len(value) >= 2 and value[0] in '\"\'' and value[-1] == value[0]:
            value = value[1:-1]
        values[key] = value
    return values


@dataclass
class Settings:
    home: Path
    values: dict
    rules: str = ''

    @classmethod
    def load(cls, home):
        home = Path(home).resolve()
        # Precedence: a canonical name set in the environment, then in .env; only when a canonical name is set
        # nowhere are the data-governance variables already present on work PCs (DG_AI_API_URL, DG_AI_API_KEY,
        # DG_AI_MODEL, PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD) and the pre-0.3 names used, environment first.
        aliases = {'RO_SQL_USER':('PGUSER','DB_USER'), 'RO_SQL_PW':('PGPASSWORD','DB_PASSWORD'),
                   'LLM_API_URL':('LOCAL_AI_ENDPOINT','DG_AI_API_URL','AI_BASE_URL'), 'LLM_API_KEY':('LOCAL_AI_API_KEY','DG_AI_API_KEY','AI_API_KEY'),
                   'LLM_MODEL_NAME':('LOCAL_AI_MODEL','DG_AI_MODEL','AI_MODEL')}
        # Alias names are matched case-insensitively (local_ai_endpoint and LOCAL_AI_ENDPOINT are the same setting).
        file_layer, env_layer = read_env(home / '.env'), dict(os.environ)
        file_layer.update({k.upper(): v for k, v in list(file_layer.items()) if k.upper() != k and k.upper() not in file_layer})
        env_layer.update({k.upper(): v for k, v in list(env_layer.items()) if k.upper() != k and k.upper() not in env_layer})
        overrides = {}
        for layer in (file_layer, env_layer):
            overrides.update({k: v for k, v in layer.items() if v != '' or k not in overrides})
        derived_endpoint = False
        for canonical, olds in aliases.items():
            if overrides.get(canonical):
                continue
            for old in olds:
                value = env_layer.get(old) or file_layer.get(old)
                if value:
                    overrides[canonical] = value
                    derived_endpoint = derived_endpoint or (canonical == 'LLM_API_URL' and old in ('LOCAL_AI_ENDPOINT', 'DG_AI_API_URL'))
                    break
        if not overrides.get('PGURL') and overrides.get('PGHOST'):
            overrides['PGURL'] = f"{overrides['PGHOST']}:{overrides.get('PGPORT') or 5432}/{overrides.get('PGDATABASE') or 'postgres'}"
            # The data-governance connection does not verify server certificates; match it unless DB_SSL is set.
            if not overrides.get('DB_SSL'):
                overrides['DB_SSL'] = 'prefer'
        values = read_env(ROOT / '.env.example') | overrides
        if 'LLM_API_URL' in overrides and 'AI_PROVIDER' not in overrides:
            values['AI_PROVIDER'] = 'openai_compatible'
        if derived_endpoint and values.get('LLM_API_URL'):
            # The endpoint named by LOCAL_AI_ENDPOINT or data governance is already trusted on this PC; allow its host.
            host = urlsplit(values['LLM_API_URL'] if '://' in values['LLM_API_URL'] else 'http://' + values['LLM_API_URL']).hostname or ''
            allowed = {h.strip() for h in values.get('B2B_LLM_ALLOWED_HOSTS', '').split(',') if h.strip()}
            if host:
                allowed.add(host)
            values['B2B_LLM_ALLOWED_HOSTS'] = ','.join(sorted(allowed))
        if not values.get('DB_KIND'):
            values['DB_KIND'] = 'postgres' if values.get('PGURL') else 'demo'
        rules_path = home / 'business_rules.md'
        rules = (rules_path if rules_path.exists() else ROOT / 'config/business_rules.example.md').read_text(encoding='utf-8-sig')
        settings = cls(home, values, rules)
        settings.validate()
        return settings

    def get(self, key, default=''):
        return self.values.get(key, default)

    def number(self, key, default, low=1, high=100000):
        try:
            value = int(self.get(key) or default)
        except (ValueError, TypeError):
            raise AppError(f'{key} must be an integer.') from None
        if not low <= value <= high:
            raise AppError(f'{key} must be between {low} and {high}.')
        return value

    def flag(self, key, default=False):
        value = self.get(key, 'true' if default else 'false').lower()
        if value not in ('true', 'false'):
            raise AppError(f'{key} must be true or false.')
        return value == 'true'

    @property
    def data_dir(self):
        configured = self.get('B2B_DATA_DIR')
        if configured:
            return Path(configured).expanduser().resolve()
        return self.home / 'data'

    @property
    def csv_path(self):
        configured = self.get('B2B_CSV_PATH')
        if not configured:
            raise AppError('DB_KIND=csv requires B2B_CSV_PATH, an absolute path or a path relative to the .env folder.')
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else self.home / path).resolve()

    @property
    def source_label(self):
        kind = self.get('DB_KIND', 'demo')
        if kind == 'demo':
            return 'Fictional sample data'
        if kind == 'csv':
            return 'CSV file ' + self.csv_path.name
        return 'PostgreSQL ' + (self.get('B2B_RAW_TABLE') or 'bi_reporting.b2b_project')

    @property
    def postgres(self):
        raw = self.get('PGURL')
        if not raw:
            return {'host':self.get('DB_HOST'), 'port':self.number('DB_PORT',5432,high=65535), 'database':self.get('DB_NAME')}
        try:
            parsed = urlsplit(raw if '://' in raw else 'postgresql://' + raw)
            if parsed.scheme not in ('postgres','postgresql') or not parsed.hostname or not parsed.path.strip('/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError
            return {'host':parsed.hostname, 'port':parsed.port or 5432, 'database':parsed.path.lstrip('/')}
        except ValueError:
            raise AppError('PGURL must be host:port/database; use RO_SQL_USER and RO_SQL_PW separately.') from None

    def validate(self):
        if self.get('DB_KIND','demo') not in ('demo','postgres','csv'):
            raise AppError('Set DB_KIND=postgres for the Salesforce replica, csv for a local export, or demo for fictional data.')
        self.number('APP_PORT',8765,high=65535)
        self.flag('B2B_ALLOW_LOCALHOST_IDENTITY',True)
        if (self.get('DB_SSL') or 'true').lower() not in ('true','false','prefer'):
            raise AppError('DB_SSL must be true (verified TLS), prefer (TLS without certificate checks, plain fallback), or false.')
        if self.get('DB_KIND') == 'postgres':
            self.postgres
        if self.get('DB_KIND') == 'csv':
            self.csv_path
        name = self.get('B2B_RAW_TABLE')
        if name and (len(name.split('.')) != 2 or not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', part) for part in name.split('.'))):
            raise AppError('B2B_RAW_TABLE must be a schema.table identifier.')


def verify_release(root=ROOT, inspect_environment=True):
    """Refuse a mixed code/contract/runtime/dependency release before launching the UI."""
    try:
        manifest = json.loads((root / 'release_manifest.json').read_text(encoding='utf-8-sig'))
        expected = {'app_version':APP_VERSION, 'query_plan_version':PLAN_VERSION, 'data_schema_version':DATA_SCHEMA_VERSION,
                    'python_tag':'cp313', 'platform':'win_amd64'}
        if any(manifest.get(k) != v for k,v in expected.items()):
            raise AppError('Release policy mismatch: code, query contract, data schema, or ABI version differs. Rerun setup.ps1.')
        digest = hashlib.sha256((root / 'dependencies.lock.json').read_bytes()).hexdigest()
        if manifest.get('dependency_lock_sha256') != digest:
            raise AppError('Release dependency lock differs from its manifest. Rerun setup.ps1.')
        for name in ('runtime.lock.json','portable_assets.lock.json'):
            if manifest.get(name.replace('.json','').replace('.','_')+'_sha256') != hashlib.sha256((root/name).read_bytes()).hexdigest():
                raise AppError('Portable download locks differ from this release. Rerun setup.ps1.')
        packages = json.loads((root / 'dependencies.lock.json').read_text(encoding='utf-8-sig'))['packages']
        locked = {item['name'].lower().replace('_','-'):item['version'] for item in packages}
        if manifest.get('dependencies') != locked:
            raise AppError('Release dependency versions do not match the lock.')
        if inspect_environment:
            if sys.version_info[:2] != (3,13) or sys.platform != 'win32' or sysconfig.get_platform() != 'win-amd64':
                raise AppError('This release requires portable Python 3.13 for Windows x64. Run setup.ps1 and start.ps1.')
            installed = {dist.metadata['Name'].lower().replace('_','-'):dist.version for dist in importlib.metadata.distributions(path=[str(root / 'vendor')])}
            if any(installed.get(name) != version for name,version in locked.items()):
                raise AppError('Local vendor dependencies are missing or incompatible. Run setup.ps1; no pip is required.')
        return manifest
    except AppError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise AppError('Release manifest is missing or invalid. Rerun setup.ps1.') from None
