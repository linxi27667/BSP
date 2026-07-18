#!/usr/bin/env python3
"""Probe Agent — run on the machine with USB debug probes.

Listens for TCP connections from a remote web_rttview.py server and
proxies DebugProbe operations to local J-Link / ST-Link / DAPLink / OpenOCD.

Usage:
  python probe_agent.py --host 0.0.0.0 --port 19201 --token mysecret
  python probe_agent.py   # defaults: 0.0.0.0:19201, token from RTTVIEW_AGENT_TOKEN

Env:
  RTTVIEW_AGENT_TOKEN  shared secret (empty = no auth, LAN only)
  RTTVIEW_AGENT_PORT   default 19201
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['PATH'] = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libusb-1.0.24', 'MinGW64', 'dll')
    + os.pathsep + os.environ.get('PATH', '')
)

from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe


def _b64e(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    elif isinstance(data, list):
        raw = bytes(int(x) & 0xFF for x in data)
    else:
        raw = bytes(data)
    return base64.b64encode(raw).decode('ascii')


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode('ascii'))


def _decode_arg(a):
    if isinstance(a, dict) and '__b64__' in a:
        return list(_b64d(a['__b64__']))
    return a


class Session:
    """One client connection may hold one open probe at a time."""

    def __init__(self):
        self.probe = None
        self.lock = threading.RLock()

    def close_probe(self):
        with self.lock:
            if self.probe is not None:
                try:
                    self.probe.close()
                except Exception:
                    pass
            self.probe = None


def _jlink_present() -> bool:
    try:
        import pylink
        jl = pylink.JLink()
        try:
            return bool(jl.connected_emulators())
        except Exception:
            pass
        try:
            return int(jl.num_connected_emulators()) > 0
        except Exception:
            return False
    except Exception:
        return False


def list_local_probes() -> list[dict]:
    out = []
    jlink_ok = _jlink_present()
    out.append({
        'name': 'J-Link (remote)' if jlink_ok else 'J-Link (未检测到)',
        'type': 'jlink',
        'index': 0,
        'backend': 'pylink',
        'available': jlink_ok,
    })
    try:
        st = STLinkProbe.detect()
        if not st:
            out.append({
                'name': 'ST-Link (未检测到)',
                'type': 'stlink', 'index': 0, 'backend': 'stlink', 'available': False,
            })
        for i, (dev, name) in enumerate(st):
            label = name if str(name).startswith('ST-Link') else f'ST-Link · {name}'
            out.append({
                'name': f'{label} @agent',
                'type': 'stlink',
                'index': i,
                'backend': 'stlink-cli' if dev is None else 'stlink',
                'available': True,
            })
    except Exception as e:
        out.append({
            'name': f'ST-Link (检测失败: {e})',
            'type': 'stlink', 'index': 0, 'backend': 'stlink', 'available': False,
        })
    try:
        daps = DAPLinkProbe.detect()
        if not daps:
            out.append({
                'name': 'DAPLink (未检测到)',
                'type': 'daplink', 'index': 0, 'backend': 'pyocd', 'available': False,
            })
        for i, p in enumerate(daps):
            pname = getattr(p, 'product_name', None) or 'CMSIS-DAP'
            uid = getattr(p, 'unique_id', '') or ''
            out.append({
                'name': f'DAPLink · {pname}' + (f' ({uid})' if uid else '') + ' @agent',
                'type': 'daplink', 'index': i, 'backend': 'pyocd', 'available': True,
            })
    except Exception as e:
        out.append({
            'name': f'DAPLink (失败: {e})',
            'type': 'daplink', 'index': 0, 'backend': 'pyocd', 'available': False,
        })
    out.append({
        'name': 'OpenOCD (TCP:6666) @agent',
        'type': 'openocd', 'index': 0, 'backend': 'openocd', 'available': True,
    })
    return out


def open_local(probe_type, index, mode, core, speed, dllpath):
    if probe_type == 'jlink':
        probe = JLinkProbe(dllpath=dllpath or None)
    elif probe_type == 'stlink':
        found = STLinkProbe.detect()
        if not found:
            raise RuntimeError('No ST-Link found on agent')
        if index < 0 or index >= len(found):
            raise RuntimeError(f'ST-Link index {index} out of range')
        probe = STLinkProbe(device=found[index][0])
    elif probe_type == 'daplink':
        found = DAPLinkProbe.detect()
        if not found:
            raise RuntimeError('No DAPLink found on agent')
        if index < 0 or index >= len(found):
            raise RuntimeError(f'DAPLink index {index} out of range')
        probe = DAPLinkProbe(probe=found[index])
    elif probe_type == 'openocd':
        probe = OpenOCDProbe()
    else:
        raise RuntimeError(f'Unknown probe type: {probe_type}')
    probe.open(mode=mode or 'arm', core=core or 'Cortex-M0', speed=int(speed or 4000))
    return probe


# Methods whose return value is a byte list / should be b64 for efficiency
_BYTES_METHODS = {
    'read_mem_U8', 'rtt_poll', 'swo_read',
}


def invoke(probe, method: str, args: list):
    if not hasattr(probe, method):
        raise AttributeError(f'method not found: {method}')
    fn = getattr(probe, method)
    if not callable(fn):
        raise AttributeError(f'not callable: {method}')
    args = [_decode_arg(a) for a in args]
    result = fn(*args)
    if method in _BYTES_METHODS or (
        isinstance(result, (bytes, bytearray))
    ):
        return {'__b64__': _b64e(result)}
    if isinstance(result, list) and result and all(isinstance(x, int) for x in result[:4]):
        # large mem reads: b64
        if method.startswith('read_mem') and len(result) >= 64:
            return {'__b64__': _b64e(result)}
    return result


def handle_client(conn: socket.socket, addr, token: str):
    session = Session()
    authed = not bool(token)  # empty token = open
    buf = bytearray()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(300)

    def send(obj: dict):
        raw = json.dumps(obj, separators=(',', ':'), default=str).encode('utf-8')
        conn.sendall(struct.pack('>I', len(raw)) + raw)

    def read_frame() -> dict | None:
        nonlocal buf
        while len(buf) < 4:
            chunk = conn.recv(65536)
            if not chunk:
                return None
            buf.extend(chunk)
        (n,) = struct.unpack('>I', buf[:4])
        if n <= 0 or n > 32 * 1024 * 1024:
            raise ConnectionError(f'bad frame {n}')
        while len(buf) < 4 + n:
            chunk = conn.recv(65536)
            if not chunk:
                return None
            buf.extend(chunk)
        body = bytes(buf[4:4 + n])
        del buf[:4 + n]
        return json.loads(body.decode('utf-8'))

    try:
        while True:
            msg = read_frame()
            if msg is None:
                break
            mid = msg.get('id')
            cmd = msg.get('cmd')
            args = msg.get('args') or {}
            try:
                if cmd == 'hello':
                    if token and args.get('token') != token:
                        send({'id': mid, 'ok': False, 'error': 'bad token'})
                        break
                    authed = True
                    send({'id': mid, 'ok': True, 'result': {
                        'agent': 'RTTView probe_agent',
                        'version': 1,
                    }})
                    continue
                if not authed:
                    send({'id': mid, 'ok': False, 'error': 'not authenticated'})
                    break
                if cmd == 'list_probes':
                    send({'id': mid, 'ok': True, 'result': list_local_probes()})
                elif cmd == 'open':
                    with session.lock:
                        session.close_probe()
                        probe = open_local(
                            args.get('type') or 'stlink',
                            int(args.get('index') or 0),
                            args.get('mode') or 'arm',
                            args.get('core') or 'Cortex-M0',
                            args.get('speed') or 4000,
                            args.get('dllpath') or None,
                        )
                        session.probe = probe
                    info = {
                        'core_regs': getattr(probe, 'core_regs', {}) or {},
                        'slow_mem': bool(getattr(probe, 'slow_mem', False)),
                        'rtt_poll_ms': int(getattr(probe, 'rtt_poll_ms', 40) or 40),
                    }
                    try:
                        if hasattr(probe, 'probe_info'):
                            info['probe_info'] = probe.probe_info()
                    except Exception:
                        pass
                    send({'id': mid, 'ok': True, 'result': info})
                elif cmd == 'close':
                    session.close_probe()
                    send({'id': mid, 'ok': True, 'result': None})
                elif cmd == 'invoke':
                    if session.probe is None:
                        raise RuntimeError('no probe open')
                    method = args.get('method')
                    margs = args.get('args') or []
                    with session.lock:
                        result = invoke(session.probe, method, margs)
                    send({'id': mid, 'ok': True, 'result': result})
                elif cmd == 'flash_upload':
                    if session.probe is None:
                        raise RuntimeError('no probe open')
                    data = _b64d(args.get('data_b64') or '')
                    addr = int(args.get('addr') or 0)
                    name = args.get('name') or 'fw.bin'
                    path = None
                    try:
                        fd, path = tempfile.mkstemp(suffix='_' + name)
                        os.close(fd)
                        with open(path, 'wb') as f:
                            f.write(data)
                        with session.lock:
                            out = session.probe.flash_file(path, addr)
                        send({'id': mid, 'ok': True, 'result': str(out) if out is not None else 'ok'})
                    finally:
                        if path and os.path.exists(path):
                            try:
                                os.unlink(path)
                            except Exception:
                                pass
                elif cmd == 'ping':
                    send({'id': mid, 'ok': True, 'result': 'pong'})
                else:
                    send({'id': mid, 'ok': False, 'error': f'unknown cmd {cmd}'})
            except Exception as e:
                send({
                    'id': mid,
                    'ok': False,
                    'error': f'{type(e).__name__}: {e}',
                    'trace': traceback.format_exc()[-800:],
                })
    except Exception as e:
        print(f'[agent] client {addr} error: {e}', flush=True)
    finally:
        session.close_probe()
        try:
            conn.close()
        except Exception:
            pass
        print(f'[agent] disconnect {addr}', flush=True)


def main():
    ap = argparse.ArgumentParser(description='RTTView Probe Agent')
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int,
                    default=int(os.environ.get('RTTVIEW_AGENT_PORT', '19201')))
    ap.add_argument('--token', default=os.environ.get('RTTVIEW_AGENT_TOKEN', ''))
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(8)
    print(f'Probe Agent listening on {args.host}:{args.port}', flush=True)
    print(f'  token: {"(set)" if args.token else "(none — LAN only)"}', flush=True)
    print('  Keep this running; connect web_rttview with agent host:port', flush=True)

    while True:
        conn, addr = srv.accept()
        print(f'[agent] connect {addr}', flush=True)
        t = threading.Thread(target=handle_client, args=(conn, addr, args.token), daemon=True)
        t.start()


if __name__ == '__main__':
    main()
