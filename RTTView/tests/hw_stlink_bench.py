"""ST-Link speed bench: open / RTT scan / poll / reset / rescan."""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from probes.stlink_probe import STLinkProbe
from core import xlink
from web_rttview import scan_rtt_control_block, _bootstrap_cached_rtt, state


def main():
    _bootstrap_cached_rtt()
    print('cached_cb', hex(state.get('rtt_cb_addr') or 0))

    found = STLinkProbe.detect()
    print('detect', len(found), found[0][1] if found else None)
    if not found:
        print('NO_STLINK')
        return 2

    probe = STLinkProbe(device=found[0][0])
    t0 = time.time()
    probe.open(mode='arm', core='Cortex-M3', speed=4000)
    print(f'open {time.time()-t0:.2f}s backend={"CLI" if probe._using_cli() else "USB"}')
    print('info', probe.probe_info())

    xlk = xlink.XLink(probe)

    t0 = time.time()
    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
    print(f'scan-auto {time.time()-t0:.2f}s cb={hex(cb)} a_up={hex(a_up)}')
    state['rtt_cb_addr'] = cb

    # warm re-scan via cached
    t0 = time.time()
    cb2, a_up2, _ = scan_rtt_control_block(xlk, 'auto', 0)
    print(f'scan-auto-cached {time.time()-t0:.2f}s cb={hex(cb2)}')

    # exact
    t0 = time.time()
    cb3, a_up3, _ = scan_rtt_control_block(xlk, hex(cb), 0)
    print(f'scan-exact {time.time()-t0:.2f}s')

    # RTT poll 3s
    total = 0
    polls = 0
    t_end = time.time() + 3.0
    while time.time() < t_end:
        try:
            data = probe.rtt_poll(a_up, max_chunk=1024)
        except Exception as e:
            print('poll err', e)
            break
        polls += 1
        if data:
            total += len(data)
            sys.stdout.write(data.decode('utf-8', 'replace'))
            sys.stdout.flush()
    print()
    print(f'rtt 3s bytes={total} polls={polls} rate={polls/3:.1f}Hz')

    t0 = time.time()
    probe.reset()
    print(f'reset {time.time()-t0:.2f}s')

    time.sleep(0.1)
    t0 = time.time()
    cb4, a_up4, _ = scan_rtt_control_block(xlk, hex(cb), 0)
    print(f'rescan-exact {time.time()-t0:.2f}s cb={hex(cb4)}')

    post = b''
    t_end = time.time() + 2.0
    while time.time() < t_end:
        try:
            d = probe.rtt_poll(a_up4, max_chunk=1024)
        except Exception as e:
            print('post err', e)
            break
        if d:
            post += d
            sys.stdout.write(d.decode('utf-8', 'replace'))
            sys.stdout.flush()
    print()
    print(f'post-reset bytes={len(post)}')
    ok = total > 0 and len(post) > 0
    print('BENCH', 'OK' if ok else 'FAIL')
    probe.close()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
