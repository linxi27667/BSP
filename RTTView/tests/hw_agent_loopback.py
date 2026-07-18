#!/usr/bin/env python3
"""Loopback: start probe_agent in-process client against local agent TCP.

Expects probe_agent already listening on 127.0.0.1:19201
  python probe_agent.py --host 127.0.0.1 --port 19201
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probes.remote_probe import RemoteProbe
from core import xlink
from web_rttview import scan_rtt_control_block


def main():
    agent = os.environ.get('RTTVIEW_AGENT', '127.0.0.1:19201')
    host, port, token = RemoteProbe.parse_agent(agent)
    print(f'agent {host}:{port}', flush=True)
    # list
    client = RemoteProbe(host, port, token)
    probes = client._client.list_probes()
    print('list', probes, flush=True)
    st = next((p for p in probes if p.get('type') == 'stlink' and p.get('available', True)), None)
    if not st:
        print('FAIL no stlink on agent')
        return 1
    idx = int(st.get('index') or 0)
    probe = RemoteProbe(host, port, token, probe_type='stlink', index=idx)
    probe.open(mode='arm', core='Cortex-M3', speed=4000)
    xlk = xlink.XLink(probe)
    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
    print(f'REMOTE RTT {hex(cb)}', flush=True)
    total = 0
    t0 = time.time()
    while time.time() - t0 < 5:
        if hasattr(probe, 'rtt_poll'):
            data = probe.rtt_poll(a_up, 1024)
        else:
            data = bytes(probe.read_mem_U8(a_up, 0) or [])
            data = b''
        if isinstance(data, list):
            data = bytes(data)
        if data:
            total += len(data)
        time.sleep(0.05)
    probe.reset()
    time.sleep(0.4)
    cb2, a_up2, _ = scan_rtt_control_block(xlk, 'auto', 0)
    total2 = 0
    t0 = time.time()
    while time.time() - t0 < 3:
        data = probe.rtt_poll(a_up2, 1024) if hasattr(probe, 'rtt_poll') else b''
        if isinstance(data, list):
            data = bytes(data)
        if data:
            total2 += len(data)
        time.sleep(0.05)
    probe.close()
    print(f'REMOTE_OK bytes={total} post_reset={total2} rtt={hex(cb2)}', flush=True)
    return 0 if total > 0 and total2 > 0 else 2


if __name__ == '__main__':
    sys.exit(main())
