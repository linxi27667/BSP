"""Unit tests for Web RTT connect helpers (no hardware)."""
import os
import sys
import ctypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from web_rttview import (
    MODE_MAP,
    normalize_probe_mode,
    core_name_for_mode,
    rtt_ring_addrs,
    _parse_addr_or_auto,
    RingBuffer,
)


def test_mode_normalize():
    assert normalize_probe_mode('swd') == 'arm'
    assert normalize_probe_mode('jtag') == 'armj'
    assert normalize_probe_mode('riscv-swd') == 'rv'
    assert normalize_probe_mode('riscv-jtag') == 'rvj'
    assert normalize_probe_mode('arm') == 'arm'
    assert normalize_probe_mode('ARM') == 'arm'
    assert normalize_probe_mode('armj') == 'armj'
    assert normalize_probe_mode('') == 'arm'
    assert normalize_probe_mode('unknown') == 'arm'


def test_core_name():
    assert core_name_for_mode('arm') == 'Cortex-M0'
    assert core_name_for_mode('armj') == 'Cortex-M0'
    assert core_name_for_mode('rv') == 'RISC-V'
    assert core_name_for_mode('rvj') == 'RISC-V'


def test_mode_map_covers_ui_and_desktop():
    for k in ('swd', 'jtag', 'riscv-swd', 'riscv-jtag', 'arm', 'armj', 'rv', 'rvj'):
        assert k in MODE_MAP


def test_rtt_ring_addrs_channel0():
    cb = 0x20000000
    rb = ctypes.sizeof(RingBuffer)
    a_up, a_down = rtt_ring_addrs(cb, max_up=3, channel=0)
    assert a_up == cb + 24
    assert a_down == cb + 24 + rb * 3


def test_rtt_ring_addrs_channel1():
    cb = 0x20001000
    rb = ctypes.sizeof(RingBuffer)
    a_up, a_down = rtt_ring_addrs(cb, max_up=3, channel=1)
    assert a_up == cb + 24 + rb
    assert a_down == cb + 24 + rb * 3 + rb


def test_parse_addr_or_auto():
    base, is_auto = _parse_addr_or_auto('auto')
    assert is_auto and base is None
    base, is_auto = _parse_addr_or_auto('')
    assert is_auto
    base, is_auto = _parse_addr_or_auto('0x20000000')
    assert not is_auto and base == 0x20000000


if __name__ == '__main__':
    test_mode_normalize()
    test_core_name()
    test_mode_map_covers_ui_and_desktop()
    test_rtt_ring_addrs_channel0()
    test_rtt_ring_addrs_channel1()
    test_parse_addr_or_auto()
    print('ALL test_web_rtt_helpers PASSED')
