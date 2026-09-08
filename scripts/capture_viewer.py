"""Local-PC capture-card recorder. No work-PC execution or network binding.

Run with this PC's Python: python scripts/capture_viewer.py
Open the printed loopback URL in Chrome. Stop & save produces a WebM under
this checkout's test-results/recordings. Interrupted chunks are recoverable.
"""
import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from urllib.parse import urlsplit
import uuid
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_CHUNK = 16 * 1024 * 1024
MAX_RECORDING = 50 * 1024 * 1024 * 1024


class Recordings:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def folder(self, recording):
        if not re.fullmatch(r'[0-9a-f]{32}', recording): raise ValueError('Unknown recording.')
        folder = self.root / recording
        if not (folder / 'manifest.json').is_file(): raise ValueError('Unknown recording.')
        return folder

    def read(self, recording):
        return json.loads((self.folder(recording) / 'manifest.json').read_text())

    def write(self, folder, manifest):
        temp = folder / 'manifest.tmp'
        temp.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        temp.replace(folder / 'manifest.json')

    def start(self, metadata):
        if metadata.get('device') != 'UGREEN-25854' or metadata.get('mime') not in ('video/webm', 'video/webm;codecs=vp8', 'video/webm;codecs=vp9'):
            raise ValueError('Expected video-only UGREEN WebM capture.')
        if len(json.dumps(metadata)) > 4096: raise ValueError('Recording metadata exceeds 4 KiB.')
        recording = uuid.uuid4().hex
        folder = self.root / recording
        folder.mkdir()
        manifest = {'id': recording, 'status': 'recording', 'started_at': time.time(), 'chunks': [], 'bytes': 0, 'metadata': metadata}
        self.write(folder, manifest)
        return manifest

    def chunk(self, recording, index, body):
        if not body or len(body) > MAX_CHUNK: raise ValueError('Chunk must be 1 byte to 16 MiB.')
        with self.lock:
            manifest = self.read(recording)
            digest = hashlib.sha256(body).hexdigest()
            if 0 <= index < len(manifest['chunks']):
                if manifest['chunks'][index]['sha256'] != digest: raise ValueError('Conflicting retry.')
                return {'next': len(manifest['chunks'])}
            if index != len(manifest['chunks']) or manifest['status'] != 'recording': raise ValueError('Out-of-order chunk or finalized recording.')
            if manifest['bytes'] + len(body) > MAX_RECORDING: raise ValueError('Recording exceeds 50 GiB; stop and begin a new recording.')
            if shutil.disk_usage(self.root).free < len(body) + 256 * 1024 * 1024: raise ValueError('Insufficient free space to retain recording.')
            if index == 0 and not body.startswith(b'\x1aE\xdf\xa3'): raise ValueError('Missing WebM header.')
            folder = self.folder(recording)
            path = folder / f'{index:06d}.chunk'
            temp = path.with_suffix('.tmp'); temp.write_bytes(body); temp.replace(path)
            manifest['chunks'].append({'index': index, 'bytes': len(body), 'sha256': digest})
            manifest['bytes'] += len(body)
            self.write(folder, manifest)
            return {'next': index + 1}

    def finish(self, recording):
        with self.lock:
            manifest = self.read(recording)
            if manifest['status'] == 'saved': return manifest
            if not manifest['chunks']: raise ValueError('No video chunks have arrived.')
            folder = self.folder(recording)
            if shutil.disk_usage(folder).free < manifest['bytes'] + 128 * 1024 * 1024: raise ValueError('Insufficient free space to assemble WebM; chunks retained.')
            temporary = folder / 'capture.webm.tmp'
            with temporary.open('wb') as output:
                for chunk in manifest['chunks']:
                    data = (folder / f"{chunk['index']:06d}.chunk").read_bytes()
                    if hashlib.sha256(data).hexdigest() != chunk['sha256']: raise ValueError('Chunk integrity check failed.')
                    output.write(data)
            temporary.replace(folder / 'capture.webm')
            manifest.update(status='saved', finished_at=time.time(), path=str(folder / 'capture.webm'))
            self.write(folder, manifest)
            return manifest

    def list(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob('*/manifest.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]]


def make_server(root=ROOT / 'test-results' / 'recordings', port=0):
    recordings = Recordings(root)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass

        def reply(self, code, value, mime='application/json'):
            body = json.dumps(value).encode() if mime == 'application/json' else value
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; media-src blob:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)

        def allowed(self):
            host = f'127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == host and self.headers.get('Origin', 'http://' + host) == 'http://' + host
                    and secrets.compare_digest(self.headers.get('X-Capture-Token', ''), token))

        def do_GET(self):
            path = urlsplit(self.path).path
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}': return self.reply(403, {'error': 'Loopback only.'})
            if path == '/': return self.reply(200, (ROOT / 'scripts/capture_viewer.html').read_bytes(), 'text/html; charset=utf-8')
            if path == '/viewer.js': return self.reply(200, (ROOT / 'scripts/capture_viewer.js').read_bytes(), 'text/javascript')
            if path == '/recordings' and self.allowed(): return self.reply(200, recordings.list())
            self.reply(404, {'error': 'Not found.'})

        def do_POST(self):
            if not self.allowed(): return self.reply(403, {'error': 'Local viewer authorization required.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 <= length <= MAX_CHUNK: raise ValueError('Request exceeds 16 MiB.')
                self.connection.settimeout(30)
                body = self.rfile.read(length)
                if len(body) != length: raise ValueError('Incomplete request.')
                path = urlsplit(self.path).path
                if path == '/recordings': result = recordings.start(json.loads(body))
                elif match := re.fullmatch(r'/recordings/([0-9a-f]{32})/chunks/(\d{1,8})', path): result = recordings.chunk(match[1], int(match[2]), body)
                elif match := re.fullmatch(r'/recordings/([0-9a-f]{32})/finish', path): result = recordings.finish(match[1])
                else: return self.reply(404, {'error': 'Not found.'})
                self.reply(200, result)
            except (ValueError, OSError, KeyError) as error: self.reply(400, {'error': str(error)})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server, token


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--open-chrome', action='store_true', help='Open the viewer in the locally installed Chrome browser.')
    args = parser.parse_args()
    server, token = make_server(port=args.port)
    url = f'http://127.0.0.1:{server.server_port}/#{token}'
    print(url, flush=True)
    if args.open_chrome:
        import os
        candidates = [Path(os.environ.get(key, '')) / 'Google/Chrome/Application/chrome.exe' for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        chrome = next((p for p in candidates if p.is_file()), None)
        if chrome: subprocess.Popen([str(chrome), url])
        else: print('Chrome was not found. Open the printed URL in Chrome.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
