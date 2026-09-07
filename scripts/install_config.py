"""Bounded, reversible install-folder configuration updates; no optional dependencies.

Never print configuration contents. Backups remain local to the installation and
can be restored with --rollback while the migrated files are still unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[1]
KEY = 'B2B_ENABLE_ACCEPTANCE_UI'
TARGETS = ('.env', 'business_rules.md')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def known_shipped_rules(raw, release=ROOT):
    """Only entire, recorded shipped defaults qualify; local additions do not."""
    text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    registry = json.loads((Path(release) / 'config/shipped_business_rules.json').read_text(encoding='utf-8'))
    return digest(text.encode('utf-8')) in {entry['sha256'] for entry in registry['versions']}


def enable_test_if_missing(raw):
    """Append only; retain every existing byte, including BOM and secret values."""
    text = raw.decode('utf-8-sig')
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, _ = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key.strip()):
            raise ValueError(f'Invalid .env entry at line {number}; configuration was not changed.')
        if key.strip().upper() == KEY:
            return raw
    match = re.search(r'\r\n|\r|\n', text)
    newline = (match.group() if match else '\r\n').encode('ascii')
    separator = b'' if not text or text.endswith(('\r', '\n')) else newline
    return raw + separator + KEY.encode('ascii') + b'=true' + newline


def contained(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Configuration path leaves the installation.')
    return target


def transaction_path(root, transaction):
    if not re.fullmatch(r'[a-f0-9]{32}', transaction):
        raise ValueError('Invalid configuration transaction identifier.')
    return contained(root, '.config-backups/' + transaction)


def atomic_write(target, raw):
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.pending')
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def migrate(root, release, transaction):
    root, release = Path(root).resolve(), Path(release).resolve()
    backup = transaction_path(root, transaction)
    # Plan and validate all changes before creating backups or touching config.
    changes = []
    for name, template in (('.env', '.env.example'), ('business_rules.md', 'config/business_rules.example.md')):
        target = contained(root, name)
        old = target.read_bytes() if target.exists() else None
        if name == '.env':
            new = enable_test_if_missing(old if old is not None else (release / template).read_bytes())
        else:
            new = (release / template).read_bytes() if old is None or known_shipped_rules(old, release) else old
        if old != new:
            changes.append((name, target, old, new))
    backup.mkdir(parents=True, exist_ok=False)
    records = []
    for name, _, old, new in changes:
        if old is not None:
            (backup / (name + '.before')).write_bytes(old)
        records.append({'name': name, 'existed': old is not None,
                        'before_sha256': digest(old) if old is not None else None,
                        'after_sha256': digest(new)})
    (backup / 'manifest.json').write_text(json.dumps({'version': 1, 'files': records}, indent=2) + '\n', encoding='utf-8')
    try:
        for _, target, _, new in changes:
            atomic_write(target, new)
    except BaseException:
        restore(root, transaction)
        raise
    return [record['name'] for record in records]


def restore(root, transaction):
    root = Path(root).resolve()
    backup = transaction_path(root, transaction)
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1:
        raise ValueError('Unsupported configuration backup.')
    actions = []
    for record in manifest['files']:
        name = record['name']
        if name not in TARGETS:
            raise ValueError('Invalid configuration backup target.')
        target = contained(root, name)
        current = target.read_bytes() if target.exists() else None
        before = (contained(root, '.config-backups/' + transaction + '/' + name + '.before').read_bytes()
                  if record['existed'] else None)
        if before is not None and digest(before) != record['before_sha256']:
            raise ValueError('Configuration backup checksum mismatch.')
        if current == before:
            continue  # Includes a partially applied transaction and repeated restore.
        if current is None or digest(current) != record['after_sha256']:
            raise ValueError('Configuration changed after setup; restore requires manual review of the local backup.')
        actions.append((target, before))
    for target, before in actions:
        if before is None:
            target.unlink()
        else:
            atomic_write(target, before)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--release', type=Path, default=ROOT)
    parser.add_argument('--transaction', required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        if args.rollback:
            restore(args.home, args.transaction)
            print('Previous local configuration restored.')
        else:
            names = migrate(args.home, args.release, args.transaction)
            print('Local configuration checked; ' + str(len(names)) + ' file(s) updated. Backups retained in .config-backups.')
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f'Configuration migration failed: {error}\n')
