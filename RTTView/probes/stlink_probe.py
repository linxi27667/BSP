"""ST-Link debug probe via bulk USB (ST-Link/V2 protocol).

Protocol references (public reverse-engineered, not proprietary source):
  - stlink-org/stlink commands / usb bulk
  - OpenOCD stlink_usb driver

PID 0x3748 is often a V2 clone (labeled V1 historically).
"""
from __future__ import annotations

import os
import re
import struct
import time

from .base import DebugProbe
from . import register_probe

# ST-Link USB identifiers
STLINK_VID = 0x0483
STLINK_PIDS = {
    0x3748: 'ST-Link/V2',       # common clones + original V2
    0x374b: 'ST-Link/V2-1',
    0x3752: 'ST-Link/V2-1',
    0x374e: 'ST-Link/V3',
    0x374f: 'ST-Link/V3 (bridge)',
    0x3753: 'ST-Link/V3E',
    0x3754: 'ST-Link/V3S',
}

# Command bytes
STLINK_GET_VERSION = 0xF1
STLINK_DEBUG_COMMAND = 0xF2
STLINK_DFU_COMMAND = 0xF3
STLINK_GET_CURRENT_MODE = 0xF5
STLINK_GET_TARGET_VOLTAGE = 0xF7

# DEBUG subcommands
STLINK_DEBUG_GETSTATUS = 0x01
STLINK_DEBUG_FORCEDEBUG = 0x02
STLINK_DEBUG_RESETSYS = 0x03
STLINK_DEBUG_READALLREGS = 0x04
STLINK_DEBUG_READREG = 0x05
STLINK_DEBUG_WRITEREG = 0x06
STLINK_DEBUG_READMEM_32BIT = 0x07
STLINK_DEBUG_WRITEMEM_32BIT = 0x08
STLINK_DEBUG_RUNCORE = 0x09
STLINK_DEBUG_STEPCORE = 0x0A
STLINK_DEBUG_READMEM_8BIT = 0x0C
STLINK_DEBUG_WRITEMEM_8BIT = 0x0D
STLINK_DEBUG_EXIT = 0x21
STLINK_DEBUG_READCOREID = 0x22
STLINK_DEBUG_APIV2_ENTER = 0x30
STLINK_DEBUG_APIV2_READ_IDCODES = 0x31
STLINK_DEBUG_APIV2_RESETSYS = 0x32
STLINK_DEBUG_APIV2_READREG = 0x33
STLINK_DEBUG_APIV2_WRITEREG = 0x34
STLINK_DEBUG_APIV2_WRITEDEBUGREG = 0x35
STLINK_DEBUG_APIV2_READDEBUGREG = 0x36
STLINK_DEBUG_APIV2_READALLREGS = 0x3A
STLINK_DEBUG_APIV2_GETLASTRWSTATUS = 0x3B
STLINK_DEBUG_APIV2_SWD_SET_FREQ = 0x43

STLINK_DEBUG_ENTER_SWD = 0xA3
STLINK_DEBUG_ENTER_JTAG_NO_RESET = 0xA4

STLINK_MODE_DFU = 0
STLINK_MODE_MASS = 1
STLINK_MODE_DEBUG = 2

STLINK_OK = 0x80
CMD_SIZE = 16


def _ensure_libusb_path():
    """Put vendored libusb-1.0.dll on PATH (Windows)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    dll_dir = os.path.join(root, 'libusb-1.0.24', 'MinGW64', 'dll')
    if os.path.isdir(dll_dir):
        os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
    return os.path.join(dll_dir, 'libusb-1.0.dll')


def _usb_backend():
    import usb.backend.libusb1
    dll = _ensure_libusb_path()
    if os.path.isfile(dll):
        be = usb.backend.libusb1.get_backend(find_library=lambda _: dll)
        if be is not None:
            return be
    return usb.backend.libusb1.get_backend()


class STLinkProbe(DebugProbe):
    """ST-Link V2/V2-1 debug probe via pyusb bulk transfers."""

    def __init__(self, device=None):
        self._device = device
        self._mode = 'arm'
        self._core_regs = {}
        self._ep_out = None
        self._ep_in = None
        self._version = None
        self._api_v2 = True
        self._pid = None
        if device is not None:
            try:
                self._pid = int(device.idProduct)
            except Exception:
                self._pid = None

    @staticmethod
    def detect():
        """Detect connected ST-Link probes. Returns list of (device_or_None, name).

        On Windows prefer ST-LINK_CLI -List so we never claim the USB device via
        libusb (which blocks the official ST driver / CLI).
        """
        probes = []
        # 1) CLI list (does not steal device from ST driver permanently)
        if os.name == 'nt':
            try:
                from .stlink_cli_probe import find_stlink_cli
                import subprocess
                cli = find_stlink_cli()
                if cli:
                    p = subprocess.run(
                        [cli, '-List'],
                        capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=15,
                    )
                    text = (p.stdout or '') + (p.stderr or '')
                    # Lines like: SN: 37FF...  or ST-LINK SN: ...
                    sns = re.findall(
                        r'(?:ST-LINK\s+)?SN\s*[:=]\s*([0-9A-Fa-f]+)',
                        text, re.I,
                    )
                    if not sns and re.search(r'ST-LINK|Connected|Device', text, re.I):
                        probes.append((None, 'ST-Link (CLI)'))
                    for sn in sns:
                        probes.append((None, f'ST-Link (CLI · SN {sn})'))
                    if probes:
                        return probes
            except Exception:
                pass

        # 2) pyusb enumerate (may Access denied on Windows ST driver)
        import usb.core
        backend = _usb_backend()
        for pid, name in STLINK_PIDS.items():
            try:
                devs = usb.core.find(
                    find_all=True, idVendor=STLINK_VID, idProduct=pid, backend=backend,
                )
            except Exception:
                continue
            for dev in devs:
                sn_safe = ''
                try:
                    sn = dev.serial_number or ''
                    sn_safe = ''.join(ch if 32 <= ord(ch) < 127 else '' for ch in sn).strip()[:24]
                except Exception:
                    sn_safe = ''
                label = f'{name}' + (f' ({sn_safe})' if sn_safe else f' [PID 0x{pid:04X}]')
                probes.append((dev, label))
                # Immediately release so CLI can use ST driver
                try:
                    import usb.util
                    usb.util.dispose_resources(dev)
                except Exception:
                    pass
        return probes

    def _open_via_cli(self, mode='arm', core='Cortex-M0', speed=4000, usb_err=None):
        """Fallback when pyusb cannot open ST-Link (common on Windows ST drivers)."""
        from .stlink_cli_probe import STLinkCLIProbe, find_stlink_cli
        if not find_stlink_cli():
            msg = 'ST-Link USB Access denied and ST-LINK_CLI.exe not found.'
            if usb_err:
                msg += f' USB error: {usb_err}'
            msg += ' Install STM32 ST-LINK Utility or bind WinUSB via Zadig.'
            raise Exception(msg)
        cli = STLinkCLIProbe()
        cli.open(mode=mode, core=core, speed=speed)
        # Become a transparent proxy to CLI probe methods
        self._cli_proxy = cli
        self._device = None
        self._ep_in = None
        self._ep_out = None
        self._core_regs = dict(cli._core_regs)
        self._mode = mode.lower()
        return None

    def _using_cli(self):
        return getattr(self, '_cli_proxy', None) is not None

    @property
    def slow_mem(self):
        if self._using_cli():
            return bool(getattr(self._cli_proxy, 'slow_mem', True))
        return False

    @property
    def rtt_poll_ms(self):
        if self._using_cli():
            return int(getattr(self._cli_proxy, 'rtt_poll_ms', 40) or 40)
        return 10

    def rtt_poll(self, a_up_addr, max_chunk=1024):
        if self._using_cli() and hasattr(self._cli_proxy, 'rtt_poll'):
            return self._cli_proxy.rtt_poll(a_up_addr, max_chunk=max_chunk)
        raise NotImplementedError('rtt_poll only on CLI backend')

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        import usb.core
        import usb.util

        self._mode = mode.lower()
        self._cli_proxy = None
        backend = _usb_backend()
        usb_err = None

        # Windows + stock ST driver: always prefer ST-LINK_CLI first.
        if os.name == 'nt':
            from .stlink_cli_probe import find_stlink_cli
            if find_stlink_cli():
                return self._open_via_cli(mode, core, speed, None)

        # pyusb path (Linux / WinUSB via Zadig)
        pid = self._pid
        if pid is None and self._device is not None:
            try:
                pid = int(self._device.idProduct)
            except Exception:
                pid = None
        self._device = None
        if pid is not None:
            try:
                self._device = usb.core.find(
                    idVendor=STLINK_VID, idProduct=pid, backend=backend,
                )
            except Exception as e:
                usb_err = e
        if self._device is None:
            for p in STLINK_PIDS:
                try:
                    self._device = usb.core.find(
                        idVendor=STLINK_VID, idProduct=p, backend=backend,
                    )
                except Exception as e:
                    usb_err = e
                    self._device = None
                if self._device is not None:
                    self._pid = p
                    break

        if self._device is None:
            return self._open_via_cli(mode, core, speed, usb_err)

        try:
            self._device.get_active_configuration()
        except Exception:
            try:
                self._device.set_configuration()
            except Exception as e:
                return self._open_via_cli(mode, core, speed, e)

        try:
            if self._device.is_kernel_driver_active(0):
                self._device.detach_kernel_driver(0)
        except Exception:
            pass

        try:
            self._device.set_configuration()
        except usb.core.USBError:
            pass

        try:
            cfg = self._device.get_active_configuration()
        except Exception as e:
            return self._open_via_cli(mode, core, speed, e)

        intf = None
        for i in cfg:
            eps = list(i)
            has_in = any(
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                for e in eps
            )
            has_out = any(
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                for e in eps
            )
            if has_in and has_out:
                intf = i
                break
        if intf is None:
            intf = cfg[(0, 0)]

        try:
            usb.util.claim_interface(self._device, intf.bInterfaceNumber)
        except Exception:
            pass

        self._ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == 0x02,
        ) or usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
            ),
        )
        self._ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == 0x81,
        ) or usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
            ),
        )
        if self._ep_out is None or self._ep_in is None:
            return self._open_via_cli(mode, core, speed, Exception('no bulk endpoints'))

        for ep in (self._ep_in, self._ep_out):
            try:
                self._device.clear_halt(ep)
            except Exception:
                pass

        try:
            ver = self._cmd([STLINK_GET_VERSION], rx_len=6)
        except Exception as e:
            return self._open_via_cli(mode, core, speed, e)
        self._version = bytes(ver) if ver is not None else b''
        self._api_v2 = True

        try:
            mode_b = self._cmd([STLINK_GET_CURRENT_MODE], rx_len=2)
            if mode_b and mode_b[0] == STLINK_MODE_DFU:
                self._cmd([STLINK_DFU_COMMAND, 0x07], rx_len=0)
                time.sleep(0.05)
        except Exception:
            pass

        try:
            self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_EXIT], rx_len=2)
        except Exception:
            pass
        time.sleep(0.02)

        enter = STLINK_DEBUG_ENTER_SWD if self._mode.startswith('arm') else STLINK_DEBUG_ENTER_JTAG_NO_RESET
        try:
            self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_APIV2_ENTER, enter], rx_len=2)
        except Exception:
            try:
                self._cmd([STLINK_DEBUG_COMMAND, 0x20, enter], rx_len=2)
            except Exception as e:
                return self._open_via_cli(mode, core, speed, e)

        try:
            table = [4000, 1800, 1200, 950, 480, 240, 125, 100, 50, 25, 15, 5]
            idx = min(range(len(table)), key=lambda i: abs(table[i] - int(speed)))
            self._cmd(
                [STLINK_DEBUG_COMMAND, STLINK_DEBUG_APIV2_SWD_SET_FREQ, idx & 0xFF, 0x00],
                rx_len=2,
            )
        except Exception:
            pass

        try:
            self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_FORCEDEBUG], rx_len=2)
        except Exception:
            pass
        try:
            self._read_core_id()
        except Exception:
            pass
        self._refresh_regs()

    def _cmd(self, cmd_bytes, rx_len=0, timeout=1000):
        """Send 16-byte padded command; optionally read rx_len bytes."""
        if self._ep_out is None:
            raise RuntimeError('ST-Link not open')
        pkt = bytearray(CMD_SIZE)
        for i, b in enumerate(cmd_bytes[:CMD_SIZE]):
            pkt[i] = b
        try:
            self._ep_out.write(pkt, timeout)
        except Exception:
            try:
                self._device.clear_halt(self._ep_out)
            except Exception:
                pass
            self._ep_out.write(pkt, timeout)
        if rx_len <= 0:
            return None
        try:
            data = self._ep_in.read(rx_len, timeout)
        except Exception:
            try:
                self._device.clear_halt(self._ep_in)
            except Exception:
                pass
            data = self._ep_in.read(rx_len, timeout)
        return bytes(data)

    def _check_status(self, resp):
        if resp is None or len(resp) < 1:
            return
        # 0x80 OK; some firmwares return little status words
        st = resp[0]
        if st in (STLINK_OK, 0x00, 0x01):
            return
        # wait statuses — ignore for now
        if st in (0x10, 0x14, 0x15, 0x16):
            return

    def _read_core_id(self):
        resp = self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_READCOREID], rx_len=4)
        if resp and len(resp) >= 4:
            return struct.unpack('<I', resp[:4])[0]
        return 0

    def _refresh_regs(self):
        regs = ['r0', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7',
                'r8', 'r9', 'r10', 'r11', 'r12', 'sp', 'lr', 'pc',
                'xpsr', 'msp', 'psp', 'cfbp']
        for i, name in enumerate(regs):
            self._core_regs[name] = i

    def close(self):
        if self._using_cli():
            try:
                self._cli_proxy.close()
            except Exception:
                pass
            self._cli_proxy = None
            return
        import usb.util
        try:
            if self._ep_out is not None:
                self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_EXIT], rx_len=2)
        except Exception:
            pass
        if self._device is not None:
            try:
                usb.util.dispose_resources(self._device)
            except Exception:
                pass
        self._device = None
        self._ep_in = None
        self._ep_out = None

    # -- Memory ----------------------------------------------------
    def _read_mem32(self, addr, count):
        """Read `count` 32-bit words."""
        result = []
        max_words = 64
        offset = 0
        while offset < count:
            n = min(max_words, count - offset)
            a = (addr + offset * 4) & 0xFFFFFFFF
            cmd = struct.pack('<BBHI', STLINK_DEBUG_COMMAND, STLINK_DEBUG_READMEM_32BIT,
                              n * 4, a)
            data = self._cmd(cmd, rx_len=n * 4, timeout=2000)
            if data is None or len(data) < n * 4:
                raise RuntimeError(f'ST-Link readmem failed @ {hex(a)}')
            for i in range(n):
                result.append(struct.unpack_from('<I', data, i * 4)[0])
            offset += n
        return result

    def _read_mem8(self, addr, count):
        result = []
        max_n = 64
        offset = 0
        while offset < count:
            n = min(max_n, count - offset)
            a = (addr + offset) & 0xFFFFFFFF
            cmd = struct.pack('<BBHI', STLINK_DEBUG_COMMAND, STLINK_DEBUG_READMEM_8BIT, n, a)
            data = self._cmd(cmd, rx_len=n, timeout=2000)
            if data is None or len(data) < n:
                words = self._read_mem32(a & ~3, (n + 3) // 4 + 1)
                blob = b''.join(struct.pack('<I', w) for w in words)
                start = a & 3
                result.extend(blob[start:start + n])
            else:
                result.extend(data[:n])
            offset += n
        return result

    def _write_mem32(self, addr, words):
        for i, val in enumerate(words):
            a = (addr + i * 4) & 0xFFFFFFFF
            cmd = bytearray(CMD_SIZE)
            cmd[0] = STLINK_DEBUG_COMMAND
            cmd[1] = STLINK_DEBUG_WRITEMEM_32BIT
            struct.pack_into('<HI', cmd, 2, 4, a)
            self._ep_out.write(cmd, 1000)
            self._ep_out.write(struct.pack('<I', val & 0xFFFFFFFF), 1000)
            try:
                self._ep_in.read(2, 1000)
            except Exception:
                pass

    def _write_mem8(self, addr, data):
        for i, val in enumerate(data):
            a = (addr + i) & 0xFFFFFFFF
            cmd = bytearray(CMD_SIZE)
            cmd[0] = STLINK_DEBUG_COMMAND
            cmd[1] = STLINK_DEBUG_WRITEMEM_8BIT
            struct.pack_into('<HI', cmd, 2, 1, a)
            self._ep_out.write(cmd, 1000)
            self._ep_out.write(bytes([val & 0xFF]), 1000)
            try:
                self._ep_in.read(2, 1000)
            except Exception:
                pass

    def read_mem_U8(self, addr, count):
        if self._using_cli():
            return self._cli_proxy.read_mem_U8(addr, count)
        return list(self._read_mem8(addr, count))

    def read_mem_U16(self, addr, count):
        if self._using_cli():
            return self._cli_proxy.read_mem_U16(addr, count)
        raw = self._read_mem8(addr, count * 2)
        return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]

    def read_mem_U32(self, addr, count):
        if self._using_cli():
            return self._cli_proxy.read_mem_U32(addr, count)
        return self._read_mem32(addr, count)

    def read_U32(self, addr):
        if self._using_cli():
            return self._cli_proxy.read_U32(addr)
        return self._read_mem32(addr, 1)[0]

    def write_U8(self, addr, val):
        if self._using_cli():
            return self._cli_proxy.write_U8(addr, val)
        self._write_mem8(addr, [val & 0xFF])

    def write_U16(self, addr, val):
        if self._using_cli():
            return self._cli_proxy.write_U16(addr, val)
        self._write_mem8(addr, [val & 0xFF, (val >> 8) & 0xFF])

    def write_U32(self, addr, val):
        if self._using_cli():
            return self._cli_proxy.write_U32(addr, val)
        self._write_mem32(addr, [val & 0xFFFFFFFF])

    def write_mem_U8(self, addr, data):
        if self._using_cli():
            return self._cli_proxy.write_mem_U8(addr, data)
        self._write_mem8(addr, list(data))

    def write_mem_U32(self, addr, data):
        if self._using_cli():
            return self._cli_proxy.write_mem_U32(addr, data)
        self._write_mem32(addr, list(data))

    # -- Registers -------------------------------------------------
    def _read_core_reg(self, idx):
        # API v2: F2 33 reg_index
        resp = self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_APIV2_READREG, idx & 0xFF], rx_len=8)
        if resp and len(resp) >= 8:
            # status(2?) + value — layouts vary; try last 4 bytes and offset 4
            try:
                return struct.unpack_from('<I', resp, 4)[0]
            except Exception:
                return struct.unpack_from('<I', resp, 0)[0]
        # fallback API v1
        resp = self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_READREG, idx & 0xFF], rx_len=4)
        if resp and len(resp) >= 4:
            return struct.unpack('<I', resp[:4])[0]
        raise RuntimeError(f'ST-Link read reg {idx} failed')

    def _write_core_reg(self, idx, val):
        cmd = struct.pack('<BBII', STLINK_DEBUG_COMMAND, STLINK_DEBUG_APIV2_WRITEREG,
                          idx & 0xFF, val & 0xFFFFFFFF)
        # pack carefully — index is u8 in some docs; use simple form
        pkt = bytearray(CMD_SIZE)
        pkt[0] = STLINK_DEBUG_COMMAND
        pkt[1] = STLINK_DEBUG_APIV2_WRITEREG
        pkt[2] = idx & 0xFF
        struct.pack_into('<I', pkt, 4, val & 0xFFFFFFFF)
        self._ep_out.write(pkt, 1000)
        try:
            self._ep_in.read(2, 1000)
        except Exception:
            pass

    def read_reg(self, reg):
        if self._using_cli():
            return self._cli_proxy.read_reg(reg)
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f'Unknown register: {reg}')
        return self._read_core_reg(idx)

    def read_regs(self, rlist):
        if self._using_cli():
            return self._cli_proxy.read_regs(rlist)
        return {reg: self.read_reg(reg) for reg in rlist}

    def write_reg(self, reg, val):
        if self._using_cli():
            return self._cli_proxy.write_reg(reg, val)
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f'Unknown register: {reg}')
        self._write_core_reg(idx, val)

    # -- CPU Control -----------------------------------------------
    def halt(self):
        if self._using_cli():
            return self._cli_proxy.halt()
        self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_FORCEDEBUG], rx_len=2)

    def go(self):
        if self._using_cli():
            return self._cli_proxy.go()
        self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_RUNCORE], rx_len=2)

    def step(self):
        if self._using_cli():
            return self._cli_proxy.step()
        self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_STEPCORE], rx_len=2)

    def reset(self):
        if self._using_cli():
            return self._cli_proxy.reset()
        try:
            self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_APIV2_RESETSYS], rx_len=2)
        except Exception:
            self._cmd([STLINK_DEBUG_COMMAND, STLINK_DEBUG_RESETSYS], rx_len=2)

    def halted(self):
        if self._using_cli():
            return self._cli_proxy.halted()
        try:
            dhcsr = self.read_U32(0xE000EDF0)
            return bool(dhcsr & (1 << 17))
        except Exception:
            return False

    def flash_file(self, path, addr=0):
        if self._using_cli():
            return self._cli_proxy.flash_file(path, addr)
        raise NotImplementedError('USB ST-Link flash_file not implemented; use CLI backend')

    def probe_info(self):
        if self._using_cli():
            return self._cli_proxy.probe_info()
        info = {'product_name': 'ST-Link (USB)', 'backend': 'pyusb'}
        if self._version:
            info['version_raw'] = self._version.hex()
        return info

    def swo_start(self, speed):
        raise NotImplementedError('SWO not supported by ST-Link raw USB probe')

    def swo_stop(self):
        pass

    def swo_read(self):
        return b''


register_probe('stlink', STLinkProbe)
