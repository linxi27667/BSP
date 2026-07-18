#!/usr/bin/env python3
"""Web RTTView — Browser-based SEGGER RTT Viewer with VS Code dark theme."""
import os, sys, json, threading, webbrowser, tempfile, re, ctypes, struct, time, configparser, signal
from pathlib import Path

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from core import xlink
from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe
from probes.remote_probe import RemoteProbe

os.environ['PATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'libusb-1.0.24/MinGW64/dll') + os.pathsep + os.environ['PATH']

# ─── RTT structures ───────────────────────────────────────────────────────

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

# ─── ANSI 256-color palette ────────────────────────────────────────────────
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

# ─── Flask + SocketIO server ──────────────────────────────────────────────────

app = Flask(__name__)
app.config['SECRET_KEY'] = 'rttview-secret'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ─── Global state ─────────────────────────────────────────────────────────────

state = {
    'probe': None,       # XLink facade
    'probe_obj': None,   # Raw probe object
    'connected': False,
    'rtt_running': False,
    'osc_running': False,
    'swo_running': False,
    'rtos_running': False,
    'core_regs_running': False,
    'hss_running': False,
    'rtt_cb_addr': 0,
    'a_up_addr': 0,
    'a_down_addr': 0,
    'rtt_channel': 0,
    'rtt_encoding': 'auto',
    'wave_mode': False,
    'osc_channels': [],
    'upload_dir': tempfile.mkdtemp(prefix='rttview_'),
    'svd_device': None,  # SVD parsed device object
    'probe_type': 'jlink',
    'probe_mode': 'arm',
    'probe_speed': 4000,
    'probe_address': '0x20000000',
    'probe_index': 0,
    'jlink_dll': '',
    'watch_running': False,
    'watch_items': [],
    '_watch_thread_started': False,
    'rtt_wanted': False,   # user wants RTT streaming (survives reset)
    'rtt_thread_gen': 0,   # bump to retire old reader threads
}
state_lock = threading.Lock()
UPLOAD_DIR = state['upload_dir']

RTOS_STATE_NAMES = {0: "Running", 1: "Ready", 2: "Blocked", 3: "Suspended", 4: "Deleted"}

# Web UI / settings → JLinkProbe.TIF_MAP keys (same as desktop RTTView)
MODE_MAP = {
    'swd': 'arm', 'jtag': 'armj',
    'riscv-swd': 'rv', 'riscv-jtag': 'rvj',
    'arm': 'arm', 'armj': 'armj', 'rv': 'rv', 'rvj': 'rvj',
}


def normalize_probe_mode(mode: str) -> str:
    m = (mode or 'arm').strip().lower()
    return MODE_MAP.get(m, 'arm')


def core_name_for_mode(mode: str) -> str:
    return 'Cortex-M0' if mode.startswith('arm') else 'RISC-V'


def rtt_ring_addrs(rtt_cb_addr: int, max_up: int, channel: int = 0):
    """Return (a_up_addr, a_down_addr) for the given RTT channel."""
    rb = ctypes.sizeof(RingBuffer)
    a_up = rtt_cb_addr + 16 + 4 + 4 + rb * channel
    a_down = rtt_cb_addr + 16 + 4 + 4 + rb * max_up + rb * channel
    return a_up, a_down


# Common Cortex-M / RISC-V SRAM regions (base, size_bytes) for auto RTT scan.
# Order: most common first; keep first-region size modest for slow CLI probes.
RTT_SEARCH_REGIONS = [
    (0x20000000, 0x10000),   # 64KB — covers STM32F1 medium / many M0+/M3
    (0x20000000, 0x40000),   # 256KB expand
    (0x20000000, 0x80000),   # 512KB
    (0x24000000, 0x40000),   # STM32H7
    (0x30000000, 0x20000),
    (0x10000000, 0x10000),   # CCM
    (0x20200000, 0x20000),
    (0x80000000, 0x10000),   # some RISC-V
]


def _parse_addr_or_auto(address: str):
    """Return (base_or_None, is_auto). address 'auto'/empty → auto multi-region scan."""
    s = (address or '').strip()
    if not s or s.lower() in ('auto', '0', 'search'):
        return None, True
    if re.match(r'0[xX][0-9a-fA-F]{1,8}$', s):
        return int(s, 16), False
    raise ValueError(f'Invalid RTT search address: {address}')


def _probe_is_slow(probe) -> bool:
    """True for ST-LINK_CLI / other spawn-per-call backends (also unwraps XLink)."""
    seen = set()
    cur = probe
    for _ in range(4):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        try:
            if getattr(cur, 'slow_mem', False):
                return True
            if hasattr(cur, '_using_cli') and cur._using_cli():
                return True
        except Exception:
            pass
        # XLink / adapters: peel to underlying probe
        nxt = getattr(cur, 'xlk', None) or getattr(cur, '_legacy', None) or getattr(cur, '_cli_proxy', None)
        cur = nxt
    return False


def _validate_rtt_cb(probe, cb_addr: int, channel: int = 0):
    """If cb_addr holds SEGGER RTT, return (cb, a_up, a_down, max_up) else None."""
    try:
        # One read: full CB (id + ring heads). Avoid 2× CLI on slow backend.
        cb_data = bytes(probe.read_mem_U8(cb_addr, ctypes.sizeof(SEGGER_RTT_CB)))
        if cb_data[:10] != b'SEGGER RTT':
            return None
        rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(cb_data))
        max_up = int(rtt_cb.MaxNumUpBuffers) or 1
        max_down = int(rtt_cb.MaxNumDownBuffers) or 1
        if max_up > 32 or max_down > 32 or max_up < 1:
            return None
        if channel < 0 or channel >= max_up:
            raise ValueError(
                f'RTT channel {channel} out of range (MaxNumUpBuffers={max_up})'
            )
        a_up, a_down = rtt_ring_addrs(cb_addr, max_up, channel)
        return cb_addr, a_up, a_down, max_up
    except ValueError:
        raise
    except Exception:
        return None


def _scan_region_for_rtt(probe, base: int, size: int, channel: int = 0):
    """Scan [base, base+size) for SEGGER RTT. Returns tuple or None."""
    slow = _probe_is_slow(probe)
    # Slow CLI: fewer larger reads (spawn cost dominates, not transfer size)
    step = 4096 if slow else 1024
    chunks = max(1, (size + step - 1) // step)
    chunks = min(chunks, 4 if slow else 512)  # slow: <=16KB in 4 spawns
    for i in range(chunks):
        addr = base + step * i
        try:
            # Overlap 16 so a CB straddling chunk edges is still found
            data_bytes = probe.read_mem_U8(addr, step + 16)
        except Exception:
            continue
        index = bytes(data_bytes).find(b'SEGGER RTT')
        if index == -1:
            continue
        cb_addr = addr + index
        # Reuse bytes already read when CB fully inside this chunk
        try:
            need = ctypes.sizeof(SEGGER_RTT_CB)
            if index + need <= len(data_bytes) and data_bytes[index:index + 10] == b'SEGGER RTT':
                rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(data_bytes[index:index + need]))
                max_up = int(rtt_cb.MaxNumUpBuffers) or 1
                max_down = int(rtt_cb.MaxNumDownBuffers) or 1
                if 1 <= max_up <= 32 and 1 <= max_down <= 32:
                    if channel < 0 or channel >= max_up:
                        raise ValueError(
                            f'RTT channel {channel} out of range (MaxNumUpBuffers={max_up})'
                        )
                    a_up, a_down = rtt_ring_addrs(cb_addr, max_up, channel)
                    return cb_addr, a_up, a_down, max_up
        except ValueError:
            raise
        except Exception:
            pass
        hit = _validate_rtt_cb(probe, cb_addr, channel)
        if hit:
            return hit
    return None


def scan_rtt_control_block(probe, address: str = 'auto', channel: int = 0):
    """Find SEGGER RTT control block.

    address:
      - 'auto' / empty: scan common SRAM regions
      - 0xXXXXXXXX: try exact CB first, then nearby, then auto

    Returns (cb_addr, a_up, a_down).
    """
    base, is_auto = _parse_addr_or_auto(address)
    tried = []
    slow = _probe_is_slow(probe)

    def try_region(b, size, label):
        tried.append(f'0x{b:08X}+{size:#x}')
        return _scan_region_for_rtt(probe, b, size, channel)

    # 0) Exact address as CB (reset / reconnect fast path) — 1–2 CLI calls
    if base is not None:
        tried.append(f'exact:0x{base:08X}')
        hit = _validate_rtt_cb(probe, base, channel)
        if hit:
            return hit[0], hit[1], hit[2]
        # nearby ±4KB around provided addr
        near = base & ~0x3FF
        hit = try_region(near, 0x2000 if slow else 0x10000, 'near')
        if hit:
            return hit[0], hit[1], hit[2]
        if not is_auto and not slow:
            hit = try_region(base & ~0xFFFF, 0x40000, 'user-base')
            if hit:
                return hit[0], hit[1], hit[2]

    # 1) Last known CB from this process (any probe)
    last = int(state.get('rtt_cb_addr') or 0)
    if last and last != base:
        tried.append(f'cached:0x{last:08X}')
        hit = _validate_rtt_cb(probe, last, channel)
        if hit:
            return hit[0], hit[1], hit[2]

    # 2) Auto regions — slow: single 4KB then 16KB (F1 RTT ~0x200009xx in first window)
    if slow:
        for b, size in ((0x20000000, 0x1000), (0x20000000, 0x4000), (0x20000000, 0x10000)):
            hit = try_region(b, size, 'auto')
            if hit:
                return hit[0], hit[1], hit[2]
    else:
        seen = set()
        for b, size in RTT_SEARCH_REGIONS:
            key = (b, size)
            if key in seen:
                continue
            seen.add(key)
            hit = try_region(b, size, 'auto')
            if hit:
                return hit[0], hit[1], hit[2]

    raise ValueError(
        'Can not find _SEGGER_RTT (searched: ' + ', '.join(tried[:8]) +
        ('...' if len(tried) > 8 else '') + ')'
    )


def open_probe_from_state(probe_type=None, mode=None, speed=None, index=None, dllpath=None, core=None,
                          agent=None, remote_type=None):
    """Create and open a probe using connection params (normalized mode)."""
    probe_type = probe_type or state.get('probe_type', 'jlink')
    mode = normalize_probe_mode(mode if mode is not None else state.get('probe_mode', 'arm'))
    speed = int(speed if speed is not None else state.get('probe_speed', 4000))
    index = int(index if index is not None else state.get('probe_index', 0))
    if dllpath is None:
        dllpath = state.get('jlink_dll') or None
    if dllpath == '':
        dllpath = None
    core = core or core_name_for_mode(mode)
    if agent is None:
        agent = state.get('probe_agent') or ''
    agent = (agent or '').strip()

    # Remote agent path: server has no USB; desk machine runs probe_agent.py
    if probe_type == 'remote':
        if not agent:
            raise Exception('Remote probe needs agent host (e.g. 192.168.1.10:19201)')
        host, port, token = RemoteProbe.parse_agent(agent)
        rtype = remote_type or state.get('remote_type') or 'stlink'
        probe = RemoteProbe(
            host=host, port=port, token=token,
            probe_type=rtype, index=index, dllpath=dllpath,
        )
        probe.open(mode=mode, core=core, speed=speed)
        return probe, mode

    if probe_type == 'jlink':
        if dllpath and not os.path.isfile(dllpath):
            raise FileNotFoundError(f'J-Link DLL not found: {dllpath}')
        probe = JLinkProbe(dllpath=dllpath)
    elif probe_type == 'stlink':
        stlinks = STLinkProbe.detect()
        if not stlinks:
            raise Exception('No ST-Link found')
        if index < 0 or index >= len(stlinks):
            raise Exception(f'ST-Link index {index} out of range ({len(stlinks)} found)')
        probe = STLinkProbe(device=stlinks[index][0])
    elif probe_type == 'daplink':
        daplinks = DAPLinkProbe.detect()
        if not daplinks:
            raise Exception('No DAPLink found')
        if index < 0 or index >= len(daplinks):
            raise Exception(f'DAPLink index {index} out of range ({len(daplinks)} found)')
        probe = DAPLinkProbe(probe=daplinks[index])
    elif probe_type == 'openocd':
        probe = OpenOCDProbe()
    else:
        raise ValueError(f'Unknown probe type: {probe_type}')

    # speed UI is kHz (4000 = 4 MHz); probe.open expects kHz for J-Link/pylink
    probe.open(mode=mode, core=core, speed=speed)
    return probe, mode


def stop_background_workers():
    """Stop all poller threads that touch the probe."""
    with state_lock:
        state['rtt_running'] = False
        state['rtt_thread_gen'] = int(state.get('rtt_thread_gen', 0)) + 1
        state['osc_running'] = False
        state['swo_running'] = False
        state['rtos_running'] = False
        state['core_regs_running'] = False
        state['hss_running'] = False
        state['wave_mode'] = False
        state['watch_running'] = False
    time.sleep(0.05)  # let ~10ms pollers exit

# ─── Throughput tracking ─────────────────────────────────────────────────
_throughput = {'rx': 0, 'tx': 0, 'last_time': time.time()}

def track_throughput(rx_bytes=0, tx_bytes=0):
    """Track data throughput."""
    _throughput['rx'] += rx_bytes
    _throughput['tx'] += tx_bytes

# ─── Settings persistence ────────────────────────────────────────────────
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web_settings.ini')

def _default_jlink_dll():
    """Prefer desktop setting.ini [link] jlink when it looks real."""
    ini = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setting.ini')
    if not os.path.exists(ini):
        return ''
    conf = configparser.ConfigParser()
    conf.read(ini, encoding='utf-8')
    path = conf.get('link', 'jlink', fallback='')
    if path and os.path.isfile(path) and path.lower().endswith('.dll'):
        return path
    return ''


def load_settings():
    """Load settings from INI file."""
    conf = configparser.ConfigParser()
    if os.path.exists(SETTINGS_FILE):
        conf.read(SETTINGS_FILE, encoding='utf-8')
    mode = normalize_probe_mode(conf.get('connection', 'mode', fallback='arm'))
    dll = conf.get('connection', 'jlink_dll', fallback='') or _default_jlink_dll()
    agent = conf.get('connection', 'agent', fallback='') or os.environ.get('RTTVIEW_AGENT', '')
    return {
        'probe_type': conf.get('connection', 'probe_type', fallback='jlink'),
        'probe_index': conf.getint('connection', 'probe_index', fallback=0),
        'mode': mode,
        'speed': conf.getint('connection', 'speed', fallback=4000),
        'address': conf.get('connection', 'address', fallback='auto'),
        'channel': conf.getint('connection', 'channel', fallback=0),
        'jlink_dll': dll,
        'encoding': conf.get('display', 'encoding', fallback='auto'),
        'last_rtt_cb': conf.get('connection', 'last_rtt_cb', fallback=''),
        'agent': agent,
    }

def save_settings(settings):
    """Save settings to INI file."""
    conf = configparser.ConfigParser()
    conf['connection'] = {
        'probe_type': settings.get('probe_type', 'jlink'),
        'probe_index': str(settings.get('probe_index', 0)),
        'mode': normalize_probe_mode(settings.get('mode', 'arm')),
        'speed': str(settings.get('speed', 4000)),
        'address': settings.get('address', 'auto'),
        'channel': str(settings.get('channel', 0)),
        'jlink_dll': settings.get('jlink_dll', '') or '',
        'last_rtt_cb': settings.get('last_rtt_cb', '') or '',
        'agent': settings.get('agent', '') or '',
    }
    conf['display'] = {
        'encoding': settings.get('encoding', 'auto'),
    }
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        conf.write(f)

# ─── HTTP routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/static/<path:filename>')
def serve_static(filename):
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    return send_from_directory(static_dir, filename)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'Empty filename'}), 400
    safe_name = secure_filename(f.filename)
    if not safe_name:
        return jsonify({'error': 'Invalid filename'}), 400
    path = os.path.join(UPLOAD_DIR, safe_name)
    f.save(path)
    return jsonify({'file_id': safe_name, 'path': path})

@app.route('/svd_files')
def list_svd_files():
    svd_dir = os.path.join(os.path.dirname(__file__), 'svd')
    files = []
    if os.path.isdir(svd_dir):
        files = [f for f in os.listdir(svd_dir) if f.endswith('.svd')]
    return jsonify({'files': files})

# ─── Probe detection ──────────────────────────────────────────────────────

def _detect_local_probes():
    """Probes attached to the machine running web_rttview."""
    probes = [
        {'name': 'J-Link', 'type': 'jlink', 'backend': 'pylink', 'available': True},
        {'name': 'OpenOCD (TCP:6666)', 'type': 'openocd', 'backend': 'openocd', 'available': True},
    ]
    try:
        stlinks = STLinkProbe.detect()
        if not stlinks:
            probes.append({
                'name': 'ST-Link (未检测到)',
                'type': 'stlink', 'index': 0, 'backend': 'stlink', 'available': False,
            })
        for i, (dev, name) in enumerate(stlinks):
            label = name if str(name).startswith('ST-Link') else f'ST-Link · {name}'
            probes.append({
                'name': label,
                'type': 'stlink', 'index': i,
                'backend': 'stlink-cli' if dev is None else 'stlink',
                'available': True,
            })
    except Exception as e:
        probes.append({
            'name': f'ST-Link (检测失败: {e})',
            'type': 'stlink', 'index': 0, 'backend': 'stlink', 'available': False,
        })
    try:
        daplinks = DAPLinkProbe.detect()
        if not daplinks:
            probes.append({
                'name': 'DAPLink / CMSIS-DAP (未检测到)',
                'type': 'daplink', 'index': 0, 'backend': 'pyocd', 'available': False,
            })
        for i, probe in enumerate(daplinks):
            pname = getattr(probe, 'product_name', None) or 'CMSIS-DAP'
            uid = getattr(probe, 'unique_id', '') or ''
            label = f'DAPLink · {pname}' + (f' ({uid})' if uid else '')
            probes.append({
                'name': label,
                'type': 'daplink', 'index': i, 'backend': 'pyocd', 'available': True,
            })
    except Exception as e:
        probes.append({
            'name': f'DAPLink (不可用: {e})',
            'type': 'daplink', 'index': 0, 'backend': 'pyocd', 'available': False,
        })
    return probes


def _detect_remote_probes(agent: str):
    """Probes on a desk machine running probe_agent.py."""
    agent = (agent or '').strip()
    if not agent:
        return [{
            'name': '请填写 Agent 地址 (工位IP:19201)',
            'type': 'remote', 'index': 0, 'remote_type': 'stlink',
            'agent': '', 'backend': 'remote', 'available': False,
        }]
    try:
        host, port, token = RemoteProbe.parse_agent(agent)
        client = RemoteProbe(host, port, token)
        remote_list = client._client.list_probes()
        client._client.close()
        agent_s = f'{host}:{port}' + (f':{token}' if token else '')
        out = []
        for p in remote_list:
            out.append({
                'name': p.get('name') or p.get('type') or 'probe',
                'type': 'remote',
                'remote_type': p.get('type') or 'stlink',
                'index': int(p.get('index') or 0),
                'agent': agent_s,
                'backend': 'remote',
                'available': bool(p.get('available', True)),
            })
        if not out:
            out.append({
                'name': f'Agent 无探针 ({host}:{port})',
                'type': 'remote', 'index': 0, 'remote_type': 'stlink',
                'agent': agent_s, 'backend': 'remote', 'available': False,
            })
        return out
    except Exception as e:
        return [{
            'name': f'Agent 连接失败: {e}',
            'type': 'remote', 'index': 0, 'remote_type': 'stlink',
            'agent': agent, 'backend': 'remote', 'available': False,
        }]


@socketio.on('probe_detect')
def handle_probe_detect(data=None):
    """scope=local → 本机 USB; scope=remote → 工位 probe_agent。"""
    data = data or {}
    scope = (data.get('scope') or 'local').strip().lower()
    if scope not in ('local', 'remote'):
        scope = 'local'
    agent = (data.get('agent') or state.get('probe_agent') or '').strip()
    if not agent:
        try:
            agent = (load_settings().get('agent') or '').strip()
        except Exception:
            agent = ''

    if scope == 'remote':
        probes = _detect_remote_probes(agent)
    else:
        probes = _detect_local_probes()

    emit('probe_list', {'probes': probes, 'agent': agent, 'scope': scope})

@socketio.on('connect')
def handle_socket_connect():
    """New browser tab — restore UI if probe session still alive (survives refresh)."""
    if state.get('connected') and state.get('probe'):
        emit('connected', {
            'probe_type': state.get('probe_type'),
            'mode': state.get('probe_mode'),
            'index': state.get('probe_index', 0),
            'rtt_found': bool(state.get('a_up_addr')),
            'rtt_addr': hex(state['rtt_cb_addr']) if state.get('rtt_cb_addr') else None,
            'channel': state.get('rtt_channel', 0),
            'rtt_error': None,
            'search': state.get('probe_address', 'auto'),
            'reconnected': True,
            'session_restored': True,
        })
        if state.get('a_up_addr') and (
            state.get('rtt_wanted') or not state.get('rtt_running')
        ):
            try:
                _start_rtt_reader()
                emit('rtt_started', {})
            except Exception:
                pass


@socketio.on('probe_connect')
def handle_probe_connect(data):
    probe = None
    try:
        probe_type = data.get('type', 'jlink')
        mode = normalize_probe_mode(data.get('mode', 'arm'))
        speed_khz = int(data.get('speed', 4000))
        address = (data.get('address') or 'auto').strip() or 'auto'
        channel = int(data.get('channel', 0) or 0)
        dllpath = (data.get('dllpath') or data.get('jlink_dll') or '').strip() or None
        idx = int(data.get('index', 0) or 0)
        core = (data.get('core') or '').strip() or None
        agent = (data.get('agent') or '').strip()
        remote_type = (data.get('remote_type') or data.get('rtype') or '').strip() or None
        if probe_type == 'remote' and not agent:
            try:
                agent = (load_settings().get('agent') or state.get('probe_agent') or '').strip()
            except Exception:
                agent = (state.get('probe_agent') or '').strip()

        # Fast path: already connected to the same probe — skip full reopen/scan
        if (
            state.get('connected') and state.get('probe')
            and state.get('probe_type') == probe_type
            and int(state.get('probe_index', 0) or 0) == idx
            and (probe_type != 'remote' or state.get('probe_agent') == agent)
            and (probe_type != 'remote' or state.get('remote_type') == (remote_type or state.get('remote_type')))
        ):
            rtt_found = bool(state.get('a_up_addr'))
            # Channel / address change → rescan only
            if channel != int(state.get('rtt_channel', 0) or 0) or (
                address.lower() not in ('auto', '')
                and address.lower() != str(state.get('probe_address', '')).lower()
            ):
                stop_background_workers()
                try:
                    cb_addr, a_up, a_down = scan_rtt_control_block(
                        state['probe'], address, channel
                    )
                    state['rtt_cb_addr'] = cb_addr
                    state['a_up_addr'] = a_up
                    state['a_down_addr'] = a_down
                    state['rtt_channel'] = channel
                    rtt_found = True
                except Exception as e:
                    emit('error', {'message': str(e)})
                    return
            emit('connected', {
                'probe_type': probe_type,
                'mode': state.get('probe_mode', mode),
                'index': idx,
                'rtt_found': rtt_found,
                'rtt_addr': hex(state['rtt_cb_addr']) if state.get('rtt_cb_addr') else None,
                'channel': state.get('rtt_channel', channel),
                'rtt_error': None,
                'search': address,
                'session_restored': True,
            })
            if rtt_found:
                try:
                    _start_rtt_reader()
                    emit('rtt_started', {})
                except Exception:
                    pass
            return

        # Close any previous session first
        stop_background_workers()
        if state.get('probe'):
            try:
                state['probe'].close()
            except Exception:
                pass
            state['probe'] = None
            state['probe_obj'] = None
            state['connected'] = False

        state['probe_agent'] = agent
        state['remote_type'] = remote_type or state.get('remote_type') or 'stlink'
        probe, mode = open_probe_from_state(
            probe_type=probe_type, mode=mode, speed=speed_khz,
            index=idx, dllpath=dllpath, core=core,
            agent=agent, remote_type=remote_type or state.get('remote_type'),
        )
        xlk = xlink.XLink(probe)

        # Auto-find RTT (multi-region). Probe stays connected even if not found
        # so Flash / memory / core-regs still work.
        rtt_found = False
        cb_addr = a_up = a_down = 0
        rtt_err = None
        # Prefer last known CB for instant reconnect after explicit disconnect
        try:
            last_cb = int(state.get('rtt_cb_addr') or 0)
            if last_cb and address.lower() in ('auto', ''):
                try:
                    cb_addr, a_up, a_down = scan_rtt_control_block(xlk, hex(last_cb), channel)
                    rtt_found = True
                except Exception:
                    pass
            if not rtt_found:
                cb_addr, a_up, a_down = scan_rtt_control_block(xlk, address, channel)
                rtt_found = True
        except Exception as e:
            rtt_err = str(e)

        state['probe_obj'] = probe
        state['probe'] = xlk
        state['connected'] = True
        state['probe_type'] = probe_type
        state['probe_mode'] = mode
        state['probe_speed'] = speed_khz
        state['probe_address'] = address if address.lower() != 'auto' else (
            hex(cb_addr & ~0xFFFF) if rtt_found else 'auto'
        )
        state['probe_index'] = idx
        state['jlink_dll'] = dllpath or ''
        state['rtt_channel'] = channel
        state['a_up_addr'] = a_up if rtt_found else 0
        state['a_down_addr'] = a_down if rtt_found else 0
        if rtt_found:
            _remember_rtt_cb(cb_addr)
        else:
            state['rtt_cb_addr'] = state.get('rtt_cb_addr') or 0

        emit('connected', {
            'probe_type': probe_type,
            'mode': mode,
            'index': idx,
            'rtt_found': rtt_found,
            'rtt_addr': hex(cb_addr) if rtt_found else None,
            'channel': channel,
            'rtt_error': rtt_err,
            'search': address,
        })
        # Server-side auto-start RTT (more reliable than client setTimeout alone)
        if rtt_found:
            try:
                _start_rtt_reader()
                emit('rtt_started', {})
            except Exception:
                pass
    except Exception as e:
        try:
            if probe is not None:
                probe.close()
        except Exception:
            pass
        with state_lock:
            state['probe'] = None
            state['probe_obj'] = None
            state['connected'] = False
            state['a_up_addr'] = 0
            state['a_down_addr'] = 0
            # keep rtt_cb_addr for next connect fast-path
        emit('error', {'message': str(e)})

@socketio.on('probe_disconnect')
def handle_probe_disconnect():
    _do_disconnect()
    emit('disconnected', {})

@socketio.on('disconnect')
def handle_disconnect():
    """Browser tab closed/refreshed — keep probe session so reconnect is instant.

    Explicit user disconnect still goes through probe_disconnect → _do_disconnect.
    """
    # Only pause RTT push to dead sockets; do NOT close the probe.
    # Reader stays wanted so a new tab can resume immediately.
    pass


def _do_disconnect():
    with state_lock:
        state['rtt_running'] = False
        state['rtt_wanted'] = False
        state['rtt_thread_gen'] = int(state.get('rtt_thread_gen', 0)) + 1
        state['osc_running'] = False
        state['swo_running'] = False
        state['rtos_running'] = False
        state['core_regs_running'] = False
        state['hss_running'] = False
        state['watch_running'] = False
        state['wave_mode'] = False
    if state['probe']:
        try:
            state['probe'].close()
        except Exception:
            pass
    with state_lock:
        state['probe'] = None
        state['probe_obj'] = None
        state['connected'] = False
        state['a_up_addr'] = 0
        state['a_down_addr'] = 0
        state['rtt_cb_addr'] = 0

# ─── RTT Read/Write ────────────────────────────────────────────────────────

def rtt_read():
    """Read from RTT up-buffer.

    Returns b'' when idle (no new data). Raises on probe I/O failure or
    corrupt ring structure so the reader can distinguish errors from silence.
    Prefers probe.rtt_poll() (ST-LINK_CLI: 1–2 process spawns) when available.
    """
    probe = state['probe']
    if not probe or not state['a_up_addr']:
        raise RuntimeError('RTT not ready')
    a_up = state['a_up_addr']
    # Fast path: native batched poll on CLI / other slow backends
    pobj = state.get('probe_obj')
    poller = None
    for obj in (pobj, getattr(pobj, '_cli_proxy', None) if pobj else None, probe):
        if obj is not None and hasattr(obj, 'rtt_poll'):
            poller = obj
            break
    if poller is not None:
        max_chunk = 1024
        try:
            if getattr(pobj, 'slow_mem', False) or (
                hasattr(pobj, '_using_cli') and pobj._using_cli()
            ):
                max_chunk = 1024
        except Exception:
            pass
        try:
            return poller.rtt_poll(a_up, max_chunk=max_chunk) or b''
        except NotImplementedError:
            pass

    data = probe.read_mem_U8(a_up, ctypes.sizeof(RingBuffer))
    aUp = RingBuffer.from_buffer(bytearray(data))
    if not (aUp.SizeOfBuffer > 0
            and aUp.SizeOfBuffer <= 1024 * 1024
            and aUp.WrOff < aUp.SizeOfBuffer
            and aUp.RdOff < aUp.SizeOfBuffer
            and aUp.pBuffer != 0
            and aUp.Flags <= 2):
        raise RuntimeError('RTT ring buffer invalid')
    if aUp.RdOff <= aUp.WrOff:
        cnt = aUp.WrOff - aUp.RdOff
        cnt1 = cnt2 = 0
    else:
        cnt1 = aUp.SizeOfBuffer - aUp.RdOff
        cnt2 = aUp.WrOff
        cnt = cnt1 + cnt2
    if cnt <= 0 or cnt >= 1024 * 1024:
        return b''
    max_chunk = 4096
    if cnt > max_chunk:
        cnt = max_chunk
        if aUp.RdOff <= aUp.WrOff:
            cnt1 = cnt
            cnt2 = 0
        else:
            if cnt1 > max_chunk:
                cnt1 = max_chunk
                cnt2 = 0
            else:
                cnt2 = max_chunk - cnt1
            cnt = cnt1 + cnt2
    bufAddr = aUp.pBuffer
    if aUp.RdOff <= aUp.WrOff or cnt2 == 0:
        data = probe.read_mem_U8(bufAddr + aUp.RdOff, cnt)
    else:
        part1 = probe.read_mem_U8(bufAddr + aUp.RdOff, cnt1)
        part2 = probe.read_mem_U8(bufAddr, cnt2) if cnt2 else []
        data = list(part1) + list(part2)
    aUp.RdOff = (aUp.RdOff + cnt) % aUp.SizeOfBuffer
    probe.write_U32(a_up + 4 * 4, aUp.RdOff)
    return bytes(data)

def rtt_write(data_bytes):
    """Write to RTT down-buffer."""
    probe = state['probe']
    if not probe or not state['a_down_addr']:
        return
    track_throughput(tx_bytes=len(data_bytes))
    raw = probe.read_mem_U8(state['a_down_addr'], ctypes.sizeof(RingBuffer))
    aDown = RingBuffer.from_buffer(bytearray(raw))
    if aDown.WrOff >= aDown.RdOff:
        avail = aDown.SizeOfBuffer - aDown.WrOff
        if aDown.RdOff == 0:
            avail -= 1
        cnt = min(avail, len(data_bytes))
        if cnt > 0:
            probe.write_mem_U8(aDown.pBuffer + aDown.WrOff, list(data_bytes[:cnt]))
            aDown.WrOff += cnt
            if aDown.WrOff == aDown.SizeOfBuffer:
                aDown.WrOff = 0
            data_bytes = data_bytes[cnt:]
    if data_bytes and aDown.RdOff > 1:
        cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(data_bytes))
        if cnt > 0:
            probe.write_mem_U8(aDown.pBuffer + aDown.WrOff, list(data_bytes[:cnt]))
            aDown.WrOff += cnt
    probe.write_U32(state['a_down_addr'] + 4 * 3, aDown.WrOff)

# ─── Encoding helpers ──────────────────────────────────────────────────────

def decode_bytes(data, encoding='auto'):
    """Decode bytes with auto-detect or specified encoding."""
    if encoding == 'hex':
        return ' '.join(f'{b:02X}' for b in data)
    if encoding == 'ascii':
        return data.decode('ascii', errors='replace')
    if encoding == 'auto':
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            pass
        try:
            return data.decode('gbk')
        except UnicodeDecodeError:
            pass
        return data.decode('utf-8', errors='replace')
    return data.decode(encoding, errors='replace')

# ─── Waveform data parser ──────────────────────────────────────────────────

def parse_wave_data(raw_bytes, n_curve=4, encoding='float'):
    """Parse RTT waveform data. Format: comma-separated values per line.
    Returns (list of value arrays, leftover bytes).
    Each sample: [v0, v1, ... vN] where N <= n_curve.
    """
    try:
        last_comma = raw_bytes.rfind(b',')
        if last_comma < 0:
            return [], raw_bytes
        complete = raw_bytes[:last_comma]
        remainder = raw_bytes[last_comma + 1:]

        lines = complete.split(b',')
        results = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if encoding == 'hex':
                vals = [int(x, 16) for x in parts[:n_curve]]
            else:
                vals = [float(x) for x in parts[:n_curve]]
            results.append(vals)
        return results, remainder
    except Exception:
        return [], b''

# ─── ANSI-to-HTML parser ───────────────────────────────────────────────────

def parse_ansi_to_html(raw_bytes, encoding='auto'):
    """Parse raw RTT bytes into HTML segments with ANSI color support.
    Returns list of {'text': html_escaped, 'style': 'color:#xxx;background:#xxx'}.
    """
    segments = []
    text_buf = []
    bold = False
    italic = False
    fg = None
    bg = None

    def color256(n):
        return PALETTE256[max(0, min(255, n))]

    def make_style():
        parts = []
        if fg:
            parts.append(f'color:#{fg[0]:02x}{fg[1]:02x}{fg[2]:02x}')
        if bg:
            parts.append(f'background-color:#{bg[0]:02x}{bg[1]:02x}{bg[2]:02x}')
        if bold:
            parts.append('font-weight:bold')
        if italic:
            parts.append('font-style:italic')
        return ';'.join(parts)

    def flush():
        if text_buf:
            text = ''.join(text_buf)
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text = text.replace('\n', '<br>')
            segments.append({'text': text, 'style': make_style()})
            text_buf.clear()

    def parse_sgr(params):
        nonlocal bold, italic, fg, bg
        if not params:
            params = [0]
        has_color = any(30 <= p <= 37 or 90 <= p <= 97 or p in (38, 48)
                       or 40 <= p <= 47 or 100 <= p <= 107 for p in params)
        has_zero = 0 in params
        i = 0
        while i < len(params):
            code = params[i]
            if code == 0:
                if has_color and has_zero:
                    bold = False; italic = False
                else:
                    bold = False; italic = False; fg = None; bg = None
            elif code == 1:
                bold = True
            elif code == 2:
                bold = False
            elif code == 3:
                italic = True
            elif 30 <= code <= 37:
                fg = ANSI_16[code - 30]
            elif 90 <= code <= 97:
                fg = ANSI_16[code - 90 + 8]
            elif code == 38:
                if i + 1 < len(params):
                    if params[i + 1] == 5 and i + 2 < len(params):
                        fg = color256(params[i + 2]); i += 2
                    elif params[i + 1] == 2 and i + 4 < len(params):
                        fg = (params[i+2], params[i+3], params[i+4]); i += 4
            elif 40 <= code <= 47:
                bg = ANSI_16[code - 40]
            elif 100 <= code <= 107:
                bg = ANSI_16[code - 100 + 8]
            elif code == 48:
                if i + 1 < len(params):
                    if params[i + 1] == 5 and i + 2 < len(params):
                        bg = color256(params[i + 2]); i += 2
                    elif params[i + 1] == 2 and i + 4 < len(params):
                        bg = (params[i+2], params[i+3], params[i+4]); i += 4
            i += 1

    # Decode raw bytes to string first, then parse ANSI escapes
    text = decode_bytes(raw_bytes, encoding)
    ansi_state = 0
    csi_buf = ''
    for ch in text:
        o = ord(ch)
        if ansi_state == 0:
            if o == 0x1B:
                flush(); ansi_state = 1
            elif ch == '\n':
                text_buf.append('\n'); flush()
            elif ch == '\r':
                pass
            else:
                text_buf.append(ch)
        elif ansi_state == 1:
            if ch == '[':
                ansi_state = 2; csi_buf = ''
            elif ch == 'J':
                flush(); segments.append({'text': '', 'style': '', 'clear': True}); ansi_state = 0
            else:
                ansi_state = 0
        elif ansi_state == 2:
            if 0x30 <= o <= 0x3F or 0x20 <= o <= 0x2F:
                csi_buf += ch
            elif 0x40 <= o <= 0x7E:
                ansi_state = 0
                params = []
                if csi_buf:
                    for part in csi_buf.split(';'):
                        if part:
                            try: params.append(int(part))
                            except ValueError: params.append(0)
                if ch == 'm':
                    parse_sgr(params)
                elif ch == 'J':
                    if not params or params[0] == 2:
                        flush(); segments.append({'text': '', 'style': '', 'clear': True})
            else:
                ansi_state = 0
    flush()
    return segments

# ─── Auto-reconnect ──────────────────────────────────────────────────────

def _auto_reconnect():
    """Attempt to reconnect to probe and rescan RTT."""
    probe_type = state.get('probe_type', 'jlink')
    mode = normalize_probe_mode(state.get('probe_mode', 'arm'))
    speed = int(state.get('probe_speed', 4000))
    address = state.get('probe_address', 'auto') or 'auto'
    channel = int(state.get('rtt_channel', 0) or 0)
    dllpath = state.get('jlink_dll') or None
    idx = int(state.get('probe_index', 0) or 0)

    # Close old connection
    try:
        if state['probe']:
            state['probe'].close()
    except Exception:
        pass
    state['probe'] = None
    state['probe_obj'] = None
    state['connected'] = False

    probe = None
    try:
        probe, mode = open_probe_from_state(
            probe_type=probe_type, mode=mode, speed=speed,
            index=idx, dllpath=dllpath,
        )
        xlk = xlink.XLink(probe)
    except Exception:
        try:
            if probe is not None:
                probe.close()
        except Exception:
            pass
        raise

    state['probe_obj'] = probe
    state['probe'] = xlk
    state['probe_mode'] = mode
    state['connected'] = True

    rtt_found = False
    cb_addr = a_up = a_down = 0
    try:
        try:
            cb_addr, a_up, a_down = scan_rtt_control_block(xlk, address, channel)
        except Exception:
            cb_addr, a_up, a_down = scan_rtt_control_block(xlk, 'auto', channel)
        rtt_found = True
    except Exception as e:
        state['rtt_cb_addr'] = 0
        state['a_up_addr'] = 0
        state['a_down_addr'] = 0
        socketio.emit('connected', {
            'probe_type': probe_type,
            'mode': mode,
            'rtt_found': False,
            'rtt_addr': None,
            'channel': channel,
            'reconnected': True,
            'rtt_error': str(e),
        })
        return

    state['rtt_cb_addr'] = cb_addr
    state['a_up_addr'] = a_up
    state['a_down_addr'] = a_down
    socketio.emit('connected', {
        'probe_type': probe_type,
        'mode': mode,
        'rtt_found': True,
        'rtt_addr': hex(cb_addr),
        'channel': channel,
        'reconnected': True,
    })

# ─── RTT background reader ─────────────────────────────────────────────────

def _start_rtt_reader():
    """Start (or restart) RTT reader thread; retires older generations."""
    state['rtt_wanted'] = True
    state['rtt_thread_gen'] = int(state.get('rtt_thread_gen', 0)) + 1
    gen = state['rtt_thread_gen']
    state['rtt_running'] = True
    socketio.start_background_task(rtt_reader_thread, gen)
    return gen


def _stop_rtt_reader(clear_wanted=False):
    state['rtt_running'] = False
    if clear_wanted:
        state['rtt_wanted'] = False
    # allow in-flight poll to exit
    time.sleep(0.05)


def _rescan_rtt_with_retry(probe, address=None, channel=None, retries=12, delay=0.15):
    """After reset, firmware may need time to re-create RTT CB."""
    address = address or state.get('probe_address') or 'auto'
    channel = int(channel if channel is not None else state.get('rtt_channel', 0) or 0)
    last_err = None
    for i in range(retries):
        try:
            # Prefer last known base first, then full auto
            try:
                cb, a_up, a_down = scan_rtt_control_block(probe, address, channel)
            except Exception:
                cb, a_up, a_down = scan_rtt_control_block(probe, 'auto', channel)
            state['rtt_cb_addr'] = cb
            state['a_up_addr'] = a_up
            state['a_down_addr'] = a_down
            state['rtt_channel'] = channel
            return cb, a_up, a_down
        except Exception as e:
            last_err = e
            time.sleep(delay)
    if last_err:
        raise last_err
    raise RuntimeError('RTT rescan failed')


def rtt_reader_thread(gen=None):
    """Background thread: reads RTT data and pushes via WebSocket."""
    fail_count = 0
    wave_buf = b''
    my_gen = gen if gen is not None else state.get('rtt_thread_gen', 0)
    while state.get('rtt_running') and state.get('rtt_thread_gen') == my_gen:
        raw = b''
        try:
            encoding = state.get('rtt_encoding', 'auto')
            raw = rtt_read()  # b'' = idle; raises on real errors
            if raw:
                fail_count = 0
                track_throughput(rx_bytes=len(raw))
                if state.get('wave_mode'):
                    wave_buf += raw
                    samples, wave_buf = parse_wave_data(
                        wave_buf,
                        n_curve=state.get('wave_ncurve', 4),
                        encoding='float' if encoding != 'hex' else 'hex'
                    )
                    if samples:
                        socketio.emit('wave_data', {'samples': samples})
                else:
                    segments = parse_ansi_to_html(raw, encoding)
                    text = decode_bytes(raw, encoding)
                    socketio.emit('rtt_data', {
                        'segments': segments,
                        'text': text,
                        'length': len(raw),
                    })
            # idle: do NOT increment fail_count
        except Exception:
            fail_count += 1
            if fail_count >= 50:  # ~0.5s of continuous errors
                socketio.emit('rtt_data', {'text': '', 'segments': [], 'reconnect': True})
                try:
                    _auto_reconnect()
                    socketio.emit('rtt_data', {
                        'text': '[+] 自动重连成功\n',
                        'segments': [{'text': '[+] 自动重连成功<br>', 'style': 'color:var(--green)'}],
                    })
                    fail_count = 0
                except Exception as re_err:
                    socketio.emit('rtt_data', {
                        'text': f'[!] 自动重连失败: {re_err}\n',
                        'segments': [{'text': f'[!] 自动重连失败: {re_err}<br>', 'style': 'color:var(--red)'}],
                    })
                    fail_count = 0
        # Poll gap: CLI is still process-spawn bound; keep short so logs don't overflow.
        poll = 0.01
        try:
            pobj = state.get('probe_obj')
            if pobj is not None and (
                getattr(pobj, 'slow_mem', False)
                or (hasattr(pobj, '_using_cli') and pobj._using_cli())
            ):
                # floor 40ms — rtt_poll is 1–2 CLI launches now
                poll = max(0.04, float(getattr(pobj, 'rtt_poll_ms', 40) or 40) / 1000.0)
        except Exception:
            pass
        # If we just got data, immediately re-poll (drain ring faster after reset bursts)
        if raw:
            poll = min(poll, 0.02)
        socketio.sleep(poll)

# ─── WebSocket RTT handlers ────────────────────────────────────────────────

@socketio.on('rtt_start')
def handle_rtt_start(data):
    if not state.get('connected') or not state.get('probe'):
        # Soft-ignore: client may race right after connect; server already auto-starts
        return
    # If CB missing, try auto-scan before starting
    if not state.get('a_up_addr'):
        try:
            addr = (data or {}).get('address') or state.get('probe_address') or 'auto'
            ch = int((data or {}).get('channel', state.get('rtt_channel', 0)) or 0)
            cb, a_up, a_down = _rescan_rtt_with_retry(state['probe'], addr, ch, retries=8, delay=0.1)
            emit('rtt_found', {'rtt_addr': hex(cb), 'channel': ch})
        except Exception as e:
            emit('error', {'message': f'RTT not found: {e}'})
            return
    state['rtt_encoding'] = (data or {}).get('encoding', state.get('rtt_encoding', 'auto'))
    # Already streaming → just ack (avoid gen churn / false errors)
    if state.get('rtt_running') and state.get('rtt_wanted'):
        emit('rtt_started', {})
        return
    _start_rtt_reader()
    emit('rtt_started', {})

@socketio.on('rtt_stop')
def handle_rtt_stop():
    _stop_rtt_reader(clear_wanted=True)
    emit('rtt_stopped', {})

@socketio.on('rtt_rescan')
def handle_rtt_rescan(data):
    """Re-scan RTT CB without reconnecting the probe."""
    if not state['connected'] or not state.get('probe'):
        emit('error', {'message': 'Not connected'})
        return
    address = (data or {}).get('address') or state.get('probe_address') or 'auto'
    channel = int((data or {}).get('channel', state.get('rtt_channel', 0)) or 0)
    want = bool(state.get('rtt_wanted') or state.get('rtt_running') or (data or {}).get('auto_start', True))
    _stop_rtt_reader(clear_wanted=False)
    try:
        cb, a_up, a_down = _rescan_rtt_with_retry(state['probe'], address, channel)
        state['probe_address'] = address
        emit('rtt_found', {'rtt_addr': hex(cb), 'channel': channel, 'search': address})
        if want:
            _start_rtt_reader()
            emit('rtt_started', {})
    except Exception as e:
        emit('error', {'message': f'RTT rescan failed: {e}'})

@socketio.on('rtt_send')
def handle_rtt_send(data):
    if not state['connected']:
        return
    text = data.get('data', '') or data.get('text', '')
    encoding = data.get('encoding', 'utf-8')
    try:
        # HTML select may send literal "\\n" — normalize common endings
        if text.endswith('\\r\\n'):
            text = text[:-4] + '\r\n'
        elif text.endswith('\\n'):
            text = text[:-2] + '\n'
        elif text.endswith('\\r'):
            text = text[:-2] + '\r'
        encoded = text.encode(encoding)
        rtt_write(encoded)
        emit('rtt_sent', {'ok': True})
    except Exception as e:
        emit('error', {'message': f'Send failed: {e}'})

@socketio.on('set_encoding')
def handle_set_encoding(data):
    state['rtt_encoding'] = data.get('encoding', 'auto')

# ─── Settings WebSocket handlers ──────────────────────────────────────────

def _remember_rtt_cb(cb_addr: int):
    """Cache RTT CB in memory + settings.ini for next-process fast connect."""
    if not cb_addr:
        return
    state['rtt_cb_addr'] = int(cb_addr)
    try:
        s = load_settings()
        hx = hex(int(cb_addr))
        if s.get('last_rtt_cb') != hx:
            s['last_rtt_cb'] = hx
            save_settings(s)
    except Exception:
        pass


def _bootstrap_cached_rtt():
    """Load last_rtt_cb from settings into state at process start."""
    try:
        s = load_settings()
        raw = (s.get('last_rtt_cb') or '').strip()
        if raw:
            state['rtt_cb_addr'] = int(raw, 16) if raw.lower().startswith('0x') else int(raw, 0)
    except Exception:
        pass


_bootstrap_cached_rtt()


@socketio.on('get_settings')
def handle_get_settings():
    emit('settings', load_settings())

@socketio.on('save_settings')
def handle_save_settings(data):
    save_settings(data)
    emit('settings_saved', {})

# ─── Throughput reporter ──────────────────────────────────────────────────

def throughput_reporter_thread():
    """Emit throughput stats every second."""
    while True:
        now = time.time()
        elapsed = now - _throughput['last_time']
        if elapsed >= 1.0:
            rx_rate = _throughput['rx'] / elapsed
            tx_rate = _throughput['tx'] / elapsed
            socketio.emit('status_update', {
                'connected': state['connected'],
                'rx_rate': rx_rate,
                'tx_rate': tx_rate,
                'probe_type': state.get('probe_type', ''),
            })
            _throughput['rx'] = 0
            _throughput['tx'] = 0
            _throughput['last_time'] = now
        socketio.sleep(1.0)

# ─── WebSocket wave handlers ───────────────────────────────────────────────

@socketio.on('wave_start')
def handle_wave_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    state['wave_ncurve'] = data.get('ncurve', 4)
    state['wave_npoint'] = data.get('npoint', 1000)
    state['wave_mode'] = True
    if not state['rtt_running']:
        _start_rtt_reader()
    emit('wave_started', {})

@socketio.on('wave_stop')
def handle_wave_stop():
    state['wave_mode'] = False
    emit('wave_stopped', {})

# ─── Oscilloscope background thread ────────────────────────────────────────

def oscilloscope_thread():
    """Read MCU memory at ~100Hz and push waveform data."""
    channels = state.get('osc_channels', [])
    timebase = state.get('osc_timebase', 0.01)
    trigger_mode = state.get('osc_trigger', 'free')
    trigger_level = state.get('osc_trigger_level', 0.0)
    trigger_ch = state.get('osc_trigger_ch', 0)
    single_shot = state.get('osc_single', False)

    n_points = 500
    buffers = [[] for _ in range(len(channels))]
    prev_trigger_val = None
    triggered = (trigger_mode == 'free')  # free mode: always triggered

    while state['osc_running']:
        if not state['connected'] or not state['probe']:
            socketio.sleep(0.1)
            continue

        values = []
        for i, ch in enumerate(channels):
            try:
                addr = ch['addr']
                dtype = ch.get('type', 'uint32')
                scale = ch.get('scale', 1.0)

                if dtype in ('uint32', 'int32'):
                    raw = state['probe'].read_U32(addr)
                    if dtype == 'int32' and raw >= 0x80000000:
                        raw -= 0x100000000
                    val = raw * scale
                elif dtype == 'float':
                    raw = state['probe'].read_U32(addr)
                    val = struct.unpack('f', struct.pack('I', raw))[0] * scale
                elif dtype in ('uint16', 'int16'):
                    raw_list = state['probe'].read_mem_U16(addr, 1)
                    raw = raw_list[0] if raw_list else 0
                    if dtype == 'int16' and raw >= 0x8000:
                        raw -= 0x10000
                    val = raw * scale
                else:
                    val = 0
                values.append(val)
            except Exception:
                values.append(None)

        # Update buffers
        for i, val in enumerate(values):
            if i < len(buffers):
                buffers[i].append(val if val is not None else 0)
                if len(buffers[i]) > n_points:
                    buffers[i] = buffers[i][-n_points:]

        # Trigger logic
        emit_data = True
        if trigger_mode != 'free' and len(values) > trigger_ch:
            curr = values[trigger_ch]
            if prev_trigger_val is not None:
                if trigger_mode == 'rising' and prev_trigger_val < trigger_level and curr >= trigger_level:
                    triggered = True
                elif trigger_mode == 'falling' and prev_trigger_val > trigger_level and curr <= trigger_level:
                    triggered = True
            prev_trigger_val = curr
            if not triggered and not single_shot:
                pass  # Free-running, always emit
            elif single_shot and triggered:
                state['osc_running'] = False

        # Only emit data when triggered
        if not triggered:
            socketio.sleep(timebase)
            continue

        # Compute measurements
        measurements = []
        for i, buf in enumerate(buffers):
            if buf:
                vmin = min(buf)
                vmax = max(buf)
                vpp = vmax - vmin
                vavg = sum(buf) / len(buf)
                measurements.append({
                    'min': round(vmin, 3),
                    'max': round(vmax, 3),
                    'pp': round(vpp, 3),
                    'avg': round(vavg, 3),
                })
            else:
                measurements.append({'min': 0, 'max': 0, 'pp': 0, 'avg': 0})

        socketio.emit('osc_data', {
            'values': values,
            'buffers': [b[-n_points:] for b in buffers],
            'measurements': measurements,
        })

        socketio.sleep(timebase)

# ─── Oscilloscope WebSocket handlers ───────────────────────────────────────

@socketio.on('osc_start')
def handle_osc_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    if state.get('osc_running'):
        emit('osc_started', {})
        return
    channels = data.get('channels', [])
    if not channels:
        emit('error', {'message': 'No channels configured'})
        return
    # Validate channels
    for ch in channels:
        if 'addr' not in ch:
            emit('error', {'message': 'Channel missing address'})
            return
        try:
            ch['addr'] = int(str(ch['addr']), 16)
        except Exception:
            emit('error', {'message': f'Invalid address: {ch["addr"]}'})
            return

    state['osc_channels'] = channels
    state['osc_timebase'] = data.get('timebase', 0.01)
    state['osc_trigger'] = data.get('trigger', 'free')
    state['osc_trigger_level'] = data.get('trigger_level', 0.0)
    state['osc_trigger_ch'] = data.get('trigger_ch', 0)
    state['osc_single'] = data.get('single', False)
    state['osc_running'] = True
    socketio.start_background_task(oscilloscope_thread)
    emit('osc_started', {})

@socketio.on('osc_stop')
def handle_osc_stop():
    state['osc_running'] = False
    emit('osc_stopped', {})

# ─── SWO helper ──────────────────────────────────────────────────────

def _exception_name(num):
    """Return ARM Cortex-M exception name from number."""
    names = {
        0: 'Thread Mode', 1: 'Reset', 2: 'NMI', 3: 'HardFault',
        4: 'MemManage', 5: 'BusFault', 6: 'UsageFault',
        11: 'SVCall', 12: 'Debug Monitor', 14: 'PendSV', 15: 'SysTick',
    }
    return names.get(num, f'IRQ {num - 16}' if num >= 16 else f'Exception {num}')

# ─── SWO background reader ──────────────────────────────────────────

def swo_reader_thread():
    """Background thread: reads SWO data and pushes via WebSocket."""
    from core.swo_decoder import SWODecoder

    decoder = SWODecoder()
    profiler_data = {}  # {pc_addr: count}
    total_samples = [0]  # use list for closure mutation

    def on_itm(frame):
        text = frame.data.decode('utf-8', errors='replace')
        socketio.emit('swo_text', {'text': text})

    def on_pc_sample(sample):
        pc = sample.pc
        total_samples[0] += 1
        profiler_data[pc] = profiler_data.get(pc, 0) + 1
        if total_samples[0] % 100 == 0:
            top = sorted(profiler_data.items(), key=lambda x: -x[1])[:20]
            socketio.emit('swo_profiler', {
                'samples': total_samples[0],
                'functions': [
                    {'addr': f'0x{pc:08X}', 'count': cnt,
                     'pct': round(cnt / total_samples[0] * 100, 1)}
                    for pc, cnt in top
                ],
            })

    def on_exception(event):
        socketio.emit('swo_exception', {
            'num': event.exception_number,
            'entry': event.event_type == 'entry',
            'name': _exception_name(event.exception_number),
        })

    decoder.on_itm_port(0, on_itm)
    decoder.on_pc_sample(on_pc_sample)
    decoder.on_exception(on_exception)

    try:
        probe = state['probe_obj']
        swo_speed = state.get('swo_speed', 2000000)
        probe.swo_start(swo_speed)
    except Exception as e:
        socketio.emit('error', {'message': f'SWO start failed: {e}'})
        return

    while state['swo_running']:
        try:
            data = state['probe_obj'].swo_read()
            if data:
                track_throughput(rx_bytes=len(data))
                decoder.feed(data)
        except Exception:
            pass
        socketio.sleep(0.01)

    try:
        state['probe_obj'].swo_stop()
    except Exception:
        pass

# ─── WebSocket SWO handlers ─────────────────────────────────────────

@socketio.on('swo_start')
def handle_swo_start(data):
    if not state['connected'] or not state['probe_obj']:
        emit('error', {'message': 'Not connected'})
        return
    if state.get('swo_running'):
        emit('swo_started', {})
        return
    state['swo_speed'] = data.get('speed', 2000000)
    state['swo_running'] = True
    socketio.start_background_task(swo_reader_thread)
    emit('swo_started', {})

@socketio.on('swo_stop')
def handle_swo_stop():
    state['swo_running'] = False
    emit('swo_stopped', {})

# ─── RTOS reader thread ─────────────────────────────────────────────────────

def rtos_reader_thread():
    """Background thread: reads FreeRTOS task list and pushes via WebSocket."""
    from core.rtos_analyzer import FreeRTOSAnalyzer

    try:
        analyzer = FreeRTOSAnalyzer(state['probe'])
    except Exception as e:
        socketio.emit('error', {'message': f'RTOS init failed: {e}'})
        return

    while state.get('rtos_running'):
        try:
            tasks = analyzer.read_tasks()
            # Sort: Running first, then by priority descending
            tasks.sort(key=lambda t: (t.state != 0, -t.priority))
            task_list = []
            for t in tasks:
                task_list.append({
                    'name': t.name,
                    'state': RTOS_STATE_NAMES.get(t.state, f'Unknown({t.state})'),
                    'state_code': t.state,
                    'priority': t.priority,
                    'stack_used': t.stack_used,
                    'stack_size': t.stack_size,
                    'stack_percent': round(t.stack_usage_percent, 1),
                    'tcb_addr': f'0x{t.tcb_addr:08X}',
                })
            socketio.emit('rtos_data', {'tasks': task_list})
        except Exception as e:
            socketio.emit('error', {'message': f'RTOS read error: {e}'})
        socketio.sleep(1.0)

# ─── WebSocket RTOS handlers ─────────────────────────────────────────────────

@socketio.on('rtos_start')
def handle_rtos_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    if state.get('rtos_running'):
        emit('rtos_started', {})
        return
    state['rtos_running'] = True
    socketio.start_background_task(rtos_reader_thread)
    emit('rtos_started', {})

@socketio.on('rtos_stop')
def handle_rtos_stop():
    state['rtos_running'] = False
    emit('rtos_stopped', {})

# ─── Crash analyzer ──────────────────────────────────────────────────────

@socketio.on('crash_analyze')
def handle_crash_analyze(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    try:
        probe = state['probe']
        probe.halt()

        # Read core registers
        reg_names = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7',
                     'r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc']
        regs = {}
        for name in reg_names:
            try:
                regs[name] = probe.read_reg(name)
            except Exception:
                regs[name] = None
        try:
            regs['xpsr'] = probe.read_reg('xpsr')
        except Exception:
            regs['xpsr'] = None

        # Read fault registers from ARM System Control Space
        faults = {}
        fault_addrs = {
            'cfsr': 0xE000ED28, 'hfsr': 0xE000ED2C,
            'mmfar': 0xE000ED34, 'bfar': 0xE000ED38,
            'afsr': 0xE000ED3C, 'dhcsr': 0xE000EDF0,
        }
        for name, addr in fault_addrs.items():
            try:
                faults[name] = probe.read_U32(addr)
            except Exception:
                faults[name] = 0

        # Decode CFSR
        cfsr = faults.get('cfsr', 0)
        cfsr_decode = {}

        # MemManage fault status (bits 0-7)
        if cfsr & 0xFF:
            mm = cfsr & 0xFF
            cfsr_decode['MemManage'] = {
                'IACCVIOL': bool(mm & 0x01),
                'DACCVIOL': bool(mm & 0x02),
                'MUNSTKERR': bool(mm & 0x08),
                'MSTKERR': bool(mm & 0x10),
                'MLSPERR': bool(mm & 0x20),
                'MMARVALID': bool(mm & 0x80),
            }

        # BusFault status (bits 8-15)
        if cfsr & 0xFF00:
            bf = (cfsr >> 8) & 0xFF
            cfsr_decode['BusFault'] = {
                'IBUSERR': bool(bf & 0x01),
                'PRECISERR': bool(bf & 0x02),
                'IMPRECISERR': bool(bf & 0x04),
                'UNSTKERR': bool(bf & 0x08),
                'STKERR': bool(bf & 0x10),
                'LSPERR': bool(bf & 0x20),
                'BFARVALID': bool(bf & 0x80),
            }

        # UsageFault status (bits 16-25)
        if cfsr & 0x3FF0000:
            uf = (cfsr >> 16) & 0x3FF
            cfsr_decode['UsageFault'] = {
                'UNDEFINSTR': bool(uf & 0x01),
                'INVSTATE': bool(uf & 0x02),
                'INVPC': bool(uf & 0x04),
                'NOCP': bool(uf & 0x08),
                'UNALIGNED': bool(uf & 0x100),
                'DIVBYZERO': bool(uf & 0x200),
            }

        # Decode HFSR
        hfsr = faults.get('hfsr', 0)
        hfsr_decode = {
            'VECTTBL': bool(hfsr & 0x02),
            'FORCED': bool(hfsr & 0x40000000),
            'DEBUGEVT': bool(hfsr & 0x80000000),
        }

        # Decode xPSR
        xpsr = regs.get('xpsr', 0)
        xpsr_decode = {}
        if xpsr is not None:
            xpsr_decode = {
                'exception_number': xpsr & 0x1FF,
                'thumb': bool(xpsr & (1 << 24)),
                'negative': bool(xpsr & (1 << 31)),
                'zero': bool(xpsr & (1 << 30)),
                'carry': bool(xpsr & (1 << 29)),
                'overflow': bool(xpsr & (1 << 28)),
            }

        # Stack walk: scan stack for values in flash region (heuristic)
        sp = regs.get('sp', 0)
        stack_addrs = []
        if sp:
            try:
                stack_data = probe.read_mem_U32(sp & 0xFFFFFFFC, 256)
                for val in stack_data:
                    if val and 0x00000000 <= val <= 0x20000000:
                        stack_addrs.append(val)
            except Exception:
                pass

        probe.go()

        # Determine fault address: MMFAR if MMARVALID, else BFAR if BFARVALID
        if cfsr & 0x80:
            fault_addr = faults.get('mmfar', 0)
        elif cfsr & 0x8000:
            fault_addr = faults.get('bfar', 0)
        else:
            fault_addr = 0

        emit('crash_data', {
            'registers': {k: f'0x{v:08X}' if v is not None else 'N/A' for k, v in regs.items()},
            'faults': {k: f'0x{v:08X}' for k, v in faults.items()},
            'cfsr_decode': cfsr_decode,
            'hfsr_decode': hfsr_decode,
            'xpsr_decode': xpsr_decode,
            'stack_addrs': [f'0x{a:08X}' for a in stack_addrs[:20]],
            'fault_addr': f'0x{fault_addr:08X}',
        })
    except Exception as e:
        emit('error', {'message': f'Crash analysis failed: {e}'})
        try:
            state['probe'].go()
        except Exception:
            pass

# ─── Firmware file parsers ─────────────────────────────────────────────

def parse_firmware_file(path, base_addr=0x08000000):
    """Parse BIN/HEX/ELF file. Returns (firmware_bytes, start_addr)."""
    ext = os.path.splitext(path)[1].lower()

    if ext == '.bin':
        with open(path, 'rb') as f:
            return f.read(), base_addr

    elif ext in ('.hex', '.ihex'):
        data, min_addr = parse_intel_hex(path)
        return data, min_addr if min_addr is not None else base_addr

    elif ext == '.elf':
        return parse_elf_segments(path)

    else:
        # Try as raw binary
        with open(path, 'rb') as f:
            return f.read(), base_addr


def parse_intel_hex(path):
    """Parse Intel HEX file into flat binary. Returns (bytes, min_addr)."""
    records = []
    base = 0
    min_addr = 0xFFFFFFFF
    max_addr = 0

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith(':'):
                continue
            byte_count = int(line[1:3], 16)
            address = int(line[3:7], 16)
            record_type = int(line[7:9], 16)
            payload = line[9:9 + byte_count * 2]

            if record_type == 0x00:  # Data
                addr = base + address
                min_addr = min(min_addr, addr)
                max_addr = max(max_addr, addr + byte_count)
                records.append((addr, payload, byte_count))

            elif record_type == 0x02:  # Extended Segment Address
                base = int(payload, 16) << 4

            elif record_type == 0x04:  # Extended Linear Address
                base = int(payload, 16) << 16

            elif record_type == 0x01:  # EOF
                break

    if min_addr > max_addr:
        return b'', None

    data = bytearray(b'\xff' * (max_addr - min_addr))
    for addr, payload, byte_count in records:
        for i in range(byte_count):
            data[addr - min_addr + i] = int(payload[i * 2:i * 2 + 2], 16)

    return bytes(data), min_addr


def parse_elf_segments(path):
    """Parse ELF file, extract PT_LOAD segments. Returns (bytes, min_addr)."""
    with open(path, 'rb') as f:
        ident = f.read(16)
        if ident[:4] != b'\x7fELF':
            raise ValueError('Not an ELF file')

        is_32 = ident[4] == 1
        is_le = ident[5] == 1

        if is_le:
            fmt32 = '<HHIIIIIHHHHHH'
            fmt64 = '<HHIQQQIHHHHHH'
        else:
            fmt32 = '>HHIIIIIHHHHHH'
            fmt64 = '>HHIQQQIHHHHHH'

        if is_32:
            header = struct.unpack(fmt32, f.read(36))
            phoff = header[5]
            phnum = header[10]
            fmt_ph = '<IIIIIIII' if is_le else '>IIIIIIII'
            ph_size = 32
        else:
            header = struct.unpack(fmt64, f.read(48))
            phoff = header[4]
            phnum = header[10]
            fmt_ph = '<IIQQQQQQ' if is_le else '>IIQQQQQQ'
            ph_size = 56

        segments = []
        for i in range(phnum):
            f.seek(phoff + i * ph_size)
            ph_data = f.read(ph_size)
            if is_32:
                ph = struct.unpack(fmt_ph, ph_data)
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = ph[0], ph[1], ph[2], ph[3], ph[4], ph[5]
            else:
                ph = struct.unpack(fmt_ph, ph_data)
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = ph[0], ph[2], ph[3], ph[4], ph[5], ph[6]

            if p_type == 1 and p_filesz > 0:  # PT_LOAD
                f.seek(p_offset)
                seg_data = f.read(p_filesz)
                segments.append((p_paddr, seg_data))

        if not segments:
            raise ValueError('No loadable segments in ELF')

        min_addr = min(addr for addr, _ in segments)
        max_addr = max(addr + len(data) for addr, data in segments)
        firmware = bytearray(b'\xff' * (max_addr - min_addr))
        for addr, data in segments:
            firmware[addr - min_addr:addr - min_addr + len(data)] = data

        return bytes(firmware), min_addr


# ─── Flash programming handler ─────────────────────────────────────────

def _rescan_rtt_after_flash():
    """Re-find RTT CB after programming; return True if found."""
    address = state.get('probe_address', '0x20000000')
    channel = int(state.get('rtt_channel', 0) or 0)
    probe = state.get('probe')
    if not probe:
        return False
    try:
        cb_addr, a_up, a_down = scan_rtt_control_block(probe, address, channel)
        state['rtt_cb_addr'] = cb_addr
        state['a_up_addr'] = a_up
        state['a_down_addr'] = a_down
        return True
    except Exception:
        state['a_up_addr'] = 0
        state['a_down_addr'] = 0
        state['rtt_cb_addr'] = 0
        return False


@socketio.on('flash_file')
def handle_flash_file(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return

    file_id = data.get('file_id')
    base_addr_str = data.get('addr', '0x08000000')
    verify = data.get('verify', True)
    resume_rtt = data.get('resume_rtt', True)

    try:
        base_addr = int(base_addr_str, 16) if str(base_addr_str).strip().lower().startswith('0x') else int(base_addr_str)
    except Exception:
        emit('error', {'message': f'Invalid address: {base_addr_str}'})
        return

    path = os.path.join(UPLOAD_DIR, secure_filename(file_id) if file_id else '')
    if not file_id or not os.path.exists(path):
        # allow original name if secure_filename stripped path was wrong
        path = os.path.join(UPLOAD_DIR, file_id or '')
    if not os.path.exists(path):
        emit('error', {'message': f'File not found: {file_id}'})
        return

    was_rtt = bool(state.get('rtt_running'))
    try:
        # Pause RTT and other workers so they don't fight flash
        stop_background_workers()
        socketio.emit('rtt_stopped', {})
        socketio.emit('flash_progress', {'percent': 0, 'status': '解析文件...'})

        firmware, start_addr = parse_firmware_file(path, base_addr)
        total = len(firmware)
        if total == 0:
            emit('error', {'message': 'Empty firmware'})
            return

        probe_obj = state.get('probe_obj')
        probe = state.get('probe')
        ext = os.path.splitext(path)[1].lower()
        use_jlink_flash = (
            state.get('probe_type') == 'jlink'
            and probe_obj is not None
            and hasattr(probe_obj, 'flash_file')
        )

        socketio.emit('flash_progress', {
            'percent': 10,
            'status': f'烧录 {total} 字节到 0x{start_addr:08X}...',
        })

        if use_jlink_flash:
            # pylink flash_file accepts bin/hex; for ELF write temp bin
            flash_path = path
            flash_addr = start_addr
            tmp_bin = None
            try:
                if ext in ('.elf', '.axf'):
                    fd, tmp_bin = tempfile.mkstemp(suffix='.bin', prefix='rttview_fw_')
                    os.close(fd)
                    with open(tmp_bin, 'wb') as f:
                        f.write(firmware)
                    flash_path = tmp_bin
                    flash_addr = start_addr
                elif ext in ('.hex', '.ihex'):
                    # Intel HEX: pass file as-is; addr often ignored by loader
                    flash_path = path
                    flash_addr = start_addr
                else:
                    flash_path = path
                    flash_addr = start_addr
                probe_obj.flash_file(flash_path, flash_addr)
            finally:
                if tmp_bin and os.path.exists(tmp_bin):
                    try:
                        os.unlink(tmp_bin)
                    except Exception:
                        pass
            if verify and probe is not None:
                socketio.emit('flash_progress', {'percent': 90, 'status': '校验中...'})
                # Spot-check first 256 bytes (full compare can be slow)
                n = min(256, total)
                actual = probe.read_mem_U8(start_addr, n)
                if list(actual) != list(firmware[:n]):
                    raise RuntimeError(f'Verify failed at 0x{start_addr:08X}')
        else:
            # Fallback: raw memory write (RAM or probes without flash loader)
            socketio.emit('flash_progress', {
                'percent': 15,
                'status': '非 J-Link：使用内存写（Flash 可能无效）...',
            })
            probe.halt()
            chunk_size = 256
            for offset in range(0, total, chunk_size):
                chunk = list(firmware[offset:offset + chunk_size])
                probe.write_mem_U8(start_addr + offset, chunk)
                percent = 15 + int(75 * (offset + len(chunk)) / total)
                socketio.emit('flash_progress', {
                    'percent': min(90, percent),
                    'status': f'写入... {offset + len(chunk)}/{total}',
                })
            if verify:
                socketio.emit('flash_progress', {'percent': 92, 'status': '校验中...'})
                for offset in range(0, total, chunk_size):
                    expected = list(firmware[offset:offset + chunk_size])
                    actual = probe.read_mem_U8(start_addr + offset, len(expected))
                    if actual != expected:
                        raise RuntimeError(f'Verify failed at 0x{start_addr + offset:08X}')

        # Reset and run new firmware
        socketio.emit('flash_progress', {'percent': 95, 'status': '复位 MCU...'})
        try:
            probe.reset()
        except Exception:
            pass
        try:
            probe.go()
        except Exception:
            pass
        time.sleep(0.2)

        rtt_ok = _rescan_rtt_after_flash()
        if resume_rtt and rtt_ok and (was_rtt or state.get('rtt_wanted') or data.get('auto_rtt', True)):
            _start_rtt_reader()
            socketio.emit('rtt_started', {})

        status = '完成! MCU 已复位运行'
        if rtt_ok:
            status += f' | RTT @ {hex(state["rtt_cb_addr"])}'
        else:
            status += ' | RTT 未找到，请手动重连'
        socketio.emit('flash_progress', {'percent': 100, 'status': status})
        emit('flash_done', {
            'size': total,
            'addr': f'0x{start_addr:08X}',
            'rtt_found': rtt_ok,
            'rtt_addr': hex(state['rtt_cb_addr']) if rtt_ok else None,
        })

    except Exception as e:
        try:
            if state.get('probe'):
                state['probe'].go()
        except Exception:
            pass
        emit('error', {'message': f'Flash failed: {e}'})
        socketio.emit('flash_progress', {'percent': 0, 'status': f'失败: {e}'})


@socketio.on('mcu_reset')
def handle_mcu_reset(data=None):
    """Reset MCU via debug probe. Always re-find RTT and resume stream if wanted."""
    data = data or {}
    halt_after = bool(data.get('halt_after', False))
    # Default: resume RTT after reset unless halt_after or explicit resume_rtt=false
    resume_rtt = data.get('resume_rtt')
    if resume_rtt is None:
        resume_rtt = (not halt_after) and bool(
            state.get('rtt_wanted') or state.get('rtt_running') or True
        )
    else:
        resume_rtt = bool(resume_rtt) and not halt_after

    if not state.get('connected') or not state.get('probe'):
        emit('error', {'message': '未连接探针，无法复位 MCU'})
        return
    try:
        probe = state['probe']
        # Stop reader so it doesn't fight reset / bad CB
        _stop_rtt_reader(clear_wanted=False)

        probe.reset()  # CLI reset already does -Rst -Run
        if halt_after:
            try:
                probe.halt()
            except Exception:
                pass
            halted = True
        else:
            # Avoid second go() on slow CLI — reset() already resumed target
            halted = False

        # Fast path: reuse last known CB after short wait; full auto only if needed
        rtt_addr = None
        rtt_err = None
        try:
            time.sleep(0.08)
            last_cb = int(state.get('rtt_cb_addr') or 0)
            ch = int(state.get('rtt_channel', 0) or 0)
            if last_cb:
                try:
                    cb, a_up, a_down = scan_rtt_control_block(probe, hex(last_cb), ch)
                except Exception:
                    cb, a_up, a_down = _rescan_rtt_with_retry(
                        probe, state.get('probe_address') or 'auto', ch,
                        retries=8, delay=0.08,
                    )
            else:
                cb, a_up, a_down = _rescan_rtt_with_retry(
                    probe, state.get('probe_address') or 'auto', ch,
                    retries=8, delay=0.08,
                )
            _remember_rtt_cb(cb)
            state['a_up_addr'] = a_up
            state['a_down_addr'] = a_down
            rtt_addr = hex(cb)
            if resume_rtt and not halt_after:
                _start_rtt_reader()
                socketio.emit('rtt_started', {})
                socketio.emit('rtt_found', {
                    'rtt_addr': rtt_addr,
                    'channel': state.get('rtt_channel', 0),
                })
                socketio.emit('rtt_data', {
                    'text': f'[+] 复位后 RTT 已恢复 @ {rtt_addr}\n',
                    'segments': [{
                        'text': f'[+] 复位后 RTT 已恢复 @ {rtt_addr}<br>',
                        'style': 'color:var(--green)',
                    }],
                })
        except Exception as e:
            rtt_err = str(e)
            state['a_up_addr'] = 0
            state['a_down_addr'] = 0
            state['rtt_cb_addr'] = 0

        emit('mcu_reset_done', {
            'halted': halted,
            'rtt_addr': rtt_addr,
            'rtt_resumed': bool(rtt_addr and resume_rtt and not halt_after),
            'rtt_error': rtt_err,
        })
        emit('cpu_state', {'halted': halted, 'reset': True})
    except Exception as e:
        emit('error', {'message': f'Reset failed: {e}'})


# ─── Serial port flash (UART bootloader / raw) ───────────────────────────────

def _serial_list_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        raise RuntimeError('需要 pyserial: pip install pyserial')
    ports = []
    for p in list_ports.comports():
        ports.append({
            'device': p.device,
            'name': p.name or p.device,
            'description': p.description or '',
            'hwid': p.hwid or '',
            'label': f'{p.device} — {p.description or p.name or ""}'.strip(' —'),
        })
    return ports


@socketio.on('serial_list')
def handle_serial_list():
    try:
        emit('serial_ports', {'ports': _serial_list_ports()})
    except Exception as e:
        emit('error', {'message': str(e)})


def _stm32_isp_checksum(data: bytes) -> int:
    c = 0
    for b in data:
        c ^= b
    return c & 0xFF


def _stm32_isp_write_mem(ser, addr: int, chunk: bytes, timeout=1.0):
    """STM32 USART bootloader Write Memory (0x31). chunk len 1..256."""
    ACK, NACK = 0x79, 0x1F
    # CMD
    ser.write(bytes([0x31, 0xCE]))
    resp = ser.read(1)
    if not resp or resp[0] != ACK:
        raise RuntimeError(f'WriteMemory cmd NACK: {resp!r}')
    # Address + checksum
    ab = struct.pack('>I', addr & 0xFFFFFFFF)
    ser.write(ab + bytes([_stm32_isp_checksum(ab)]))
    resp = ser.read(1)
    if not resp or resp[0] != ACK:
        raise RuntimeError(f'WriteMemory addr NACK @ {hex(addr)}')
    # N-1 length, data, checksum
    n = len(chunk)
    if not (1 <= n <= 256):
        raise ValueError('chunk must be 1..256 bytes')
    payload = bytes([n - 1]) + chunk
    ser.write(payload + bytes([_stm32_isp_checksum(payload)]))
    resp = ser.read(1)
    if not resp or resp[0] != ACK:
        raise RuntimeError(f'WriteMemory data NACK @ {hex(addr)}')


def _stm32_isp_erase_all(ser):
    """Global erase via Erase Memory (0x43) or Extended Erase (0x44)."""
    ACK = 0x79
    # Try Extended Erase mass (0x44): 0xFFFF
    ser.write(bytes([0x44, 0xBB]))
    resp = ser.read(1)
    if resp and resp[0] == ACK:
        # mass erase special
        ser.write(bytes([0xFF, 0xFF, 0x00]))  # N=0xFFFF means global, xor=0
        # wait longer for erase
        old = ser.timeout
        ser.timeout = 30
        resp2 = ser.read(1)
        ser.timeout = old
        if resp2 and resp2[0] == ACK:
            return 'extended_mass'
    # Fallback classic erase (0x43) global
    ser.write(bytes([0x43, 0xBC]))
    resp = ser.read(1)
    if not resp or resp[0] != ACK:
        raise RuntimeError('Erase command rejected (not in bootloader?)')
    ser.write(bytes([0xFF, 0x00]))  # global erase
    old = ser.timeout
    ser.timeout = 30
    resp2 = ser.read(1)
    ser.timeout = old
    if not resp2 or resp2[0] != ACK:
        raise RuntimeError('Global erase failed')
    return 'classic_mass'


def _serial_flash_raw(ser, data: bytes, progress_cb):
    total = len(data)
    chunk = 1024
    sent = 0
    while sent < total:
        n = min(chunk, total - sent)
        ser.write(data[sent:sent + n])
        sent += n
        progress_cb(sent, total)
        time.sleep(0.001)


def _serial_flash_stm32_isp(ser, data: bytes, base_addr: int, progress_cb, do_erase=True):
    ACK = 0x79
    # Sync: send 0x7F until ACK (auto baud)
    ser.reset_input_buffer()
    synced = False
    for _ in range(20):
        ser.write(b'\x7F')
        time.sleep(0.05)
        resp = ser.read(1)
        if resp and resp[0] == ACK:
            synced = True
            break
    if not synced:
        raise RuntimeError('STM32 ISP 同步失败：请确认 BOOT0=1 且串口接到 USART bootloader')

    # Get ID (optional)
    try:
        ser.write(bytes([0x02, 0xFD]))
        if ser.read(1) == bytes([ACK]):
            n = ser.read(1)
            if n:
                ser.read(n[0] + 1)  # id bytes + ACK
    except Exception:
        pass

    if do_erase:
        progress_cb(0, len(data), '擦除 Flash...')
        _stm32_isp_erase_all(ser)

    total = len(data)
    # pad to 4-byte
    if total % 4:
        data = data + b'\xFF' * (4 - total % 4)
        total = len(data)
    off = 0
    while off < total:
        chunk = data[off:off + 256]
        _stm32_isp_write_mem(ser, base_addr + off, chunk)
        off += len(chunk)
        progress_cb(off, total, f'写入 {off}/{total}')

    # Go
    try:
        ser.write(bytes([0x21, 0xDE]))
        if ser.read(1) == bytes([ACK]):
            ab = struct.pack('>I', base_addr & 0xFFFFFFFF)
            ser.write(ab + bytes([_stm32_isp_checksum(ab)]))
            ser.read(1)
    except Exception:
        pass


@socketio.on('serial_flash')
def handle_serial_flash(data):
    """Flash firmware over UART.

    protocol: 'raw' | 'stm32_isp'
    """
    port = (data.get('port') or '').strip()
    baud = int(data.get('baud', 115200))
    protocol = (data.get('protocol') or 'raw').lower()
    file_id = data.get('file_id')
    base_addr = int(str(data.get('addr', '0x08000000')), 0)
    do_erase = bool(data.get('erase', True))
    dtr_reset = bool(data.get('dtr_reset', False))

    if not port:
        emit('error', {'message': '未选择串口'})
        return
    path = os.path.join(UPLOAD_DIR, file_id or '')
    if not file_id or not os.path.exists(path):
        emit('error', {'message': f'文件不存在: {file_id}'})
        return

    try:
        import serial
    except ImportError:
        emit('error', {'message': '需要 pyserial: pip install pyserial'})
        return

    try:
        firmware, start = parse_firmware_file(path, base_addr)
        if start is not None and str(data.get('addr', '')).strip() in ('', 'auto'):
            base_addr = start
        if not firmware:
            emit('error', {'message': '固件为空'})
            return

        socketio.emit('serial_flash_progress', {
            'percent': 0, 'status': f'打开 {port} @ {baud}...',
        })

        ser = serial.Serial(port=port, baudrate=baud, timeout=0.5,
                            write_timeout=5, bytesize=8, parity='E' if protocol == 'stm32_isp' else 'N',
                            stopbits=1)
        try:
            if dtr_reset:
                # Common USB-UART: DTR/RTS pulse to reset / enter boot
                ser.dtr = False
                ser.rts = True
                time.sleep(0.05)
                ser.rts = False
                time.sleep(0.1)

            def progress(done, total, status=None):
                pct = int(100 * done / total) if total else 0
                socketio.emit('serial_flash_progress', {
                    'percent': min(99, pct),
                    'status': status or f'{done}/{total} 字节',
                })

            if protocol in ('stm32', 'stm32_isp', 'isp'):
                _serial_flash_stm32_isp(ser, firmware, base_addr, progress, do_erase=do_erase)
            else:
                _serial_flash_raw(ser, firmware, progress)

            socketio.emit('serial_flash_progress', {'percent': 100, 'status': '完成'})
            emit('serial_flash_done', {
                'size': len(firmware),
                'addr': hex(base_addr),
                'port': port,
                'protocol': protocol,
            })
        finally:
            ser.close()
    except Exception as e:
        emit('error', {'message': f'串口烧录失败: {e}'})
        socketio.emit('serial_flash_progress', {'percent': 0, 'status': f'失败: {e}'})


# ─── CPU control / target info / watch / disasm ──────────────────────────────

def _require_probe():
    if not state.get('connected') or not state.get('probe'):
        raise RuntimeError('Not connected')
    return state['probe'], state.get('probe_obj')


def _simple_thumb_disasm(probe, addr, count):
    """Minimal Thumb dump when native disassemble unavailable."""
    lines = []
    a = int(addr) & ~1
    for _ in range(int(count)):
        try:
            hw = probe.read_mem_U16(a, 1)[0] if hasattr(probe, 'read_mem_U16') else (
                probe.read_mem_U8(a, 2)[0] | (probe.read_mem_U8(a, 2)[1] << 8)
            )
            # 32-bit Thumb if high half in 0xE8xx/F0xx range (simplified)
            if (hw & 0xF800) in (0xE800, 0xF000, 0xF800):
                hw2 = probe.read_mem_U8(a + 2, 2)
                w = hw | ((hw2[0] | (hw2[1] << 8)) << 16)
                lines.append({'addr': f'0x{a:08X}', 'bytes': f'{w:08X}', 'text': f'.word 0x{w:08X}'})
                a += 4
            else:
                lines.append({'addr': f'0x{a:08X}', 'bytes': f'{hw:04X}', 'text': f'.hword 0x{hw:04X}'})
                a += 2
        except Exception as e:
            lines.append({'addr': f'0x{a:08X}', 'bytes': '????', 'text': f'; {e}'})
            break
    return lines


@socketio.on('cpu_halt')
def handle_cpu_halt():
    try:
        probe, _ = _require_probe()
        probe.halt()
        emit('cpu_state', {'halted': True})
    except Exception as e:
        emit('error', {'message': f'Halt failed: {e}'})


@socketio.on('cpu_go')
def handle_cpu_go():
    try:
        probe, _ = _require_probe()
        probe.go()
        emit('cpu_state', {'halted': False})
    except Exception as e:
        emit('error', {'message': f'Go failed: {e}'})


@socketio.on('cpu_step')
def handle_cpu_step():
    try:
        probe, _ = _require_probe()
        if not probe.halted():
            probe.halt()
        probe.step()
        # report PC after step
        pc = None
        try:
            pc = probe.read_reg('pc')
        except Exception:
            pass
        emit('cpu_state', {'halted': True, 'pc': hex(pc) if pc is not None else None})
    except Exception as e:
        emit('error', {'message': f'Step failed: {e}'})


@socketio.on('cpu_reset_halt')
def handle_cpu_reset_halt():
    try:
        probe, _ = _require_probe()
        try:
            # prefer xlink helper if present
            if hasattr(probe, 'reset_and_halt'):
                probe.reset_and_halt()
            else:
                probe.reset()
                probe.halt()
        except Exception:
            probe.reset()
            probe.halt()
        emit('cpu_state', {'halted': True, 'reset': True})
    except Exception as e:
        emit('error', {'message': f'Reset+Halt failed: {e}'})


@socketio.on('target_info')
def handle_target_info():
    try:
        probe, pobj = _require_probe()
        info = {
            'probe_type': state.get('probe_type'),
            'mode': state.get('probe_mode'),
            'rtt_addr': hex(state['rtt_cb_addr']) if state.get('rtt_cb_addr') else None,
            'rtt_channel': state.get('rtt_channel', 0),
            'connected': True,
        }
        try:
            info['halted'] = bool(probe.halted())
        except Exception:
            info['halted'] = None
        try:
            if hasattr(probe, 'read_core_type'):
                info['core_type'] = probe.read_core_type()
            else:
                cpuid = probe.read_U32(0xE000ED00)
                part = (cpuid >> 4) & 0xFFF
                info['cpuid'] = hex(cpuid)
                info['core_type'] = {
                    0xC20: 'Cortex-M0', 0xC60: 'Cortex-M0+', 0xC23: 'Cortex-M3',
                    0xC24: 'Cortex-M4', 0xC27: 'Cortex-M7', 0xD20: 'Cortex-M23',
                    0xD21: 'Cortex-M33',
                }.get(part, f'Unknown(0x{part:03X})')
        except Exception as e:
            info['core_type_error'] = str(e)
        if pobj is not None and hasattr(pobj, 'probe_info'):
            try:
                info['probe'] = pobj.probe_info()
            except Exception:
                pass
        elif pobj is not None and hasattr(pobj, 'target_voltage'):
            try:
                info['voltage_mv'] = pobj.target_voltage()
            except Exception:
                pass
        # PC/SP snapshot without forcing halt if already running may fail — try
        for r in ('pc', 'sp', 'lr', 'xpsr', 'msp', 'psp'):
            try:
                info[r] = hex(probe.read_reg(r))
            except Exception:
                pass
        emit('target_info', info)
    except Exception as e:
        emit('error', {'message': f'target_info failed: {e}'})


@socketio.on('mem_write')
def handle_mem_write(data):
    try:
        probe, _ = _require_probe()
        addr = int(str(data.get('addr', '0')), 0)
        width = int(data.get('width', 32))
        val = int(str(data.get('value', '0')), 0)
        if width == 8:
            probe.write_U8(addr, val & 0xFF)
        elif width == 16:
            probe.write_U16(addr, val & 0xFFFF)
        else:
            probe.write_U32(addr, val & 0xFFFFFFFF)
        emit('mem_write_done', {'addr': hex(addr), 'value': hex(val), 'width': width})
    except Exception as e:
        emit('error', {'message': f'Memory write failed: {e}'})


@socketio.on('mem_fill')
def handle_mem_fill(data):
    try:
        probe, _ = _require_probe()
        addr = int(str(data.get('addr', '0')), 0)
        size = min(int(data.get('size', 0)), 64 * 1024)
        pattern = int(str(data.get('pattern', '0')), 0) & 0xFF
        if size <= 0:
            raise ValueError('size must be > 0')
        chunk = [pattern] * min(size, 256)
        left = size
        off = 0
        while left > 0:
            n = min(left, len(chunk))
            probe.write_mem_U8(addr + off, chunk[:n])
            off += n
            left -= n
        emit('mem_fill_done', {'addr': hex(addr), 'size': size, 'pattern': hex(pattern)})
    except Exception as e:
        emit('error', {'message': f'Memory fill failed: {e}'})


@socketio.on('reg_write')
def handle_reg_write(data):
    try:
        probe, _ = _require_probe()
        name = str(data.get('name', '')).lower()
        val = int(str(data.get('value', '0')), 0)
        if not probe.halted():
            probe.halt()
        probe.write_reg(name, val)
        emit('reg_write_done', {'name': name, 'value': hex(val)})
    except Exception as e:
        emit('error', {'message': f'Register write failed: {e}'})


@socketio.on('disasm')
def handle_disasm(data):
    try:
        probe, pobj = _require_probe()
        addr = int(str(data.get('addr', '0')), 0)
        count = min(int(data.get('count', 16)), 64)
        lines = []
        if pobj is not None and hasattr(pobj, 'disassemble'):
            raw = pobj.disassemble(addr, count)
            if isinstance(raw, (list, tuple)):
                for i, item in enumerate(raw):
                    if isinstance(item, str):
                        lines.append({'addr': f'0x{addr + i * 2:08X}', 'text': item})
                    elif isinstance(item, dict):
                        lines.append(item)
                    else:
                        lines.append({'addr': f'0x{addr + i * 2:08X}', 'text': str(item)})
            elif isinstance(raw, str):
                for line in raw.splitlines():
                    lines.append({'text': line})
        if not lines:
            lines = _simple_thumb_disasm(probe, addr, count)
        emit('disasm_data', {'addr': hex(addr), 'lines': lines})
    except Exception as e:
        emit('error', {'message': f'Disasm failed: {e}'})


@socketio.on('watch_start')
def handle_watch_start(data):
    """Poll a list of memory variables (software watch, not DWT)."""
    if not state.get('connected'):
        emit('error', {'message': 'Not connected'})
        return
    items = data.get('items') or []
    # normalize: [{name, addr, type}] type=u8/u16/u32/i32/float
    norm = []
    for it in items[:32]:
        try:
            norm.append({
                'name': it.get('name') or it.get('addr'),
                'addr': int(str(it.get('addr')), 0),
                'type': (it.get('type') or 'u32').lower(),
            })
        except Exception:
            continue
    state['watch_items'] = norm
    state['watch_running'] = True
    if not state.get('_watch_thread_started'):
        state['_watch_thread_started'] = True
        socketio.start_background_task(watch_reader_thread)
    emit('watch_started', {'count': len(norm)})


@socketio.on('watch_stop')
def handle_watch_stop():
    state['watch_running'] = False
    emit('watch_stopped', {})


def watch_reader_thread():
    while True:
        if not state.get('watch_running') or not state.get('connected') or not state.get('probe'):
            socketio.sleep(0.2)
            continue
        probe = state['probe']
        rows = []
        for it in state.get('watch_items') or []:
            try:
                t = it['type']
                a = it['addr']
                if t in ('u8', 'uint8'):
                    v = probe.read_mem_U8(a, 1)[0]
                    rows.append({'name': it['name'], 'addr': hex(a), 'value': v, 'hex': f'0x{v:02X}'})
                elif t in ('u16', 'uint16'):
                    b = probe.read_mem_U8(a, 2)
                    v = b[0] | (b[1] << 8)
                    rows.append({'name': it['name'], 'addr': hex(a), 'value': v, 'hex': f'0x{v:04X}'})
                elif t in ('i32', 'int32'):
                    v = probe.read_U32(a)
                    if v >= 0x80000000:
                        v -= 0x100000000
                    rows.append({'name': it['name'], 'addr': hex(a), 'value': v, 'hex': f'0x{v & 0xFFFFFFFF:08X}'})
                elif t == 'float':
                    raw = probe.read_U32(a)
                    v = struct.unpack('<f', struct.pack('<I', raw & 0xFFFFFFFF))[0]
                    rows.append({'name': it['name'], 'addr': hex(a), 'value': v, 'hex': f'0x{raw:08X}'})
                else:
                    v = probe.read_U32(a)
                    rows.append({'name': it['name'], 'addr': hex(a), 'value': v, 'hex': f'0x{v:08X}'})
            except Exception as e:
                rows.append({'name': it.get('name'), 'addr': hex(it.get('addr', 0)), 'error': str(e)})
        socketio.emit('watch_data', {'rows': rows})
        socketio.sleep(0.2)


@socketio.on('rtt_list_channels')
def handle_rtt_list_channels():
    """List RTT up/down buffer names and sizes from control block."""
    try:
        probe, _ = _require_probe()
        cb = state.get('rtt_cb_addr') or 0
        if not cb:
            cb, _, _ = scan_rtt_control_block(probe, state.get('probe_address') or 'auto', 0)
            state['rtt_cb_addr'] = cb
        raw = probe.read_mem_U8(cb, ctypes.sizeof(SEGGER_RTT_CB))
        rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(raw))
        max_up = int(rtt_cb.MaxNumUpBuffers) or 0
        max_down = int(rtt_cb.MaxNumDownBuffers) or 0
        rb = ctypes.sizeof(RingBuffer)
        channels = {'up': [], 'down': []}
        for i in range(min(max_up, 16)):
            a = cb + 24 + rb * i
            hdr = probe.read_mem_U8(a, rb)
            ring = RingBuffer.from_buffer(bytearray(hdr))
            name = ''
            try:
                if ring.sName:
                    nb = probe.read_mem_U8(ring.sName, 32)
                    name = bytes(nb).split(b'\x00', 1)[0].decode('ascii', errors='replace')
            except Exception:
                pass
            channels['up'].append({
                'index': i, 'name': name or f'up{i}',
                'size': ring.SizeOfBuffer, 'flags': ring.Flags,
                'addr': hex(a),
            })
        for i in range(min(max_down, 16)):
            a = cb + 24 + rb * max_up + rb * i
            hdr = probe.read_mem_U8(a, rb)
            ring = RingBuffer.from_buffer(bytearray(hdr))
            name = ''
            try:
                if ring.sName:
                    nb = probe.read_mem_U8(ring.sName, 32)
                    name = bytes(nb).split(b'\x00', 1)[0].decode('ascii', errors='replace')
            except Exception:
                pass
            channels['down'].append({
                'index': i, 'name': name or f'down{i}',
                'size': ring.SizeOfBuffer, 'flags': ring.Flags,
                'addr': hex(a),
            })
        emit('rtt_channels', {'cb': hex(cb), 'channels': channels})
    except Exception as e:
        emit('error', {'message': f'rtt_list_channels failed: {e}'})


@socketio.on('svd_write')
def handle_svd_write(data):
    try:
        probe, _ = _require_probe()
        addr = int(str(data.get('addr')), 0)
        val = int(str(data.get('value')), 0) & 0xFFFFFFFF
        probe.write_U32(addr, val)
        emit('svd_value', {'addr': f'0x{addr:08X}', 'value': val, 'hex': f'0x{val:08X}', 'written': True})
    except Exception as e:
        emit('error', {'message': f'SVD write failed: {e}'})


# ─── SVD Register Viewer ─────────────────────────────────────────────────────

@socketio.on('svd_load')
def handle_svd_load(data):
    file_id = data.get('file_id')
    path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(path):
        svd_dir = os.path.join(os.path.dirname(__file__), 'svd')
        path = os.path.join(svd_dir, file_id)
    if not os.path.exists(path):
        emit('error', {'message': f'SVD file not found: {file_id}'})
        return

    try:
        from core.svd_parser import parse_svd
        device = parse_svd(path)
        state['svd_device'] = device

        tree = {'name': device.name, 'peripherals': []}
        for p in (device.peripherals or []):
            periph = {
                'name': p.name,
                'base_addr': f'0x{p.base_address:08X}',
                'description': getattr(p, 'description', '') or '',
                'registers': [],
            }
            for r in (p.registers or []):
                reg = {
                    'name': r.name,
                    'offset': f'0x{r.address_offset:04X}',
                    'addr': f'0x{p.base_address + r.address_offset:08X}',
                    'description': getattr(r, 'description', '') or '',
                    'access': getattr(r, 'access', 'read-write') or 'read-write',
                    'fields': [],
                }
                for f in (r.fields or []):
                    reg['fields'].append({
                        'name': f.name,
                        'bit_offset': f.bit_offset,
                        'bit_width': f.bit_width,
                        'description': getattr(f, 'description', '') or '',
                    })
                periph['registers'].append(reg)
            tree['peripherals'].append(periph)

        emit('svd_tree', tree)
    except Exception as e:
        emit('error', {'message': f'SVD parse failed: {e}'})

@socketio.on('svd_read')
def handle_svd_read(data):
    """Read a single register value."""
    if not state['connected']:
        return
    try:
        addr = int(data.get('addr', '0'), 16)
        val = state['probe'].read_U32(addr)
        emit('svd_value', {'addr': f'0x{addr:08X}', 'value': val, 'hex': f'0x{val:08X}'})
    except Exception as e:
        emit('error', {'message': f'SVD read failed: {e}'})

@socketio.on('svd_read_batch')
def handle_svd_read_batch(data):
    """Read multiple registers (for live refresh)."""
    if not state['connected']:
        return
    addrs = data.get('addrs', [])
    values = {}
    for addr_str in addrs:
        try:
            addr = int(addr_str, 16)
            val = state['probe'].read_U32(addr)
            values[addr_str] = val
        except Exception:
            values[addr_str] = None
    emit('svd_values', {'values': values})

# ─── Core Register Viewer ────────────────────────────────────────────────────

@socketio.on('core_regs_start')
def handle_core_regs_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    if state.get('core_regs_running'):
        emit('core_regs_started', {})
        return
    state['core_regs_running'] = True
    socketio.start_background_task(core_regs_reader_thread)
    emit('core_regs_started', {})

@socketio.on('core_regs_stop')
def handle_core_regs_stop():
    state['core_regs_running'] = False
    emit('core_regs_stopped', {})

def core_regs_reader_thread():
    """Background thread: reads core registers at 100ms interval."""
    prev_values = {}
    probe = state['probe']
    mode = probe.mode if hasattr(probe, 'mode') else 'arm'

    if mode.startswith('arm'):
        reg_names = ['r0','r1','r2','r3','r4','r5','r6','r7',
                     'r8','r9','r10','r11','r12','sp','lr','pc',
                     'xpsr','msp','psp','control','faultmask','basepri','primask']
    else:  # RISC-V
        reg_names = [f'x{i}' for i in range(32)] + ['pc','mstatus','mcause','mtval','mie','mip']

    while state.get('core_regs_running'):
        try:
            values = {}
            changed = {}
            for name in reg_names:
                try:
                    val = probe.read_reg(name)
                    values[name] = val
                    if name in prev_values and prev_values[name] != val:
                        changed[name] = True
                except Exception:
                    values[name] = None
            prev_values = dict(values)

            # Decode xPSR if ARM
            xpsr_decode = {}
            if mode.startswith('arm') and values.get('xpsr') is not None:
                xpsr = values['xpsr']
                xpsr_decode = {
                    'exception_number': xpsr & 0x1FF,
                    'exception_name': _exception_name(xpsr & 0x1FF),
                    'thumb': bool(xpsr & (1 << 24)),
                    'negative': bool(xpsr & (1 << 31)),
                    'zero': bool(xpsr & (1 << 30)),
                    'carry': bool(xpsr & (1 << 29)),
                    'overflow': bool(xpsr & (1 << 28)),
                    'saturation': bool(xpsr & (1 << 27)),
                    'ici_it': (xpsr >> 10) & 0x3F,
                    'ge': (xpsr >> 16) & 0xF,
                }

            # Decode mstatus if RISC-V
            mstatus_decode = {}
            if mode.startswith('rv') and values.get('mstatus') is not None:
                ms = values['mstatus']
                mstatus_decode = {
                    'mie': bool(ms & (1 << 3)),
                    'mpie': bool(ms & (1 << 7)),
                    'mpp': (ms >> 11) & 0x3,
                    'sie': bool(ms & (1 << 1)),
                    'spie': bool(ms & (1 << 5)),
                    'spp': bool(ms & (1 << 8)),
                }

            socketio.emit('core_regs_data', {
                'values': {k: v for k, v in values.items()},
                'changed': changed,
                'xpsr_decode': xpsr_decode,
                'mstatus_decode': mstatus_decode,
                'mode': mode,
            })
        except Exception as e:
            socketio.emit('error', {'message': f'Core register read error: {e}'})
        socketio.sleep(0.1)  # 100ms

# ─── Memory viewer ──────────────────────────────────────────────────────────

@socketio.on('mem_read')
def handle_mem_read(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    try:
        addr = int(str(data.get('addr', '0x20000000')), 16)
        size = min(int(data.get('size', 256)), 4096)
        # Align to 16 bytes
        addr = addr & 0xFFFFFFF0
        size = (size + 15) & 0xFFF0

        raw = state['probe'].read_mem_U8(addr, size)

        lines = []
        for i in range(0, len(raw), 16):
            chunk = raw[i:i+16]
            hex_parts = []
            ascii_parts = []
            for j, b in enumerate(chunk):
                hex_parts.append(f'{b:02X}')
                if j == 7:
                    hex_parts.append('')  # Extra space in middle
                ascii_parts.append(chr(b) if 32 <= b < 127 else '.')

            line_addr = addr + i
            # Determine region
            if 0x00000000 <= line_addr < 0x20000000:
                region = 'flash'      # Code region (Flash aliases)
            elif 0x20000000 <= line_addr < 0x40000000:
                region = 'sram'       # SRAM region
            elif 0x40000000 <= line_addr < 0xE0000000:
                region = 'periph'     # Peripheral region
            else:
                region = 'other'

            lines.append({
                'addr': f'{line_addr:08X}',
                'hex': ' '.join(hex_parts),
                'ascii': ''.join(ascii_parts),
                'region': region,
            })

        emit('mem_data', {
            'addr': f'0x{addr:08X}',
            'size': size,
            'lines': lines,
        })
    except Exception as e:
        emit('error', {'message': f'Memory read failed: {e}'})

# ─── J-Scope HSS (High-Speed Sampling) ─────────────────────────────────────

def parse_elf_variables(path):
    """Extract variable symbols from ELF file. Returns list of {name, addr, size, type}."""
    variables = []
    try:
        with open(path, 'rb') as f:
            # Read ELF header
            ident = f.read(16)
            if ident[:4] != b'\x7fELF':
                return variables

            is_32 = ident[4] == 1
            is_le = ident[5] == 1

            if is_le:
                fmt32 = '<HHIIIIIHHHHHH'
                fmt64 = '<HHIQQQIHHHHHH'
            else:
                fmt32 = '>HHIIIIIHHHHHH'
                fmt64 = '>HHIQQQIHHHHHH'

            if is_32:
                header = struct.unpack(fmt32, f.read(36))
                shoff = header[6]
                shentsize = header[9]
                shnum = header[10]
                shstrndx = header[11]
            else:
                header = struct.unpack(fmt64, f.read(48))
                shoff = header[6]
                shentsize = header[10]
                shnum = header[11]
                shstrndx = header[12]

            # Read section headers
            def read_sh(idx):
                f.seek(shoff + idx * shentsize)
                if is_32:
                    data = f.read(40)
                    return struct.unpack('<IIIIIIIIII' if is_le else '>IIIIIIIIII', data)
                else:
                    data = f.read(64)
                    return struct.unpack('<IIQQQQIIII' if is_le else '>IIQQQQIIII', data)

            # Get section name string table
            shstr = read_sh(shstrndx)
            if is_32:
                strtab_off = shstr[4]
                strtab_size = shstr[5]
            else:
                strtab_off = shstr[4]
                strtab_size = shstr[5]

            f.seek(strtab_off)
            strtab = f.read(strtab_size)

            def get_section_name(idx):
                sh = read_sh(idx)
                name_off = sh[0]
                end = strtab.find(b'\x00', name_off)
                return strtab[name_off:end].decode('ascii', errors='replace')

            # Find .symtab and .strtab
            symtab_sh = None
            symstr_sh = None
            for i in range(shnum):
                name = get_section_name(i)
                sh = read_sh(i)
                if name == '.symtab':
                    symtab_sh = sh
                elif name == '.strtab':
                    symstr_sh = sh

            if not symtab_sh or not symstr_sh:
                return variables

            # Read symbol string table
            if is_32:
                symstr_off = symstr_sh[4]
                symstr_size = symstr_sh[5]
            else:
                symstr_off = symstr_sh[4]
                symstr_size = symstr_sh[5]
            f.seek(symstr_off)
            symstr = f.read(symstr_size)

            # Read symbols
            if is_32:
                sym_off = symtab_sh[4]
                sym_size = symtab_sh[5]
                sym_entsize = symtab_sh[6] or 16
            else:
                sym_off = symtab_sh[4]
                sym_size = symtab_sh[5]
                sym_entsize = symtab_sh[6] or 24

            count = sym_size // sym_entsize
            for i in range(count):
                f.seek(sym_off + i * sym_entsize)
                if is_32:
                    sym = struct.unpack('<IIIBBH' if is_le else '>IIIBBH', f.read(16))
                    name_idx, value, size, info, other, shndx = sym
                else:
                    sym = struct.unpack('<IBBHQQ' if is_le else '>IBBHQQ', f.read(24))
                    name_idx, info, other, shndx, value, size = sym

                # STT_OBJECT = 1 (variable)
                stype = info & 0xF
                if stype != 1 or size == 0:
                    continue

                # Get name
                name_end = symstr.find(b'\x00', name_idx)
                name = symstr[name_idx:name_end].decode('ascii', errors='replace')

                if name and value > 0:
                    variables.append({
                        'name': name,
                        'addr': value,
                        'size': size,
                        'type': _guess_var_type(size),
                    })
    except Exception:
        pass

    return variables

def _guess_var_type(size):
    """Guess display type from byte size."""
    if size == 1: return 'uint8'
    if size == 2: return 'uint16'
    if size == 4: return 'float'
    if size == 8: return 'double'
    return f'bytes[{size}]'

@socketio.on('hss_load_elf')
def handle_hss_load_elf(data):
    file_id = data.get('file_id')
    path = os.path.join(UPLOAD_DIR, file_id)
    if not os.path.exists(path):
        emit('error', {'message': f'ELF file not found: {file_id}'})
        return
    try:
        variables = parse_elf_variables(path)
        state['hss_elf_path'] = path
        state['hss_all_vars'] = variables
        emit('hss_symbols', {'variables': variables[:200]})  # Limit to 200
    except Exception as e:
        emit('error', {'message': f'ELF parse failed: {e}'})

@socketio.on('hss_start')
def handle_hss_start(data):
    if not state['connected']:
        emit('error', {'message': 'Not connected'})
        return
    if state.get('hss_running'):
        emit('hss_started', {})
        return
    state['hss_vars'] = data.get('variables', [])
    state['hss_interval'] = data.get('interval', 0.01)
    state['hss_running'] = True
    socketio.start_background_task(hss_reader_thread)
    emit('hss_started', {})

@socketio.on('hss_stop')
def handle_hss_stop():
    state['hss_running'] = False
    emit('hss_stopped', {})

def hss_reader_thread():
    """Read HSS variables at high speed and push waveform data."""
    probe = state['probe']
    hss_vars = state.get('hss_vars', [])
    interval = state.get('hss_interval', 0.01)

    if not hss_vars:
        return

    while state.get('hss_running'):
        if not state['connected'] or not probe:
            socketio.sleep(0.1)
            continue

        values = []
        for var in hss_vars:
            try:
                addr = var['addr']
                size = var['size']
                raw = probe.read_mem_U8(addr, size)

                if size == 1:
                    val = raw[0]
                elif size == 2:
                    val = struct.unpack('<h', bytes(raw))[0]
                elif size == 4:
                    val = struct.unpack('<f', bytes(raw))[0]
                elif size == 8:
                    val = struct.unpack('<d', bytes(raw))[0]
                else:
                    val = int.from_bytes(bytes(raw), 'little')

                values.append({'name': var['name'], 'value': val})
            except Exception:
                values.append({'name': var.get('name', '?'), 'value': 0})

        socketio.emit('hss_data', {'values': values})
        socketio.sleep(interval)

# ─── HTML template ────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Web RTTView</title>
<style>
/* ─── CSS Variables ──────────────────────────────────────────────── */
:root {
    --bg: #f0f5fb;
    --bg-panel: #ffffff;
    --bg-input: #f7fafc;
    --bg-hover: #e8f1fb;
    --bg-terminal: #0b1f3a;
    --border: #c9daf0;
    --border-focus: #2f6fed;
    --text: #1a2b45;
    --text-dim: #6b7c93;
    --text-bright: #0b1f3a;
    --accent: #2f6fed;
    --accent-soft: #dce9ff;
    --green: #1a9b5c;
    --red: #e03e3e;
    --orange: #d97706;
    --cyan: #0e8f9d;
    --yellow: #b45309;
    --purple: #6d28d9;
    --shadow: 0 1px 3px rgba(15, 55, 120, 0.08);
    --shadow-md: 0 4px 14px rgba(15, 55, 120, 0.10);
    --radius: 8px;
}

/* ─── Reset & Base ───────────────────────────────────────────────── */
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; }
body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
    font-size: 13px;
    display: flex;
    flex-direction: column;
    letter-spacing: 0.01em;
}

/* ─── Scrollbar ──────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #b7c9e3; border-radius: 8px; border: 2px solid transparent; background-clip: padding-box; }
::-webkit-scrollbar-thumb:hover { background: #8eabda; border: 2px solid transparent; background-clip: padding-box; }

/* ─── Top Bar ────────────────────────────────────────────────────── */
.top-bar {
    background: linear-gradient(180deg, #ffffff 0%, #f5f9ff 100%);
    border-bottom: 1px solid var(--border);
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    flex-shrink: 0;
    box-shadow: var(--shadow);
    z-index: 5;
}
.brand {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-right: 10px;
    padding-right: 12px;
    border-right: 1px solid var(--border);
}
.brand-mark {
    width: 28px; height: 28px;
    border-radius: 8px;
    background: linear-gradient(135deg, #2f6fed, #60a5fa);
    color: #fff;
    font-weight: 700;
    font-size: 12px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 8px rgba(47,111,237,0.35);
}
.brand-title {
    font-weight: 700;
    color: var(--text-bright);
    font-size: 14px;
    line-height: 1.1;
}
.brand-sub {
    color: var(--text-dim);
    font-size: 10px;
}
.top-bar label {
    color: var(--text-dim);
    font-size: 12px;
    white-space: nowrap;
}
.top-bar select,
.top-bar input {
    background: var(--bg-input);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 8px;
    font-family: inherit;
    font-size: 12px;
    outline: none;
    transition: border-color 0.15s, box-shadow 0.15s;
}
.top-bar select:focus,
.top-bar input:focus {
    border-color: var(--border-focus);
    box-shadow: 0 0 0 3px rgba(47,111,237,0.15);
}
.top-bar select { min-width: 100px; }
.top-bar input[type="text"] { width: 120px; }
.top-bar input[type="number"] { width: 60px; }
#jlink-dll { width: 170px !important; }

/* ─── Buttons ────────────────────────────────────────────────────── */
.btn {
    background: var(--bg-panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 14px;
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s, border-color 0.15s, box-shadow 0.15s, transform 0.05s;
    box-shadow: var(--shadow);
}
.btn:hover { background: var(--bg-hover); border-color: var(--accent); color: var(--accent); }
.btn:active { transform: translateY(1px); }
.btn-accent {
    background: linear-gradient(180deg, #3b7cff 0%, #2f6fed 100%);
    color: #ffffff;
    border-color: #2a63d8;
    box-shadow: 0 2px 8px rgba(47,111,237,0.28);
}
.btn-accent:hover { filter: brightness(1.05); color: #fff; border-color: #2a63d8; }
.btn-danger {
    background: #fee2e2;
    color: var(--red);
    border-color: #fca5a5;
}
.btn-danger:hover { background: #fecaca; color: var(--red); }

/* ─── Tab Bar ────────────────────────────────────────────────────── */
.tab-bar {
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-shrink: 0;
    overflow-x: auto;
    padding: 0 8px;
    gap: 2px;
}
.tab-btn {
    background: transparent;
    color: var(--text-dim);
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 14px;
    font-family: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
    border-radius: 8px 8px 0 0;
}
.tab-btn:hover { color: var(--accent); background: var(--accent-soft); }
.tab-btn.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
    background: var(--accent-soft);
    font-weight: 600;
}

/* ─── Tab Panels ─────────────────────────────────────────────────── */
.tab-content { flex: 1; overflow: hidden; position: relative; background: var(--bg); }
.tab-panel {
    display: none;
    position: absolute;
    inset: 0;
    overflow: auto;
    padding: 14px;
    background: var(--bg);
}
.tab-panel.active { display: block; }

/* ─── Status Bar ─────────────────────────────────────────────────── */
.status-bar {
    background: linear-gradient(90deg, #1e4fd6 0%, #2f6fed 55%, #4b8bff 100%);
    color: #ffffff;
    padding: 5px 14px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
    box-shadow: 0 -1px 0 rgba(255,255,255,0.12) inset;
}
.status-led {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}
.led-red { background: var(--red); }
.led-green { background: var(--green); }
.led-orange { background: var(--orange); }
.status-bar .spacer { flex: 1; }

/* ─── Panel Sections ─────────────────────────────────────────────── */
.section-title {
    color: var(--accent);
    font-size: 14px;
    font-weight: bold;
    margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
}
.panel-card {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 14px;
    margin-bottom: 12px;
    box-shadow: var(--shadow);
}

/* ─── RTT Terminal ───────────────────────────────────────────────── */
.rtt-display {
    background: var(--bg-terminal);
    border: 1px solid #1e3a5f;
    border-radius: var(--radius);
    padding: 10px 12px;
    font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
    font-size: 13px;
    color: #9ae6b4;
    height: calc(100% - 50px);
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03), var(--shadow-md);
}
.rtt-input-bar {
    display: flex;
    gap: 8px;
    margin-top: 8px;
}
.rtt-input-bar input {
    flex: 1;
    background: var(--bg-panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    font-family: inherit;
    font-size: 13px;
    outline: none;
    box-shadow: var(--shadow);
}
.rtt-input-bar input:focus {
    border-color: var(--border-focus);
    box-shadow: 0 0 0 3px rgba(47,111,237,0.15);
}

/* ─── Canvas panels ──────────────────────────────────────────────── */
.chart-canvas {
    background: var(--bg-terminal);
    border: 1px solid var(--border);
    border-radius: 4px;
    width: 100%;
    height: calc(100% - 20px);
}

/* ─── Tables ─────────────────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
}
th, td {
    padding: 7px 10px;
    border: 1px solid var(--border);
    text-align: left;
}
th {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
}
tr:hover td { background: var(--bg-hover); }
table { background: var(--bg-panel); border-radius: var(--radius); overflow: hidden; }

/* ─── Flash panel ────────────────────────────────────────────────── */
.progress-bar {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: 4px;
    height: 20px;
    overflow: hidden;
    margin-top: 8px;
}
.progress-fill {
    background: var(--accent);
    height: 100%;
    width: 0%;
    transition: width 0.3s;
    border-radius: 3px;
}
.upload-zone {
    border: 2px dashed var(--border);
    border-radius: 6px;
    padding: 30px;
    text-align: center;
    color: var(--text-dim);
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
}
.upload-zone:hover {
    border-color: var(--accent);
    background: rgba(86, 156, 214, 0.05);
}

/* ─── Memory hex dump ────────────────────────────────────────────── */
.mem-toolbar { display:flex; gap:12px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); flex-wrap:wrap; }
.mem-toolbar label { color:var(--text-dim); font-size:12px; display:flex; align-items:center; gap:4px; }
.mem-input { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:3px 8px; border-radius:4px; font-family:monospace; width:120px; }
.mem-toolbar select { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:3px 6px; border-radius:4px; }
.mem-quick-jump { display:flex; gap:4px; margin-left:auto; }
.btn-quick { background:var(--bg); border:1px solid var(--border); color:var(--text-dim); padding:2px 8px; border-radius:3px; font-size:11px; cursor:pointer; }
.btn-quick:hover { background:var(--bg-hover); color:var(--text); }
.mem-hexdump { overflow:auto; height:calc(100% - 48px); padding:8px 12px; font-family:'Cascadia Code','Fira Code',Consolas,monospace; font-size:13px; line-height:1.6; }
.mem-placeholder { color:var(--text-dim); text-align:center; padding:40px; }
.mem-line { display:flex; white-space:pre; }
.mem-line-addr { color:var(--text-dim); min-width:80px; }
.mem-line-hex { flex:1; }
.mem-line-ascii { color:var(--text-dim); min-width:140px; padding-left:12px; border-left:1px solid var(--border); margin-left:8px; }
.mem-region-flash .mem-line-addr { color:var(--cyan); }
.mem-region-sram .mem-line-addr { color:var(--green); }
.mem-region-periph .mem-line-addr { color:var(--orange); }
.mem-byte { display:inline-block; min-width:24px; text-align:center; }
.mem-byte-zero { color:var(--text-dim); }
.mem-byte-ff { color:var(--purple); }
.mem-byte-print { color:var(--green); }
.mem-ascii-char { display:inline-block; width:10px; text-align:center; }
.mem-ascii-dot { color:var(--text-dim); }
.hex-dump {
    background: var(--bg-terminal);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 8px;
    font-family: 'Cascadia Code', 'Fira Code', monospace;
    font-size: 12px;
    color: var(--text);
    overflow: auto;
    height: calc(100% - 60px);
    white-space: pre;
}
.hex-addr { color: var(--accent); }
.hex-val { color: var(--cyan); }
.hex-ascii { color: var(--yellow); }

/* ─── SVD Register Viewer ──────────────────────────────────────────── */
.svd-toolbar { display:flex; gap:12px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); }
.svd-toolbar select { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:4px; min-width:200px; font-family:inherit; font-size:12px; outline:none; }
.svd-toolbar select:focus { border-color:var(--border-focus); }
.svd-status { color:var(--text-dim); font-size:12px; margin-left:auto; }
.svd-layout { display:flex; height:calc(100% - 44px); }
.svd-tree-panel { width:300px; overflow-y:auto; border-right:1px solid var(--border); background:var(--bg-panel); }
.svd-detail-panel { flex:1; overflow-y:auto; padding:12px; }
.svd-tree { padding:4px; }
.svd-periph { margin-bottom:2px; }
.svd-periph-header { display:flex; align-items:center; gap:6px; padding:4px 8px; cursor:pointer; color:var(--accent); font-size:12px; border-radius:4px; }
.svd-periph-header:hover { background:var(--bg-hover); }
.svd-periph-header .arrow { font-size:10px; transition:transform 0.2s; }
.svd-periph-header .arrow.open { transform:rotate(90deg); }
.svd-periph-addr { color:var(--text-dim); font-size:10px; margin-left:auto; }
.svd-reg-list { display:none; padding-left:16px; }
.svd-reg-list.open { display:block; }
.svd-reg { display:flex; align-items:center; gap:6px; padding:3px 8px; cursor:pointer; font-size:11px; border-radius:3px; }
.svd-reg:hover { background:var(--bg-hover); }
.svd-reg .reg-name { color:var(--text); }
.svd-reg .reg-addr { color:var(--text-dim); font-size:10px; margin-left:auto; }
.svd-reg .reg-val { color:var(--cyan); font-family:monospace; min-width:80px; text-align:right; }
.svd-reg .reg-changed { color:var(--red) !important; font-weight:bold; }
.svd-detail h3 { color:var(--accent); font-size:14px; margin-bottom:8px; }
.svd-detail .reg-info { color:var(--text-dim); font-size:12px; margin-bottom:12px; }
.svd-detail .reg-value { font-family:monospace; font-size:18px; color:var(--cyan); margin-bottom:12px; padding:8px 12px; background:var(--bg); border-radius:6px; }
.svd-field-table { width:100%; border-collapse:collapse; font-size:12px; }
.svd-field-table th { background:var(--bg-panel); color:var(--text-dim); padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }
.svd-field-table td { padding:4px 8px; border-bottom:1px solid var(--border); }
.svd-placeholder { color:var(--text-dim); text-align:center; padding:40px; }

/* ─── Sub-tabs (SWO) ─────────────────────────────────────────────── */
.sub-tab-bar {
    display: flex;
    gap: 2px;
    margin-bottom: 8px;
}
.sub-tab-btn {
    background: var(--bg-input);
    color: var(--text-dim);
    border: 1px solid var(--border);
    border-bottom: none;
    border-radius: 4px 4px 0 0;
    padding: 5px 14px;
    font-family: inherit;
    font-size: 12px;
    cursor: pointer;
}
.sub-tab-btn.active {
    background: var(--bg-panel);
    color: var(--text-bright);
    border-color: var(--accent);
}

/* ─── SWO panel ────────────────────────────────────────────────────── */
.swo-toolbar { display:flex; gap:8px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); flex-wrap:wrap; }
.swo-toolbar select { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:2px 6px; border-radius:4px; font-family:inherit; font-size:12px; outline:none; }
.swo-toolbar select:focus { border-color:var(--border-focus); }
.swo-subtabs { display:flex; gap:4px; margin-left:auto; }
.swo-subtab { background:transparent; border:none; color:var(--text-dim); padding:4px 10px; cursor:pointer; border-bottom:2px solid transparent; font-family:inherit; font-size:12px; }
.swo-subtab.active { color:var(--text-bright); border-bottom-color:var(--accent); }
.swo-subpanel { display:none; height:calc(100% - 48px); overflow:auto; padding:8px; }
.swo-subpanel.active { display:block; }
.swo-terminal-output { font-family:'Cascadia Code','Fira Code',monospace; font-size:13px; white-space:pre-wrap; word-break:break-all; color:var(--text); line-height:1.5; background:var(--bg-terminal); border:1px solid var(--border); border-radius:4px; padding:8px; height:100%; overflow-y:auto; }
.swo-data-table { width:100%; border-collapse:collapse; font-size:12px; }
.swo-data-table th { background:var(--bg-panel); color:var(--text-dim); padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }
.swo-data-table td { padding:4px 8px; border-bottom:1px solid var(--border); }
.swo-data-table tr:hover td { background:var(--bg-hover); }
.data-table { width:100%; border-collapse:collapse; font-size:12px; }
.data-table th { background:var(--bg-panel); color:var(--text-dim); padding:6px 8px; text-align:left; border-bottom:1px solid var(--border); }
.data-table td { padding:4px 8px; border-bottom:1px solid var(--border); }
.data-table tr:hover td { background:var(--bg-hover); }
.profiler-bar { display:flex; height:20px; margin-top:8px; border-radius:4px; overflow:hidden; }

/* ─── Oscilloscope channel config ────────────────────────────────── */
.osc-channel {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
}
.osc-ch-color {
    width: 14px; height: 14px;
    border-radius: 50%;
    flex-shrink: 0;
}

/* ─── Oscilloscope (register-based) ──────────────────────────────── */
.osc-toolbar { background:var(--bg-panel); border-bottom:1px solid var(--border); padding:8px; flex-shrink:0; }
.osc-controls-row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.osc-controls-row label { color:var(--text-dim); font-size:12px; display:flex; align-items:center; gap:4px; white-space:nowrap; }
.osc-controls-row select, .osc-controls-row input[type="number"] { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:2px 6px; border-radius:4px; font-size:12px; font-family:inherit; outline:none; }
.osc-controls-row select:focus, .osc-controls-row input:focus { border-color:var(--border-focus); }
.osc-channels { margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; }
.osc-ch-row { display:flex; gap:4px; align-items:center; font-size:11px; padding:3px 8px; background:var(--bg); border-radius:4px; border:1px solid var(--border); }
.osc-ch-row .ch-color { width:12px; height:12px; border-radius:2px; flex-shrink:0; }
.osc-ch-row input[type="text"] { width:80px; background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:1px 4px; border-radius:3px; font-size:11px; font-family:inherit; outline:none; }
.osc-ch-row input[type="text"]:focus { border-color:var(--border-focus); }
.osc-ch-row input[type="number"] { width:50px; background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:1px 4px; border-radius:3px; font-size:11px; font-family:inherit; outline:none; }
.osc-ch-row select { background:var(--bg-input); border:1px solid var(--border); color:var(--text); font-size:11px; font-family:inherit; outline:none; }
.osc-ch-row label { color:var(--text-dim); font-size:11px; display:flex; align-items:center; gap:2px; }
.osc-main { position:relative; height:calc(100% - 100px); }
#osc-canvas { width:100%; height:100%; }
.osc-measurements { position:absolute; top:8px; right:8px; background:rgba(255,255,255,0.92); padding:8px 12px; border-radius:6px; border:1px solid var(--border); font-size:11px; pointer-events:none; }
.osc-measurements div { margin:2px 0; white-space:nowrap; }

/* ─── RTOS task viewer ──────────────────────────────────────────────── */
.rtos-toolbar { display:flex; gap:12px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); }
.rtos-status { color:var(--text-dim); font-size:12px; margin-left:auto; }
.rtos-table-wrap { overflow:auto; height:calc(100% - 44px); padding:0; }
.rtos-table { width:100%; border-collapse:collapse; }
.rtos-table th { position:sticky; top:0; background:var(--bg-panel); z-index:1; }
.rtos-table td { font-size:12px; }
.state-running { color:var(--green); font-weight:bold; }
.state-ready { color:var(--accent); }
.state-blocked { color:var(--orange); }
.state-suspended { color:var(--text-dim); }
.state-deleted { color:var(--red); }
.stack-bar { display:inline-block; height:10px; border-radius:2px; min-width:60px; background:var(--bg-input); position:relative; vertical-align:middle; }
.stack-bar-fill { height:100%; border-radius:2px; transition:width 0.3s; }
.stack-low { background:var(--green); }
.stack-mid { background:var(--orange); }
.stack-high { background:var(--red); }

/* ─── Wave controls ────────────────────────────────────────────────── */
.wave-controls {
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 8px 12px;
    background: var(--bg-panel);
    border-bottom: 1px solid var(--border);
}
.wave-controls label {
    color: var(--text-dim);
    font-size: 12px;
}
.wave-controls select,
.wave-controls input {
    background: var(--bg-input);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: inherit;
    font-size: 12px;
    outline: none;
}
.wave-controls select:focus,
.wave-controls input:focus {
    border-color: var(--border-focus);
}
.btn-action {
    background: var(--bg-input);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 4px 14px;
    font-family: inherit;
    font-size: 12px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s, border-color 0.15s;
}
.btn-action:hover {
    background: var(--bg-hover);
    border-color: var(--text-dim);
}
.btn-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
.btn-action.btn-start {
    background: linear-gradient(180deg, #3b7cff 0%, #2f6fed 100%);
    color: #ffffff;
    border-color: #2a63d8;
}
.btn-action.btn-start:hover {
    opacity: 0.85;
}
#wave-canvas {
    width: 100%;
    height: calc(100% - 40px);
}
.hss-section { border-top:2px solid var(--border); margin-top:12px; padding-top:12px; }
.hss-header { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.hss-title { color:var(--yellow); font-weight:bold; font-size:13px; }
.hss-body { display:flex; gap:12px; margin-top:8px; }
.hss-var-list { width:280px; max-height:200px; overflow-y:auto; background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; }
.hss-var-header { display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:var(--bg); border-bottom:1px solid var(--border); font-size:11px; color:var(--text-dim); }
.hss-symbols { padding:4px; max-height:160px; overflow-y:auto; }
.hss-var-item { display:flex; align-items:center; gap:6px; padding:2px 6px; font-size:11px; cursor:pointer; border-radius:3px; }
.hss-var-item:hover { background:var(--bg-hover); }
.hss-var-item input { margin:0; }
.hss-var-item .var-name { color:var(--text); flex:1; }
.hss-var-item .var-addr { color:var(--text-dim); font-size:10px; }
.hss-var-item .var-size { color:var(--text-dim); font-size:10px; min-width:30px; }
.hss-controls { display:flex; gap:12px; align-items:center; }
.btn-small { font-size:11px; padding:2px 8px; }

/* ─── Crash analyzer ─────────────────────────────────────────────── */
.crash-toolbar { display:flex; gap:12px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); }
.crash-status { color:var(--text-dim); font-size:12px; margin-left:auto; }
.crash-layout { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding:12px; overflow:auto; height:calc(100% - 44px); }
.crash-section { background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:12px; }
.crash-section h3 { color:var(--accent); font-size:12px; margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:4px; }
.crash-regs-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:4px; }
.crash-reg { display:flex; justify-content:space-between; padding:3px 6px; background:var(--bg); border-radius:3px; font-size:11px; }
.crash-reg .name { color:var(--text-dim); }
.crash-reg .val { color:var(--cyan); font-family:monospace; }
.crash-faults { font-size:12px; }
.crash-fault-row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border); }
.crash-decode { font-size:11px; }
.crash-decode-group { margin-bottom:8px; }
.crash-decode-group h4 { color:var(--yellow); font-size:11px; margin:4px 0; }
.crash-flag { display:inline-block; padding:2px 6px; margin:2px; border-radius:3px; font-size:10px; }
.crash-flag-set { background:var(--red); color:#fff; }
.crash-flag-clear { background:var(--bg); color:var(--text-dim); }
.crash-stack { font-family:monospace; font-size:12px; }
.crash-stack-addr { padding:2px 4px; color:var(--cyan); cursor:pointer; }
.crash-stack-addr:hover { text-decoration:underline; }

/* ─── Flash programmer ─────────────────────────────────────────────── */
.flash-layout { display:flex; flex-direction:column; height:100%; padding:12px; gap:12px; }
.flash-config { background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:16px; }
.flash-config h3 { color:var(--accent); font-size:14px; margin-bottom:12px; }
.flash-form { display:flex; flex-direction:column; gap:10px; }
.flash-row { display:flex; align-items:center; gap:8px; }
.flash-row label { color:var(--text-dim); font-size:12px; min-width:70px; }
.flash-input { background:var(--bg-input); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:4px; font-family:monospace; width:140px; }
.flash-file-area { flex:1; }
.flash-file-info { color:var(--text-dim); font-size:11px; margin-top:4px; }
.btn-flash { background: #dcfce7 !important; color:var(--green) !important; border-color:#86efac !important; font-weight:bold; padding:6px 20px; }
.btn-flash:disabled { opacity:0.5; cursor:not-allowed; }
.flash-progress-area { background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:12px; }
.flash-progress-bar { height:20px; background:var(--bg-input); border-radius:4px; overflow:hidden; }
.flash-progress-fill { height:100%; width:0%; background:linear-gradient(90deg, var(--accent), var(--cyan)); border-radius:4px; transition:width 0.3s; }
.flash-status { color:var(--text-dim); font-size:12px; margin-top:6px; }
.flash-log-area { flex:1; background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:12px; overflow:hidden; display:flex; flex-direction:column; }
.flash-log-area h3 { color:var(--accent); font-size:12px; margin-bottom:8px; }
.flash-log { flex:1; overflow-y:auto; font-family:monospace; font-size:12px; color:var(--text); line-height:1.6; }
.flash-log .log-info { color:var(--text-dim); }
.flash-log .log-ok { color:var(--green); }
.flash-log .log-err { color:var(--red); }
.flash-log .log-warn { color:var(--orange); }

/* ─── Probe connect button states ──────────────────────────────────── */
.btn-connect.connected {
    background: #fee2e2 !important;
    color: var(--red) !important;
    border-color: #fca5a5 !important;
}
.status-led.connected {
    background: var(--green);
}

/* ─── Core Register Viewer ──────────────────────────────────────────── */
.cpu-toolbar { display:flex; gap:12px; align-items:center; padding:8px 12px; background:var(--bg-panel); border-bottom:1px solid var(--border); }
.cpu-mode { color:var(--cyan); font-size:12px; padding:2px 8px; background:var(--bg); border-radius:4px; }
.cpu-status { color:var(--text-dim); font-size:12px; margin-left:auto; }
.cpu-layout { display:flex; height:calc(100% - 44px); }
.cpu-regs-panel { flex:1; overflow-y:auto; }
.cpu-decode-panel { width:280px; border-left:1px solid var(--border); overflow-y:auto; padding:12px; background:var(--bg-panel); }
.cpu-regs-table { width:100%; }
.cpu-regs-table td { font-family:monospace; font-size:12px; }
.cpu-regs-table .reg-name { color:var(--accent); font-weight:bold; }
.cpu-regs-table .reg-val { color:var(--cyan); }
.cpu-regs-table .reg-dec { color:var(--text-dim); }
.cpu-regs-table .reg-changed { color:var(--red) !important; font-weight:bold; }
.cpu-decode-section { margin-bottom:16px; }
.cpu-decode-section h3 { color:var(--accent); font-size:12px; margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:4px; }
.cpu-decode-row { display:flex; justify-content:space-between; padding:3px 0; font-size:11px; }
.cpu-decode-row .label { color:var(--text-dim); }
.cpu-decode-row .value { color:var(--cyan); font-family:monospace; }
.cpu-flags { display:flex; gap:6px; margin-top:8px; }
.cpu-flag { padding:2px 6px; border-radius:3px; font-size:11px; font-weight:bold; }
.cpu-flag-set { background:var(--green); color:#fff; }
.cpu-flag-clear { background:var(--bg); color:var(--text-dim); }

/* ─── Debug / Watch / Disasm ─────────────────────────────────────── */
.debug-layout { display:grid; grid-template-columns: 1fr 1fr; gap:12px; height:100%; }
.debug-card { background:var(--bg-panel); border:1px solid var(--border); border-radius:var(--radius); padding:12px; box-shadow:var(--shadow); display:flex; flex-direction:column; min-height:0; }
.debug-card h3 { color:var(--accent); font-size:13px; margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:4px; }
.debug-row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
.debug-row input, .debug-row select { background:var(--bg-input); border:1px solid var(--border); border-radius:6px; padding:4px 8px; font-family:monospace; font-size:12px; color:var(--text); }
.debug-mono { font-family:Consolas,'Cascadia Code',monospace; font-size:12px; white-space:pre; overflow:auto; background:var(--bg-terminal); color:#cde4ff; border-radius:6px; padding:8px; flex:1; min-height:120px; }
.watch-table { width:100%; font-size:12px; }
.watch-table th { background:var(--accent-soft); color:var(--accent); }
.info-kv { display:grid; grid-template-columns:120px 1fr; gap:4px 8px; font-size:12px; }
.info-kv .k { color:var(--text-dim); }
.info-kv .v { font-family:monospace; color:var(--text-bright); }
.rtt-filter-bar { display:flex; gap:8px; align-items:center; margin-bottom:6px; }
.rtt-filter-bar input { flex:1; background:var(--bg-panel); border:1px solid var(--border); border-radius:6px; padding:4px 8px; }
</style>
</head>
<body>

<!-- ─── Top Bar ─────────────────────────────────────────────────────── -->
<div class="top-bar">
    <div class="brand">
        <div class="brand-mark">RV</div>
        <div>
            <div class="brand-title">Web RTTView</div>
            <div class="brand-sub">J-Link · ST-Link · DAPLink · RTT</div>
        </div>
    </div>
    <label>入口:</label>
    <select id="probe-scope" title="本机=服务器USB；远程=工位agent；浏览器=点一下连本机ST-Link">
        <option value="webusb" selected>浏览器直连 (WebUSB)</option>
        <option value="local">本机 USB (服务器)</option>
        <option value="remote">远程代理 (Agent)</option>
    </select>
    <span id="agent-box" style="display:none; align-items:center; gap:6px;">
        <label>Agent:</label>
        <input type="text" id="probe-agent" placeholder="工位IP:19201 或 IP:19201:token" spellcheck="false" style="width:180px" title="工位运行 python probe_agent.py --port 19201">
    </span>
    <span id="local-probe-box" style="display:none; align-items:center; gap:6px;">
        <label>Probe:</label>
        <select id="probe-select">
            <option value="">检测中...</option>
        </select>
        <button class="btn" id="btn-probe-scan" onclick="detectProbes()" title="扫描探针">扫描</button>
    </span>
    <span id="webusb-hint" style="color:var(--text-dim); font-size:12px;">需 HTTPS 或本机 localhost；插 ST-Link 后点连接</span>
    <label>Mode:</label>
    <select id="mode-select">
        <option value="arm" selected>ARM SWD</option>
        <option value="armj">ARM JTAG</option>
        <option value="rv">RISC-V SWD</option>
        <option value="rvj">RISC-V JTAG</option>
    </select>
    <label>Speed:</label>
    <select id="speed-select">
        <option value="1000">1 MHz</option>
        <option value="2000">2 MHz</option>
        <option value="4000" selected>4 MHz</option>
        <option value="8000">8 MHz</option>
        <option value="12000">12 MHz</option>
        <option value="20000">20 MHz</option>
        <option value="50000">50 MHz</option>
    </select>
    <label>RTT:</label>
    <input type="text" id="rtt-addr" value="auto" spellcheck="false" title="auto=多区域自动搜索; 也可填 0x20000000">
    <label>Ch:</label>
    <input type="number" id="rtt-channel" value="0" min="0" max="15" style="width:48px">
    <label>DLL:</label>
    <input type="text" id="jlink-dll" placeholder="可选 JLink_x64.dll 路径" spellcheck="false" style="width:160px" title="留空则使用 pylink 自动发现">
    <label>Encoding:</label>
    <select id="encoding-select">
        <option value="auto">自动检测</option>
        <option value="utf-8">UTF-8</option>
        <option value="gbk">GBK</option>
        <option value="gb2312">GB2312</option>
        <option value="ascii">ASCII</option>
        <option value="hex">HEX</option>
    </select>
    <button class="btn btn-accent btn-connect" id="btn-connect">连接</button>
    <button class="btn" id="btn-top-reset" onclick="mcuReset(false)" title="通过调试探针复位 MCU">复位 MCU</button>
    <button class="btn" id="btn-top-reset-halt" onclick="mcuReset(true)" title="复位并保持 Halt">复位+Halt</button>
</div>

<!-- ─── Tab Bar ─────────────────────────────────────────────────────── -->
<div class="tab-bar">
    <button class="tab-btn active" data-tab="rtt" onclick="switchTab('rtt')">RTT终端</button>
    <button class="tab-btn" data-tab="wave" onclick="switchTab('wave')">波形</button>
    <button class="tab-btn" data-tab="osc" onclick="switchTab('osc')">示波器</button>
    <button class="tab-btn" data-tab="swo" onclick="switchTab('swo')">SWO</button>
    <button class="tab-btn" data-tab="rtos" onclick="switchTab('rtos')">RTOS</button>
    <button class="tab-btn" data-tab="crash" onclick="switchTab('crash')">崩溃分析</button>
    <button class="tab-btn" data-tab="cpu" onclick="switchTab('cpu')">核心寄存器</button>
    <button class="tab-btn" data-tab="debug" onclick="switchTab('debug')">调试</button>
    <button class="tab-btn" data-tab="flash" onclick="switchTab('flash')">SWD烧录</button>
    <button class="tab-btn" data-tab="serial" onclick="switchTab('serial')">串口烧录</button>
    <button class="tab-btn" data-tab="reg" onclick="switchTab('reg')">寄存器</button>
    <button class="tab-btn" data-tab="mem" onclick="switchTab('mem')">内存</button>
</div>

<!-- ─── Tab Content ─────────────────────────────────────────────────── -->
<div class="tab-content">

    <!-- RTT 终端 -->
    <div class="tab-panel active" id="panel-rtt">
        <div style="display:flex; gap:6px; margin-bottom:6px; align-items:center; flex-wrap:wrap;">
            <button class="btn btn-accent" id="btn-rtt-start" onclick="startRTT()">启动RTT</button>
            <button class="btn" id="btn-rtt-stop" onclick="stopRTT()" style="display:none;">停止</button>
            <button class="btn" id="btn-rtt-rescan" onclick="rescanRTT()">重扫RTT</button>
            <button class="btn" onclick="listRttChannels()">通道列表</button>
            <button class="btn" id="btn-autoscroll" onclick="toggleAutoScroll()" style="background:var(--bg-input);">自动滚动</button>
            <button class="btn" id="btn-clear-terminal" onclick="clearRtt()">清屏</button>
            <button class="btn" onclick="saveRttLog()">保存</button>
            <label style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--text-dim);cursor:pointer;">
                <input type="checkbox" id="rtt-timestamp"> 时间戳
            </label>
            <input type="text" id="rtt-filter" placeholder="过滤关键词..." style="width:140px;background:var(--bg-panel);border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:12px;">
            <span style="flex:1;"></span>
            <span id="rtt-stats" style="font-size:11px;color:var(--text-dim);"></span>
        </div>
        <div class="rtt-display" id="rtt-terminal" style="height:calc(100% - 85px);">等待连接...</div>
        <div class="rtt-input-bar">
            <input type="text" id="rtt-input" placeholder="输入指令, 按 Enter 发送...">
            <select id="rtt-lineending" style="background:var(--bg-input);color:var(--text);border:1px solid var(--border);border-radius:3px;padding:4px 6px;font-size:12px;">
                <option value="">无</option>
                <option value="\n" selected>LF</option>
                <option value="\r\n">CRLF</option>
                <option value="\r">CR</option>
            </select>
            <button class="btn" onclick="sendRttInput()">发送</button>
        </div>
    </div>

    <!-- 波形 -->
    <div class="tab-panel" id="panel-wave">
        <div class="wave-controls">
            <label>曲线数: <select id="wave-ncurve">
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4" selected>4</option>
            </select></label>
            <label>点数: <input id="wave-npoint" type="number" value="1000" min="100" max="10000" step="100"></label>
            <button id="btn-wave-start" class="btn-action btn-start">开始波形</button>
            <button id="btn-wave-stop" class="btn-action" disabled>停止</button>
        </div>
        <canvas id="wave-canvas"></canvas>
        <!-- J-Scope HSS 模式 -->
        <div class="hss-section">
            <div class="hss-header">
                <span class="hss-title">J-Scope HSS 模式</span>
                <label>ELF 文件: <input type="file" id="hss-elf-file" accept=".elf,.out"></label>
                <button id="btn-hss-load" class="btn-action btn-small">加载符号</button>
            </div>
            <div class="hss-body">
                <div class="hss-var-list">
                    <div class="hss-var-header">
                        <span>变量列表</span>
                        <button id="btn-hss-select-all" class="btn-small">全选</button>
                    </div>
                    <input type="text" id="hss-filter" placeholder="搜索变量..." oninput="filterHssVars(this.value)" style="width:100%;background:var(--bg-input);color:var(--text);border:1px solid var(--border);border-radius:3px;padding:4px 8px;font-size:12px;margin-bottom:6px;">
                    <div id="hss-symbols" class="hss-symbols"></div>
                </div>
                <div class="hss-controls">
                    <label>采样间隔:
                        <select id="hss-interval">
                            <option value="0.001">1ms</option>
                            <option value="0.005">5ms</option>
                            <option value="0.01" selected>10ms</option>
                            <option value="0.05">50ms</option>
                            <option value="0.1">100ms</option>
                        </select>
                    </label>
                    <button id="btn-hss-start" class="btn-action btn-start" disabled>开始 HSS</button>
                    <button id="btn-hss-stop" class="btn-action" disabled>停止</button>
                </div>
            </div>
        </div>
    </div>

    <!-- 示波器 -->
    <div class="tab-panel" id="panel-osc">
        <div class="osc-toolbar">
            <div class="osc-controls-row">
                <label>时基:
                    <select id="osc-timebase">
                        <option value="0.001">1ms</option>
                        <option value="0.002">2ms</option>
                        <option value="0.005">5ms</option>
                        <option value="0.01" selected>10ms</option>
                        <option value="0.02">20ms</option>
                        <option value="0.05">50ms</option>
                        <option value="0.1">100ms</option>
                        <option value="0.5">500ms</option>
                        <option value="1">1s</option>
                        <option value="5">5s</option>
                        <option value="10">10s</option>
                    </select>
                </label>
                <label>触发:
                    <select id="osc-trigger">
                        <option value="free">自由运行</option>
                        <option value="rising">上升沿</option>
                        <option value="falling">下降沿</option>
                    </select>
                </label>
                <label>触发电平: <input id="osc-trigger-level" type="number" value="0" step="0.1"></label>
                <label>触发通道:
                    <select id="osc-trigger-ch">
                        <option value="0">CH1</option>
                        <option value="1">CH2</option>
                        <option value="2">CH3</option>
                        <option value="3">CH4</option>
                    </select>
                </label>
                <label><input id="osc-single" type="checkbox"> 单次</label>
                <button id="btn-osc-start" class="btn-action btn-start">开始</button>
                <button id="btn-osc-stop" class="btn-action" disabled>停止</button>
            </div>
            <div id="osc-channels" class="osc-channels"></div>
        </div>
        <div class="osc-main">
            <canvas id="osc-canvas"></canvas>
            <div id="osc-measurements" class="osc-measurements"></div>
        </div>
    </div>

    <!-- SWO -->
    <div class="tab-panel" id="panel-swo">
        <div class="swo-toolbar">
            <select id="swo-speed">
                <option value="1000000">1 MHz</option>
                <option value="2000000" selected>2 MHz</option>
                <option value="4000000">4 MHz</option>
                <option value="8000000">8 MHz</option>
                <option value="12000000">12 MHz</option>
            </select>
            <button id="btn-swo-start" class="btn-action btn-start">开始 SWO</button>
            <button id="btn-swo-stop" class="btn-action" disabled>停止</button>
            <div class="swo-subtabs">
                <button class="swo-subtab active" data-subtab="console">SWO 控制台</button>
                <button class="swo-subtab" data-subtab="profiler">CPU 分析</button>
                <button class="swo-subtab" data-subtab="exception">异常追踪</button>
            </div>
        </div>
        <div id="swo-console" class="swo-subpanel active">
            <div id="swo-terminal" class="swo-terminal-output">等待 SWO 数据...</div>
        </div>
        <div id="swo-profiler" class="swo-subpanel">
            <table class="swo-data-table">
                <thead><tr><th>地址</th><th>采样数</th><th>CPU%</th><th>占比</th></tr></thead>
                <tbody id="profiler-table"></tbody>
            </table>
            <div class="profiler-bar" id="profiler-bar"></div>
        </div>
        <div id="swo-exception" class="swo-subpanel">
            <div id="exception-log" class="swo-terminal-output">等待异常事件...</div>
        </div>
    </div>

    <!-- RTOS -->
    <div class="tab-panel" id="panel-rtos">
        <div class="rtos-toolbar">
            <button id="btn-rtos-start" class="btn-action btn-start">开始监控</button>
            <button id="btn-rtos-stop" class="btn-action" disabled>停止</button>
            <span class="rtos-status" id="rtos-status">任务数: 0</span>
        </div>
        <div class="rtos-table-wrap">
            <table class="data-table rtos-table">
                <thead>
                    <tr>
                        <th>任务名</th>
                        <th>状态</th>
                        <th>优先级</th>
                        <th>栈使用率</th>
                        <th>已用/总量</th>
                        <th>TCB 地址</th>
                    </tr>
                </thead>
                <tbody id="rtos-tbody"></tbody>
            </table>
        </div>
    </div>

    <!-- 崩溃分析 -->
    <div class="tab-panel" id="panel-crash" style="padding:0;">
        <div class="crash-toolbar">
            <button id="btn-crash-analyze" class="btn-action btn-start">分析崩溃</button>
            <button class="btn-action" onclick="crashClear()">清空</button>
            <span class="crash-status" id="crash-status"></span>
        </div>
        <div class="crash-layout">
            <div class="crash-section">
                <h3>核心寄存器</h3>
                <div id="crash-regs" class="crash-regs-grid"></div>
            </div>
            <div class="crash-section">
                <h3>故障寄存器</h3>
                <div id="crash-faults" class="crash-faults"></div>
            </div>
            <div class="crash-section">
                <h3>CFSR 解码</h3>
                <div id="crash-cfsr" class="crash-decode"></div>
            </div>
            <div class="crash-section">
                <h3>HFSR 解码</h3>
                <div id="crash-hfsr" class="crash-decode"></div>
            </div>
            <div class="crash-section">
                <h3>xPSR 解码</h3>
                <div id="crash-xpsr" class="crash-decode"></div>
            </div>
            <div class="crash-section">
                <h3>栈回溯 (疑似返回地址)</h3>
                <div id="crash-stack" class="crash-stack"></div>
            </div>
        </div>
    </div>

    <!-- 核心寄存器 -->
    <div id="panel-cpu" class="tab-panel" style="padding:0;">
        <div class="cpu-toolbar">
            <button id="btn-cpu-start" class="btn-action">开始读取</button>
            <button id="btn-cpu-stop" class="btn-action" disabled>停止</button>
            <button class="btn-action" onclick="cpuHalt()">Halt</button>
            <button class="btn-action" onclick="cpuStep()">Step</button>
            <button class="btn-action" onclick="cpuGo()">Go</button>
            <button class="btn-action" onclick="cpuResetHalt()">Reset+Halt</button>
            <span id="cpu-mode" class="cpu-mode">ARM Cortex-M</span>
            <span id="cpu-status" class="cpu-status"></span>
        </div>
        <div class="cpu-layout">
            <div class="cpu-regs-panel">
                <table class="data-table cpu-regs-table">
                    <thead><tr><th>寄存器</th><th>值</th><th>十进制</th></tr></thead>
                    <tbody id="cpu-regs-tbody"></tbody>
                </table>
            </div>
            <div class="cpu-decode-panel">
                <div id="cpu-xpsr" class="cpu-decode-section">
                    <h3>xPSR 解码</h3>
                    <div id="cpu-xpsr-content"></div>
                </div>
                <div id="cpu-mstatus" class="cpu-decode-section" style="display:none">
                    <h3>mstatus 解码</h3>
                    <div id="cpu-mstatus-content"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- 调试：控制/监视/反汇编/目标信息 -->
    <div class="tab-panel" id="panel-debug">
        <div class="debug-layout">
            <div class="debug-card">
                <h3>目标信息 / CPU 控制</h3>
                <div class="debug-row">
                    <button class="btn btn-accent" onclick="refreshTargetInfo()">刷新信息</button>
                    <button class="btn" onclick="cpuHalt()">Halt</button>
                    <button class="btn" onclick="cpuStep()">Step</button>
                    <button class="btn" onclick="cpuGo()">Go</button>
                    <button class="btn" onclick="cpuResetHalt()">Reset+Halt</button>
                    <button class="btn" onclick="mcuReset()">Reset+Run</button>
                </div>
                <div id="target-info" class="info-kv"><div class="k">状态</div><div class="v">未连接</div></div>
            </div>
            <div class="debug-card">
                <h3>变量监视 (软件轮询)</h3>
                <div class="debug-row">
                    <input id="watch-name" placeholder="名称" style="width:90px">
                    <input id="watch-addr" placeholder="0x20000000" style="width:110px">
                    <select id="watch-type">
                        <option value="u32">u32</option>
                        <option value="i32">i32</option>
                        <option value="u16">u16</option>
                        <option value="u8">u8</option>
                        <option value="float">float</option>
                    </select>
                    <button class="btn" onclick="watchAdd()">添加</button>
                    <button class="btn btn-accent" onclick="watchStart()">开始</button>
                    <button class="btn" onclick="watchStop()">停止</button>
                </div>
                <table class="data-table watch-table">
                    <thead><tr><th>名称</th><th>地址</th><th>类型</th><th>值</th><th></th></tr></thead>
                    <tbody id="watch-tbody"></tbody>
                </table>
            </div>
            <div class="debug-card">
                <h3>内存写 / 填充</h3>
                <div class="debug-row">
                    <label>地址</label><input id="mw-addr" value="0x20000000" style="width:110px">
                    <label>宽度</label>
                    <select id="mw-width"><option value="32">32</option><option value="16">16</option><option value="8">8</option></select>
                    <label>值</label><input id="mw-value" value="0" style="width:100px">
                    <button class="btn btn-accent" onclick="memWrite()">写入</button>
                </div>
                <div class="debug-row">
                    <label>填充</label><input id="mf-addr" value="0x20000000" style="width:110px">
                    <input id="mf-size" value="16" style="width:60px" title="字节数">
                    <input id="mf-pat" value="0x00" style="width:60px" title="pattern">
                    <button class="btn" onclick="memFill()">Fill</button>
                </div>
                <div class="debug-row">
                    <label>寄存器写</label>
                    <input id="rw-name" value="r0" style="width:60px">
                    <input id="rw-value" value="0" style="width:100px">
                    <button class="btn" onclick="regWrite()">写寄存器</button>
                </div>
            </div>
            <div class="debug-card">
                <h3>反汇编</h3>
                <div class="debug-row">
                    <label>地址</label><input id="dis-addr" value="0x00000000" style="width:110px">
                    <label>条数</label><input id="dis-count" value="16" style="width:50px">
                    <button class="btn btn-accent" onclick="runDisasm()">反汇编</button>
                    <button class="btn" onclick="disasmAtPc()">从 PC</button>
                </div>
                <div id="disasm-out" class="debug-mono">连接后点击反汇编…</div>
            </div>
        </div>
    </div>

    <!-- Flash 烧录 (SWD / 探针) -->
    <div class="tab-panel" id="panel-flash">
        <div class="flash-layout">
            <div class="flash-config">
                <h3>SWD / 探针烧录（J-Link · ST-Link · DAPLink）</h3>
                <div class="flash-form">
                    <div class="flash-row">
                        <label>固件文件:</label>
                        <div class="flash-file-area">
                            <div class="upload-zone" id="upload-zone"
                                 onclick="document.getElementById('file-input').click()"
                                 ondrop="handleDrop(event)" ondragover="event.preventDefault();this.style.borderColor='var(--accent)'"
                                 ondragleave="this.style.borderColor='var(--border)'">
                                拖拽固件文件到此处，或点击选择<br>
                                <span style="font-size:11px;color:var(--text-dim)">支持 .bin / .hex / .elf</span>
                            </div>
                            <input type="file" id="file-input" accept=".bin,.hex,.ihex,.elf" style="display:none" onchange="handleFileSelect(event)">
                            <div id="flash-file-info" class="flash-file-info">未选择文件</div>
                        </div>
                    </div>
                    <div class="flash-row">
                        <label>基地址:</label>
                        <input type="text" id="flash-addr" value="0x08000000" class="flash-input">
                    </div>
                    <div class="flash-row">
                        <label><input type="checkbox" id="flash-verify" checked> 烧录后校验</label>
                    </div>
                    <div class="flash-row">
                        <button id="btn-flash" class="btn-action btn-flash" disabled onclick="flashProgram()">烧录</button>
                        <button id="btn-mcu-reset" class="btn-action" onclick="mcuReset()">复位 MCU</button>
                    </div>
                </div>
            </div>
            <div class="flash-progress-area">
                <div class="flash-progress-bar">
                    <div id="flash-progress" class="flash-progress-fill"></div>
                </div>
                <div id="flash-status" class="flash-status">就绪</div>
            </div>
            <div class="flash-log-area">
                <h3>日志</h3>
                <div id="flash-log" class="flash-log"></div>
            </div>
        </div>
    </div>

    <!-- 串口烧录 -->
    <div class="tab-panel" id="panel-serial">
        <div class="flash-layout">
            <div class="flash-config">
                <h3>串口烧录（UART）</h3>
                <div class="flash-form">
                    <div class="flash-row">
                        <label>串口:</label>
                        <select id="serial-port" class="flash-input" style="width:220px"></select>
                        <button class="btn-action" onclick="refreshSerialPorts()">刷新</button>
                    </div>
                    <div class="flash-row">
                        <label>波特率:</label>
                        <select id="serial-baud" class="flash-input">
                            <option value="9600">9600</option>
                            <option value="115200" selected>115200</option>
                            <option value="230400">230400</option>
                            <option value="460800">460800</option>
                            <option value="921600">921600</option>
                        </select>
                        <label>协议:</label>
                        <select id="serial-proto" class="flash-input" style="width:160px">
                            <option value="stm32_isp">STM32 ISP 引导</option>
                            <option value="raw">原始流写 (Raw)</option>
                        </select>
                    </div>
                    <div class="flash-row">
                        <label>固件:</label>
                        <div class="flash-file-area">
                            <div class="upload-zone" id="serial-upload-zone"
                                 onclick="document.getElementById('serial-file-input').click()"
                                 ondrop="handleSerialDrop(event)" ondragover="event.preventDefault();this.style.borderColor='var(--accent)'"
                                 ondragleave="this.style.borderColor='var(--border)'">
                                拖拽固件到此处，或点击选择<br>
                                <span style="font-size:11px;color:var(--text-dim)">.bin / .hex / .elf · STM32 请先 BOOT0=1 进系统 bootloader</span>
                            </div>
                            <input type="file" id="serial-file-input" accept=".bin,.hex,.ihex,.elf" style="display:none" onchange="handleSerialFile(event)">
                            <div id="serial-file-info" class="flash-file-info">未选择文件</div>
                        </div>
                    </div>
                    <div class="flash-row">
                        <label>基地址:</label>
                        <input type="text" id="serial-addr" value="0x08000000" class="flash-input">
                        <label><input type="checkbox" id="serial-erase" checked> 擦除</label>
                        <label><input type="checkbox" id="serial-dtr"> DTR/RTS 脉冲复位</label>
                    </div>
                    <div class="flash-row">
                        <button id="btn-serial-flash" class="btn-action btn-flash" disabled onclick="serialFlash()">串口烧录</button>
                    </div>
                </div>
            </div>
            <div class="flash-progress-area">
                <div class="flash-progress-bar">
                    <div id="serial-progress" class="flash-progress-fill"></div>
                </div>
                <div id="serial-status" class="flash-status">就绪 — 需 pip install pyserial</div>
            </div>
            <div class="flash-log-area">
                <h3>串口日志</h3>
                <div id="serial-log" class="flash-log"></div>
            </div>
        </div>
    </div>

    <!-- 寄存器 -->
    <div class="tab-panel" id="panel-reg">
        <div class="svd-toolbar">
            <select id="svd-file-select">
                <option value="">选择 SVD 文件...</option>
            </select>
            <button id="btn-svd-load" class="btn-action">加载</button>
            <label style="display:flex;align-items:center;gap:4px;font-size:12px;color:var(--text-dim);">
                <input type="checkbox" id="svd-auto-refresh"> 自动刷新 (200ms)
            </label>
            <span id="svd-status" class="svd-status"></span>
        </div>
        <div class="svd-layout">
            <div class="svd-tree-panel">
                <div id="svd-tree" class="svd-tree"></div>
            </div>
            <div class="svd-detail-panel">
                <div id="svd-detail" class="svd-detail">
                    <div class="svd-placeholder">选择一个寄存器查看详情</div>
                </div>
            </div>
        </div>
    </div>

    <!-- 内存 -->
    <div class="tab-panel" id="panel-mem">
        <div class="mem-toolbar">
            <label>地址: <input type="text" id="mem-addr" value="0x20000000" class="mem-input"></label>
            <label>大小:
                <select id="mem-size">
                    <option value="64">64 B</option>
                    <option value="128">128 B</option>
                    <option value="256" selected>256 B</option>
                    <option value="512">512 B</option>
                    <option value="1024">1 KB</option>
                    <option value="2048">2 KB</option>
                    <option value="4096">4 KB</option>
                </select>
            </label>
            <button id="btn-mem-read" class="btn-action">读取</button>
            <button class="btn-action" onclick="switchTab('debug')">内存写…</button>
            <label><input type="checkbox" id="mem-auto-refresh"> 自动刷新 (500ms)</label>
            <div class="mem-quick-jump">
                <button class="btn-quick" data-addr="0x08000000">Flash</button>
                <button class="btn-quick" data-addr="0x20000000">SRAM</button>
                <button class="btn-quick" data-addr="0x40000000">外设</button>
                <button class="btn-quick" data-addr="0x2001FF00">栈顶</button>
            </div>
        </div>
        <div class="mem-hexdump" id="mem-hexdump">
            <div class="mem-placeholder">点击"读取"查看内存</div>
        </div>
    </div>
</div>

<!-- ─── Status Bar ──────────────────────────────────────────────────── -->
<div class="status-bar">
    <span class="status-led led-red" id="status-led"></span>
    <span id="status-text">未连接</span>
    <span class="spacer"></span>
    <span style="color:var(--text-dim)">RX:</span>
    <span id="status-rx" style="color:var(--cyan);font-family:monospace;font-size:11px">0 B/s</span>
    <span style="color:var(--text-dim)">TX:</span>
    <span id="status-tx" style="color:var(--cyan);font-family:monospace;font-size:11px">0 B/s</span>
    <span class="spacer"></span>
    <span id="status-time"></span>
</div>

<!-- ─── Chart.js ───────────────────────────────────────────────────── -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>

<!-- ─── Socket.IO Client ────────────────────────────────────────────── -->
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<script>
// ─── Socket.IO connection ───────────────────────────────────────────
const socket = io({ transports: ['websocket', 'polling'] });

socket.on('connect', () => {
    console.log('[WS] Connected to server');
});

socket.on('disconnect', () => {
    console.log('[WS] Disconnected');
    connected = false;
    document.getElementById('btn-connect').textContent = '连接';
    document.getElementById('btn-connect').classList.remove('connected');
    document.getElementById('status-led').classList.remove('connected');
    document.getElementById('status-text').textContent = '未连接';
});

// ─── Status bar throughput ────────────────────────────────────────────
function formatRate(bytes) {
    if (bytes < 1024) return bytes.toFixed(0) + ' B/s';
    if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB/s';
    return (bytes/1024/1024).toFixed(1) + ' MB/s';
}

socket.on('status_update', function(data) {
    var statusLed = document.getElementById('status-led');
    var statusText = document.getElementById('status-text');
    var statusRx = document.getElementById('status-rx');
    var statusTx = document.getElementById('status-tx');

    if (data.connected) {
        statusLed.classList.add('connected');
        statusLed.classList.remove('led-red');
        statusText.textContent = '已连接' + (data.probe_type ? ' (' + data.probe_type + ')' : '');
    } else {
        statusLed.classList.remove('connected');
        statusLed.classList.add('led-red');
        statusText.textContent = '未连接';
    }

    if (statusRx) statusRx.textContent = formatRate(data.rx_rate || 0);
    if (statusTx) statusTx.textContent = formatRate(data.tx_rate || 0);
});

// ─── Tab switching ──────────────────────────────────────────────────
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.querySelector(`[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(`panel-${tabId}`).classList.add('active');
}

// ─── Probe scope: webusb | local | remote ─────────────────────────────
var preferredProbe = null;
var connecting = false;
var lastProbeListSig = '';
var connected = false;
var webusbMode = false;
var webusbClient = null;

function getProbeScope() {
    var el = document.getElementById('probe-scope');
    return el ? el.value : 'webusb';
}

function webusbAvailable() {
    return !!(window.isSecureContext && navigator.usb && navigator.usb.requestDevice);
}

function updateScopeUi() {
    var scope = getProbeScope();
    var agentBox = document.getElementById('agent-box');
    var localBox = document.getElementById('local-probe-box');
    var hint = document.getElementById('webusb-hint');
    if (agentBox) agentBox.style.display = (scope === 'remote') ? 'inline-flex' : 'none';
    if (localBox) localBox.style.display = (scope === 'local' || scope === 'remote') ? 'inline-flex' : 'none';
    if (hint) {
        hint.style.display = (scope === 'webusb') ? 'inline' : 'none';
        if (scope === 'webusb' && !webusbAvailable()) {
            if (!window.isSecureContext) {
                hint.style.color = '#f0a020';
                hint.textContent = '当前是 http 远程页，WebUSB 被浏览器禁用 → 用 https（服务器 --ssl）或改「远程代理」';
            } else {
                hint.style.color = '#f0a020';
                hint.textContent = '请用 Chrome/Edge 打开';
            }
        } else if (scope === 'webusb') {
            hint.style.color = 'var(--text-dim)';
            hint.textContent = '插上 ST-Link 后点连接，浏览器弹窗选设备';
        }
    }
    if (scope === 'local' || scope === 'remote') detectProbes();
}

function detectProbes() {
    var scope = getProbeScope();
    if (scope === 'webusb') return;
    var agent = (document.getElementById('probe-agent') && document.getElementById('probe-agent').value || '').trim();
    socket.emit('probe_detect', {scope: scope === 'remote' ? 'remote' : 'local', agent: agent});
}

function getSelectedProbe() {
    try {
        return JSON.parse(document.getElementById('probe-select').value);
    } catch (e) {
        return null;
    }
}

function setPreferredProbe(p) {
    if (p && p.type) {
        preferredProbe = {
            type: p.type,
            index: p.index || 0,
            agent: p.agent || '',
            remote_type: p.remote_type || '',
        };
    }
}

socket.on('probe_list', function(data) {
    const sel = document.getElementById('probe-select');
    if (!sel) return;
    const prev = getSelectedProbe() || preferredProbe;
    var sig = (data.scope || '') + '|' + (data.probes || []).map(function(p) {
        return (p.type || '') + ':' + (p.index || 0) + ':' + (p.name || '') + ':' + (p.available !== false) + ':' + (p.agent || '') + ':' + (p.remote_type || '');
    }).join('|');
    if (sig === lastProbeListSig && sel.options.length > 0) return;
    lastProbeListSig = sig;
    sel.innerHTML = '';
    var preferIdx = 0;
    var autoPrefer = null;
    (data.probes || []).forEach(function(p, i) {
        const opt = document.createElement('option');
        opt.value = JSON.stringify({
            type: p.type,
            index: p.index || 0,
            agent: p.agent || '',
            remote_type: p.remote_type || '',
        });
        opt.textContent = p.name;
        if (p.available === false) {
            opt.disabled = true;
            opt.textContent = p.name + ' (不可用)';
        }
        sel.appendChild(opt);
        if (prev && p.type === prev.type && (p.index || 0) === (prev.index || 0)
            && (p.agent || '') === (prev.agent || '') && p.available !== false) {
            preferIdx = i;
        }
        if (!prev && p.available !== false && autoPrefer === null) {
            if (p.type === 'remote' || p.type === 'stlink') autoPrefer = i;
        }
    });
    if (autoPrefer !== null && !prev) preferIdx = autoPrefer;
    if (sel.options.length) {
        sel.selectedIndex = preferIdx;
        setPreferredProbe(getSelectedProbe());
    }
});

var probeSelEl = document.getElementById('probe-select');
if (probeSelEl) probeSelEl.addEventListener('change', function() {
    setPreferredProbe(getSelectedProbe());
});
var scopeEl = document.getElementById('probe-scope');
if (scopeEl) scopeEl.addEventListener('change', function() {
    lastProbeListSig = '';
    updateScopeUi();
});

function appendTerminal(text, color) {
    const el = document.getElementById('rtt-terminal');
    if (!el) return;
    if (color) {
        const span = document.createElement('span');
        span.style.color = color;
        span.textContent = text;
        el.appendChild(span);
    } else {
        el.textContent += text;
    }
    el.scrollTop = el.scrollHeight;
}

function setConnectUi(state) {
    var btn = document.getElementById('btn-connect');
    var led = document.getElementById('status-led');
    var txt = document.getElementById('status-text');
    if (state === 'connecting') {
        connecting = true;
        btn.disabled = true;
        btn.textContent = '连接中...';
        btn.classList.remove('connected');
        led.classList.remove('connected');
        txt.textContent = '连接中...';
    } else if (state === 'connected') {
        connecting = false;
        btn.disabled = false;
        btn.textContent = '断开连接';
        btn.classList.add('connected');
        led.classList.add('connected');
    } else {
        connecting = false;
        connected = false;
        webusbMode = false;
        btn.disabled = false;
        btn.textContent = '连接';
        btn.classList.remove('connected');
        led.classList.remove('connected');
        txt.textContent = '未连接';
    }
}

function decodeRttBytes(u8) {
    try {
        return new TextDecoder('utf-8', {fatal: false}).decode(u8);
    } catch (e) {
        var s = '';
        for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
        return s;
    }
}

async function connectWebUsb() {
    if (typeof WebUsbStlinkRtt === 'undefined') {
        appendTerminal('[!] WebUSB 脚本未加载\n', '#f44336');
        setConnectUi('idle');
        return;
    }
    webusbClient = new WebUsbStlinkRtt();
    var why = webusbClient.unsupportedReason && webusbClient.unsupportedReason();
    if (why) {
        appendTerminal('[!] WebUSB 不可用: ' + why + '\n', '#f44336');
        if (!window.isSecureContext) {
            appendTerminal('[*] 做法 A: 服务器 python web_rttview.py --host 0.0.0.0 --ssl --no-browser\n', 'orange');
            appendTerminal('[*]         浏览器打开 https://服务器IP:5000 ，点「高级→继续访问」\n', 'orange');
            appendTerminal('[*] 做法 B: 入口改「远程代理」，工位跑 python probe_agent.py（不用 HTTPS/WinUSB）\n', 'orange');
        } else {
            appendTerminal('[*] 请用 Chrome / Edge\n', 'orange');
        }
        webusbClient = null;
        setConnectUi('idle');
        return;
    }
    webusbClient.onStatus = function(m) { appendTerminal('[WebUSB] ' + m + '\n', '#569cd6'); };
    webusbClient.onData = function(u8) {
        var t = decodeRttBytes(u8);
        if (t) appendTerminal(t);
    };
    try {
        appendTerminal('[*] 浏览器将弹出 USB 设备选择（ST-Link）...\n', '#569cd6');
        await webusbClient.connect();
        await webusbClient.startRtt({base: 0x20000000, size: 0x10000});
        connected = true;
        webusbMode = true;
        setConnectUi('connected');
        document.getElementById('status-text').textContent = '已连接 (WebUSB ST-Link)';
        appendTerminal('[+] WebUSB RTT 已启动 @ 0x' + webusbClient.cb.toString(16) + '\n', '#4caf50');
        if (document.getElementById('rtt-stats')) {
            document.getElementById('rtt-stats').textContent = '0x' + webusbClient.cb.toString(16);
        }
    } catch (e) {
        var msg = (e && e.message) ? e.message : String(e);
        appendTerminal('[!] WebUSB 失败: ' + msg + '\n', '#f44336');
        if (/Access|claim|NotFound|Security/i.test(msg)) {
            appendTerminal('[*] Windows: Zadig 把 ST-Link 绑成 WinUSB；关掉占用该口的 ST 工具\n', 'orange');
        }
        try { await webusbClient.disconnect(); } catch (x) {}
        webusbClient = null;
        setConnectUi('idle');
    }
}

async function disconnectWebUsb() {
    if (webusbClient) {
        try { webusbClient.stopRtt(); await webusbClient.disconnect(); } catch (e) {}
        webusbClient = null;
    }
    webusbMode = false;
    setConnectUi('idle');
    appendTerminal('[*] WebUSB 已断开\n', '#569cd6');
}

document.getElementById('btn-connect').addEventListener('click', function() {
    if (connecting) return;
    if (!connected) {
        var scope = getProbeScope();
        if (scope === 'webusb') {
            setConnectUi('connecting');
            connectWebUsb();
            return;
        }
        const sel = document.getElementById('probe-select');
        if (!sel || !sel.value) {
            appendTerminal('[!] 请先扫描并选择探针\n', '#f44336');
            return;
        }
        const probeData = JSON.parse(sel.value);
        setPreferredProbe(probeData);
        const dll = (document.getElementById('jlink-dll').value || '').trim();
        var agent = (document.getElementById('probe-agent') && document.getElementById('probe-agent').value || '').trim();
        if (probeData.agent) agent = probeData.agent;
        if (scope === 'remote' && probeData.type !== 'remote') {
            // force remote path
            probeData.type = 'remote';
            probeData.remote_type = probeData.remote_type || probeData.type;
        }
        setConnectUi('connecting');
        var label = probeData.type === 'remote'
            ? ('remote/' + (probeData.remote_type || '?') + ' @ ' + (agent || '?'))
            : probeData.type;
        appendTerminal('[*] 正在连接 ' + label + ' ...\n', '#569cd6');
        socket.emit('probe_connect', {
            type: probeData.type,
            index: probeData.index || 0,
            mode: document.getElementById('mode-select').value,
            speed: parseInt(document.getElementById('speed-select').value),
            address: document.getElementById('rtt-addr').value,
            channel: parseInt(document.getElementById('rtt-channel').value) || 0,
            dllpath: dll,
            agent: agent,
            remote_type: probeData.remote_type || '',
        });
    } else {
        if (webusbMode) {
            disconnectWebUsb();
        } else {
            socket.emit('probe_disconnect');
        }
    }
});

socket.on('connected', function(data) {
    connected = true;
    webusbMode = false;
    setConnectUi('connected');
    var modeTag = data.mode ? ('/' + data.mode) : '';
    document.getElementById('status-text').textContent = '已连接 (' + data.probe_type + modeTag + ')';
    setPreferredProbe({type: data.probe_type, index: data.index || 0, agent: data.agent || '', remote_type: data.remote_type || ''});
    var sel = document.getElementById('probe-select');
    if (sel) {
        for (var i = 0; i < sel.options.length; i++) {
            try {
                var o = JSON.parse(sel.options[i].value);
                if (o.type === data.probe_type) { sel.selectedIndex = i; break; }
            } catch (e) {}
        }
    }
    if (data.rtt_found) {
        var ch = (data.channel !== undefined) ? data.channel : 0;
        appendTerminal('[+] SEGGER RTT @ ' + data.rtt_addr + '  ch=' + ch + '\n', '#4caf50');
        if (data.rtt_addr && document.getElementById('rtt-addr').value.toLowerCase() === 'auto') {
            document.getElementById('rtt-stats').textContent = data.rtt_addr;
        }
        if (data.session_restored) {
            setTimeout(startRTT, 80);
        }
    } else {
        appendTerminal('[!] 探针已连接，但未找到 RTT 控制块\n', 'orange');
        if (data.rtt_error) appendTerminal('    ' + data.rtt_error + '\n', 'orange');
        appendTerminal('[*] 仍可使用 内存/寄存器/Flash；可改 RTT 地址后点「重扫RTT」\n', '#569cd6');
    }
});

socket.on('disconnected', function() {
    setConnectUi('idle');
    document.getElementById('btn-rtt-start').style.display = '';
    document.getElementById('btn-rtt-stop').style.display = 'none';
});

socket.on('error', function(data) {
    appendTerminal('[!] Error: ' + data.message + '\n', '#f44336');
    if (!connected || connecting) {
        setConnectUi('idle');
    }
    var btnFlash = document.getElementById('btn-flash');
    if (btnFlash) btnFlash.disabled = false;
    if (document.getElementById('panel-flash') &&
        document.getElementById('panel-flash').classList.contains('active')) {
        flashLog('err', data.message);
    }
});

// init scope UI; only poll local/remote lists when those modes selected
updateScopeUi();
setInterval(function() {
    if (getProbeScope() === 'webusb') return;
    // Skip refresh while connecting / connected (avoids USB contention + UI flicker)
    if (connecting || connected) return;
    detectProbes();
}, 15000);

// ─── RTT Terminal ───────────────────────────────────────────────────
let rttAutoScroll = true;
let rttFontSize = 13;
let rttTotalBytes = 0;
let rttLogBuffer = '';  // full text for save (survives DOM trim)

function startRTT() {
    if (webusbMode) {
        appendTerminal('[*] WebUSB RTT 已在浏览器侧运行\n', '#569cd6');
        return;
    }
    const encoding = document.getElementById('encoding-select').value;
    socket.emit('rtt_start', {encoding: encoding});
    appendTerminal('[*] RTT reading started\n', '#569cd6');
}

function rescanRTT() {
    if (webusbMode && webusbClient) {
        webusbClient.findRtt(0x20000000, 0x10000).then(function(cb) {
            appendTerminal('[+] WebUSB RTT @ 0x' + cb.toString(16) + '\n', '#4caf50');
        }).catch(function(e) {
            appendTerminal('[!] ' + e.message + '\n', '#f44336');
        });
        return;
    }
    socket.emit('rtt_rescan', {
        address: document.getElementById('rtt-addr').value,
        channel: parseInt(document.getElementById('rtt-channel').value) || 0,
    });
}

function stopRTT() {
    if (webusbMode && webusbClient) {
        webusbClient.stopRtt();
        appendTerminal('[*] WebUSB RTT 已暂停\n', '#569cd6');
        return;
    }
    socket.emit('rtt_stop');
    appendTerminal('[*] RTT reading stopped\n', '#569cd6');
}

function toggleAutoScroll() {
    rttAutoScroll = !rttAutoScroll;
    const btn = document.getElementById('btn-autoscroll');
    btn.style.background = rttAutoScroll ? 'var(--green)' : 'var(--bg-input)';
    btn.style.color = rttAutoScroll ? '#fff' : 'var(--text)';
}

socket.on('rtt_started', function() {
    document.getElementById('btn-rtt-start').style.display = 'none';
    document.getElementById('btn-rtt-stop').style.display = '';
});

socket.on('rtt_stopped', function() {
    document.getElementById('btn-rtt-start').style.display = '';
    document.getElementById('btn-rtt-stop').style.display = 'none';
});

socket.on('rtt_found', function(data) {
    appendTerminal('[+] SEGGER RTT @ ' + data.rtt_addr + '  ch=' + (data.channel || 0) + '\n', '#4caf50');
    if (data.rtt_addr) document.getElementById('rtt-stats').textContent = data.rtt_addr;
});

socket.on('rtt_data', function(data) {
    if (data.reconnect) {
        appendTerminal('[!] Connection lost, reconnecting...\n', 'orange');
        rttLogBuffer += '[!] Connection lost, reconnecting...\n';
        return;
    }
    if (rttFilter && data.text && data.text.indexOf(rttFilter) < 0) {
        // still keep log buffer full text for save
        if (data.text) rttLogBuffer += data.text;
        if (data.length) {
            rttTotalBytes += data.length;
            document.getElementById('rtt-stats').textContent = (rttTotalBytes / 1024).toFixed(1) + ' KB';
        }
        return;
    }
    if (data.text) {
        rttLogBuffer += data.text;
        // Cap log buffer at ~2MB text
        if (rttLogBuffer.length > 2 * 1024 * 1024) {
            rttLogBuffer = rttLogBuffer.slice(-1024 * 1024);
        }
    }
    var showTimestamp = document.getElementById('rtt-timestamp').checked;
    if (data.segments) {
        const terminal = document.getElementById('rtt-terminal');
        data.segments.forEach(function(seg) {
            if (seg.clear) {
                terminal.innerHTML = '';
                return;
            }
            if (showTimestamp && !seg.clear && seg.text.trim()) {
                var now = new Date();
                var ts = '[' + String(now.getHours()).padStart(2,'0') + ':' +
                         String(now.getMinutes()).padStart(2,'0') + ':' +
                         String(now.getSeconds()).padStart(2,'0') + '.' +
                         String(now.getMilliseconds()).padStart(3,'0') + '] ';
                seg.text = ts + seg.text;
                showTimestamp = false;
            }
            const span = document.createElement('span');
            span.innerHTML = seg.text;
            if (seg.style) span.style.cssText = seg.style;
            terminal.appendChild(span);
        });
        while (terminal.childNodes.length > 5000) {
            terminal.removeChild(terminal.firstChild);
        }
        if (rttAutoScroll) {
            terminal.scrollTop = terminal.scrollHeight;
        }
    }
    if (data.length) {
        rttTotalBytes += data.length;
        document.getElementById('rtt-stats').textContent = (rttTotalBytes / 1024).toFixed(1) + ' KB';
    }
});

function sendRttInput() {
    const input = document.getElementById('rtt-input');
    if (input.value) {
        var text = input.value;
        var le = document.getElementById('rtt-lineending').value;
        // HTML select values are literal backslash sequences — convert to real chars
        if (le === '\\n') text += '\n';
        else if (le === '\\r\\n') text += '\r\n';
        else if (le === '\\r') text += '\r';
        else if (le) text += le;
        socket.emit('rtt_send', {data: text, encoding: 'utf-8'});
        input.value = '';
    }
}

function clearRtt() {
    document.getElementById('rtt-terminal').innerHTML = '';
    rttTotalBytes = 0;
    rttLogBuffer = '';
    document.getElementById('rtt-stats').textContent = '';
}

function saveRttLog() {
    var text = rttLogBuffer || (document.getElementById('rtt-terminal').innerText || '');
    var blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'rtt_log_' + new Date().toISOString().replace(/[:.]/g, '-').slice(0,19) + '.txt';
    a.click();
    URL.revokeObjectURL(a.href);
}

// Send on Enter
document.getElementById('rtt-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        sendRttInput();
    }
});

// Encoding change
document.getElementById('encoding-select').addEventListener('change', function() {
    socket.emit('set_encoding', {encoding: this.value});
});

// Ctrl+Wheel font zoom
document.getElementById('rtt-terminal').addEventListener('wheel', function(e) {
    if (e.ctrlKey) {
        e.preventDefault();
        rttFontSize += (e.deltaY < 0) ? 1 : -1;
        rttFontSize = Math.max(8, Math.min(24, rttFontSize));
        this.style.fontSize = rttFontSize + 'px';
    }
});

// Init auto-scroll button style
(function() {
    const btn = document.getElementById('btn-autoscroll');
    btn.style.background = 'var(--green)';
    btn.style.color = '#fff';
})();

// ─── Waveform display (Chart.js) ──────────────────────────────────────
let waveChart = null;
const WAVE_COLORS = ['#569cd6','#4ec9b0','#dcdcaa','#c586c0','#4caf50','#f44336','#ff9800','#9cdcfe'];

function initWaveChart(nCurve) {
    const ctx = document.getElementById('wave-canvas').getContext('2d');
    if (waveChart) waveChart.destroy();
    const datasets = [];
    for (let i = 0; i < nCurve; i++) {
        datasets.push({
            label: 'Curve ' + (i + 1),
            data: [],
            borderColor: WAVE_COLORS[i % WAVE_COLORS.length],
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
        });
    }
    waveChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: { type: 'linear', display: true, grid: { color: '#3e3e3e' }, ticks: { color: '#808080' } },
                y: { grid: { color: '#3e3e3e' }, ticks: { color: '#808080' } }
            },
            plugins: {
                legend: { labels: { color: '#d4d4d4' } }
            }
        }
    });
}

document.getElementById('btn-wave-start').addEventListener('click', function() {
    const nCurve = parseInt(document.getElementById('wave-ncurve').value);
    const nPoint = parseInt(document.getElementById('wave-npoint').value);
    if (hssChart) { hssChart.destroy(); hssChart = null; }
    socket.emit('hss_stop');  // Stop HSS if running
    initWaveChart(nCurve);
    socket.emit('wave_start', {ncurve: nCurve, npoint: nPoint});
    this.disabled = true;
    document.getElementById('btn-wave-stop').disabled = false;
    document.getElementById('btn-hss-start').disabled = false;
    document.getElementById('btn-hss-stop').disabled = true;
});

document.getElementById('btn-wave-stop').addEventListener('click', function() {
    socket.emit('wave_stop');
    this.disabled = true;
    document.getElementById('btn-wave-start').disabled = false;
});

socket.on('wave_started', function() {
    console.log('[Wave] Started');
});

socket.on('wave_stopped', function() {
    console.log('[Wave] Stopped');
});

socket.on('wave_data', function(data) {
    if (!waveChart || !data.samples) return;
    const nPoint = parseInt(document.getElementById('wave-npoint').value);
    data.samples.forEach(function(sample) {
        for (let i = 0; i < waveChart.data.datasets.length && i < sample.length; i++) {
            const ds = waveChart.data.datasets[i];
            ds.data.push({x: ds.data.length, y: sample[i]});
            if (ds.data.length > nPoint) ds.data.shift();
        }
    });
    // Re-index x values
    waveChart.data.datasets.forEach(function(ds) {
        ds.data.forEach(function(pt, idx) { pt.x = idx; });
    });
    waveChart.update('none');
});

// ─── J-Scope HSS (High-Speed Sampling) ──────────────────────────────
let hssAllVars = [];
let hssChart = null;
const HSS_COLORS = ['#569cd6','#4ec9b0','#dcdcaa','#c586c0','#4caf50','#f44336','#ff9800','#9cdcfe'];

document.getElementById('hss-elf-file').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    fetch('/upload', {method: 'POST', body: formData})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.file_id) {
                socket.emit('hss_load_elf', {file_id: data.file_id});
            }
        });
});

document.getElementById('btn-hss-load').addEventListener('click', function() {
    document.getElementById('hss-elf-file').click();
});

function filterHssVars(query) {
    query = query.toLowerCase();
    document.querySelectorAll('#hss-symbols .hss-var-item').forEach(function(item) {
        var name = item.querySelector('.var-name').textContent.toLowerCase();
        item.style.display = name.includes(query) ? '' : 'none';
    });
}

socket.on('hss_symbols', function(data) {
    hssAllVars = data.variables;
    const container = document.getElementById('hss-symbols');
    container.innerHTML = data.variables.map(function(v, i) {
        return '<div class="hss-var-item">' +
            '<input type="checkbox" data-idx="' + i + '">' +
            '<span class="var-name">' + v.name + '</span>' +
            '<span class="var-addr">0x' + v.addr.toString(16) + '</span>' +
            '<span class="var-size">' + v.size + 'B</span>' +
        '</div>';
    }).join('');
    document.getElementById('btn-hss-start').disabled = false;
});

document.getElementById('btn-hss-select-all').addEventListener('click', function() {
    document.querySelectorAll('#hss-symbols input[type=checkbox]').forEach(function(cb) { cb.checked = true; });
});

document.getElementById('btn-hss-start').addEventListener('click', function() {
    var selected = [];
    document.querySelectorAll('#hss-symbols input[type=checkbox]:checked').forEach(function(cb) {
        var idx = parseInt(cb.dataset.idx);
        if (hssAllVars[idx]) selected.push(hssAllVars[idx]);
    });
    if (selected.length === 0) { alert('请选择至少一个变量'); return; }

    // Init chart (reuse wave-canvas)
    initHssChart(selected.length);
    socket.emit('hss_start', {
        variables: selected,
        interval: parseFloat(document.getElementById('hss-interval').value),
    });
    this.disabled = true;
    document.getElementById('btn-hss-stop').disabled = false;
});

document.getElementById('btn-hss-stop').addEventListener('click', function() {
    socket.emit('hss_stop');
    this.disabled = true;
    document.getElementById('btn-hss-start').disabled = false;
});

function initHssChart(nVars) {
    var ctx = document.getElementById('wave-canvas').getContext('2d');
    if (waveChart) waveChart.destroy();
    if (hssChart) hssChart.destroy();
    var datasets = [];
    for (var i = 0; i < nVars; i++) {
        datasets.push({
            label: 'Var ' + (i+1),
            data: [],
            borderColor: HSS_COLORS[i % HSS_COLORS.length],
            borderWidth: 1.5,
            pointRadius: 0,
        });
    }
    hssChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: {
                x: { type:'linear', grid:{color:'#3e3e3e'}, ticks:{color:'#808080'} },
                y: { grid:{color:'#3e3e3e'}, ticks:{color:'#808080'} }
            },
            plugins: { legend: { labels: { color:'#d4d4d4' } } }
        }
    });
    waveChart = null;  // HSS takes over the canvas
}

socket.on('hss_data', function(data) {
    if (!hssChart || !data.values) return;
    var nPoint = 1000;
    data.values.forEach(function(v, i) {
        if (i < hssChart.data.datasets.length) {
            var ds = hssChart.data.datasets[i];
            ds.label = v.name;
            ds.data.push({x: ds.data.length, y: v.value});
            if (ds.data.length > nPoint) ds.data.shift();
        }
    });
    hssChart.data.datasets.forEach(function(ds) {
        ds.data.forEach(function(pt, idx) { pt.x = idx; });
    });
    hssChart.update('none');
});

socket.on('hss_started', function() {
    console.log('[HSS] Started');
});

socket.on('hss_stopped', function() {
    console.log('[HSS] Stopped');
});

// ─── Oscilloscope (register-based) ─────────────────────────────────
let oscChart = null;
const OSC_COLORS = ['#569cd6','#4ec9b0','#dcdcaa','#c586c0','#4caf50','#f44336','#ff9800','#9cdcfe'];

// Generate channel config rows (default 4 channels, 2 visible)
function initOscChannels(n) {
    const container = document.getElementById('osc-channels');
    container.innerHTML = '';
    for (let i = 0; i < n; i++) {
        const row = document.createElement('div');
        row.className = 'osc-ch-row';
        row.innerHTML = '<span class="ch-color" style="background:' + OSC_COLORS[i] + '"></span>' +
            '<span>CH' + (i+1) + '</span>' +
            '<input type="text" placeholder="地址 0x..." value="' + (i === 0 ? '0x20000000' : '') + '">' +
            '<select><option value="uint32">U32</option><option value="int32">I32</option><option value="float">F32</option><option value="uint16">U16</option><option value="int16">I16</option></select>' +
            '<input type="number" placeholder="缩放" value="1" step="0.1" style="width:50px">' +
            '<label><input type="checkbox" ' + (i < 2 ? 'checked' : '') + '> 显示</label>';
        container.appendChild(row);
    }
}
initOscChannels(4);

function getOscChannels() {
    const rows = document.querySelectorAll('#osc-channels .osc-ch-row');
    const channels = [];
    rows.forEach(function(row) {
        const addrInput = row.querySelector('input[type="text"]');
        const sel = row.querySelector('select');
        const scaleInput = row.querySelector('input[type="number"]');
        const showCb = row.querySelector('input[type="checkbox"]');
        if (showCb.checked) {
            channels.push({
                addr: addrInput.value,
                type: sel.value,
                scale: parseFloat(scaleInput.value) || 1.0,
            });
        }
    });
    return channels;
}

function initOscChart(nChannels) {
    const ctx = document.getElementById('osc-canvas').getContext('2d');
    if (oscChart) oscChart.destroy();
    const datasets = [];
    for (let i = 0; i < nChannels; i++) {
        datasets.push({
            label: 'CH' + (i + 1),
            data: [],
            borderColor: OSC_COLORS[i % OSC_COLORS.length],
            borderWidth: 1.5,
            pointRadius: 0,
        });
    }
    oscChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: { type: 'linear', display: true, grid: { color: '#3e3e3e' }, ticks: { color: '#808080' } },
                y: { grid: { color: '#3e3e3e' }, ticks: { color: '#808080' } }
            },
            plugins: { legend: { labels: { color: '#d4d4d4' } } }
        }
    });
}

document.getElementById('btn-osc-start').addEventListener('click', function() {
    var channels = getOscChannels();
    if (channels.length === 0) { alert('请至少启用一个通道'); return; }
    initOscChart(channels.length);
    socket.emit('osc_start', {
        channels: channels,
        timebase: parseFloat(document.getElementById('osc-timebase').value),
        trigger: document.getElementById('osc-trigger').value,
        trigger_level: parseFloat(document.getElementById('osc-trigger-level').value) || 0,
        trigger_ch: parseInt(document.getElementById('osc-trigger-ch').value),
        single: document.getElementById('osc-single').checked,
    });
    this.disabled = true;
    document.getElementById('btn-osc-stop').disabled = false;
});

document.getElementById('btn-osc-stop').addEventListener('click', function() {
    socket.emit('osc_stop');
    this.disabled = true;
    document.getElementById('btn-osc-start').disabled = false;
});

socket.on('osc_started', function() {
    console.log('[OSC] Started');
});

socket.on('osc_stopped', function() {
    console.log('[OSC] Stopped');
    document.getElementById('btn-osc-stop').disabled = true;
    document.getElementById('btn-osc-start').disabled = false;
});

socket.on('osc_data', function(data) {
    if (!oscChart || !data.buffers) return;
    for (var i = 0; i < oscChart.data.datasets.length && i < data.buffers.length; i++) {
        var buf = data.buffers[i];
        oscChart.data.datasets[i].data = buf.map(function(v, idx) { return {x: idx, y: v}; });
    }
    oscChart.update('none');

    // Update measurements
    if (data.measurements) {
        var div = document.getElementById('osc-measurements');
        div.innerHTML = data.measurements.map(function(m, i) {
            return '<div><span style="color:' + OSC_COLORS[i % OSC_COLORS.length] + '">CH' + (i+1) + '</span>: ' +
                'Vpp=' + m.pp + ' Min=' + m.min + ' Max=' + m.max + ' Avg=' + m.avg + '</div>';
        }).join('');
    }
});

// ─── SWO ────────────────────────────────────────────────────────────
// Sub-tab switching
document.querySelectorAll('.swo-subtab').forEach(function(btn) {
    btn.addEventListener('click', function() {
        document.querySelectorAll('.swo-subtab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.swo-subpanel').forEach(p => p.classList.remove('active'));
        this.classList.add('active');
        document.getElementById('swo-' + this.dataset.subtab).classList.add('active');
    });
});

document.getElementById('btn-swo-start').addEventListener('click', function() {
    socket.emit('swo_start', {speed: parseInt(document.getElementById('swo-speed').value)});
    this.disabled = true;
    document.getElementById('btn-swo-stop').disabled = false;
});

document.getElementById('btn-swo-stop').addEventListener('click', function() {
    socket.emit('swo_stop');
    this.disabled = true;
    document.getElementById('btn-swo-start').disabled = false;
});

socket.on('swo_started', function() {
    console.log('[SWO] Started');
});

socket.on('swo_stopped', function() {
    console.log('[SWO] Stopped');
    document.getElementById('btn-swo-stop').disabled = true;
    document.getElementById('btn-swo-start').disabled = false;
});

// SWO Console
socket.on('swo_text', function(data) {
    var term = document.getElementById('swo-terminal');
    term.textContent += data.text;
    if (term.textContent.length > 50000) {
        term.textContent = term.textContent.slice(-25000);
    }
    term.scrollTop = term.scrollHeight;
});

// CPU Profiler
socket.on('swo_profiler', function(data) {
    var tbody = document.getElementById('profiler-table');
    tbody.innerHTML = data.functions.map(function(f) {
        return '<tr><td>' + f.addr + '</td><td>' + f.count + '</td><td>' + f.pct + '%</td>' +
            '<td><div style="background:var(--accent);height:8px;width:' + f.pct + '%;border-radius:2px"></div></td></tr>';
    }).join('');
});

// Exception Tracker
socket.on('swo_exception', function(data) {
    var log = document.getElementById('exception-log');
    var dir = data.entry ? '→' : '←';
    var color = data.entry ? 'var(--green)' : 'var(--red)';
    log.innerHTML += '<div><span style="color:' + color + '">' + dir + ' ' + data.name + ' (IRQ ' + data.num + ')</span></div>';
    while (log.childNodes.length > 500) {
        log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
});

// ─── RTOS task viewer ─────────────────────────────────────────────────
document.getElementById('btn-rtos-start').addEventListener('click', function() {
    socket.emit('rtos_start', {});
    this.disabled = true;
    document.getElementById('btn-rtos-stop').disabled = false;
});

document.getElementById('btn-rtos-stop').addEventListener('click', function() {
    socket.emit('rtos_stop');
    this.disabled = true;
    document.getElementById('btn-rtos-start').disabled = false;
});

socket.on('rtos_started', function() {
    console.log('[RTOS] Started');
});

socket.on('rtos_stopped', function() {
    console.log('[RTOS] Stopped');
    document.getElementById('btn-rtos-stop').disabled = true;
    document.getElementById('btn-rtos-start').disabled = false;
});

socket.on('rtos_data', function(data) {
    var tbody = document.getElementById('rtos-tbody');
    document.getElementById('rtos-status').textContent = '任务数: ' + data.tasks.length;

    tbody.innerHTML = data.tasks.map(function(t) {
        var stateClass = 'state-ready';
        if (t.state === 'Running') stateClass = 'state-running';
        else if (t.state === 'Blocked') stateClass = 'state-blocked';
        else if (t.state === 'Suspended') stateClass = 'state-suspended';
        else if (t.state === 'Deleted') stateClass = 'state-deleted';

        var stackClass = 'stack-low';
        if (t.stack_percent > 90) stackClass = 'stack-high';
        else if (t.stack_percent > 70) stackClass = 'stack-mid';

        return '<tr>' +
            '<td>' + t.name + '</td>' +
            '<td class="' + stateClass + '">' + t.state + '</td>' +
            '<td>' + t.priority + '</td>' +
            '<td><div class="stack-bar"><div class="stack-bar-fill ' + stackClass + '" style="width:' + Math.min(100, t.stack_percent) + '%"></div></div> ' + t.stack_percent + '%</td>' +
            '<td>' + t.stack_used + ' / ' + t.stack_size + ' B</td>' +
            '<td>' + t.tcb_addr + '</td>' +
        '</tr>';
    }).join('');
});

// ─── Crash analyzer ──────────────────────────────────────────────────
document.getElementById('btn-crash-analyze').addEventListener('click', function() {
    document.getElementById('crash-status').textContent = '分析中...';
    socket.emit('crash_analyze', {});
});

function crashClear() {
    document.getElementById('crash-regs').innerHTML = '';
    document.getElementById('crash-faults').innerHTML = '';
    document.getElementById('crash-cfsr').innerHTML = '';
    document.getElementById('crash-hfsr').innerHTML = '';
    document.getElementById('crash-xpsr').innerHTML = '';
    document.getElementById('crash-stack').innerHTML = '';
    document.getElementById('crash-status').textContent = '';
}

function getExceptionName(num) {
    var names = {
        0:'Thread Mode', 1:'Reset', 2:'NMI', 3:'HardFault',
        4:'MemManage', 5:'BusFault', 6:'UsageFault',
        11:'SVCall', 12:'Debug Monitor', 14:'PendSV', 15:'SysTick',
    };
    return names[num] || (num >= 16 ? 'IRQ ' + (num - 16) : 'Exception ' + num);
}

socket.on('crash_data', function(data) {
    document.getElementById('crash-status').textContent = '分析完成';

    // Core registers
    var regsDiv = document.getElementById('crash-regs');
    regsDiv.innerHTML = Object.entries(data.registers).map(function(entry) {
        return '<div class="crash-reg"><span class="name">' + entry[0] + '</span><span class="val">' + entry[1] + '</span></div>';
    }).join('');

    // Fault registers
    var faultsDiv = document.getElementById('crash-faults');
    faultsDiv.innerHTML = Object.entries(data.faults).map(function(entry) {
        return '<div class="crash-fault-row"><span>' + entry[0].toUpperCase() + '</span><span style="color:var(--cyan)">' + entry[1] + '</span></div>';
    }).join('');

    // CFSR decode
    var cfsrDiv = document.getElementById('crash-cfsr');
    var cfsrHtml = '';
    for (var group in data.cfsr_decode) {
        if (!data.cfsr_decode.hasOwnProperty(group)) continue;
        var flags = data.cfsr_decode[group];
        cfsrHtml += '<div class="crash-decode-group"><h4>' + group + '</h4>';
        for (var flag in flags) {
            if (!flags.hasOwnProperty(flag)) continue;
            var set = flags[flag];
            cfsrHtml += '<span class="crash-flag ' + (set ? 'crash-flag-set' : 'crash-flag-clear') + '">' + flag + '</span>';
        }
        cfsrHtml += '</div>';
    }
    if (!cfsrHtml) cfsrHtml = '<div style="color:var(--text-dim)">无故障</div>';
    cfsrDiv.innerHTML = cfsrHtml;

    // HFSR decode
    var hfsrDiv = document.getElementById('crash-hfsr');
    var hfsrHtml = '';
    for (var flag in data.hfsr_decode) {
        if (!data.hfsr_decode.hasOwnProperty(flag)) continue;
        var set = data.hfsr_decode[flag];
        hfsrHtml += '<span class="crash-flag ' + (set ? 'crash-flag-set' : 'crash-flag-clear') + '">' + flag + '</span>';
    }
    if (!hfsrHtml) hfsrHtml = '<div style="color:var(--text-dim)">无硬故障</div>';
    hfsrDiv.innerHTML = hfsrHtml;

    // xPSR decode
    var xpsrDiv = document.getElementById('crash-xpsr');
    if (data.xpsr_decode && data.xpsr_decode.exception_number !== undefined) {
        var x = data.xpsr_decode;
        xpsrDiv.innerHTML =
            '<div>异常号: <span style="color:var(--cyan)">' + x.exception_number + '</span> (' + getExceptionName(x.exception_number) + ')</div>' +
            '<div>Thumb: <span style="color:' + (x.thumb ? 'var(--green)' : 'var(--red)') + '">' + x.thumb + '</span></div>' +
            '<div>Flags: ' + (x.negative?'N':'n') + (x.zero?'Z':'z') + (x.carry?'C':'c') + (x.overflow?'V':'v') + '</div>';
    } else {
        xpsrDiv.innerHTML = '<div style="color:var(--text-dim)">无法读取 xPSR</div>';
    }

    // Stack walk
    var stackDiv = document.getElementById('crash-stack');
    stackDiv.innerHTML = data.stack_addrs.map(function(addr) {
        return '<div class="crash-stack-addr">' + addr + '</div>';
    }).join('') || '<div style="color:var(--text-dim)">未找到有效返回地址</div>';

    // Fault address highlight
    if (data.fault_addr && data.fault_addr !== '0x00000000') {
        stackDiv.innerHTML = '<div style="color:var(--yellow);margin-bottom:6px">故障地址: ' + data.fault_addr + '</div>' + stackDiv.innerHTML;
    }
});

// ─── Flash programmer ────────────────────────────────────────────────
var flashFileId = null;

function handleFileSelect(e) { uploadFile(e.target.files[0]); }
function handleDrop(e) {
    e.preventDefault();
    document.getElementById('upload-zone').style.borderColor = 'var(--border)';
    if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
}
function uploadFile(file) {
    const fd = new FormData();
    fd.append('file', file);
    fetch('/upload', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(d => {
            if (d.error) {
                flashLog('err', '上传失败: ' + d.error);
                return;
            }
            flashFileId = d.file_id;
            document.getElementById('flash-file-info').textContent =
                file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
            document.getElementById('flash-file-info').style.color = 'var(--green)';
            document.getElementById('btn-flash').disabled = false;
            flashLog('info', '文件已上传: ' + file.name);
        })
        .catch(function(err) { flashLog('err', '上传错误: ' + err); });
}

function flashProgram() {
    if (!flashFileId) return;
    document.getElementById('btn-flash').disabled = true;
    flashLog('info', '开始烧录...');
    socket.emit('flash_file', {
        file_id: flashFileId,
        addr: document.getElementById('flash-addr').value,
        verify: document.getElementById('flash-verify').checked,
    });
}

function mcuReset(haltAfter) {
    if (!connected) {
        appendTerminal('[!] 未连接探针，无法复位\n', '#e03e3e');
        return;
    }
    if (webusbMode && webusbClient) {
        appendTerminal('[*] WebUSB 复位 MCU...\n', '#569cd6');
        webusbClient.reset().then(function() {
            appendTerminal('[+] WebUSB 复位后 RTT @ 0x' + webusbClient.cb.toString(16) + '\n', '#4caf50');
            if (!webusbClient.running) webusbClient.startRtt({base: 0x20000000, size: 0x10000});
        }).catch(function(e) {
            appendTerminal('[!] 复位失败: ' + e.message + '\n', '#f44336');
        });
        return;
    }
    socket.emit('mcu_reset', {halt_after: !!haltAfter});
    appendTerminal(haltAfter ? '[*] 复位+Halt...\n' : '[*] 复位 MCU...\n', '#569cd6');
    try { flashLog('info', haltAfter ? '复位+Halt 请求已发送' : 'MCU 复位请求已发送'); } catch(e) {}
}

socket.on('flash_progress', function(data) {
    document.getElementById('flash-progress').style.width = data.percent + '%';
    document.getElementById('flash-status').textContent = data.status;
    if (data.percent === 100) {
        document.getElementById('btn-flash').disabled = false;
        flashLog('ok', data.status);
    }
});

socket.on('flash_done', function(data) {
    flashLog('ok', '烧录完成: ' + data.size + ' 字节 @ ' + data.addr);
    if (data.rtt_found) {
        flashLog('ok', 'RTT 已恢复 @ ' + data.rtt_addr);
        appendTerminal('[+] 烧录后 RTT @ ' + data.rtt_addr + '\n', '#4caf50');
    } else {
        flashLog('warn', '烧录完成但未找到 RTT，请检查固件或地址后重连');
    }
    document.getElementById('btn-flash').disabled = false;
});

socket.on('mcu_reset_done', function(data) {
    var msg = 'MCU 复位完成';
    if (data && data.halted) msg += ' (Halt)';
    if (data && data.rtt_addr) msg += ' | RTT ' + data.rtt_addr;
    if (data && data.rtt_resumed) {
        msg += ' | 已自动恢复读取';
        // UI buttons: show Stop
        var s = document.getElementById('btn-rtt-start');
        var t = document.getElementById('btn-rtt-stop');
        if (s) s.style.display = 'none';
        if (t) t.style.display = '';
    } else if (data && data.rtt_error) {
        msg += ' | RTT恢复失败: ' + data.rtt_error;
    }
    appendTerminal('[+] ' + msg + '\n', (data && data.rtt_resumed) ? '#1a9b5c' : '#d97706');
    try { flashLog('ok', msg); } catch(e) {}
});

// ─── Serial flash UI ──────────────────────────────────────────────────
var serialFileId = null;
function serialLog(level, msg) {
    var log = document.getElementById('serial-log');
    if (!log) return;
    var div = document.createElement('div');
    div.className = 'log-' + level;
    div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}
function refreshSerialPorts() {
    socket.emit('serial_list');
}
socket.on('serial_ports', function(data) {
    var sel = document.getElementById('serial-port');
    if (!sel) return;
    var prev = sel.value;
    sel.innerHTML = '';
    (data.ports || []).forEach(function(p) {
        var opt = document.createElement('option');
        opt.value = p.device;
        opt.textContent = p.label || p.device;
        sel.appendChild(opt);
    });
    if (!sel.options.length) {
        var o = document.createElement('option');
        o.value = ''; o.textContent = '无串口';
        sel.appendChild(o);
    } else if (prev) {
        sel.value = prev;
    }
    serialLog('info', '串口列表: ' + (data.ports || []).length + ' 个');
});
function handleSerialFile(e) { uploadSerialFile(e.target.files[0]); }
function handleSerialDrop(e) {
    e.preventDefault();
    if (e.dataTransfer.files.length) uploadSerialFile(e.dataTransfer.files[0]);
}
function uploadSerialFile(file) {
    if (!file) return;
    var fd = new FormData();
    fd.append('file', file);
    fetch('/upload', { method: 'POST', body: fd })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.error) { serialLog('err', d.error); return; }
            serialFileId = d.file_id;
            document.getElementById('serial-file-info').textContent =
                file.name + ' (' + (file.size/1024).toFixed(1) + ' KB)';
            document.getElementById('serial-file-info').style.color = 'var(--green)';
            document.getElementById('btn-serial-flash').disabled = false;
            serialLog('info', '已上传: ' + file.name);
        })
        .catch(function(err) { serialLog('err', String(err)); });
}
function serialFlash() {
    if (!serialFileId) return;
    var port = document.getElementById('serial-port').value;
    if (!port) { serialLog('err', '请选择串口'); return; }
    document.getElementById('btn-serial-flash').disabled = true;
    serialLog('info', '开始串口烧录 ' + port + '...');
    socket.emit('serial_flash', {
        port: port,
        baud: parseInt(document.getElementById('serial-baud').value),
        protocol: document.getElementById('serial-proto').value,
        file_id: serialFileId,
        addr: document.getElementById('serial-addr').value,
        erase: document.getElementById('serial-erase').checked,
        dtr_reset: document.getElementById('serial-dtr').checked,
    });
}
socket.on('serial_flash_progress', function(data) {
    var bar = document.getElementById('serial-progress');
    var st = document.getElementById('serial-status');
    if (bar) bar.style.width = (data.percent || 0) + '%';
    if (st) st.textContent = data.status || '';
    if (data.percent === 100) {
        document.getElementById('btn-serial-flash').disabled = false;
        serialLog('ok', data.status || '完成');
    }
});
socket.on('serial_flash_done', function(data) {
    serialLog('ok', '烧录完成 ' + data.size + ' 字节 @ ' + data.addr + ' via ' + data.port);
    document.getElementById('btn-serial-flash').disabled = false;
});
// refresh ports when opening serial tab
var _origSwitchTab = switchTab;
switchTab = function(tabId) {
    _origSwitchTab(tabId);
    if (tabId === 'serial') refreshSerialPorts();
};

function flashLog(level, msg) {
    var log = document.getElementById('flash-log');
    var time = new Date().toLocaleTimeString();
    var div = document.createElement('div');
    div.className = 'log-' + level;
    div.textContent = '[' + time + '] ' + msg;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

// ─── Memory viewer ─────────────────────────────────────────────────────
let memRefreshTimer = null;

document.getElementById('btn-mem-read').addEventListener('click', readMemory);

function readMemory() {
    socket.emit('mem_read', {
        addr: document.getElementById('mem-addr').value,
        size: parseInt(document.getElementById('mem-size').value),
    });
}

// Quick jump buttons
document.querySelectorAll('.btn-quick').forEach(function(btn) {
    btn.addEventListener('click', function() {
        document.getElementById('mem-addr').value = this.dataset.addr;
        readMemory();
    });
});

// Auto-refresh
document.getElementById('mem-auto-refresh').addEventListener('change', function() {
    if (this.checked) {
        memRefreshTimer = setInterval(readMemory, 500);
    } else {
        clearInterval(memRefreshTimer);
        memRefreshTimer = null;
    }
});

socket.on('mem_data', function(data) {
    const container = document.getElementById('mem-hexdump');

    container.innerHTML = data.lines.map(function(line) {
        // Color hex bytes
        const hexHtml = line.hex.split(' ').map(function(byte) {
            if (byte === '') return ' ';  // Middle spacer
            let cls = 'mem-byte';
            if (byte === '00') cls += ' mem-byte-zero';
            else if (byte === 'FF') cls += ' mem-byte-ff';
            return `<span class="${cls}">${byte}</span>`;
        }).join(' ');

        // Color ASCII
        const asciiHtml = line.ascii.split('').map(function(ch) {
            const cls = ch === '.' ? 'mem-ascii-char mem-ascii-dot' : 'mem-ascii-char mem-byte-print';
            return `<span class="${cls}">${ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : ch === '&' ? '&amp;' : ch}</span>`;
        }).join('');

        return `<div class="mem-line mem-region-${line.region}">
            <span class="mem-line-addr">${line.addr}</span>
            <span class="mem-line-hex">${hexHtml}</span>
            <span class="mem-line-ascii">${asciiHtml}</span>
        </div>`;
    }).join('');
});

// ─── Core Register Viewer ──────────────────────────────────────────────
document.getElementById('btn-cpu-start').addEventListener('click', function() {
    socket.emit('core_regs_start', {});
    this.disabled = true;
    document.getElementById('btn-cpu-stop').disabled = false;
    document.getElementById('cpu-status').textContent = '读取中...';
});

document.getElementById('btn-cpu-stop').addEventListener('click', function() {
    socket.emit('core_regs_stop');
    this.disabled = true;
    document.getElementById('btn-cpu-start').disabled = false;
    document.getElementById('cpu-status').textContent = '已停止';
});

socket.on('core_regs_started', function() {
    document.getElementById('cpu-status').textContent = '读取中...';
});

socket.on('core_regs_stopped', function() {
    document.getElementById('cpu-status').textContent = '已停止';
});

socket.on('core_regs_data', function(data) {
    var tbody = document.getElementById('cpu-regs-tbody');
    var mode = data.mode;

    // Update mode indicator
    document.getElementById('cpu-mode').textContent = mode.startsWith('arm') ? 'ARM Cortex-M' : 'RISC-V';

    // Build register rows
    var html = '';
    var vals = data.values;
    var changed = data.changed || {};

    // Group registers
    var groups;
    if (mode.startsWith('arm')) {
        groups = [
            {name: '通用寄存器', regs: ['r0','r1','r2','r3','r4','r5','r6','r7','r8','r9','r10','r11','r12']},
            {name: '特殊寄存器', regs: ['sp','lr','pc']},
            {name: '状态/控制', regs: ['xpsr','msp','psp','control','faultmask','basepri','primask']},
        ];
    } else {
        groups = [
            {name: 'x0-x15', regs: Array.from({length:16}, function(_,i){return 'x'+i;})},
            {name: 'x16-x31', regs: Array.from({length:16}, function(_,i){return 'x'+(i+16);})},
            {name: '特殊', regs: ['pc','mstatus','mcause','mtval','mie','mip']},
        ];
    }

    groups.forEach(function(g) {
        html += '<tr><td colspan="3" style="color:var(--yellow);font-size:11px;padding-top:8px">' + g.name + '</td></tr>';
        g.regs.forEach(function(name) {
            var val = vals[name];
            if (val === undefined) return;
            var hex = val === null ? 'N/A' : '0x' + (val >>> 0).toString(16).padStart(8, '0');
            var dec = val === null ? '—' : (val >>> 0).toString();
            var cls = changed[name] ? ' reg-changed' : '';
            html += '<tr><td class="reg-name">' + name + '</td><td class="reg-val' + cls + '">' + hex + '</td><td class="reg-dec">' + dec + '</td></tr>';
        });
    });

    tbody.innerHTML = html;

    // xPSR decode (ARM)
    if (data.xpsr_decode && Object.keys(data.xpsr_decode).length > 0) {
        document.getElementById('cpu-xpsr').style.display = 'block';
        var x = data.xpsr_decode;
        document.getElementById('cpu-xpsr-content').innerHTML =
            '<div class="cpu-decode-row"><span class="label">异常号</span><span class="value">' + x.exception_number + ' (' + x.exception_name + ')</span></div>' +
            '<div class="cpu-decode-row"><span class="label">Thumb</span><span class="value">' + (x.thumb ? '是' : '否') + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">GE</span><span class="value">' + x.ge + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">ICI/IT</span><span class="value">' + x.ici_it + '</span></div>' +
            '<div class="cpu-flags">' +
                '<span class="cpu-flag ' + (x.negative ? 'cpu-flag-set' : 'cpu-flag-clear') + '">N</span>' +
                '<span class="cpu-flag ' + (x.zero ? 'cpu-flag-set' : 'cpu-flag-clear') + '">Z</span>' +
                '<span class="cpu-flag ' + (x.carry ? 'cpu-flag-set' : 'cpu-flag-clear') + '">C</span>' +
                '<span class="cpu-flag ' + (x.overflow ? 'cpu-flag-set' : 'cpu-flag-clear') + '">V</span>' +
                '<span class="cpu-flag ' + (x.saturation ? 'cpu-flag-set' : 'cpu-flag-clear') + '">Q</span>' +
            '</div>';
    } else {
        document.getElementById('cpu-xpsr').style.display = 'none';
    }

    // mstatus decode (RISC-V)
    if (data.mstatus_decode && Object.keys(data.mstatus_decode).length > 0) {
        document.getElementById('cpu-mstatus').style.display = 'block';
        var m = data.mstatus_decode;
        document.getElementById('cpu-mstatus-content').innerHTML =
            '<div class="cpu-decode-row"><span class="label">MIE</span><span class="value">' + (m.mie ? '使能' : '禁止') + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">MPIE</span><span class="value">' + (m.mpie ? '是' : '否') + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">MPP</span><span class="value">' + m.mpp + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">SIE</span><span class="value">' + (m.sie ? '使能' : '禁止') + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">SPIE</span><span class="value">' + (m.spie ? '是' : '否') + '</span></div>' +
            '<div class="cpu-decode-row"><span class="label">SPP</span><span class="value">' + (m.spp ? 'S-mode' : 'U-mode') + '</span></div>';
    } else {
        document.getElementById('cpu-mstatus').style.display = 'none';
    }
});

// ─── Status bar clock ───────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    document.getElementById('status-time').textContent = h + ':' + m + ':' + s;
}
setInterval(updateClock, 1000);
updateClock();

// ─── Load SVD files list ────────────────────────────────────────────
fetch('/svd_files').then(r => r.json()).then(d => {
    const sel = document.getElementById('svd-file-select');
    d.files.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f; opt.textContent = f;
        sel.appendChild(opt);
    });
});

// ─── SVD Register Viewer ──────────────────────────────────────────────
let svdTree = null;
let svdAutoRefreshTimer = null;
let svdVisibleRegs = new Set();  // Set of "0x40021000" addresses being displayed
let svdPrevValues = {};  // Previous values for change detection

document.getElementById('btn-svd-load').addEventListener('click', function() {
    const fileId = document.getElementById('svd-file-select').value;
    if (!fileId) return;
    socket.emit('svd_load', {file_id: fileId});
    document.getElementById('svd-status').textContent = '加载中...';
});

socket.on('svd_tree', function(data) {
    svdTree = data;
    document.getElementById('svd-status').textContent = data.peripherals.length + ' 个外设';
    renderSvdTree(data);
});

function renderSvdTree(tree) {
    const container = document.getElementById('svd-tree');
    container.innerHTML = tree.peripherals.map(function(p, pi) {
        const regHtml = p.registers.map(function(r, ri) {
            return '<div class="svd-reg" data-addr="' + r.addr + '" data-name="' + p.name + '.' + r.name + '" onclick="selectRegister(this)">' +
                '<span class="reg-name">' + r.name + '</span>' +
                '<span class="reg-addr">' + r.offset + '</span>' +
                '<span class="reg-val" id="svd-val-' + r.addr.replace('0x','') + '">&mdash;</span>' +
            '</div>';
        }).join('');

        return '<div class="svd-periph">' +
            '<div class="svd-periph-header" onclick="togglePeriph(this)">' +
                '<span class="arrow">&#9654;</span>' +
                '<span>' + p.name + '</span>' +
                '<span class="svd-periph-addr">' + p.base_addr + '</span>' +
            '</div>' +
            '<div class="svd-reg-list" id="svd-periph-' + pi + '">' + regHtml + '</div>' +
        '</div>';
    }).join('');
}

function togglePeriph(el) {
    const list = el.nextElementSibling;
    const arrow = el.querySelector('.arrow');
    list.classList.toggle('open');
    arrow.classList.toggle('open');

    // Auto-read all register values when opening
    if (list.classList.contains('open')) {
        const regs = list.querySelectorAll('.svd-reg');
        const addrs = [];
        regs.forEach(r => addrs.push(r.dataset.addr));
        if (addrs.length > 0) {
            socket.emit('svd_read_batch', {addrs: addrs});
        }
    }
}

function selectRegister(el) {
    const addr = el.dataset.addr;
    const name = el.dataset.name;

    // Find register details in tree
    let regInfo = null;
    for (const p of svdTree.peripherals) {
        for (const r of p.registers) {
            if (r.addr === addr) {
                regInfo = r;
                break;
            }
        }
        if (regInfo) break;
    }
    if (!regInfo) return;

    // Read current value
    socket.emit('svd_read', {addr: addr});

    // Show detail
    const detail = document.getElementById('svd-detail');
    const valEl = document.getElementById('svd-val-' + addr.replace('0x',''));
    const currentVal = valEl ? valEl.textContent : '—';

    let fieldsHtml = '';
    if (regInfo.fields && regInfo.fields.length > 0) {
        fieldsHtml = '<table class="svd-field-table">' +
            '<thead><tr><th>位域</th><th>位范围</th><th>描述</th><th>值</th></tr></thead>' +
            '<tbody>' + regInfo.fields.map(function(f) {
                const lo = f.bit_offset;
                const hi = lo + f.bit_width - 1;
                const bits = f.bit_width === 1 ? '[' + lo + ']' : '[' + hi + ':' + lo + ']';
                return '<tr>' +
                    '<td style="color:var(--yellow)">' + f.name + '</td>' +
                    '<td>' + bits + '</td>' +
                    '<td>' + (f.description || '—') + '</td>' +
                    '<td class="field-val" data-lo="' + lo + '" data-width="' + f.bit_width + '">—</td>' +
                '</tr>';
            }).join('') + '</tbody>' +
        '</table>';
    }

    detail.innerHTML =
        '<h3>' + name + '</h3>' +
        '<div class="reg-info">' + (regInfo.description || '') + ' | ' + regInfo.access + '</div>' +
        '<div class="reg-value" id="svd-detail-val">' + currentVal + '</div>' +
        fieldsHtml;

    svdVisibleRegs.add(addr);
}

// Register value updates
socket.on('svd_value', function(data) {
    const hex = data.hex;
    const cellId = 'svd-val-' + data.addr.replace('0x','');
    const cell = document.getElementById(cellId);
    if (cell) {
        const prev = svdPrevValues[data.addr];
        cell.textContent = hex;
        if (prev !== undefined && prev !== data.value) {
            cell.classList.add('reg-changed');
            setTimeout(function() { cell.classList.remove('reg-changed'); }, 1000);
        }
        svdPrevValues[data.addr] = data.value;
    }

    // Update detail view
    const detailVal = document.getElementById('svd-detail-val');
    if (detailVal) detailVal.textContent = hex;

    // Update field values
    document.querySelectorAll('.field-val').forEach(function(el) {
        const lo = parseInt(el.dataset.lo);
        const width = parseInt(el.dataset.width);
        const mask = (1 << width) - 1;
        const val = (data.value >> lo) & mask;
        el.textContent = width <= 4 ? '0x' + val.toString(16) : val;
    });
});

socket.on('svd_values', function(data) {
    for (const [addr, val] of Object.entries(data.values)) {
        if (val === null) continue;
        const hex = '0x' + val.toString(16).padStart(8, '0');
        const cellId = 'svd-val-' + addr.replace('0x','');
        const cell = document.getElementById(cellId);
        if (cell) {
            const prev = svdPrevValues[addr];
            cell.textContent = hex;
            if (prev !== undefined && prev !== val) {
                cell.classList.add('reg-changed');
                setTimeout(function() { cell.classList.remove('reg-changed'); }, 1000);
            }
            svdPrevValues[addr] = val;
        }
    }
});

// Auto-refresh
document.getElementById('svd-auto-refresh').addEventListener('change', function() {
    if (this.checked) {
        svdAutoRefreshTimer = setInterval(function() {
            if (svdVisibleRegs.size > 0) {
                socket.emit('svd_read_batch', {addrs: Array.from(svdVisibleRegs)});
            }
        }, 200);
    } else {
        clearInterval(svdAutoRefreshTimer);
        svdAutoRefreshTimer = null;
    }
});

// ─── Debug: CPU control / watch / disasm / mem write ──────────────────
var watchItems = [];

function cpuHalt() { socket.emit('cpu_halt'); }
function cpuGo() { socket.emit('cpu_go'); }
function cpuStep() { socket.emit('cpu_step'); }
function cpuResetHalt() { socket.emit('cpu_reset_halt'); }

socket.on('cpu_state', function(data) {
    var s = data.halted ? 'HALTED' : 'RUNNING';
    if (data.pc) s += ' PC=' + data.pc;
    appendTerminal('[CPU] ' + s + '\n', data.halted ? '#e03e3e' : '#1a9b5c');
    var el = document.getElementById('cpu-status');
    if (el) el.textContent = s;
    refreshTargetInfo();
});

function refreshTargetInfo() {
    socket.emit('target_info');
}
socket.on('target_info', function(info) {
    var box = document.getElementById('target-info');
    if (!box) return;
    var rows = [];
    function add(k, v) { if (v !== undefined && v !== null && v !== '') rows.push([k, v]); }
    add('探针', info.probe_type);
    add('模式', info.mode);
    add('内核', info.core_type);
    add('CPUID', info.cpuid);
    add('Halt', info.halted === true ? '是' : (info.halted === false ? '否' : '?'));
    add('RTT', info.rtt_addr);
    add('PC', info.pc); add('SP', info.sp); add('LR', info.lr);
    add('xPSR', info.xpsr); add('MSP', info.msp); add('PSP', info.psp);
    if (info.probe) {
        add('产品', info.probe.product_name);
        add('序列号', info.probe.serial_number);
        if (info.probe.voltage_mv != null) add('VTref', (info.probe.voltage_mv/1000).toFixed(2) + ' V');
    }
    if (info.voltage_mv != null) add('VTref', (info.voltage_mv/1000).toFixed(2) + ' V');
    box.innerHTML = rows.map(function(r) {
        return '<div class="k">' + r[0] + '</div><div class="v">' + r[1] + '</div>';
    }).join('') || '<div class="k">状态</div><div class="v">无数据</div>';
});

function watchAdd() {
    var name = document.getElementById('watch-name').value || document.getElementById('watch-addr').value;
    var addr = document.getElementById('watch-addr').value;
    var type = document.getElementById('watch-type').value;
    if (!addr) return;
    watchItems.push({name: name, addr: addr, type: type});
    renderWatchTable();
}
function watchRemove(i) {
    watchItems.splice(i, 1);
    renderWatchTable();
    if (watchItems.length) watchStart();
    else watchStop();
}
function renderWatchTable() {
    var tb = document.getElementById('watch-tbody');
    if (!tb) return;
    tb.innerHTML = watchItems.map(function(it, i) {
        return '<tr><td>' + it.name + '</td><td>' + it.addr + '</td><td>' + it.type +
            '</td><td id="watch-val-' + i + '">—</td><td><button class="btn" onclick="watchRemove(' + i + ')">删</button></td></tr>';
    }).join('');
}
function watchStart() {
    socket.emit('watch_start', {items: watchItems});
}
function watchStop() { socket.emit('watch_stop'); }
socket.on('watch_data', function(data) {
    (data.rows || []).forEach(function(r, i) {
        var el = document.getElementById('watch-val-' + i);
        if (!el) return;
        el.textContent = r.error ? ('ERR ' + r.error) : (r.hex + ' (' + r.value + ')');
    });
});

function memWrite() {
    socket.emit('mem_write', {
        addr: document.getElementById('mw-addr').value,
        width: parseInt(document.getElementById('mw-width').value),
        value: document.getElementById('mw-value').value,
    });
}
function memFill() {
    socket.emit('mem_fill', {
        addr: document.getElementById('mf-addr').value,
        size: parseInt(document.getElementById('mf-size').value),
        pattern: document.getElementById('mf-pat').value,
    });
}
function regWrite() {
    socket.emit('reg_write', {
        name: document.getElementById('rw-name').value,
        value: document.getElementById('rw-value').value,
    });
}
socket.on('mem_write_done', function(d) { appendTerminal('[MEM] write ' + d.addr + '=' + d.value + '\n', '#2f6fed'); });
socket.on('mem_fill_done', function(d) { appendTerminal('[MEM] fill ' + d.addr + ' x' + d.size + '\n', '#2f6fed'); });
socket.on('reg_write_done', function(d) { appendTerminal('[REG] ' + d.name + '=' + d.value + '\n', '#2f6fed'); });

function runDisasm() {
    socket.emit('disasm', {
        addr: document.getElementById('dis-addr').value,
        count: parseInt(document.getElementById('dis-count').value) || 16,
    });
}
function disasmAtPc() {
    socket.emit('target_info');
    // will set after target_info if pc available — also direct read via core
    setTimeout(function() {
        var v = document.querySelector('#target-info .v');
        // prefer input from last PC in info block
        var pcEl = null;
        document.querySelectorAll('#target-info .k').forEach(function(k, idx) {
            if (k.textContent === 'PC') {
                var vs = document.querySelectorAll('#target-info .v');
                if (vs[idx]) document.getElementById('dis-addr').value = vs[idx].textContent;
            }
        });
        runDisasm();
    }, 300);
}
socket.on('disasm_data', function(data) {
    var out = document.getElementById('disasm-out');
    if (!out) return;
    out.textContent = (data.lines || []).map(function(l) {
        if (l.addr) return l.addr + '  ' + (l.bytes || '') + '  ' + (l.text || '');
        return l.text || JSON.stringify(l);
    }).join('\n');
});

function listRttChannels() {
    socket.emit('rtt_list_channels');
}
socket.on('rtt_channels', function(data) {
    appendTerminal('[RTT] CB ' + data.cb + '\n', '#2f6fed');
    (data.channels.up || []).forEach(function(c) {
        appendTerminal('  UP[' + c.index + '] ' + c.name + ' size=' + c.size + '\n', '#1a9b5c');
    });
    (data.channels.down || []).forEach(function(c) {
        appendTerminal('  DN[' + c.index + '] ' + c.name + ' size=' + c.size + '\n', '#0e8f9d');
    });
});

// RTT filter
var rttFilter = '';
document.addEventListener('DOMContentLoaded', function() {});
// bind after DOM exists (inline script at end of body — elements exist)
(function() {
    var f = document.getElementById('rtt-filter');
    if (f) f.addEventListener('input', function() { rttFilter = this.value || ''; });
})();

// wrap original rtt_data append with filter — monkey-patch via extra listener order:
// We filter in a patched approach: intercept text in existing handler by overriding append for segments
var _origRttDataHandlers = true;

// ─── Settings persistence ──────────────────────────────────────────────
socket.on('settings', function(data) {
    if (data.probe_type) {
        setPreferredProbe({type: data.probe_type, index: data.probe_index || 0});
        var sel = document.getElementById('probe-select');
        for (var i = 0; i < sel.options.length; i++) {
            try {
                var opt = JSON.parse(sel.options[i].value);
                if (opt.type === data.probe_type) {
                    sel.selectedIndex = i;
                    break;
                }
            } catch(e) {}
        }
    }
    // migrate legacy mode values
    var modeMap = {swd:'arm', jtag:'armj', 'riscv-swd':'rv', 'riscv-jtag':'rvj'};
    if (data.mode) {
        var m = modeMap[data.mode] || data.mode;
        document.getElementById('mode-select').value = m;
    }
    if (data.speed) document.getElementById('speed-select').value = data.speed;
    if (data.address) document.getElementById('rtt-addr').value = data.address;
    if (data.channel !== undefined) document.getElementById('rtt-channel').value = data.channel;
    if (data.jlink_dll) document.getElementById('jlink-dll').value = data.jlink_dll;
    if (data.encoding) document.getElementById('encoding-select').value = data.encoding;
    if (data.agent) {
        var ag = document.getElementById('probe-agent');
        if (ag) ag.value = data.agent;
        // rescan so remote probes show up
        setTimeout(detectProbes, 100);
    }
});

socket.on('settings_saved', function() {
    console.log('[Settings] Saved');
});

// Load settings on page load
socket.emit('get_settings');

// Save settings on connect (use preferredProbe, not a race-reset select)
document.getElementById('btn-connect').addEventListener('click', function() {
    if (!connected && !connecting) {
        var p = getSelectedProbe() || preferredProbe || {type: 'jlink', index: 0};
        setPreferredProbe(p);
        socket.emit('save_settings', {
            probe_type: p.type || 'jlink',
            probe_index: p.index || 0,
            mode: document.getElementById('mode-select').value,
            speed: parseInt(document.getElementById('speed-select').value),
            address: document.getElementById('rtt-addr').value,
            channel: parseInt(document.getElementById('rtt-channel').value) || 0,
            jlink_dll: (document.getElementById('jlink-dll').value || '').trim(),
            encoding: document.getElementById('encoding-select').value,
            agent: (document.getElementById('probe-agent') && document.getElementById('probe-agent').value || '').trim() || (p.agent || ''),
        });
    }
});
</script>
<script src="/static/webusb_stlink_rtt.js"></script>
</body>
</html>"""

# ─── Graceful shutdown ─────────────────────────────────────────────────────

def _shutdown_handler(sig, frame):
    """Graceful shutdown on SIGINT/SIGTERM."""
    _do_disconnect()
    print('\n[*] Server shutting down...')
    sys.exit(0)

signal.signal(signal.SIGINT, _shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)

# ─── Main entry point ──────────────────────────────────────────────────────────

def _ssl_context_adhoc_or_files():
    """Self-signed TLS so WebUSB works on https://server-ip (Chrome secure context)."""
    try:
        import OpenSSL  # noqa: F401
        return 'adhoc'
    except ImportError:
        pass
    cert_dir = Path(__file__).resolve().parent / 'certs'
    cert_dir.mkdir(exist_ok=True)
    cert_file = cert_dir / 'cert.pem'
    key_file = cert_dir / 'key.pem'
    if cert_file.is_file() and key_file.is_file():
        return (str(cert_file), str(key_file))
    # try openssl CLI once
    import subprocess
    try:
        subprocess.run(
            [
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                '-keyout', str(key_file), '-out', str(cert_file),
                '-days', '3650', '-nodes', '-subj', '/CN=RTTView',
            ],
            check=True, capture_output=True,
        )
        return (str(cert_file), str(key_file))
    except Exception as e:
        raise SystemExit(
            'HTTPS 需要 pyOpenSSL 或系统 openssl，以便生成自签名证书。\n'
            '  pip install pyopenssl\n'
            f'  或手动生成 certs/cert.pem + certs/key.pem\n  ({e})'
        )


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Web RTTView')
    parser.add_argument('--host', default=os.environ.get('RTTVIEW_HOST', '127.0.0.1'),
                        help='Bind address (0.0.0.0 for LAN/server deploy)')
    parser.add_argument('--port', type=int, default=int(os.environ.get('RTTVIEW_PORT', '5000')))
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--ssl', action='store_true',
                        default=os.environ.get('RTTVIEW_SSL', '').strip() in ('1', 'true', 'yes'),
                        help='HTTPS self-signed (required for WebUSB when not on localhost)')
    args = parser.parse_args()

    # Start throughput reporter thread
    socketio.start_background_task(throughput_reporter_thread)

    ssl_ctx = _ssl_context_adhoc_or_files() if args.ssl else None
    scheme = 'https' if ssl_ctx else 'http'

    if not args.no_browser and args.host in ('127.0.0.1', 'localhost'):
        threading.Timer(1.0, lambda: webbrowser.open(f'{scheme}://127.0.0.1:{args.port}')).start()
    print(f'Web RTTView running at {scheme}://{args.host}:{args.port}')
    if ssl_ctx:
        print('  TLS: self-signed — browser may warn; click Advanced → Continue')
        print('  WebUSB works on this https URL (Chrome/Edge)')
    else:
        print('  Tip: remote WebUSB needs --ssl (or use probe_agent / local USB)')
    print('  RTT search: multi-region auto (or set Address)')
    print('  Probes: J-Link / ST-Link / DAPLink(pyOCD) / OpenOCD / WebUSB / Agent')
    print('  Serial flash: pyserial (STM32 ISP / raw)')
    run_kw = dict(host=args.host, port=args.port, debug=False, allow_unsafe_werkzeug=True)
    if ssl_ctx is not None:
        run_kw['ssl_context'] = ssl_ctx
    socketio.run(app, **run_kw)
