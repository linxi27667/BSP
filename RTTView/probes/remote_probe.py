"""Remote probe client — talks to probe_agent.py on the machine with USB probes.

Framing: 4-byte big-endian length + UTF-8 JSON.
Binary payloads use base64.
"""
from __future__ import annotations

import base64
import json
import socket
import struct
import threading
from typing import Any

from .base import DebugProbe
from . import register_probe


def _b64_encode(data) -> str:
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
    else:
        raw = bytes(int(x) & 0xFF for x in data)
    return base64.b64encode(raw).decode('ascii')


def _b64_decode(s: str) -> list[int]:
    return list(base64.b64decode(s.encode('ascii')))


class RemoteAgentClient:
    """Low-level JSON-RPC style client for one agent connection."""

    def __init__(self, host: str, port: int = 19201, token: str = '', timeout: float = 30.0):
        self.host = host
        self.port = int(port)
        self.token = token or ''
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._lock = threading.RLock()
        self._next_id = 1

    def connect(self):
        if self._sock:
            return
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s
        # Hello / auth
        r = self.call('hello', {'token': self.token})
        if not r.get('ok'):
            self.close()
            raise ConnectionError(r.get('error') or 'agent hello failed')

    def close(self):
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
            self._sock = None

    def _send(self, obj: dict):
        raw = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        self._sock.sendall(struct.pack('>I', len(raw)) + raw)

    def _recv(self) -> dict:
        hdr = self._recvexact(4)
        (n,) = struct.unpack('>I', hdr)
        if n <= 0 or n > 32 * 1024 * 1024:
            raise ConnectionError(f'bad frame size {n}')
        body = self._recvexact(n)
        return json.loads(body.decode('utf-8'))

    def _recvexact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('agent connection closed')
            buf.extend(chunk)
        return bytes(buf)

    def call(self, cmd: str, args: dict | None = None) -> dict:
        with self._lock:
            if not self._sock:
                self.connect()
            rid = self._next_id
            self._next_id += 1
            self._send({'id': rid, 'cmd': cmd, 'args': args or {}})
            while True:
                resp = self._recv()
                if resp.get('id') == rid:
                    return resp

    def list_probes(self) -> list[dict]:
        self.connect()
        r = self.call('list_probes')
        if not r.get('ok'):
            raise RuntimeError(r.get('error') or 'list_probes failed')
        return list(r.get('result') or [])


class RemoteProbe(DebugProbe):
    """DebugProbe that proxies all ops to a remote probe_agent."""

    def __init__(self, host: str, port: int = 19201, token: str = '',
                 probe_type: str = 'stlink', index: int = 0, dllpath: str | None = None):
        self._host = host
        self._port = int(port)
        self._token = token or ''
        self._probe_type = probe_type
        self._index = int(index)
        self._dllpath = dllpath
        self._client = RemoteAgentClient(host, port, token)
        self._mode = 'arm'
        self._core_regs = {}
        self._opened = False
        # Hint web layer: network RTT still benefits from batched poll
        self.slow_mem = True
        self.rtt_poll_ms = 30

    @staticmethod
    def parse_agent(spec: str) -> tuple[str, int, str]:
        """Parse 'host:port' or 'host:port:token' or 'host'."""
        spec = (spec or '').strip()
        if not spec:
            raise ValueError('empty agent address')
        # host:port:token  (token may contain ':' — take first two splits only for host/port)
        if '://' in spec:
            # strip optional scheme
            spec = spec.split('://', 1)[1]
        token = ''
        parts = spec.split(':')
        host = parts[0]
        port = 19201
        if len(parts) >= 2 and parts[1].isdigit():
            port = int(parts[1])
            if len(parts) >= 3:
                token = ':'.join(parts[2:])
        elif len(parts) >= 2:
            token = ':'.join(parts[1:])
        return host, port, token

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._mode = (mode or 'arm').lower()
        self._client.connect()
        r = self._client.call('open', {
            'type': self._probe_type,
            'index': self._index,
            'mode': self._mode,
            'core': core or 'Cortex-M0',
            'speed': int(speed),
            'dllpath': self._dllpath or '',
        })
        if not r.get('ok'):
            raise RuntimeError(r.get('error') or 'remote open failed')
        res = r.get('result') or {}
        self._core_regs = res.get('core_regs') or {}
        self._opened = True
        # Prefer agent-reported slow flags
        if 'slow_mem' in res:
            self.slow_mem = bool(res['slow_mem'])
        if 'rtt_poll_ms' in res:
            try:
                self.rtt_poll_ms = int(res['rtt_poll_ms'])
            except Exception:
                pass

    def close(self):
        try:
            if self._opened:
                self._client.call('close')
        except Exception:
            pass
        self._opened = False
        self._client.close()

    def _call(self, method: str, *args) -> Any:
        # encode bytes-like args
        enc_args = []
        for a in args:
            if isinstance(a, (bytes, bytearray)):
                enc_args.append({'__b64__': _b64_encode(a)})
            elif isinstance(a, list) and a and all(isinstance(x, int) for x in a[:8]):
                # bulk byte list for write_mem — base64 if long
                if len(a) >= 32:
                    enc_args.append({'__b64__': _b64_encode(a)})
                else:
                    enc_args.append(a)
            else:
                enc_args.append(a)
        r = self._client.call('invoke', {'method': method, 'args': enc_args})
        if not r.get('ok'):
            raise RuntimeError(r.get('error') or f'remote {method} failed')
        result = r.get('result')
        if isinstance(result, dict) and '__b64__' in result:
            return _b64_decode(result['__b64__'])
        return result

    def read_mem_U8(self, addr, count):
        return self._call('read_mem_U8', int(addr), int(count))

    def read_mem_U16(self, addr, count):
        return self._call('read_mem_U16', int(addr), int(count))

    def read_mem_U32(self, addr, count):
        return self._call('read_mem_U32', int(addr), int(count))

    def read_U32(self, addr):
        return int(self._call('read_U32', int(addr)))

    def write_U8(self, addr, val):
        self._call('write_U8', int(addr), int(val))

    def write_U16(self, addr, val):
        self._call('write_U16', int(addr), int(val))

    def write_U32(self, addr, val):
        self._call('write_U32', int(addr), int(val))

    def write_mem_U8(self, addr, data):
        self._call('write_mem_U8', int(addr), list(data))

    def write_mem_U32(self, addr, data):
        self._call('write_mem_U32', int(addr), list(data))

    def read_reg(self, reg):
        return int(self._call('read_reg', reg))

    def read_regs(self, rlist):
        return self._call('read_regs', list(rlist))

    def write_reg(self, reg, val):
        self._call('write_reg', reg, int(val))

    def halt(self):
        self._call('halt')

    def go(self):
        self._call('go')

    def step(self):
        self._call('step')

    def reset(self):
        self._call('reset')

    def halted(self):
        return bool(self._call('halted'))

    def rtt_poll(self, a_up_addr, max_chunk=1024):
        r = self._client.call('invoke', {
            'method': 'rtt_poll',
            'args': [int(a_up_addr), int(max_chunk)],
        })
        if not r.get('ok'):
            # fallback: no rtt_poll on agent backend
            err = r.get('error') or ''
            if 'not found' in err.lower() or 'not implemented' in err.lower() or 'AttributeError' in err:
                raise NotImplementedError('remote rtt_poll unavailable')
            raise RuntimeError(err or 'rtt_poll failed')
        result = r.get('result')
        if isinstance(result, dict) and '__b64__' in result:
            return bytes(_b64_decode(result['__b64__']))
        if isinstance(result, list):
            return bytes(int(x) & 0xFF for x in result)
        return b''

    def flash_file(self, path, addr=0):
        # Upload file content to agent then flash
        with open(path, 'rb') as f:
            data = f.read()
        r = self._client.call('flash_upload', {
            'addr': int(addr),
            'data_b64': _b64_encode(data),
            'name': path.split('\\')[-1].split('/')[-1],
        })
        if not r.get('ok'):
            raise RuntimeError(r.get('error') or 'remote flash failed')
        return r.get('result')

    def probe_info(self):
        try:
            return self._call('probe_info')
        except Exception:
            return {
                'product_name': f'Remote {self._probe_type}',
                'backend': 'remote',
                'agent': f'{self._host}:{self._port}',
            }


register_probe('remote', RemoteProbe)
