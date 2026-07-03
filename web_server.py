# web_app.py - the control page in the browser and all its endpoints.
# Serves the HTML page, the camera snapshots and the small endpoints the
# page calls: timed motor runs, speed, calibrate, emergency stop, status.

from flask import Flask, Response, jsonify, request

import settings
import state


app = Flask(__name__)

page_html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Gaze Control</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
         background:#111; color:#eee; text-align:center; }
  h1 { font-size:1.2rem; padding:14px 0 6px; margin:0; }
  .wrap { max-width:640px; margin:0 auto; padding:10px; }
  .pills { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; margin:6px 0 12px; }
  .pill { display:flex; align-items:center; gap:6px; background:#1f2937; border-radius:999px;
          padding:6px 12px; font-size:0.85rem; font-weight:600; }
  .dot { width:12px; height:12px; border-radius:50%; background:#6b7280; }
  .dot.ok { background:#22c55e; } .dot.bad { background:#dc2626; }
  .dot.warn { background:#f59e0b; }
  .row { display:flex; gap:8px; margin:8px 0; }
  .btn { flex:1; border:none; border-radius:14px; color:#fff; font-weight:700;
         font-size:1.0rem; min-height:64px; padding:10px; }
  .btn:active { filter:brightness(1.3); }
  .t10,.t20,.t60 { background:#b45309; }
  .spd { background:#334155; }
  .spd.active { background:#2563eb; outline:3px solid #93c5fd; }
  .feed { background:#0f766e; }
  .cal { background:#7c3aed; }
  .toggle { background:#334155; }
  .toggle.on { background:#15803d; }
  .estop { width:100%; margin:12px 0; border:none; border-radius:18px;
           background:#dc2626; color:#fff; font-weight:800; font-size:1.4rem;
           padding:24px; box-shadow:0 0 0 4px #7f1d1d inset; }
  .estop:active { filter:brightness(1.2); }
  .estop.clear { background:#374151; box-shadow:none; font-size:1.05rem; padding:16px; }
  #status { margin-top:10px; min-height:1.3em; font-size:0.9rem; color:#9ca3af; }
  .feeds { display:none; margin-top:12px; }
  .feeds.show { display:block; }
  img { width:100%; border-radius:12px; background:#000; }
  .lbl { font-size:0.75rem; color:#9ca3af; margin:10px 0 2px; text-align:left; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Gaze Control Panel</h1>

  <div class="pills">
    <span class="pill"><span class="dot" id="espDot"></span><span id="espTxt">ESP: ...</span></span>
    <span class="pill"><span class="dot" id="calDot"></span><span id="calTxt">...</span></span>
    <span class="pill"><span class="dot" id="motDot"></span><span id="motTxt">Motor: ...</span></span>
  </div>

  <div class="lbl">Run motor for:</div>
  <div class="row">
    <button class="btn t10" onclick="timed(10)">10 s</button>
    <button class="btn t20" onclick="timed(20)">20 s</button>
    <button class="btn t60" onclick="timed(60)">60 s</button>
  </div>

  <div class="lbl">Speed:</div>
  <div class="row">
    <button class="btn spd" id="spdNormal" onclick="setSpeed('normal')">Normal</button>
    <button class="btn spd" id="spdFast" onclick="setSpeed('fast')">Fast (x1.5)</button>
  </div>

  <button class="estop" id="estopBtn" onclick="estop()">EMERGENCY STOP</button>

  <div class="row">
    <button class="btn cal" onclick="calibrate()">Calibrate</button>
    <button class="btn feed" id="feedBtn" onclick="toggleFeed()">Show live feed</button>
  </div>

  <button class="btn toggle" id="rwcBtn" style="width:100%" onclick="toggleRWC()">Run without calibration: OFF</button>

  <div id="status">Hold eye contact 1.5 s to run the motor 20 s.</div>

  <div class="feeds" id="feeds"><img id="img0" alt="camera"></div>
</div>

<script>
let feedOn = false;
let estopped = false;
let rwc = false;
function setStatus(t){ document.getElementById('status').textContent = t; }

async function timed(sec){
  try {
    const j = await (await fetch('/motor/timed?seconds=' + sec, {method:'POST'})).json();
    if (j.ok) setStatus('Motor ON for ' + j.seconds + ' s.');
    else setStatus('Motor: ' + (j.error || 'could not start'));
  } catch(e){ setStatus('Error: ' + e); }
}
async function setSpeed(mode){
  try { await fetch('/speed?mode=' + mode, {method:'POST'}); } catch(e){}
}
async function calibrate(){
  setStatus('Calibrating, keep looking at the camera...');
  try {
    const j = await (await fetch('/calibrate', {method:'POST'})).json();
    if (j.ok) setStatus('Calibrated over ' + j.frames + ' frames.');
    else setStatus(j.error || 'calibration failed');
  } catch(e){ setStatus('Error: ' + e); }
}
async function estop(){
  const btn = document.getElementById('estopBtn');
  try {
    if (!estopped){
      await (await fetch('/motor/estop', {method:'POST'})).json();
      estopped = true; btn.textContent = 'STOPPED - tap to re-enable';
      btn.classList.add('clear'); setStatus('EMERGENCY STOP active.');
    } else {
      await (await fetch('/motor/clear', {method:'POST'})).json();
      estopped = false; btn.textContent = 'EMERGENCY STOP';
      btn.classList.remove('clear'); setStatus('Motor re-enabled.');
    }
  } catch(e){ setStatus('Error: ' + e); }
}
async function toggleRWC(){
  rwc = !rwc;
  try { await fetch('/run_uncalibrated?on=' + (rwc?1:0), {method:'POST'}); } catch(e){}
  document.getElementById('rwcBtn').textContent = 'Run without calibration: ' + (rwc?'ON':'OFF');
  document.getElementById('rwcBtn').classList.toggle('on', rwc);
}

async function pollStatus(){
  try {
    const j = await (await fetch('/status')).json();
    const m = j.motor || {};
    const espDot = document.getElementById('espDot');
    const espTxt = document.getElementById('espTxt');
    espDot.className = 'dot ' + (j.connected ? 'ok' : 'bad');
    espTxt.textContent = j.connected ? ('ESP: connected (' + j.rssi + ' dBm)') : 'ESP: not connected';
    const calDot = document.getElementById('calDot');
    const calTxt = document.getElementById('calTxt');
    calDot.className = 'dot ' + (j.calibrated ? 'ok' : 'bad');
    calTxt.textContent = j.calibrated ? 'Calibrated' : 'Not calibrated';
    const motDot = document.getElementById('motDot');
    const motTxt = document.getElementById('motTxt');
    if (j.estopped){ motDot.className = 'dot bad'; motTxt.textContent = 'Motor: E-STOP'; }
    else if (m.spinning){ motDot.className = 'dot ok';
      motTxt.textContent = 'Motor: ON' + (m.timed_left > 0 ? (' (' + m.timed_left + 's)') : ''); }
    else { motDot.className = 'dot'; motTxt.textContent = 'Motor: stopped'; }
    document.getElementById('spdNormal').classList.toggle('active', j.speed_mode === 'normal');
    document.getElementById('spdFast').classList.toggle('active', j.speed_mode === 'fast');
  } catch(e){ }
}
setInterval(pollStatus, 700);
pollStatus();

let snapTimer = null;
function toggleFeed(){
  feedOn = !feedOn;
  const feeds = document.getElementById('feeds');
  const btn = document.getElementById('feedBtn');
  const i0 = document.getElementById('img0');
  if (feedOn){
    btn.textContent = 'Hide live feed'; feeds.classList.add('show');
    if (!snapTimer) snapTimer = setInterval(function(){
      if (feedOn) i0.src = '/snapshot?' + Date.now();
    }, 300);
  } else {
    btn.textContent = 'Show live feed'; feeds.classList.remove('show');
    if (snapTimer){ clearInterval(snapTimer); snapTimer = null; } i0.src = '';
  }
}
</script>
</body>
</html>"""


# Serve the control page (with caching disabled so edits show up right away).
@app.route("/")
def index():
    resp = Response(page_html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# Serve the newest camera frame as one jpeg (the page polls this).
@app.route("/snapshot")
def snapshot():
    data = state.shared.get_jpeg()
    if data is None:
        return Response("no frame yet", status=503, mimetype="text/plain")
    resp = Response(data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# Start a calibration and wait until the camera thread finished it.
@app.route("/calibrate", methods=["POST", "GET"])
def calibrate():
    with state.shared.lock:
        if not state.shared.camera_active:
            return jsonify({"ok": False, "error": "camera not active"}), 404
        state.shared.calib_event.clear()
        state.shared.calib_result = None
        state.shared.calib_request = True
    got = state.shared.calib_event.wait(timeout=settings.calib_timeout_s)
    if not got:
        with state.shared.lock:
            state.shared.calib_request = False
        return jsonify({"ok": False, "error": "timed out (no face detected?)"}), 200
    with state.shared.lock:
        return jsonify(state.shared.calib_result)


# Start a manual motor run for 10, 20 or 60 seconds.
@app.route("/motor/timed", methods=["POST", "GET"])
def motor_timed():
    if state.esp is None:
        return jsonify({"ok": False, "error": "esp not ready"}), 200
    try:
        seconds = float(request.args.get("seconds", "10"))
    except ValueError:
        seconds = 10.0
    if seconds not in (10.0, 20.0, 60.0):
        seconds = 10.0
    ok, err = state.esp.start_timed(seconds)
    if not ok:
        return jsonify({"ok": False, "error": err}), 200
    return jsonify({"ok": True, "seconds": seconds})


# Switch the motor speed between normal and fast.
@app.route("/speed", methods=["POST", "GET"])
def speed():
    mode = request.args.get("mode", "normal")
    if state.esp is not None:
        state.esp.set_speed_fast(mode == "fast")
    return jsonify({"ok": True, "mode": mode})


# Toggle the run-without-calibration override.
@app.route("/run_uncalibrated", methods=["POST", "GET"])
def run_uncalibrated():
    on = request.args.get("on", "0") in ("1", "true", "on")
    if state.esp is not None:
        state.esp.set_run_without_calib(on)
    return jsonify({"ok": True, "on": on})


# Emergency stop button on the web page.
@app.route("/motor/estop", methods=["POST", "GET"])
def motor_estop():
    if state.esp is not None:
        state.esp.emergency_stop()
    return jsonify({"ok": True, "estop": True})


# Re-enable the motor after an emergency stop.
@app.route("/motor/clear", methods=["POST", "GET"])
def motor_clear():
    if state.esp is not None:
        state.esp.clear_estop()
    return jsonify({"ok": True, "estop": False})


# Full status for the pills at the top of the page.
@app.route("/status")
def status():
    out = state.esp.status() if state.esp is not None else {"connected": False}
    with state.shared.lock:
        out["camera_active"] = state.shared.camera_active
    return jsonify(out)