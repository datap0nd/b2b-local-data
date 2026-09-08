import {expect, test} from './fixtures';
import {spawn} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';

test('local recorder produces playable video and retains ordered recovery chunks', async ({page}, info) => {
  test.skip(!!info.project.use.isMobile, 'Local-PC recorder targets desktop Chrome.');
  const root = path.resolve('..');
  const portable = path.join(root, '.install-test/runtime/python-3.13.15-amd64/python.exe');
  const python = process.env.B2B_TEST_PYTHON ?? (existsSync(portable) ? portable : 'python');
  const program = "import sys; sys.path.insert(0,'.'); from scripts.capture_viewer import make_server; server,token=make_server(root='.local/capture-recorder-validation'); print('http://127.0.0.1:%d/#%s' % (server.server_port,token),flush=True); server.serve_forever()";
  const child = spawn(python, ['-c', program], {cwd: root, windowsHide: true});
  const url = await new Promise<string>((resolve, reject) => {
    child.once('error', reject); child.stdout.once('data', data => resolve(data.toString().trim()));
    child.once('exit', code => { if (code) reject(Error('Capture fixture server exited: ' + code)); });
  });
  try {
    await page.addInitScript(() => {
      // Explicit synthetic camera fixture. This test never opens real hardware.
      Object.defineProperty(navigator, 'mediaDevices', {value: {
        enumerateDevices: async () => [{kind: 'videoinput', label: 'UGREEN-25854 (synthetic regression)', deviceId: 'fixture'}],
        getUserMedia: async (constraints: MediaStreamConstraints) => {
          if (constraints.audio !== false) throw Error('Audio must remain disabled.');
          const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 180;
          const ctx = canvas.getContext('2d')!; let n = 0;
          setInterval(() => { ctx.fillStyle = '#123456'; ctx.fillRect(0, 0, 320, 180); ctx.fillStyle = '#fff'; ctx.font = '18px sans-serif'; ctx.fillText('Synthetic recording ' + n++, 15, 70); }, 50);
          return canvas.captureStream(20);
        },
      }});
    });
    await page.goto(url);
    await page.getByRole('button', {name: 'Connect feed'}).click();
    await expect(page.getByRole('button', {name: 'Start recording'})).toBeEnabled();
    await expect(page.locator('#status')).toContainText('320×180');
    await page.getByRole('button', {name: 'Start recording'}).click();
    await expect(page.locator('#elapsed')).toHaveText('3 s', {timeout: 10000});
    await page.getByRole('button', {name: 'Stop & save'}).click();
    await expect(page.locator('#status')).toHaveText('Saved locally');
    const filename = (await page.locator('#saved').textContent())!;
    expect(filename).toContain('.local');
    const bytes = await readFile(filename);
    expect(bytes.subarray(0, 4).toString('hex')).toBe('1a45dfa3');
    const metadata = JSON.parse(await readFile(path.join(path.dirname(filename), 'manifest.json'), 'utf8'));
    expect(metadata.chunks.length).toBeGreaterThanOrEqual(2);
    const dimensions = await page.evaluate(async base64 => {
      const binary = atob(base64); const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
      const video = document.createElement('video'); video.muted = true; video.src = URL.createObjectURL(new Blob([bytes], {type: 'video/webm'}));
      await new Promise<void>((resolve, reject) => { video.onloadeddata = () => resolve(); video.onerror = () => reject(Error('Recorded video cannot be decoded.')); });
      await video.play(); return [video.videoWidth, video.videoHeight];
    }, bytes.toString('base64'));
    expect(dimensions).toEqual([320, 180]);
    await info.attach('synthetic-recorder.webm', {body: bytes, contentType: 'video/webm'});
  } finally { child.kill(); }
});
