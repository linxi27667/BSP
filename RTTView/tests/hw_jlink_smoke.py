"""Hardware smoke test: J-Link connect + auto RTT scan + mem/core/flash path.

Run with a board attached:
  python tests/hw_jlink_smoke.py
  python tests/hw_jlink_smoke.py --dll "C:\\...\\JLink_x64.dll" --core Cortex-M4
"""
import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll', default='')
    ap.add_argument('--core', default='Cortex-M0')
    ap.add_argument('--speed', type=int, default=4000)
    ap.add_argument('--mode', default='arm')
    ap.add_argument('--addr', default='auto')
    args = ap.parse_args()

    from probes.jlink_probe import JLinkProbe
    from core import xlink
    from web_rttview import scan_rtt_control_block, normalize_probe_mode, core_name_for_mode

    mode = normalize_probe_mode(args.mode)
    dll = args.dll.strip() or None
    print(f'[*] Opening J-Link mode={mode} core={args.core} speed={args.speed}kHz dll={dll or "auto"}')

    probe = JLinkProbe(dllpath=dll)
    try:
        probe.open(mode=mode, core=args.core or core_name_for_mode(mode), speed=args.speed)
    except Exception as e:
        # Retry common cores
        last = e
        for core in [args.core, 'Cortex-M0', 'Cortex-M3', 'Cortex-M4', 'Cortex-M7', 'Cortex-M33']:
            if not core:
                continue
            try:
                print(f'[*] retry core={core}')
                probe = JLinkProbe(dllpath=dll)
                probe.open(mode=mode, core=core, speed=args.speed)
                last = None
                break
            except Exception as e2:
                last = e2
                try:
                    probe.close()
                except Exception:
                    pass
        if last is not None:
            print('[FAIL] open:', last)
            return 1

    xlk = xlink.XLink(probe)
    print('[OK] probe open')

    # Core type
    try:
        ctype = xlk.read_core_type()
        print(f'[OK] core type: {ctype}')
    except Exception as e:
        print('[WARN] read_core_type:', e)

    # RTT auto scan
    try:
        t0 = time.time()
        cb, a_up, a_down = scan_rtt_control_block(xlk, args.addr, 0)
        dt = time.time() - t0
        print(f'[OK] RTT @ {hex(cb)} aUp={hex(a_up)} aDown={hex(a_down)} ({dt:.2f}s)')
        # Peek ring
        rb = xlk.read_mem_U8(a_up, 24)
        print(f'     aUp header bytes: {bytes(rb[:16]).hex()}')
    except Exception as e:
        print('[WARN] RTT not found:', e)

    # Memory read SRAM
    try:
        words = xlk.read_mem_U32(0x20000000, 4)
        print(f'[OK] SRAM@0x20000000: {[hex(w) for w in words]}')
    except Exception as e:
        print('[WARN] SRAM read:', e)

    # Registers (may need halt)
    try:
        if not xlk.halted():
            xlk.halt()
        pc = xlk.read_reg('pc')
        sp = xlk.read_reg('sp')
        print(f'[OK] pc={hex(pc)} sp={hex(sp)}')
        xlk.go()
    except Exception as e:
        print('[WARN] regs:', e)
        try:
            xlk.go()
        except Exception:
            pass

    # flash_file API present
    print('[OK] flash_file available:', hasattr(probe, 'flash_file'))

    probe.close()
    print('[DONE] smoke finished')
    return 0


if __name__ == '__main__':
    sys.exit(main())
