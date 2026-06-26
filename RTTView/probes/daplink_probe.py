from .base import DebugProbe
from . import register_probe


class DAPLinkProbe(DebugProbe):
    """CMSIS-DAP / DAPLink debug probe via vendored pyocd library.

    Wraps pyocd's CortexM object behind the DebugProbe interface.
    Initialization chain: probe.open() -> DebugPort -> AHB_AP -> CortexM.
    """

    def __init__(self, probe=None):
        self._probe = probe          # pyocd CMSISDAPProbe (low-level USB probe)
        self._dp = None              # pyocd DebugPort
        self._ap = None              # pyocd AHB_AP
        self._cortex = None          # pyocd CortexM
        self._mode = 'arm'
        self._core_regs = {}

    @staticmethod
    def detect():
        """Detect connected DAPLink / CMSIS-DAP probes.

        Returns a list of raw pyocd probe objects.
        Each has .product_name and .unique_id attributes.
        """
        from pyocd.probe.aggregator import DebugProbeAggregator
        return DebugProbeAggregator.get_all_connected_probes()

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._mode = mode.lower()

        if self._probe is None:
            probes = self.detect()
            if not probes:
                raise Exception('No DAPLink / CMSIS-DAP probe found')
            self._probe = probes[0]

        self._probe.open()

        from pyocd.coresight import dap, ap, cortex_m

        self._dp = dap.DebugPort(self._probe, None)
        self._dp.init()
        self._dp.power_up_debug()
        self._dp.set_clock(speed * 1000)

        self._ap = ap.AHB_AP(self._dp, 0)
        self._ap.init()

        self._cortex = cortex_m.CortexM(None, self._ap)

        self._refresh_regs()

    def _refresh_regs(self):
        """Populate core_regs from pyocd's CORE_REGISTER table."""
        from pyocd.coresight.cortex_m import CORE_REGISTER
        self._core_regs = {k: v for k, v in CORE_REGISTER.items()
                           if isinstance(v, int) and v >= 0}

    def close(self):
        if self._probe:
            self._probe.close()
            self._probe = None
        self._dp = None
        self._ap = None
        self._cortex = None

    # -- Memory -------------------------------------------------
    def read_mem_U8(self, addr, count):
        return list(self._cortex.read_memory_block8(addr, count))

    def read_mem_U16(self, addr, count):
        return [self._cortex.read16(addr + i * 2) for i in range(count)]

    def read_mem_U32(self, addr, count):
        return list(self._cortex.read_memory_block32(addr, count))

    def read_U32(self, addr):
        return self._cortex.read32(addr)

    def write_U8(self, addr, val):
        self._cortex.write8(addr, val)

    def write_U16(self, addr, val):
        self._cortex.write16(addr, val)

    def write_U32(self, addr, val):
        self._cortex.write32(addr, val)

    def write_mem_U8(self, addr, data):
        self._cortex.write_memory_block8(addr, data)

    def write_mem_U32(self, addr, data):
        self._cortex.write_memory_block32(addr, data)

    # -- Registers ----------------------------------------------
    def read_reg(self, reg):
        return self._cortex.read_core_register_raw(reg)

    def read_regs(self, rlist):
        return dict(zip(rlist, self._cortex.read_core_registers_raw(rlist)))

    def write_reg(self, reg, val):
        self._cortex.write_core_register_raw(reg, val)

    # -- CPU Control --------------------------------------------
    def halt(self):
        self._cortex.halt()

    def go(self):
        self._cortex.resume()

    def step(self):
        self._cortex.step()

    def reset(self):
        self._cortex.reset()

    def halted(self):
        return self._cortex.is_halted()


register_probe('daplink', DAPLinkProbe)
