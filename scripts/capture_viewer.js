/* Local capture only. The card supplies video; no keyboard/mouse/control channel. */
const token = location.hash.slice(1);
const $ = id => document.getElementById(id);
const feed = $('feed');
let stream, recorder, recording, sequence = 0, queue = Promise.resolve(), started = 0, failed = false, pendingBytes = 0;
const deviceLabel = /^UGREEN-25854(?: \([^()]+\))?$/;
async function call(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', headers: {'X-Capture-Token': token}, body});
  const value = await response.json(); if (!response.ok) throw Error(value.error); return value;
}
function error(e) { $('error').textContent = e.message ?? String(e); }
async function recoveries() {
  const items = await call('/recordings'); $('recover').replaceChildren();
  for (const item of items.filter(i => i.status === 'recording' && i.chunks.length)) {
    const button = document.createElement('button'); button.textContent = 'Recover ' + item.id.slice(0, 8);
    button.onclick = async () => { try { const done = await call(`/recordings/${item.id}/finish`, ''); $('saved').textContent = done.path; await recoveries(); } catch (e) { error(e); } };
    $('recover').append(button);
  }
}
$('connect').onclick = async () => {
  try {
    $('error').textContent = '';
    let devices = await navigator.mediaDevices.enumerateDevices();
    // Obtain permission only to reveal device labels. Never attach this temporary
    // permission stream to the viewer or recorder; stop it immediately.
    if (!devices.some(d => d.kind === 'videoinput' && d.label)) {
      const permission = await navigator.mediaDevices.getUserMedia({video: true, audio: false});
      permission.getTracks().forEach(t => t.stop()); devices = await navigator.mediaDevices.enumerateDevices();
    }
    const matches = devices.filter(d => d.kind === 'videoinput' && deviceLabel.test(d.label.trim()));
    if (matches.length !== 1) throw Error(`Expected one UGREEN-25854 device; found ${matches.length}.`);
    stream?.getTracks().forEach(t => t.stop());
    stream = await navigator.mediaDevices.getUserMedia({video: {deviceId: {exact: matches[0].deviceId}, width: {ideal: 1920}, height: {ideal: 1080}, frameRate: {ideal: 30}}, audio: false});
    feed.srcObject = stream; await feed.play();
    const deadline = Date.now() + 10000;
    while ((feed.readyState !== 4 || !feed.videoWidth) && Date.now() < deadline) await new Promise(r => setTimeout(r, 100));
    if (feed.readyState !== 4 || !feed.videoWidth || !feed.videoHeight) throw Error('Capture feed did not become ready within ten seconds.');
    document.documentElement.dataset.captureReady = 'true';
    $('status').textContent = `${feed.videoWidth}×${feed.videoHeight} · live`; $('start').disabled = false;
    stream.getVideoTracks()[0].addEventListener('ended', () => { document.documentElement.dataset.captureReady = 'false'; $('start').disabled = true; error(Error('Capture card disconnected. Saving received video.')); if (recorder?.state !== 'inactive') recorder?.stop(); });
  } catch (e) { stream?.getTracks().forEach(t => t.stop()); $('start').disabled = true; error(e); }
};
$('start').onclick = async () => {
  $('start').disabled = true; $('connect').disabled = true;
  try {
    if (!stream || feed.readyState !== 4) throw Error('Connect a healthy capture feed first.');
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(m => MediaRecorder.isTypeSupported(m));
    if (!mime) throw Error('This Chrome installation cannot record WebM.');
    recording = await call('/recordings', JSON.stringify({device: 'UGREEN-25854', mime, width: feed.videoWidth, height: feed.videoHeight}));
    sequence = 0; queue = Promise.resolve(); failed = false; pendingBytes = 0; started = Date.now(); $('error').textContent = '';
    recorder = new MediaRecorder(stream, {mimeType: mime, videoBitsPerSecond: 8000000});
    recorder.ondataavailable = event => {
      if (!event.data.size) return;
      pendingBytes += event.data.size;
      if (pendingBytes > 64 * 1024 * 1024 && recorder.state === 'recording') {
        error(Error('Local disk cannot keep up. Stopping and saving received video.')); recorder.stop();
      }
      // A delayed browser event can exceed one chunk; split bytes without
      // altering their order in the single WebM stream.
      for (let offset = 0; offset < event.data.size; offset += 8 * 1024 * 1024) {
        const blob = event.data.slice(offset, offset + 8 * 1024 * 1024), index = sequence++;
        queue = queue.then(async () => {
          for (let attempt = 0; ; attempt++) {
            try { await call(`/recordings/${recording.id}/chunks/${index}`, blob); pendingBytes -= blob.size; return; }
            catch (e) { if (attempt >= 2) throw e; await new Promise(r => setTimeout(r, 1000)); }
          }
        });
      }
      queue.catch(e => { failed = true; error(e); if (recorder.state !== 'inactive') recorder.stop(); });
    };
    recorder.onerror = event => { failed = true; error(event.error ?? Error('Recorder failed.')); };
    recorder.onstop = async () => {
      $('stop').disabled = true; $('status').textContent = 'Saving on this PC…';
      try { await queue; if (!failed) { const done = await call(`/recordings/${recording.id}/finish`, ''); $('saved').textContent = done.path; $('status').textContent = 'Saved locally'; } }
      catch (e) { error(e); $('status').textContent = 'Interrupted · received chunks retained'; }
      finally { started = 0; $('connect').disabled = false; $('start').disabled = feed.readyState !== 4; await recoveries().catch(error); }
    };
    recorder.start(1000); $('stop').disabled = false; $('status').textContent = '● Recording on this PC';
  } catch (e) { error(e); $('connect').disabled = false; $('start').disabled = false; }
};
$('stop').onclick = () => { if (recorder?.state === 'recording') recorder.stop(); };
setInterval(() => { $('elapsed').textContent = started ? `${Math.floor((Date.now() - started) / 1000)} s` : ''; }, 500);
addEventListener('beforeunload', e => { if (started) { e.preventDefault(); e.returnValue = ''; } });
recoveries().catch(error);
