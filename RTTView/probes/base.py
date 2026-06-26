from abc import ABC, abstractmethod


class DebugProbe(ABC):
    """Abstract base class for all debug probes.

    Every probe must implement these methods. The XLink facade
    delegates to this interface, eliminating isinstance() dispatch.
    """

    # -- Lifecycle ------------------------------------------------
    @abstractmethod
    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        """Open connection to the debug probe."""
        pass

    @abstractmethod
    def close(self):
        """Close connection."""
        pass

    # -- Memory Access --------------------------------------------
    @abstractmethod
    def read_mem_U8(self, addr, count):
        """Read `count` bytes starting at `addr`. Returns list[int]."""
        pass

    @abstractmethod
    def read_mem_U16(self, addr, count):
        """Read `count` 16-bit words. Returns list[int]."""
        pass

    @abstractmethod
    def read_mem_U32(self, addr, count):
        """Read `count` 32-bit words. Returns list[int]."""
        pass

    @abstractmethod
    def read_U32(self, addr):
        """Read one 32-bit word. Returns int."""
        pass

    @abstractmethod
    def write_U8(self, addr, val):
        pass

    @abstractmethod
    def write_U16(self, addr, val):
        pass

    @abstractmethod
    def write_U32(self, addr, val):
        pass

    @abstractmethod
    def write_mem_U8(self, addr, data):
        """Write bytes (list[int]) starting at addr."""
        pass

    @abstractmethod
    def write_mem_U32(self, addr, data):
        """Write 32-bit words (list[int]) starting at addr."""
        pass

    # -- Register Access ------------------------------------------
    @abstractmethod
    def read_reg(self, reg):
        """Read one core register by name. Returns int."""
        pass

    @abstractmethod
    def read_regs(self, rlist):
        """Read multiple registers. Returns dict[str, int]."""
        pass

    @abstractmethod
    def write_reg(self, reg, val):
        pass

    # -- CPU Control ----------------------------------------------
    @abstractmethod
    def halt(self):
        pass

    @abstractmethod
    def go(self):
        pass

    @abstractmethod
    def step(self):
        pass

    @abstractmethod
    def reset(self):
        pass

    @abstractmethod
    def halted(self):
        """Returns True if CPU is halted."""
        pass

    # -- Probe Info -----------------------------------------------
    @property
    def mode(self):
        """Current mode: 'arm', 'armj', 'rv', 'rvj'."""
        return getattr(self, '_mode', 'arm')

    @property
    def core_regs(self):
        """Dict of register name -> index/value."""
        return getattr(self, '_core_regs', {})

    @core_regs.setter
    def core_regs(self, value):
        self._core_regs = value

    # -- Optional: SWO support ------------------------------------
    def swo_start(self, speed):
        """Start SWO capture. Override if probe supports it."""
        raise NotImplementedError("SWO not supported by this probe")

    def swo_stop(self):
        pass

    def swo_read(self):
        """Read SWO data. Returns bytes."""
        return b''

    # -- Optional: Flash support ----------------------------------
    def flash_file(self, path, addr=0):
        """Flash a file. Override if probe supports it."""
        raise NotImplementedError("Flash not supported by this probe")

    # -- Optional: Disassembly ------------------------------------
    def disassemble(self, addr, count=1):
        """Disassemble instructions. Override if probe supports it."""
        raise NotImplementedError("Disassembly not supported by this probe")
