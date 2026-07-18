# Web RTTView Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the PyQt5 RTTView desktop application to a single-file web application (`web_rttview.py`) with embedded HTML/JS/CSS, supporting JLink/DAPLink/STLink with Chinese encoding.

**Architecture:** Single Python file containing a Flask+SocketIO backend that reuses existing `probes/`, `core/`, and `xlink.py` modules, with all frontend code (HTML/CSS/JS/Chart.js) embedded as string literals. WebSocket for real-time data streaming.

**Tech Stack:** Python 3.8+, Flask, Flask-SocketIO, Chart.js (minified, embedded), existing probes/core modules

## Global Constraints

- Single file: `web_rttview.py` at project root (~3500 lines)
- All frontend assets (HTML, CSS, JS, Chart.js) embedded as Python string literals
- Reuse `probes/`, `core/`, `xlink.py` modules — do not rewrite probe logic
- VS Code dark theme: bg `#1e1e1e`, text `#d4d4d4`, accent `#569cd6`
- Chinese encoding: auto-detect UTF-8/GBK, manual switch in UI
- WebSocket for all real-time data (RTT, SWO, oscilloscope, registers)
- HTTP for file uploads (SVD, ELF, firmware)
- Server listens on `localhost:5000` only
- All 11 features from desktop版 must be present

## File Structure

```
web_rttview.py          ← THE single file (create)
├── Python imports & constants
├── RTT structures (RingBuffer, SEGGER_RTT_CB — copied from RTTView.py)
├── ANSI 256-color palette (copied from RTTView.py)
├── Flask app & SocketIO setup
├── Background worker threads (RTT read, oscilloscope, SWO, register poll)
├── WebSocket event handlers
├── HTTP route handlers (index, file upload)
├── Embedded HTML (HTML_TEMPLATE string)
│   ├── <style> — VS Code dark theme CSS
│   ├── <body> — tab layout, all 9 feature panels
│   ├── <script src="data:..."> — Chart.js minified
│   └── <script> — application JS
│       ├── WebSocket client
│       ├── Tab management
│       ├── RTT Terminal (ANSI rendering, encoding switch)
│       ├── Waveform display (Chart.js)
│       ├── Oscilloscope (Chart.js, 8 channels, trigger)
│       ├── SWO Console (3 sub-tabs)
│       ├── RTOS Task Viewer (table with progress bars)
│       ├── Crash Analyzer (register decode, stack walk)
│       ├── Flash Programmer (upload + progress)
│       ├── SVD Register Viewer (tree + live values)
│       ├── Core Register Viewer (ARM/RISC-V)
│       └── Memory Viewer (hex dump)
└── if __name__ == '__main__': start server + open browser
```

---

### Task 1: Server Skeleton + HTML Shell + Tab Navigation

**Files:**
- Create: `web_rttview.py`

**Interfaces:**
- Produces: Flask app on port 5000, WebSocket connection, 9 tab UI shell
- Consumes: none (first task)

- [ ] **Step 1: Create `web_rttview.py` with Flask+SocketIO skeleton**

```python
#!/usr/bin/env python3
"""Web RTTView — Browser-based SEGGER RTT Viewer with VS Code dark theme."""
import os
import sys
import json
import threading
import webbrowser
import tempfile
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rttview-secret'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
state = {
    'probe': None,       # Current XLink facade
    'probe_obj': None,   # Raw probe object
    'connected': False,
    'rtt_running': False,
    'osc_running': False,
    'swo_running': False,
    'rtt_cb_addr': 0,
    'a_up_addr': 0,
    'a_down_addr': 0,
    'upload_dir': tempfile.mkdtemp(prefix='rttview_'),
}

UPLOAD_DIR = state['upload_dir']
```

- [ ] **Step 2: Add HTTP routes**

Append to `web_rttview.py`:

```python
@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(path)
    return jsonify({'file_id': f.filename, 'path': path})

@app.route('/svd_files')
def list_svd_files():
    svd_dir = os.path.join(os.path.dirname(__file__), 'svd')
    files = []
    if os.path.isdir(svd_dir):
        files = [f for f in os.listdir(svd_dir) if f.endswith('.svd')]
    return jsonify({'files': files})
```

- [ ] **Step 3: Add main entry point**

```python
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Web RTTView')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f'http://localhost:{args.port}')).start()

    print(f'Web RTTView running at http://localhost:{args.port}')
    socketio.run(app, host='127.0.0.1', port=args.port, debug=False)
```

- [ ] **Step 4: Add embedded HTML template (shell with tabs)**

Define `HTML_TEMPLATE` as a Python triple-quoted string containing the full HTML. Start with the shell:

```python
HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Web RTTView</title>
<style>
/* VS Code Dark Theme */
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: 'Cascadia Code','Fira Code','JetBrains Mono',Consolas,monospace;
    font-size: 13px; color: #d4d4d4; background: #1e1e1e;
    height: 100vh; display: flex; flex-direction: column; overflow: hidden;
}
/* ... (full CSS in Step 5) ... */
</style>
</head>
<body>
<!-- Top bar: probe controls -->
<div id="topbar">...</div>
<!-- Tab bar -->
<div id="tabbar">...</div>
<!-- Tab content panels -->
<div id="panels">...</div>
<!-- Status bar -->
<div id="statusbar">...</div>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
// Application JS (all features)
</script>
</body>
</html>'''
```

- [ ] **Step 5: Verify server starts**

Run: `python web_rttview.py --no-browser --port 5001`
Expected: Server starts, `curl http://localhost:5001/` returns HTML
Stop server after verification.

- [ ] **Step 6: Commit**

```bash
git add web_rttview.py
git commit -m "feat: web rttview skeleton with Flask+SocketIO and tab navigation"
```

---

### Task 2: Probe Detection & Connection

**Files:**
- Modify: `web_rttview.py` — add probe WebSocket handlers + frontend probe UI

**Interfaces:**
- Consumes: `probes/__init__.py` (`list_probes()`, `create_probe()`), `xlink.XLink`
- Produces: WebSocket events `probe_list`, `connected`, `disconnected`, `error`

- [ ] **Step 1: Add probe detection and connection WebSocket handlers**

```python
import xlink
from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe

os.environ['PATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'libusb-1.0.24/MinGW64/dll') + os.pathsep + os.environ['PATH']

@socketio.on('probe_detect')
def handle_probe_detect():
    probes = [{'name': 'JLink', 'type': 'jlink'}, {'name': 'OpenOCD', 'type': 'openocd'}]
    try:
        stlinks = STLinkProbe.detect()
        for i, (dev, name) in enumerate(stlinks):
            probes.append({'name': name, 'type': 'stlink', 'index': i})
    except Exception:
        pass
    try:
        daplinks = DAPLinkProbe.detect()
        for i, probe in enumerate(daplinks):
            probes.append({'name': f'{probe.product_name} ({probe.unique_id})', 'type': 'daplink', 'index': i})
    except Exception:
        pass
    emit('probe_list', {'probes': probes})

@socketio.on('probe_connect')
def handle_probe_connect(data):
    try:
        probe_type = data.get('type', 'jlink')
        mode = data.get('mode', 'arm')
        speed = data.get('speed', 4000) * 1000
        address = data.get('address', '0x20000000')
        channel = data.get('channel', 0)

        if probe_type == 'jlink':
            probe = JLinkProbe()
        elif probe_type == 'stlink':
            stlinks = STLinkProbe.detect()
            idx = data.get('index', 0)
            probe = STLinkProbe(device=stlinks[idx][0])
        elif probe_type == 'daplink':
            daplinks = DAPLinkProbe.detect()
            idx = data.get('index', 0)
            probe = DAPLinkProbe(probe=daplinks[idx])
        elif probe_type == 'openocd':
            probe = OpenOCDProbe()
        else:
            raise ValueError(f'Unknown probe type: {probe_type}')

        core = 'Cortex-M0' if mode.startswith('arm') else 'RISC-V'
        probe.open(mode=mode, core=core, speed=speed)
        state['probe_obj'] = probe
        state['probe'] = xlink.XLink(probe)
        state['connected'] = True

        # Scan for RTT control block
        rtt_found = False
        if re.match(r'0[xX][0-9a-fA-F]{8}', address):
            addr = int(address, 16)
            for i in range(64):
                data_bytes = state['probe'].read_mem_U8(addr + 1024 * i, 1024 + 32)
                index = bytes(data_bytes).find(b'SEGGER RTT')
                if index != -1:
                    state['rtt_cb_addr'] = addr + 1024 * i + index
                    cb_data = state['probe'].read_mem_U8(state['rtt_cb_addr'], ctypes.sizeof(SEGGER_RTT_CB))
                    rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(cb_data))
                    state['a_up_addr'] = state['rtt_cb_addr'] + 16 + 4 + 4
                    state['a_down_addr'] = state['a_up_addr'] + ctypes.sizeof(RingBuffer) * rtt_cb.MaxNumUpBuffers
                    rtt_found = True
                    break

        emit('connected', {
            'probe_type': probe_type,
            'rtt_found': rtt_found,
            'rtt_addr': hex(state['rtt_cb_addr']) if rtt_found else None,
        })
    except Exception as e:
        emit('error', {'message': str(e)})

@socketio.on('probe_disconnect')
def handle_probe_disconnect():
    _do_disconnect()
    emit('disconnected', {})

def _do_disconnect():
    state['rtt_running'] = False
    state['osc_running'] = False
    state['swo_running'] = False
    if state['probe']:
        try:
            state['probe'].close()
        except:
            pass
    state['probe'] = None
    state['probe_obj'] = None
    state['connected'] = False
```

- [ ] **Step 2: Add probe UI to frontend (topbar + JS handlers)**

In the HTML template, add the topbar with probe selector, mode/speed/address controls, and connect button. Add JS for `probe_detect`, `probe_connect`, `probe_list`, `connected`, `disconnected` events.

- [ ] **Step 3: Test probe detection**

Run server, open browser, verify probe list populates (even if no probe connected, JLink/OpenOCD should appear).

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: probe detection and connection via WebSocket"
```

---

### Task 3: RTT Terminal with Chinese Encoding + ANSI Colors

**Files:**
- Modify: `web_rttview.py` — add RTT read/write logic + terminal UI

**Interfaces:**
- Consumes: `state['probe']` (XLink), `state['a_up_addr']`, `state['a_down_addr']`
- Produces: WebSocket events `rtt_data`, `rtt_sent`; handlers `rtt_start`, `rtt_stop`, `rtt_send`
- Reuses: `RingBuffer`, `SEGGER_RTT_CB` structs, `_parse_ansi()` logic from RTTView.py

- [ ] **Step 1: Add RTT structures (copy from RTTView.py)**

```python
import ctypes
import struct

class RingBuffer(ctypes.Structure):
    _fields_ = [
        ('sName', ctypes.c_uint), ('pBuffer', ctypes.c_uint),
        ('SizeOfBuffer', ctypes.c_uint), ('WrOff', ctypes.c_uint),
        ('RdOff', ctypes.c_uint), ('Flags', ctypes.c_uint),
    ]

RTT_MAX_NUM_UP_BUFFERS = 3
RTT_MAX_NUM_DOWN_BUFFERS = 3

class SEGGER_RTT_CB(ctypes.Structure):
    _fields_ = [
        ('acID', ctypes.c_char * 16), ('MaxNumUpBuffers', ctypes.c_uint),
        ('MaxNumDownBuffers', ctypes.c_uint),
        ('aUp', RingBuffer * RTT_MAX_NUM_UP_BUFFERS),
        ('aDown', RingBuffer * RTT_MAX_NUM_DOWN_BUFFERS),
    ]
```

- [ ] **Step 2: Add RTT read/write functions**

```python
def rtt_read():
    """Read from RTT up-buffer. Returns bytes."""
    probe = state['probe']
    if not probe or not state['a_up_addr']:
        return b''
    data = probe.read_mem_U8(state['a_up_addr'], ctypes.sizeof(RingBuffer))
    aUp = RingBuffer.from_buffer(bytearray(data))
    if not (aUp.SizeOfBuffer == 2048 and aUp.WrOff < aUp.SizeOfBuffer
            and aUp.RdOff < aUp.SizeOfBuffer):
        return b''
    if aUp.RdOff <= aUp.WrOff:
        cnt = aUp.WrOff - aUp.RdOff
    else:
        cnt1 = aUp.SizeOfBuffer - aUp.RdOff
        cnt2 = aUp.WrOff
        cnt = cnt1 + cnt2
    if 0 < cnt < 1024 * 1024:
        bufAddr = aUp.pBuffer
        if aUp.RdOff <= aUp.WrOff:
            data = probe.read_mem_U8(bufAddr + aUp.RdOff, cnt)
        else:
            part1 = probe.read_mem_U8(bufAddr + aUp.RdOff, cnt1)
            part2 = probe.read_mem_U8(bufAddr, cnt2)
            data = part1 + part2
        aUp.RdOff = (aUp.RdOff + cnt) % aUp.SizeOfBuffer
        probe.write_U32(state['a_up_addr'] + 4 * 4, aUp.RdOff)
        return bytes(data)
    return b''

def rtt_write(data_bytes):
    """Write to RTT down-buffer."""
    probe = state['probe']
    if not probe or not state['a_down_addr']:
        return
    raw = probe.read_mem_U8(state['a_down_addr'], ctypes.sizeof(RingBuffer))
    aDown = RingBuffer.from_buffer(bytearray(raw))
    if aDown.WrOff >= aDown.RdOff:
        cnt = min(aDown.SizeOfBuffer - aDown.WrOff - (0 if aDown.RdOff else 1), len(data_bytes))
        probe.write_mem_U8(aDown.pBuffer + aDown.WrOff, list(data_bytes[:cnt]))
        aDown.WrOff += cnt
        if aDown.WrOff == aDown.SizeOfBuffer:
            aDown.WrOff = 0
        data_bytes = data_bytes[cnt:]
    if data_bytes and aDown.RdOff > 1:
        cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(data_bytes))
        probe.write_mem_U8(aDown.pBuffer + aDown.WrOff, list(data_bytes[:cnt]))
        aDown.WrOff += cnt
    probe.write_U32(state['a_down_addr'] + 4 * 3, aDown.WrOff)
```

- [ ] **Step 3: Add RTT background reader thread**

```python
def rtt_reader_thread():
    """Background thread: reads RTT data and pushes via WebSocket."""
    fail_count = 0
    encoding = state.get('rtt_encoding', 'auto')
    while state['rtt_running']:
        try:
            data = rtt_read()
            if data:
                fail_count = 0
                # Decode with auto-detect or specified encoding
                text = decode_bytes(data, encoding)
                # Parse ANSI and send as HTML segments
                segments = parse_ansi_to_html(data, encoding)
                socketio.emit('rtt_data', {'text': text, 'segments': segments, 'raw_hex': data.hex()})
            else:
                fail_count += 1
                if fail_count >= 500:  # ~5 seconds at 10ms poll
                    socketio.emit('rtt_data', {'text': '', 'segments': [], 'reconnect': True})
                    fail_count = 0
        except Exception as e:
            fail_count += 1
        socketio.sleep(0.01)  # 10ms poll interval
```

- [ ] **Step 4: Add Chinese encoding detection function**

```python
def decode_bytes(data, encoding='auto'):
    """Decode bytes with auto-detect or specified encoding."""
    if encoding == 'hex':
        return ' '.join(f'{b:02X}' for b in data)
    if encoding == 'ascii':
        return data.decode('ascii', errors='replace')
    if encoding == 'auto':
        # Try UTF-8 first
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        # Try GBK
        try:
            return data.decode('gbk')
        except UnicodeDecodeError:
            pass
        # Fallback
        return data.decode('utf-8', errors='replace')
    return data.decode(encoding, errors='replace')
```

- [ ] **Step 5: Add ANSI-to-HTML parser (port from RTTView.py `_parse_ansi`)**

Port the `_parse_ansi` and `_render_ansi_codes` logic to produce HTML spans with inline styles. The function should return a list of `{'text': str, 'style': str}` objects.

```python
ANSI_16 = [
    (0,0,0),(197,15,31),(19,161,14),(193,156,0),(0,55,218),(136,23,152),
    (58,150,221),(204,204,204),(118,118,118),(231,72,86),(22,198,12),
    (249,241,165),(59,120,255),(180,0,158),(97,214,214),(255,255,255),
]
PALETTE256 = list(ANSI_16)
for r in (0,95,135,175,215,255):
    for g in (0,95,135,175,215,255):
        for b in (0,95,135,175,215,255):
            PALETTE256.append((r,g,b))
for i in range(24):
    v = 8 + i * 10
    PALETTE256.append((v,v,v))

def parse_ansi_to_html(raw_bytes, encoding='auto'):
    """Parse raw RTT bytes into HTML segments with ANSI color support."""
    # Port from RTTView.py _parse_ansi method
    # Returns list of {'text': html_escaped, 'style': 'color:#xxx;background:#xxx;font-weight:bold'}
    segments = []
    # ... (full implementation ported from RTTView.py lines 1270-1373)
    return segments
```

- [ ] **Step 6: Add WebSocket RTT handlers**

```python
@socketio.on('rtt_start')
def handle_rtt_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    state['rtt_encoding'] = data.get('encoding', 'auto')
    state['rtt_running'] = True
    socketio.start_background_task(rtt_reader_thread)
    emit('rtt_started', {})

@socketio.on('rtt_stop')
def handle_rtt_stop():
    state['rtt_running'] = False
    emit('rtt_stopped', {})

@socketio.on('rtt_send')
def handle_rtt_send(data):
    if not state['connected']:
        return
    text = data.get('data', '')
    encoding = data.get('encoding', 'utf-8')
    try:
        encoded = text.encode(encoding)
        rtt_write(encoded)
        emit('rtt_sent', {'ok': True})
    except Exception as e:
        emit('error', {'message': f'Send failed: {e}'})
```

- [ ] **Step 7: Build frontend RTT terminal tab**

HTML: text display area with monospace font, auto-scroll, encoding selector, input box + send button.
JS: handle `rtt_data` event, append colored HTML to terminal, auto-scroll, Ctrl+wheel font zoom.

- [ ] **Step 8: Test RTT terminal**

Run server, connect to a running MCU with RTT output, verify Chinese text displays correctly.

- [ ] **Step 9: Commit**

```bash
git add web_rttview.py
git commit -m "feat: RTT terminal with ANSI 256-color and Chinese encoding support"
```

---

### Task 4: RTT Waveform Display

**Files:**
- Modify: `web_rttview.py` — add waveform parsing + Chart.js waveform tab

**Interfaces:**
- Consumes: RTT data stream (reuses rtt_reader_thread)
- Produces: WebSocket event `wave_data`

- [ ] **Step 1: Add waveform data parsing (port from RTTView.py `_process_wave_data`)**

```python
def parse_wave_data(raw_bytes, n_curve=4, encoding='float'):
    """Parse RTT waveform data. Format: comma-separated values per line."""
    # Port from RTTView.py lines 1143-1182
    # Returns list of lists: [[curve0_values...], [curve1_values...], ...]
    pass
```

- [ ] **Step 2: Add waveform WebSocket handlers**

```python
@socketio.on('wave_start')
def handle_wave_start(data):
    state['wave_ncurve'] = data.get('ncurve', 4)
    state['wave_npoint'] = data.get('npoint', 1000)
    state['wave_mode'] = True  # Wave mode vs text mode
    emit('wave_started', {})

@socketio.on('wave_stop')
def handle_wave_stop():
    state['wave_mode'] = False
    emit('wave_stopped', {})
```

- [ ] **Step 3: Modify rtt_reader_thread to handle wave mode**

When `state['wave_mode']` is True, parse data as waveform and emit `wave_data` instead of `rtt_data`.

- [ ] **Step 4: Build frontend waveform tab with Chart.js**

HTML: Canvas element for Chart.js, controls for ncurve/npoint.
JS: Real-time Chart.js line chart update.

- [ ] **Step 5: Test waveform display**

Connect MCU with waveform output, verify curves render.

- [ ] **Step 6: Commit**

```bash
git add web_rttview.py
git commit -m "feat: RTT waveform display with Chart.js"
```

---

### Task 5: Register Oscilloscope

**Files:**
- Modify: `web_rttview.py` — add oscilloscope backend + frontend tab

**Interfaces:**
- Consumes: `state['probe'].read_mem_U32(addr, count)`
- Produces: WebSocket event `osc_data`

- [ ] **Step 1: Add oscilloscope background thread**

```python
def oscilloscope_thread():
    """Read MCU memory at ~100Hz and push waveform data."""
    channels = state.get('osc_channels', [])
    interval = 0.01  # 100Hz
    while state['osc_running']:
        values = []
        for ch in channels:
            try:
                if ch['type'] in ('uint32', 'int32'):
                    val = state['probe'].read_U32(ch['addr'])
                    if ch['type'] == 'int32' and val >= 0x80000000:
                        val -= 0x100000000
                elif ch['type'] == 'float':
                    import struct
                    raw = state['probe'].read_U32(ch['addr'])
                    val = struct.unpack('f', struct.pack('I', raw))[0]
                elif ch['type'] in ('uint16', 'int16'):
                    raw = state['probe'].read_mem_U16(ch['addr'], 1)[0]
                    val = raw if ch['type'] == 'uint16' else (raw - 0x10000 if raw >= 0x8000 else raw)
                else:
                    val = 0
                values.append(val * ch.get('scale', 1.0))
            except:
                values.append(None)
        socketio.emit('osc_data', {'values': values})
        socketio.sleep(interval)
```

- [ ] **Step 2: Add oscilloscope WebSocket handlers**

```python
@socketio.on('osc_start')
def handle_osc_start(data):
    state['osc_channels'] = data.get('channels', [])
    state['osc_running'] = True
    socketio.start_background_task(oscilloscope_thread)
    emit('osc_started', {})

@socketio.on('osc_stop')
def handle_osc_stop():
    state['osc_running'] = False
    emit('osc_stopped', {})
```

- [ ] **Step 3: Build frontend oscilloscope tab**

HTML: Canvas for Chart.js, channel config table (address, type, scale), timebase selector, trigger controls, measurement display (Vpp, Vmin, Vmax, freq).
JS: Rolling window Chart.js update, trigger logic, auto-scale.

- [ ] **Step 4: Test oscilloscope**

Connect MCU, read a known variable, verify waveform.

- [ ] **Step 5: Commit**

```bash
git add web_rttview.py
git commit -m "feat: register-based oscilloscope with 8 channels"
```

---

### Task 6: SWO/ITM Trace

**Files:**
- Modify: `web_rttview.py` — add SWO backend + frontend 3-subtab panel

**Interfaces:**
- Consumes: `state['probe'].swo_start()`, `.swo_read()`, `.swo_stop()`
- Produces: WebSocket events `swo_text`, `swo_pc_sample`, `swo_exception`
- Reuses: `core/swo_decoder.py` (SWODecoder class)

- [ ] **Step 1: Add SWO reader thread**

```python
from core.swo_decoder import SWODecoder

def swo_reader_thread():
    decoder = SWODecoder()
    decoder.on_itm_port(0, lambda data: socketio.emit('swo_text', {'text': data.decode('utf-8', errors='replace')}))
    decoder.on_pc_sample(lambda pc: socketio.emit('swo_pc_sample', {'pc': hex(pc)}))
    decoder.on_exception(lambda num, entry: socketio.emit('swo_exception', {'num': num, 'entry': entry}))

    try:
        state['probe_obj'].swo_start(speed=2000000)
    except:
        return

    while state['swo_running']:
        try:
            data = state['probe_obj'].swo_read()
            if data:
                decoder.process(data)
        except:
            pass
        socketio.sleep(0.01)
    state['probe_obj'].swo_stop()
```

- [ ] **Step 2: Add SWO WebSocket handlers**

```python
@socketio.on('swo_start')
def handle_swo_start(data):
    state['swo_running'] = True
    state['swo_elf_path'] = data.get('elf_path')
    socketio.start_background_task(swo_reader_thread)
    emit('swo_started', {})

@socketio.on('swo_stop')
def handle_swo_stop():
    state['swo_running'] = False
    emit('swo_stopped', {})
```

- [ ] **Step 3: Build frontend SWO tab with 3 sub-tabs**

- SWO Console: text display with ANSI colors
- CPU Profiler: table of functions with CPU% bars (ELF symbol resolution)
- Exception Tracker: timeline of IRQ entry/exit

- [ ] **Step 4: Test SWO**

Connect MCU with SWO output, verify ITM text appears.

- [ ] **Step 5: Commit**

```bash
git add web_rttview.py
git commit -m "feat: SWO/ITM trace with console, CPU profiler, exception tracker"
```

---

### Task 7: RTOS Task Viewer

**Files:**
- Modify: `web_rttview.py` — add RTOS backend + frontend tab

**Interfaces:**
- Consumes: `core/rtos_analyzer.py` (`RTOSAnalyzer` class)
- Produces: WebSocket event `rtos_data`

- [ ] **Step 1: Add RTOS analyzer integration**

```python
from core.rtos_analyzer import RTOSAnalyzer

@socketio.on('rtos_start')
def handle_rtos_start(data):
    state['rtos_running'] = True
    socketio.start_background_task(rtos_reader_thread)
    emit('rtos_started', {})

def rtos_reader_thread():
    analyzer = RTOSAnalyzer(state['probe'])
    while state.get('rtos_running'):
        try:
            tasks = analyzer.analyze()
            socketio.emit('rtos_data', {'tasks': [
                {
                    'name': t.name, 'state': t.state, 'priority': t.priority,
                    'stack_used': t.stack_used, 'stack_size': t.stack_size,
                    'tcb_addr': hex(t.tcb_addr), 'stack_percent': t.stack_percent,
                } for t in tasks
            ]})
        except Exception as e:
            socketio.emit('error', {'message': f'RTOS error: {e}'})
        socketio.sleep(1.0)
```

- [ ] **Step 2: Build frontend RTOS tab**

HTML: Table with columns — Name, State (color-coded), Priority, Stack (progress bar), Stack Size, TCB Address.
JS: Auto-refresh, color thresholds (green <70%, orange 70-90%, red >90%).

- [ ] **Step 3: Test RTOS viewer**

Connect MCU running FreeRTOS, verify task list appears.

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: FreeRTOS task viewer with stack usage monitoring"
```

---

### Task 8: Crash Analyzer

**Files:**
- Modify: `web_rttview.py` — add crash analyzer backend + frontend tab

**Interfaces:**
- Consumes: `state['probe'].read_reg()`, `.read_U32()`, `.halt()`, `.go()`
- Produces: WebSocket event `crash_data`

- [ ] **Step 1: Add crash analysis function (port from widgets/crash_analyzer.py)**

```python
@socketio.on('crash_analyze')
def handle_crash_analyze(data):
    try:
        probe = state['probe']
        probe.halt()

        # Read core registers
        regs = {}
        for name in ['r0','r1','r2','r3','r4','r5','r6','r7','r8','r9','r10','r11','r12','sp','lr','pc']:
            regs[name] = probe.read_reg(name)
        regs['xpsr'] = probe.read_reg('xpsr')

        # Read fault registers
        DHCSR = 0xE000EDF0
        CFSR = 0xE000ED28
        HFSR = 0xE000ED2C
        MMFAR = 0xE000ED34
        BFAR = 0xE000ED38

        faults = {
            'cfsr': probe.read_U32(CFSR),
            'hfsr': probe.read_U32(HFSR),
            'mmfar': probe.read_U32(MMFAR),
            'bfar': probe.read_U32(BFAR),
        }

        # Decode CFSR
        # ... (port bit decoding from crash_analyzer.py)

        # Stack walk
        sp = regs['sp']
        stack_data = probe.read_mem_U32(sp, 256)
        return_addrs = [addr for addr in stack_data if 0x08000000 <= addr <= 0x08200000]

        probe.go()

        emit('crash_data', {
            'registers': regs,
            'faults': faults,
            'return_addrs': [hex(a) for a in return_addrs[:20]],
        })
    except Exception as e:
        emit('error', {'message': f'Crash analysis failed: {e}'})
```

- [ ] **Step 2: Build frontend crash analyzer tab**

HTML: Register table, fault register decode panel, stack walk list with symbol resolution.
JS: Decode CFSR/HFSR bits, display fault descriptions.

- [ ] **Step 3: Test crash analyzer**

Connect MCU in fault state, verify registers and fault decode.

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: crash analyzer with fault register decoding and stack walk"
```

---

### Task 9: Flash Programmer

**Files:**
- Modify: `web_rttview.py` — add flash backend + frontend tab

**Interfaces:**
- Consumes: `state['probe'].write_mem_U8()`, `.read_mem_U8()`, `.reset()`
- Produces: WebSocket event `flash_progress`

- [ ] **Step 1: Add flash programming functions (port from widgets/flash_programmer.py)**

```python
@socketio.on('flash_file')
def handle_flash_file(data):
    try:
        file_id = data.get('file_id')
        base_addr = int(data.get('addr', '0x08000000'), 16)
        path = os.path.join(UPLOAD_DIR, file_id)

        # Parse file (BIN/HEX/ELF)
        firmware, start_addr = parse_firmware_file(path, base_addr)

        # Flash in 256-byte chunks
        probe = state['probe']
        probe.halt()
        chunk_size = 256
        total = len(firmware)

        for offset in range(0, total, chunk_size):
            chunk = firmware[offset:offset + chunk_size]
            probe.write_mem_U8(start_addr + offset, list(chunk))
            progress = min(100, int((offset + chunk_size) / total * 100))
            socketio.emit('flash_progress', {'percent': progress, 'status': 'flashing'})

        # Verify
        for offset in range(0, total, chunk_size):
            expected = firmware[offset:offset + chunk_size]
            actual = probe.read_mem_U8(start_addr + offset, len(expected))
            if list(expected) != actual:
                raise Exception(f'Verify failed at 0x{start_addr + offset:08X}')

        probe.reset()
        probe.go()
        socketio.emit('flash_progress', {'percent': 100, 'status': 'done'})
    except Exception as e:
        emit('error', {'message': f'Flash failed: {e}'})
```

- [ ] **Step 2: Add firmware file parser (BIN/HEX/ELF)**

Port Intel HEX parser and ELF PT_LOAD extractor from `widgets/flash_programmer.py`.

- [ ] **Step 3: Build frontend flash programmer tab**

HTML: File upload button, address input, flash button, progress bar, log area.
JS: Upload file, trigger flash, show progress.

- [ ] **Step 4: Test flash programmer**

Upload a .bin file, flash to MCU, verify.

- [ ] **Step 5: Commit**

```bash
git add web_rttview.py
git commit -m "feat: flash programmer with BIN/HEX/ELF support and verification"
```

---

### Task 10: SVD Register Viewer

**Files:**
- Modify: `web_rttview.py` — add SVD backend + frontend tab

**Interfaces:**
- Consumes: `core/svd_parser.py` (`parse_svd()`), `state['probe'].read_U32()`
- Produces: WebSocket events `svd_tree`, `svd_values`

- [ ] **Step 1: Add SVD loading and register reading**

```python
from core.svd_parser import parse_svd

@socketio.on('svd_load')
def handle_svd_load(data):
    try:
        file_id = data.get('file_id')
        path = os.path.join(UPLOAD_DIR, file_id)
        if not os.path.exists(path):
            svd_dir = os.path.join(os.path.dirname(__file__), 'svd')
            path = os.path.join(svd_dir, file_id)
        device = parse_svd(path)
        state['svd_device'] = device
        tree = {
            'name': device.name,
            'peripherals': [
                {
                    'name': p.name, 'base_addr': hex(p.base_address),
                    'registers': [
                        {
                            'name': r.name, 'offset': hex(r.address_offset),
                            'fields': [
                                {'name': f.name, 'bit_offset': f.bit_offset, 'bit_width': f.bit_width}
                                for f in (r.fields or [])
                            ]
                        } for r in (p.registers or [])
                    ]
                } for p in (device.peripherals or [])
            ]
        }
        emit('svd_tree', tree)
    except Exception as e:
        emit('error', {'message': f'SVD load failed: {e}'})

@socketio.on('svd_read')
def handle_svd_read(data):
    try:
        addr = int(data.get('addr', '0'), 16)
        val = state['probe'].read_U32(addr)
        emit('svd_value', {'addr': hex(addr), 'value': hex(val)})
    except Exception as e:
        emit('error', {'message': f'SVD read failed: {e}'})
```

- [ ] **Step 2: Build frontend SVD viewer tab**

HTML: Tree view (peripheral → register → field), detail panel, live value display.
JS: Tree expand/collapse, auto-refresh values, highlight changes in red.

- [ ] **Step 3: Test SVD viewer**

Load STM32F407.svd, read RCC registers.

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: SVD register viewer with live value display"
```

---

### Task 11: Core Register Viewer

**Files:**
- Modify: `web_rttview.py` — add core register backend + frontend tab

**Interfaces:**
- Consumes: `state['probe'].read_reg()`, `.read_regs()`
- Produces: WebSocket event `core_regs`

- [ ] **Step 1: Add core register reading**

```python
@socketio.on('core_regs_read')
def handle_core_regs_read():
    try:
        probe = state['probe']
        probe.halt()
        regs = {}
        # ARM Cortex-M registers
        for name in ['r0','r1','r2','r3','r4','r5','r6','r7','r8','r9','r10','r11','r12','sp','lr','pc','xpsr','msp','psp']:
            try:
                regs[name] = probe.read_reg(name)
            except:
                pass
        probe.go()
        emit('core_regs', {'registers': {k: hex(v) for k, v in regs.items()}})
    except Exception as e:
        emit('error', {'message': f'Core register read failed: {e}'})
```

- [ ] **Step 2: Build frontend core register tab**

HTML: Table with register name, value (hex), decoded fields (xPSR: exception number, Thumb, NZCVQ).
JS: Auto-refresh at 100ms, highlight changes, decode xPSR/mstatus fields.

- [ ] **Step 3: Test core register viewer**

Connect MCU, verify registers display and update.

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: core register viewer with ARM/RISC-V support"
```

---

### Task 12: Memory Viewer

**Files:**
- Modify: `web_rttview.py` — add memory viewer backend + frontend tab

**Interfaces:**
- Consumes: `state['probe'].read_mem_U8()`
- Produces: WebSocket event `mem_data`

- [ ] **Step 1: Add memory reading handler**

```python
@socketio.on('mem_read')
def handle_mem_read(data):
    try:
        addr = int(data.get('addr', '0x20000000'), 16)
        size = min(int(data.get('size', 256)), 4096)
        raw = state['probe'].read_mem_U8(addr, size)

        # Build hex dump
        lines = []
        for i in range(0, len(raw), 16):
            chunk = raw[i:i+16]
            hex_part = ' '.join(f'{b:02X}' for b in chunk)
            ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            # Determine region color
            line_addr = addr + i
            if 0x08000000 <= line_addr < 0x08200000:
                region = 'flash'
            elif 0x20000000 <= line_addr < 0x20020000:
                region = 'sram'
            else:
                region = 'peripheral'
            lines.append({
                'addr': hex(line_addr), 'hex': hex_part,
                'ascii': ascii_part, 'region': region,
            })

        emit('mem_data', {'addr': hex(addr), 'size': size, 'lines': lines})
    except Exception as e:
        emit('error', {'message': f'Memory read failed: {e}'})
```

- [ ] **Step 2: Build frontend memory viewer tab**

HTML: Address input, size selector, hex dump display with color coding (Flash=teal, SRAM=green, Peripheral=orange), ASCII sidebar.
JS: Quick-jump buttons (Flash/SRAM/Peripheral/Stack), auto-refresh at 500ms.

- [ ] **Step 3: Test memory viewer**

Read SRAM region, verify hex dump with colors.

- [ ] **Step 4: Commit**

```bash
git add web_rttview.py
git commit -m "feat: memory viewer with hex dump and region coloring"
```

---

### Task 13: Status Bar + Auto-Reconnect + Final Polish

**Files:**
- Modify: `web_rttview.py` — add status bar, auto-reconnect, settings persistence

**Interfaces:**
- Consumes: all existing WebSocket events
- Produces: WebSocket event `status_update`

- [ ] **Step 1: Add throughput monitoring**

```python
import time

_throughput = {'rx': 0, 'tx': 0, 'last': time.time()}

def update_throughput(rx_bytes=0, tx_bytes=0):
    _throughput['rx'] += rx_bytes
    _throughput['tx'] += tx_bytes
    now = time.time()
    elapsed = now - _throughput['last']
    if elapsed >= 1.0:
        socketio.emit('status_update', {
            'rx_rate': _throughput['rx'] / elapsed,
            'tx_rate': _throughput['tx'] / elapsed,
            'connected': state['connected'],
        })
        _throughput['rx'] = 0
        _throughput['tx'] = 0
        _throughput['last'] = now
```

- [ ] **Step 2: Add auto-reconnect logic**

Port from RTTView.py `_auto_reconnect()`. When RTT read fails 50 consecutive times, attempt reconnection.

- [ ] **Step 3: Add settings persistence**

Save/load settings to `setting.ini` (probe type, mode, speed, address, encoding).

- [ ] **Step 4: Add frontend status bar**

HTML: Connection LED, throughput display, frame rate.
JS: Update status bar from `status_update` events.

- [ ] **Step 5: Final integration test**

Start server, test all 11 features end-to-end:
1. Probe detection and connection
2. RTT terminal with Chinese text
3. RTT waveform
4. Register oscilloscope
5. SWO trace
6. RTOS task viewer
7. Crash analyzer
8. Flash programmer
9. SVD register viewer
10. Core register viewer
11. Memory viewer

- [ ] **Step 6: Commit**

```bash
git add web_rttview.py
git commit -m "feat: status bar, auto-reconnect, settings persistence, final polish"
```

---

### Task 14: J-Scope HSS Mode + ELF Variable Support

**Files:**
- Modify: `web_rttview.py` — add HSS variable reading

**Interfaces:**
- Consumes: ELF file parsing (pyelftools), `state['probe'].read_mem_U8()`
- Produces: WebSocket event `hss_data`

- [ ] **Step 1: Add ELF symbol extraction**

```python
def parse_elf_symbols(path):
    """Extract variable symbols from ELF file."""
    from elftools.elf.elffile import ELFFile
    symbols = []
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        if symtab:
            for sym in symtab.iter_symbols():
                if sym['st_size'] > 0 and sym['st_info']['type'] == 'STT_OBJECT':
                    symbols.append({
                        'name': sym.name,
                        'addr': sym['st_value'],
                        'size': sym['st_size'],
                    })
    return symbols
```

- [ ] **Step 2: Add HSS WebSocket handlers**

```python
@socketio.on('hss_load_elf')
def handle_hss_load_elf(data):
    try:
        path = os.path.join(UPLOAD_DIR, data.get('file_id'))
        symbols = parse_elf_symbols(path)
        emit('hss_symbols', {'symbols': symbols})
    except Exception as e:
        emit('error', {'message': f'ELF parse failed: {e}'})

@socketio.on('hss_add_var')
def handle_hss_add_var(data):
    # Add variable to watch list
    pass

@socketio.on('hss_start')
def handle_hss_start(data):
    # Start reading variables at interval
    pass
```

- [ ] **Step 3: Build frontend HSS panel (add as sub-tab under Waveform)**

- [ ] **Step 4: Test HSS mode**

- [ ] **Step 5: Commit**

```bash
git add web_rttview.py
git commit -m "feat: J-Scope HSS mode with ELF variable reading"
```

---

## Verification Checklist

After all tasks, verify:

- [ ] Server starts with `python web_rttview.py`
- [ ] Browser opens automatically to `http://localhost:5000`
- [ ] All 9 tabs are visible and functional
- [ ] Probe detection works (JLink/STLink/DAPLink list)
- [ ] Connection to MCU works
- [ ] RTT terminal shows colored text with Chinese characters
- [ ] Encoding switch (auto/UTF-8/GBK) works
- [ ] Waveform display renders curves
- [ ] Oscilloscope reads memory and plots
- [ ] SWO console shows ITM output
- [ ] RTOS task viewer shows FreeRTOS tasks
- [ ] Crash analyzer reads fault registers
- [ ] Flash programmer uploads and flashes firmware
- [ ] SVD viewer loads .svd files and shows registers
- [ ] Core register viewer shows ARM/RISC-V registers
- [ ] Memory viewer shows hex dump with colors
- [ ] Status bar shows connection state and throughput
- [ ] Auto-reconnect works on MCU reset
