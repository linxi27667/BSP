"""ST-Link closed-loop: open (CLI fallback), RTT scan, mem, reset, stream logs."""
import os
import sys
import time
import ctypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ['PATH'] = (
    os.path.join(_ROOT, 'libusb-1.0.24', 'MinGW64', 'dll')
    + os.pathsep + os.environ.get('PATH', '')
)

from probes.stlink_probe import STLinkProbe
from core import xlink
from web_rttview import scan_rtt_control_block, RingBuffer


def main():
    print('=== ST-Link closed loop ===')
    found = STLinkProbe.detect()
    print('detect', len(found), found[0][1] if found else None)

    probe = STLinkProbe(device=found[0][0] if found else None)
    print('open...')
    probe.open(mode='arm', core='Cortex-M3', speed=4000)
    print('backend', 'CLI' if probe._using_cli() else 'USB')
    if hasattr(probe, 'probe_info'):
        print('info', probe.probe_info())

    xlk = xlink.XLink(probe)
    try:
        print('core_type', xlk.read_core_type())
    except Exception as e:
        print('core_type', e)
    try:
        print('cpuid', hex(xlk.read_U32(0xE000ED00)))
    except Exception as e:
        print('cpuid', e)

    print('scan RTT...')
    t0 = time.time()
    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
    print(f'RTT {hex(cb)} aUp={hex(a_up)} ({time.time()-t0:.2f}s)')

    # ensure running
    try:
        xlk.go()
    except Exception:
        pass

    print('--- RTT 6s ---')
    t_end = time.time() + 6
    total = b''
    while time.time() < t_end:
        data = xlk.read_mem_U8(a_up, ctypes.sizeof(RingBuffer))
        a_up_rb = RingBuffer.from_buffer(bytearray(data))
        if not (0 < a_up_rb.SizeOfBuffer <= 1024 * 1024
                and a_up_rb.WrOff < a_up_rb.SizeOfBuffer
                and a_up_rb.RdOff < a_up_rb.SizeOfBuffer
                and a_up_rb.pBuffer):
            time.sleep(0.08)
            continue
        if a_up_rb.RdOff <= a_up_rb.WrOff:
            cnt = a_up_rb.WrOff - a_up_rb.RdOff
            if cnt <= 0:
                time.sleep(0.08)
                continue
            payload = bytes(xlk.read_mem_U8(a_up_rb.pBuffer + a_up_rb.RdOff, cnt))
        else:
            cnt1 = a_up_rb.SizeOfBuffer - a_up_rb.RdOff
            cnt2 = a_up_rb.WrOff
            payload = (
                bytes(xlk.read_mem_U8(a_up_rb.pBuffer + a_up_rb.RdOff, cnt1))
                + bytes(xlk.read_mem_U8(a_up_rb.pBuffer, cnt2))
            )
            cnt = cnt1 + cnt2
        a_up_rb.RdOff = (a_up_rb.RdOff + cnt) % a_up_rb.SizeOfBuffer
        xlk.write_U32(a_up + 16, a_up_rb.RdOff)
        total += payload
        sys.stdout.write(payload.decode('utf-8', 'replace'))
        sys.stdout.flush()
        time.sleep(0.05)
    print()
    print('TOTAL_BYTES', len(total))

    print('reset...')
    xlk.reset()
    time.sleep(0.5)
    try:
        xlk.go()
    except Exception:
        pass
    time.sleep(0.3)
    cb2, a_up2, a_down2 = scan_rtt_control_block(xlk, 'auto', 0)
    print('RTT after reset', hex(cb2))

    # brief post-reset stream
    a_up = a_up2
    t_end = time.time() + 3
    post = b''
    while time.time() < t_end:
        try:
            data = xlk.read_mem_U8(a_up, ctypes.sizeof(RingBuffer))
            a_up_rb = RingBuffer.from_buffer(bytearray(data))
            if a_up_rb.RdOff == a_up_rb.WrOff or a_up_rb.SizeOfBuffer == 0:
                time.sleep(0.08)
                continue
            if a_up_rb.RdOff <= a_up_rb.WrOff:
                cnt = a_up_rb.WrOff - a_up_rb.RdOff
                payload = bytes(xlk.read_mem_U8(a_up_rb.pBuffer + a_up_rb.RdOff, cnt))
            else:
                cnt1 = a_up_rb.SizeOfBuffer - a_up_rb.RdOff
                cnt2 = a_up_rb.WrOff
                payload = (
                    bytes(xlk.read_mem_U8(a_up_rb.pBuffer + a_up_rb.RdOff, cnt1))
                    + bytes(xlk.read_mem_U8(a_up_rb.pBuffer, cnt2))
                )
                cnt = cnt1 + cnt2
            a_up_rb.RdOff = (a_up_rb.RdOff + cnt) % a_up_rb.SizeOfBuffer
            xlk.write_U32(a_up + 16, a_up_rb.RdOff)
            post += payload
            sys.stdout.write(payload.decode('utf-8', 'replace'))
            sys.stdout.flush()
        except Exception as e:
            print('post err', e)
            break
        time.sleep(0.05)
    print()
    print('POST_RESET_BYTES', len(post))
    probe.close()
    ok = len(total) > 0 or len(post) > 0
    print('RESULT', 'OK' if ok else 'NO_RTT_DATA')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
