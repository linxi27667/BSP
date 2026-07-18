"""ST-Link open + auto RTT dump (needs libusb on PATH)."""
import os
import sys
import time
import ctypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ['PATH'] = os.path.join(_ROOT, 'libusb-1.0.24', 'MinGW64', 'dll') + os.pathsep + os.environ.get('PATH', '')

from probes.stlink_probe import STLinkProbe
from core import xlink
from web_rttview import scan_rtt_control_block, RingBuffer


def main():
    found = STLinkProbe.detect()
    print('count', len(found))
    if not found:
        return 2
    print('name', found[0][1])
    probe = STLinkProbe(device=found[0][0])
    print('open...')
    probe.open(mode='arm', core='Cortex-M0', speed=4000)
    print('open OK ver', probe._version.hex() if probe._version else None)
    xlk = xlink.XLink(probe)
    for label, fn in [
        ('core_id', lambda: probe._read_core_id()),
        ('cpuid', lambda: xlk.read_U32(0xE000ED00)),
        ('core_type', lambda: xlk.read_core_type()),
        ('halted', lambda: xlk.halted()),
    ]:
        try:
            v = fn()
            print(label, hex(v) if isinstance(v, int) else v)
        except Exception as e:
            print(label, 'ERR', e)

    print('scan RTT...')
    cb, a_up, a_down = scan_rtt_control_block(xlk, 'auto', 0)
    print('RTT', hex(cb), hex(a_up), hex(a_down))

    print('--- log 5s ---')
    t_end = time.time() + 5
    total = b''
    while time.time() < t_end:
        data = xlk.read_mem_U8(a_up, ctypes.sizeof(RingBuffer))
        a_up_rb = RingBuffer.from_buffer(bytearray(data))
        if not (0 < a_up_rb.SizeOfBuffer <= 1024 * 1024
                and a_up_rb.WrOff < a_up_rb.SizeOfBuffer
                and a_up_rb.RdOff < a_up_rb.SizeOfBuffer
                and a_up_rb.pBuffer):
            time.sleep(0.05)
            continue
        if a_up_rb.RdOff <= a_up_rb.WrOff:
            cnt = a_up_rb.WrOff - a_up_rb.RdOff
            if cnt <= 0:
                time.sleep(0.05)
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
        time.sleep(0.03)
    print()
    print('TOTAL', len(total))
    probe.close()
    print('DONE')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
