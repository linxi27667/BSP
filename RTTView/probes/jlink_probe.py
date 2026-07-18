import pylink
from .base import DebugProbe
from . import register_probe


class JLinkProbe(DebugProbe):
    """J-Link debug probe via pylink-square library."""

    TIF_MAP = {
        'arm':  pylink.enums.JLinkInterfaces.SWD,
        'armj': pylink.enums.JLinkInterfaces.JTAG,
        'rv':   pylink.enums.JLinkInterfaces.SWD,   # RISC-V over SWD
        'rvj':  pylink.enums.JLinkInterfaces.JTAG,
    }

    def __init__(self, dllpath=None):
        self._dllpath = dllpath
        self._jlink = None
        self._mode = 'arm'
        self._core_regs = {}

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._mode = mode.lower()

        if self._dllpath:
            self._jlink = pylink.JLink(lib=self._dllpath)
        else:
            self._jlink = pylink.JLink()

        self._jlink.open()
        self._jlink.set_tif(self.TIF_MAP.get(self._mode, pylink.enums.JLinkInterfaces.SWD))

        # Try requested core first, then common Cortex-M names (auto device)
        candidates = []
        for c in [core, 'Cortex-M0', 'Cortex-M0+', 'Cortex-M3', 'Cortex-M4',
                  'Cortex-M7', 'Cortex-M33', 'Cortex-M23', 'RISC-V']:
            if c and c not in candidates:
                candidates.append(c)

        last_err = None
        for c in candidates:
            try:
                self._jlink.connect(c, speed=int(speed))
                if self._jlink.connected():
                    last_err = None
                    break
            except Exception as e:
                last_err = e
                continue
        else:
            msg = f'J-Link: failed to connect to target (tried {candidates})'
            if last_err:
                msg += f': {last_err}'
            raise Exception(msg)

        if not self._jlink.connected():
            raise Exception('J-Link: failed to connect to target')

        self._refresh_regs()

    def _refresh_regs(self):
        """Read register names from J-Link."""
        self._core_regs = {}
        try:
            n_regs = self._jlink.num_regs()
            for i in range(n_regs):
                name = self._jlink.register_name(i)
                if name:
                    self._core_regs[name.lower()] = i
        except Exception:
            # Fallback: common ARM registers
            for i, name in enumerate(['r0','r1','r2','r3','r4','r5','r6','r7',
                                       'r8','r9','r10','r11','r12','sp','lr','pc',
                                       'xpsr','msp','psp']):
                self._core_regs[name] = i

    def close(self):
        if self._jlink:
            self._jlink.close()
            self._jlink = None

    # -- Memory -------------------------------------------------
    def read_mem_U8(self, addr, count):
        return list(self._jlink.memory_read(addr, count, nbits=8))

    def read_mem_U16(self, addr, count):
        return list(self._jlink.memory_read(addr, count, nbits=16))

    def read_mem_U32(self, addr, count):
        return list(self._jlink.memory_read(addr, count, nbits=32))

    def read_U32(self, addr):
        return self._jlink.memory_read(addr, 1, nbits=32)[0]

    def write_U8(self, addr, val):
        self._jlink.memory_write(addr, [val], nbits=8)

    def write_U16(self, addr, val):
        self._jlink.memory_write(addr, [val], nbits=16)

    def write_U32(self, addr, val):
        self._jlink.memory_write(addr, [val], nbits=32)

    def write_mem_U8(self, addr, data):
        self._jlink.memory_write(addr, data, nbits=8)

    def write_mem_U32(self, addr, data):
        self._jlink.memory_write(addr, data, nbits=32)

    # -- Registers ----------------------------------------------
    def read_reg(self, reg):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        return self._jlink.register_read(idx)

    def read_regs(self, rlist):
        return {reg: self.read_reg(reg) for reg in rlist}

    def write_reg(self, reg, val):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        self._jlink.register_write(idx, val)

    # -- CPU Control --------------------------------------------
    def halt(self):
        self._jlink.halt()

    def go(self):
        self._jlink.restart()

    def step(self):
        self._jlink.step()

    def reset(self):
        self._jlink.reset()

    def halted(self):
        return self._jlink.halted()

    # -- SWO (pylink-square native support) ---------------------
    def swo_start(self, speed):
        self._jlink.swo_start(speed)

    def swo_stop(self):
        self._jlink.swo_stop()

    def swo_read(self):
        buf = bytearray(4096)
        n = self._jlink.swo_read(buf, len(buf))
        return bytes(buf[:n])

    # -- Flash --------------------------------------------------
    def flash_file(self, path, addr=0):
        if not path:
            raise ValueError('flash_file: empty path')
        try:
            self._jlink.flash_file(path, int(addr))
        except Exception as e:
            raise RuntimeError(
                f'J-Link flash_file failed path={path} addr=0x{int(addr):08X}: {e}'
            ) from e

    # -- Probe / target info ------------------------------------
    def target_voltage(self):
        """Return target VTref in mV if available."""
        try:
            return int(self._jlink.target_voltage())
        except Exception:
            return None

    def probe_info(self):
        j = self._jlink
        info = {}
        for attr in ('product_name', 'serial_number', 'firmware_version',
                     'hardware_version', 'oem'):
            try:
                info[attr] = getattr(j, attr, None)
            except Exception:
                pass
        try:
            info['voltage_mv'] = self.target_voltage()
        except Exception:
            pass
        return info

    # -- Disassembly --------------------------------------------
    def disassemble(self, addr, count=1):
        try:
            return self._jlink.disassemble(int(addr), int(count))
        except Exception:
            # Fallback: raw halfwords (Thumb-ish dump)
            out = []
            for i in range(int(count)):
                a = int(addr) + i * 2
                try:
                    hw = self._jlink.memory_read(a, 1, nbits=16)[0]
                    out.append(f'0x{a:08X}:  {hw:04X}')
                except Exception as e:
                    out.append(f'0x{a:08X}:  ? ({e})')
            return out


register_probe('jlink', JLinkProbe)
