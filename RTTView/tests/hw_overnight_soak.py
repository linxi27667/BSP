#!/usr/bin/env python3
"""Overnight soak: ST-Link RTT poll + periodic reset. Ctrl+C or --minutes.

Usage:
  python tests/hw_overnight_soak.py --minutes 480
  python tests/hw_overnight_soak.py --minutes 5   # quick
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probes.stlink_probe import STLinkProbe
from web_rttview import scan_rtt_control_block
from core import xlink


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=480)
    ap.add_argument('--reset-every', type=float, default=120, help='seconds between MCU reset')
    args = ap.parse_args()

    found = STLinkProbe.detect()
    if not found:
        print('FAIL no ST-Link')
        return 1
    probe = STLinkProbe(device=found[0][0])
    probe.open(mode='arm', core='Cortex-M3', speed=4000)
    xlk = xlink.XLink(probe)
    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
    print(f'SOAK start RTT@{hex(cb)} aUp={hex(a_up)} minutes={args.minutes}', flush=True)

    t0 = time.time()
    deadline = t0 + args.minutes * 60
    total = 0
    polls = 0
    errors = 0
    resets = 0
    last_reset = time.time()
    last_report = time.time()

    try:
        while time.time() < deadline:
            try:
                if hasattr(probe, 'rtt_poll'):
                    data = probe.rtt_poll(a_up, 1024)
                else:
                    data = b''
                if data:
                    total += len(data)
                polls += 1
            except Exception as e:
                errors += 1
                print(f'ERR poll {e}', flush=True)
                time.sleep(0.2)

            if time.time() - last_reset >= args.reset_every:
                try:
                    probe.reset()
                    time.sleep(0.3)
                    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
                    resets += 1
                    last_reset = time.time()
                    print(f'RESET #{resets} RTT@{hex(cb)}', flush=True)
                except Exception as e:
                    errors += 1
                    print(f'ERR reset {e}', flush=True)
                    last_reset = time.time()

            if time.time() - last_report >= 30:
                elapsed = time.time() - t0
                print(
                    f'REPORT t={elapsed:.0f}s bytes={total} polls={polls} '
                    f'errors={errors} resets={resets}',
                    flush=True,
                )
                last_report = time.time()

            time.sleep(0.04)
    except KeyboardInterrupt:
        print('interrupted', flush=True)
    finally:
        try:
            probe.close()
        except Exception:
            pass

    elapsed = time.time() - t0
    ok = total > 0 and errors < max(10, polls // 50)
    print(
        f'SOAK_DONE ok={ok} elapsed={elapsed:.0f}s bytes={total} '
        f'polls={polls} errors={errors} resets={resets}',
        flush=True,
    )
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
