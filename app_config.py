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
APP_VERSION = '0.2.0'
PLAN_VERSION = 1
SCHEMA_VERSION = 1


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
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
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
        aliases = {'RO_SQL_USER':'DB_USER', 'RO_SQL_PW':'DB_PASSWORD',
                   'LLM_API_URL':'AI_BASE_URL', 'LLM_API_KEY':'AI_API_KEY', 'LLM_MODEL_NAME':'AI_MODEL'}
        overrides = {}
        for layer in (read_env(home / '.env'), dict(os.environ)):
            for canonical, old in aliases.items():
                if canonical not in layer and old in layer:
                    layer[canonical] = layer[old]
            overrides.update(layer)
        values = read_env(ROOT / '.env.example') | overrides
        if 'LLM_API_URL' in overrides and 'AI_PROVIDER' not in overrides:
            values['AI_PROVIDER'] = 'openai_compatible'
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
        if self.get('DB_KIND','demo') not in ('demo','postgres'):
            raise AppError('This Salesforce replica uses PostgreSQL. Set DB_KIND=postgres or demo.')
        self.number('APP_PORT',8765,high=65535)
        for key in ('DB_SSL','B2B_ALLOW_LOCALHOST_IDENTITY'):
            self.flag(key,True)
        if self.get('DB_KIND') == 'postgres':
            self.postgres
        for key in ('B2B_RAW_TABLE','B2B_SKU_VIEW','B2B_OPPORTUNITY_VIEW','B2B_SCHEMA_VERSION_TABLE'):
            name = self.get(key)
            if name and (len(name.split('.')) != 2 or not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', part) for part in name.split('.'))):
                raise AppError(f'{key} must be a schema.table identifier.')


def verify_release(root=ROOT, inspect_environment=True):
    """Refuse a mixed code/contract/runtime/dependency release before launching the UI."""
    try:
        manifest = json.loads((root / 'release_manifest.json').read_text(encoding='utf-8-sig'))
        expected = {'app_version':APP_VERSION, 'query_plan_version':PLAN_VERSION, 'database_schema_version':SCHEMA_VERSION,
                    'python_tag':'cp313', 'platform':'win_amd64'}
        if any(manifest.get(k) != v for k,v in expected.items()):
            raise AppError('Release policy mismatch: code, query contract, schema, or ABI version differs. Rerun setup.ps1.')
        digest = hashlib.sha256((root / 'dependencies.lock.json').read_bytes()).hexdigest()
        if manifest.get('dependency_lock_sha256') != digest:
            raise AppError('Release dependency lock differs from its manifest. Rerun setup.ps1.')
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
