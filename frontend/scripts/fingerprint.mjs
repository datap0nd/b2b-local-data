// Source fingerprint of the compiled frontend: sha256 over src/, index.html, vite/ts configs, and package-lock.json.
// `write` stores it in ../web/dist/.fingerprint next to the built assets; `check` verifies the committed assets match the source.
import {createHash} from 'node:crypto';
import {readdirSync, readFileSync, statSync, writeFileSync, existsSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const dist = join(root, '..', 'web', 'dist');
const inputs = ['index.html', 'package.json', 'package-lock.json', 'vite.config.ts', 'tsconfig.json'];

function walk(dir, out) {
  for (const entry of readdirSync(dir).sort()) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, out); else if (!/\.test\.tsx?$/.test(entry)) out.push(path);
  }
  return out;
}

export function fingerprint() {
  const hash = createHash('sha256');
  const files = [...inputs.map(f => join(root, f)).filter(existsSync), ...walk(join(root, 'src'), [])];
  // Line endings are normalized so a Windows checkout (CRLF) and a CI checkout (LF) fingerprint identically.
  for (const file of files) { hash.update(relative(root, file).replaceAll('\\', '/') + '\n'); hash.update(readFileSync(file, 'utf8').replaceAll('\r\n', '\n')); hash.update('\n'); }
  return 'sha256:' + hash.digest('hex');
}

const mode = process.argv[2];
if (mode === 'write') {
  writeFileSync(join(dist, '.fingerprint'), fingerprint() + '\n');
  console.log('frontend fingerprint written:', fingerprint());
} else if (mode === 'check') {
  const stored = existsSync(join(dist, '.fingerprint')) ? readFileSync(join(dist, '.fingerprint'), 'utf8').trim() : '(missing)';
  const current = fingerprint();
  if (stored !== current) { console.error(`Compiled frontend is stale: web/dist/.fingerprint ${stored} != source ${current}. Run npm run build in frontend/ and commit web/dist.`); process.exit(1); }
  console.log('compiled frontend matches its source:', current);
} else {
  console.log(fingerprint());
}
