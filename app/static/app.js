const $ = (selector) => document.querySelector(selector);

let ws;
let completedSweeps = 0;
let latestCompletedResult = null;
const ui = {
  connect: $('#connect'),
  disconnect: $('#disconnect'),
  start: $('#start'),
  stop: $('#stop'),
  badge: $('#connectionBadge'),
};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

async function post(url, body) {
  return api(url, {
    method: 'POST',
    headers: body ? {'Content-Type': 'application/json'} : {},
    body: body ? JSON.stringify(body) : null,
  });
}

function isConnected() {
  return ui.badge.classList.contains('online');
}

function isScanning() {
  return document.body.classList.contains('scanning');
}

function setConnected(connected) {
  ui.badge.classList.toggle('online', connected);
  ui.badge.classList.toggle('offline', !connected);
  $('#connection').textContent = connected ? 'Connected' : 'Disconnected';
  ui.connect.disabled = connected || !$('#ports').value;
  ui.disconnect.disabled = !connected;
  ui.start.disabled = !connected || isScanning();
  ui.stop.disabled = true;
}

function setScanning(scanning) {
  document.body.classList.toggle('scanning', scanning);
  $('#measurement').textContent = scanning ? 'Measuring' : 'Idle';
  ui.start.disabled = scanning || !isConnected();
  ui.stop.disabled = !scanning;
}

function showScanLoading(completed = 0) {
  const panel = $('#resultPanel');
  panel.classList.remove(
    'state-idle', 'state-air', 'state-normal', 'state-fractured',
    'state-uncertain', 'state-pending',
  );
  panel.classList.add('state-loading');
  $('#sweepProgress').textContent = completed > 0
    ? `${Math.min(completed, 3)}/3`
    : 'Preparing';
}

function hideScanLoading() {
  $('#resultPanel').classList.remove('state-loading');
}

async function scanPorts() {
  try {
    const data = await api('/api/device/ports');
    const select = $('#ports');
    select.replaceChildren(...data.ports.map((port) => new Option(
      `${port.port} — ${port.description}${port.protocol === 'nanovna_v2' ? ' · NanoVNA V2' : ''}`,
      port.port,
    )));
    if (!data.ports.length) select.add(new Option('No serial devices found', ''));
    ui.connect.disabled = isConnected() || !select.value;
  } catch (error) {
    $('#status').textContent = error.message;
  }
}

function showResult(result) {
  const panel = $('#resultPanel');
  const label = result.prediction || result.predicted_class;
  const probabilities = result.class_probabilities || {};
  panel.classList.remove(
    'state-idle', 'state-air', 'state-normal', 'state-fractured',
    'state-uncertain', 'state-pending', 'state-loading',
  );

  let state = 'pending';
  let title = 'Collecting sweeps…';
  let thai = '';
  let description = `${result.completed_sweeps || 0}/3 completed sweeps required`;
  let score = null;
  let scoreLabel = 'Class score';

  if (label === 'AIR') {
    state = 'air';
    title = 'AIR';
    thai = 'ตรวจพบอากาศ / ไม่มีชิ้นตัวอย่าง';
    score = result.similarity_air ?? probabilities.AIR;
    scoreLabel = 'Air score';
    description = 'Empty fixture or air reference detected';
  } else if (label === 'FRACTURED') {
    state = 'fractured';
    title = 'FRACTURED';
    thai = 'ตรวจพบแนวโน้มการแตก';
    score = result.similarity_crack ?? probabilities.FRACTURED;
    scoreLabel = 'Crack score';
    description = 'Matched with the crack reference group';
  } else if (label === 'NOT_FRACTURED') {
    state = 'normal';
    title = 'NOT FRACTURED';
    thai = 'ไม่พบแนวโน้มการแตก';
    score = result.similarity_normal ?? probabilities.NOT_FRACTURED;
    scoreLabel = 'Normal score';
    description = 'Matched with the normal reference group';
  } else if (label === 'UNCERTAIN') {
    state = 'uncertain';
    title = 'UNCERTAIN';
    thai = 'ผลยังไม่ชัดเจน';
    score = Math.max(0, ...Object.values(probabilities));
    scoreLabel = 'Best match';
    description = 'No class has a safe winning margin';
  }

  panel.classList.add(`state-${state}`);
  $('#resultTitle').textContent = title;
  $('#resultThai').textContent = thai;
  $('#scoreValue').textContent = score == null ? '—' : `${(score * 100).toFixed(1)}%`;
  $('#scoreLabel').textContent = scoreLabel;
  $('#confidenceText').textContent = description;
  $('#air').textContent = result.similarity_air == null ? '—' : `${(result.similarity_air * 100).toFixed(1)}%`;
  $('#normal').textContent = result.similarity_normal == null ? '—' : `${(result.similarity_normal * 100).toFixed(1)}%`;
  $('#crack').textContent = result.similarity_crack == null ? '—' : `${(result.similarity_crack * 100).toFixed(1)}%`;
  if (result.frequency_hz) draw(result.s21_db);
}

function draw(values) {
  const canvas = $('#chart');
  const ctx = canvas.getContext('2d');
  const {width: w, height: h} = canvas;
  const pad = {l: 55, r: 18, t: 16, b: 24};
  ctx.clearRect(0, 0, w, h);
  if (!values?.length) return;

  const low = Math.floor(Math.min(...values) / 5) * 5;
  const high = Math.ceil(Math.max(...values) / 5) * 5 || low + 5;
  ctx.font = '11px Segoe UI';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i += 1) {
    const y = pad.t + (i * (h - pad.t - pad.b)) / 5;
    ctx.strokeStyle = '#8fc4e61a';
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
    ctx.fillStyle = '#698397';
    ctx.textAlign = 'right';
    ctx.fillText(`${(high - (i * (high - low)) / 5).toFixed(0)} dB`, pad.l - 8, y + 4);
  }

  const gradient = ctx.createLinearGradient(pad.l, 0, w - pad.r, 0);
  gradient.addColorStop(0, '#4be3ff');
  gradient.addColorStop(1, '#208bff');
  ctx.strokeStyle = gradient;
  ctx.shadowColor = '#39cfff';
  ctx.shadowBlur = 8;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = pad.l + (index / (values.length - 1)) * (w - pad.l - pad.r);
    const y = pad.t + ((high - value) / (high - low || 1)) * (h - pad.t - pad.b);
    if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
  });
  ctx.stroke();
  ctx.shadowBlur = 0;
}

async function startScan() {
  if (!isConnected()) {
    const message = 'Connect the NanoVNA before starting a scan.';
    alert(message);
    return;
  }
  try {
    latestCompletedResult = null;
    completedSweeps = 0;
    showScanLoading();
    await post('/api/live/start');
    completedSweeps = 0;
    setScanning(true);
    $('#scanMessage').textContent = 'Starting segmented sweep…';
  } catch (error) {
    hideScanLoading();
    alert(error.message);
  }
}

function openSocket() {
  if (ws && ws.readyState < 2) return;
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`);
  ws.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    if (data.status === 'connected' && data.device) {
      setConnected(data.device.connected);
      if (data.sample_complete) {
        setScanning(true);
        showScanLoading(3);
        await new Promise((resolve) => setTimeout(resolve, 300));
        if (latestCompletedResult) showResult(latestCompletedResult);
        setScanning(false);
        $('#measurement').textContent = 'Complete';
        $('#scanMessage').textContent = 'Sweep 3 stabilized and processed';
        $('#status').textContent = 'Complete';
        return;
      }
      setScanning(data.device.running);
      return;
    }
    if (data.status === 'measuring') {
      $('#measurement').textContent = 'Measuring';
      $('#scanMessage').textContent = 'Acquiring and averaging S21 sweep…';
      setScanning(true);
    } else if (data.status === 'complete') {
      completedSweeps = data.completed_sweeps || 0;
      latestCompletedResult = data;
      showScanLoading(completedSweeps);
      $('#measurement').textContent = 'Measuring';
      $('#scanMessage').textContent = `Sweep ${completedSweeps}/3 completed`;
      $('#timestamp').textContent = new Date(data.timestamp).toLocaleString();
      $('#status').textContent = 'Measuring';
      if (data.frequency_hz) draw(data.s21_db);
    } else if (data.status === 'error') {
      hideScanLoading();
      $('#measurement').textContent = 'Error';
      $('#scanMessage').textContent = data.error;
      $('#status').textContent = data.error;
      setScanning(false);
    }
  };
  ws.onclose = () => {
    ws = null;
    setTimeout(openSocket, 1500);
  };
}

$('#rescan').onclick = scanPorts;

ui.connect.onclick = async () => {
  try {
    const port = $('#ports').value;
    await post('/api/device/connect', {port});
    setConnected(true);
    $('#scanMessage').textContent = 'NanoVNA ready — start a live scan';
    $('#status').textContent = 'Device ready';
  } catch (error) {
    setConnected(false);
    alert(error.message);
  }
};

ui.disconnect.onclick = async () => {
  try {
    await post('/api/device/disconnect');
    setConnected(false);
    setScanning(false);
    hideScanLoading();
    $('#scanMessage').textContent = 'Device disconnected';
  } catch (error) {
    alert(error.message);
  }
};

ui.start.onclick = () => startScan();

ui.stop.onclick = async () => {
  try {
    await post('/api/live/stop');
    setScanning(false);
    hideScanLoading();
    $('#scanMessage').textContent = 'Scan stopped — change the sample or start again';
  } catch (error) {
    alert(error.message);
  }
};

setConnected(false);
scanPorts();
openSocket();
