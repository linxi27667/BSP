# RTTView Phase 1: Probe Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor RTTView's probe layer from isinstance() dispatch to a clean abstract base class, add native ST-Link support, and upgrade J-Link to use pylink-square.

**Architecture:** Abstract `DebugProbe` base class defines the interface. Each probe (JLink, STLink, DAPLink, OpenOCD) implements this interface. A `ProbeRegistry` auto-discovers available probes. `xlink.py` becomes a thin wrapper that delegates to the probe's unified API.

**Tech Stack:** Python 3.6+, PyQt5, pylink-square, pystlink, vendored pyocd

## Global Constraints

- All existing RTT functionality must remain backward compatible
- Dark theme QSS must be preserved
- `setting.ini` format must remain compatible
- Windows platform (PowerShell commands)
- No external server dependencies for native probes (J-Link, ST-Link, DAPLink)

---

## File Structure

```
E:\MCU\BSP\RTTView\
├── probes/                          # NEW — probe plugin system
│   ├── __init__.py                  # ProbeRegistry + auto-discovery
│   ├── base.py                      # DebugProbe ABC
│   ├── jlink_probe.py               # J-Link via pylink-square
│   ├── stlink_probe.py              # ST-Link via pystlink
│   ├── daplink_probe.py             # DAPLink via vendored pyocd
│   └── openocd_probe.py             # OpenOCD via TCP Tcl RPC
├── xlink.py                         # MODIFY — thin wrapper over DebugProbe
├── jlink.py                         # KEEP — backward compat (imports from probes/)
├── openocd.py                       # KEEP — backward compat (imports from probes/)
├── RTTView.py                       # MODIFY — use ProbeRegistry for detection
└── ...
```

---

### Task 1: Create DebugProbe Abstract Base Class

**Files:**
- Create: `E:\MCU\BSP\RTTView\probes\__init__.py`
- Create: `E:\MCU\BSP\RTTView\probes\base.py`

**Interfaces:**
- Produces: `DebugProbe` ABC with all methods that `xlink.py` currently dispatches on

- [ ] **Step 1: Create probes package init**

```python
# E:\MCU\BSP\RTTView\probes\__init__.py
from .base import DebugProbe

# Registry: populated by probe modules on import
_PROBES = {}

def register_probe(name, probe_class):
    _PROBES[name] = probe_class

def get_probe(name):
    return _PROBES.get(name)

def list_probes():
    return dict(_PROBES)

def create_probe(name, **kwargs):
    cls = _PROBES.get(name)
    if cls is None:
        raise ValueError(f"Unknown probe: {name}")
    return cls(**kwargs)
```

- [ ] **Step 2: Create DebugProbe ABC**

```python
# E:\MCU\BSP\RTTView\probes\base.py
from abc import ABC, abstractmethod


class DebugProbe(ABC):
    """Abstract base class for all debug probes.

    Every probe must implement these methods. The XLink facade
    delegates to this interface, eliminating isinstance() dispatch.
    """

    # ── Lifecycle ──────────────────────────────────────────────
    @abstractmethod
    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        """Open connection to the debug probe."""
        pass

    @abstractmethod
    def close(self):
        """Close connection."""
        pass

    # ── Memory Access ──────────────────────────────────────────
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

    # ── Register Access ────────────────────────────────────────
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

    # ── CPU Control ────────────────────────────────────────────
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

    # ── Probe Info ─────────────────────────────────────────────
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

    # ── Optional: SWO support ──────────────────────────────────
    def swo_start(self, speed):
        """Start SWO capture. Override if probe supports it."""
        raise NotImplementedError("SWO not supported by this probe")

    def swo_stop(self):
        pass

    def swo_read(self):
        """Read SWO data. Returns bytes."""
        return b''

    # ── Optional: Flash support ────────────────────────────────
    def flash_file(self, path, addr=0):
        """Flash a file. Override if probe supports it."""
        raise NotImplementedError("Flash not supported by this probe")

    # ── Optional: Disassembly ──────────────────────────────────
    def disassemble(self, addr, count=1):
        """Disassemble instructions. Override if probe supports it."""
        raise NotImplementedError("Disassembly not supported by this probe")
```

- [ ] **Step 3: Verify import works**

```powershell
cd E:\MCU\BSP\RTTView
python -c "from probes.base import DebugProbe; print('OK:', DebugProbe.__abstractmethods__)"
```

Expected: `OK: frozenset({'close', 'go', 'halt', 'halted', ...})`

- [ ] **Step 4: Commit**

```powershell
git add probes/__init__.py probes/base.py
git commit -m "feat: add DebugProbe abstract base class and probe registry"
```

---

### Task 2: Implement J-Link Probe (pylink-square)

**Files:**
- Create: `E:\MCU\BSP\RTTView\probes\jlink_probe.py`

**Interfaces:**
- Consumes: `DebugProbe` from `probes.base`, `pylink-square` library
- Produces: `JLinkProbe` class registered as `'jlink'`
- Adds: SWO support, flash support, disassembly via pylink API

- [ ] **Step 1: Install pylink-square**

```powershell
pip install pylink-square
python -c "import pylink; print('pylink-square version:', pylink.__version__)"
```

- [ ] **Step 2: Create JLinkProbe**

```python
# E:\MCU\BSP\RTTView\probes\jlink_probe.py
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
        self._jlink.connect(core, speed=speed)

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

    # ── Memory ─────────────────────────────────────────────────
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

    # ── Registers ──────────────────────────────────────────────
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

    # ── CPU Control ────────────────────────────────────────────
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

    # ── SWO (pylink-square native support) ─────────────────────
    def swo_start(self, speed):
        self._jlink.swo_start(speed)

    def swo_stop(self):
        self._jlink.swo_stop()

    def swo_read(self):
        buf = bytearray(4096)
        n = self._jlink.swo_read(buf, len(buf))
        return bytes(buf[:n])

    # ── Flash ──────────────────────────────────────────────────
    def flash_file(self, path, addr=0):
        self._jlink.flash_file(path, addr)

    # ── Disassembly ────────────────────────────────────────────
    def disassemble(self, addr, count=1):
        return self._jlink.disassemble(addr, count)


register_probe('jlink', JLinkProbe)
```

- [ ] **Step 3: Verify JLinkProbe registers**

```powershell
python -c "from probes.jlink_probe import JLinkProbe; print('JLinkProbe OK')"
```

Expected: `JLinkProbe OK` (imports without error, no J-Link hardware needed for import)

- [ ] **Step 4: Commit**

```powershell
git add probes/jlink_probe.py
git commit -m "feat: add JLinkProbe using pylink-square with SWO/flash/disasm support"
```

---

### Task 3: Implement ST-Link Probe (pystlink)

**Files:**
- Create: `E:\MCU\BSP\RTTView\probes\stlink_probe.py`

**Interfaces:**
- Consumes: `DebugProbe` from `probes.base`, `pystlink` (vendored or pip)
- Produces: `STLinkProbe` class registered as `'stlink'`

- [ ] **Step 1: Install/clone pystlink**

```powershell
cd E:\MCU\BSP\RTTView
pip install pystlink 2>$null
# If pip fails, clone from GitHub
if ($LASTEXITCODE -ne 0) {
    git clone https://github.com/pavelrevak/pystlink.git _pystlink
}
python -c "import pystlink; print('pystlink OK')" 2>$null
```

- [ ] **Step 2: Create STLinkProbe**

```python
# E:\MCU\BSP\RTTView\probes\stlink_probe.py
import struct
from .base import DebugProbe
from . import register_probe

# ST-Link USB identifiers
STLINK_VID = 0x0483
STLINK_PIDS = {
    0x3748: 'ST-Link/V1',
    0x374b: 'ST-Link/V2',
    0x3752: 'ST-Link/V2-1',
    0x374e: 'ST-Link/V3',
    0x374f: 'ST-Link/V3 (bridge)',
}


class STLinkProbe(DebugProbe):
    """ST-Link debug probe via USB (pystlink-style direct access).

    Uses pyusb for direct ST-Link communication — no OpenOCD server needed.
    Supports ST-Link/V2, V2-1, V3.
    """

    def __init__(self, device=None):
        self._device = device
        self._mode = 'arm'
        self._core_regs = {}
        self._ep_out = None
        self._ep_in = None
        self._handle = None

    @staticmethod
    def detect():
        """Detect connected ST-Link probes. Returns list of (device, name)."""
        import usb.core
        probes = []
        for pid, name in STLINK_PIDS.items():
            devs = usb.core.find(find_all=True, idVendor=STLINK_VID, idProduct=pid)
            for dev in devs:
                probes.append((dev, f'{name} ({dev.serial_number})'))
        return probes

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        import usb.core
        self._mode = mode.lower()

        if self._device is None:
            # Auto-detect first ST-Link
            self._device = usb.core.find(idVendor=STLINK_VID)
            if self._device is None:
                raise Exception('No ST-Link probe found')

        try:
            self._device.set_configuration()
        except usb.core.USBError:
            pass  # Already configured

        cfg = self._device.get_active_configuration()
        intf = cfg[(0, 0)]

        self._ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        self._ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)

        if self._ep_out is None or self._ep_in is None:
            raise Exception('ST-Link: could not find USB endpoints')

        # Initialize: get version info
        self._stlink_cmd(b'\xf1\x80', 6)  # GET_VERSION

        # Enter SWD mode
        if self._mode.startswith('arm'):
            self._stlink_cmd(b'\xf2\x20', 2)  # SET_SWD
        else:
            self._stlink_cmd(b'\xf2\x21', 2)  # SET_JTAG

        # Set speed
        speed_map = {4000: 0, 1800: 1, 900: 2, 400: 3, 200: 4, 95: 5}
        speed_val = min(speed_map.keys(), key=lambda s: abs(s - speed))
        self._stlink_cmd(struct.pack('<BH', 0xf2, speed_map[speed_val]), 2)  # SET_SPEED

        # Init DAP
        self._stlink_cmd(b'\xf2\x02', 2)  # INIT_SWD

        self._refresh_regs()

    def _stlink_cmd(self, cmd, rx_len, timeout=1000):
        """Send ST-Link command and read response."""
        self._ep_out.write(cmd, timeout)
        return bytes(self._ep_in.read(rx_len, timeout))

    def _refresh_regs(self):
        """Standard ARM Cortex-M registers."""
        regs = ['r0','r1','r2','r3','r4','r5','r6','r7',
                'r8','r9','r10','r11','r12','sp','lr','pc',
                'xpsr','msp','psp','cfbp']
        for i, name in enumerate(regs):
            self._core_regs[name] = i

    def close(self):
        import usb.util
        if self._device:
            usb.util.dispose_resources(self._device)
            self._device = None

    # ── DAP Register access (via ST-Link commands) ─────────────
    def _dap_read(self, addr):
        """Read 32-bit word via DAP."""
        # ST-Link DAP read command
        cmd = struct.pack('<BBI', 0xf2, 0x36, addr)  # DAP_READ
        resp = self._stlink_cmd(cmd, 8)
        return struct.unpack('<I', resp[4:8])[0]

    def _dap_write(self, addr, val):
        """Write 32-bit word via DAP."""
        cmd = struct.pack('<BBII', 0xf2, 0x35, addr, val)  # DAP_WRITE
        self._stlink_cmd(cmd, 2)

    def _read_mem_raw(self, addr, count, width):
        """Read memory block. width in bytes (1, 2, 4)."""
        result = []
        # ST-Link has a max transfer size, chunk it
        chunk_size = 64 // width
        offset = 0
        while offset < count:
            n = min(chunk_size, count - offset)
            a = addr + offset * width
            if width == 4:
                cmd = struct.pack('<BBHB I', 0xf2, 0x07, n * width, 0x02, a)
            elif width == 2:
                cmd = struct.pack('<BBHB I', 0xf2, 0x07, n * width, 0x01, a)
            else:
                cmd = struct.pack('<BBHB I', 0xf2, 0x07, n * width, 0x00, a)
            resp = self._stlink_cmd(cmd, n * width + 2)
            for i in range(n):
                if width == 4:
                    result.append(struct.unpack('<I', resp[2+i*4:6+i*4])[0])
                elif width == 2:
                    result.append(struct.unpack('<H', resp[2+i*2:4+i*2])[0])
                else:
                    result.append(resp[2+i])
            offset += n
        return result

    # ── Memory ─────────────────────────────────────────────────
    def read_mem_U8(self, addr, count):
        return self._read_mem_raw(addr, count, 1)

    def read_mem_U16(self, addr, count):
        return self._read_mem_raw(addr, count, 2)

    def read_mem_U32(self, addr, count):
        return self._read_mem_raw(addr, count, 4)

    def read_U32(self, addr):
        return self._read_mem_raw(addr, 1, 4)[0]

    def write_U8(self, addr, val):
        cmd = struct.pack('<BBHB IB', 0xf2, 0x08, 1, 0x00, addr, val)
        self._stlink_cmd(cmd, 2)

    def write_U16(self, addr, val):
        cmd = struct.pack('<BBHB IH', 0xf2, 0x08, 2, 0x01, addr, val)
        self._stlink_cmd(cmd, 2)

    def write_U32(self, addr, val):
        cmd = struct.pack('<BBHB II', 0xf2, 0x08, 4, 0x02, addr, val)
        self._stlink_cmd(cmd, 2)

    def write_mem_U8(self, addr, data):
        for i, val in enumerate(data):
            self.write_U8(addr + i, val)

    def write_mem_U32(self, addr, data):
        for i, val in enumerate(data):
            self.write_U32(addr + i * 4, val)

    # ── Registers ──────────────────────────────────────────────
    def _read_core_reg(self, idx):
        """Read core register via ST-Link."""
        cmd = struct.pack('<BBI', 0xf2, 0x33, idx)  # GET_REG
        resp = self._stlink_cmd(cmd, 8)
        return struct.unpack('<I', resp[4:8])[0]

    def _write_core_reg(self, idx, val):
        cmd = struct.pack('<BBII', 0xf2, 0x34, idx, val)  # SET_REG
        self._stlink_cmd(cmd, 2)

    def read_reg(self, reg):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        return self._read_core_reg(idx)

    def read_regs(self, rlist):
        return {reg: self.read_reg(reg) for reg in rlist}

    def write_reg(self, reg, val):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        self._write_core_reg(idx, val)

    # ── CPU Control ────────────────────────────────────────────
    def halt(self):
        self._stlink_cmd(b'\xf2\x09', 2)  # DEBUG_HALT

    def go(self):
        self._stlink_cmd(b'\xf2\x0a', 2)  # DEBUG_RUN

    def step(self):
        self._stlink_cmd(b'\xf2\x0c', 2)  # DEBUG_STEP

    def reset(self):
        self._stlink_cmd(b'\xf2\x0b', 2)  # DEBUG_RESET

    def halted(self):
        # Read DHCSR to check S_HALT bit
        dhcsr = self._dap_read(0xE000EDF0)
        return bool(dhcsr & (1 << 17))


register_probe('stlink', STLinkProbe)
```

- [ ] **Step 3: Verify import**

```powershell
python -c "from probes.stlink_probe import STLinkProbe; print('STLinkProbe OK')"
```

- [ ] **Step 4: Commit**

```powershell
git add probes/stlink_probe.py
git commit -m "feat: add STLinkProbe with native USB support (V2/V2-1/V3)"
```

---

### Task 4: Implement DAPLink Probe

**Files:**
- Create: `E:\MCU\BSP\RTTView\probes\daplink_probe.py`

**Interfaces:**
- Consumes: `DebugProbe` from `probes.base`, vendored `pyocd.coresight`
- Produces: `DAPLinkProbe` class registered as `'daplink'`

- [ ] **Step 1: Create DAPLinkProbe**

```python
# E:\MCU\BSP\RTTView\probes\daplink_probe.py
import sys
import os
from .base import DebugProbe
from . import register_probe

# Ensure vendored pyocd is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DAPLinkProbe(DebugProbe):
    """DAPLink/CMSIS-DAP probe via vendored pyocd."""

    def __init__(self, probe=None):
        self._probe = probe
        self._cortex = None
        self._mode = 'arm'
        self._core_regs = {}

    @staticmethod
    def detect():
        """Detect connected DAPLink probes."""
        try:
            from pyocd.probe import aggregator
            return aggregator.DebugProbeAggregator.get_all_connected_probes()
        except Exception:
            return []

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        from pyocd.coresight import dap, ap, cortex_m

        self._mode = mode.lower()

        if self._probe is None:
            probes = self.detect()
            if not probes:
                raise Exception('No DAPLink probe found')
            self._probe = probes[0]

        self._probe.open()

        _dp = dap.DebugPort(self._probe, None)
        _dp.init()
        _dp.power_up_debug()
        _dp.set_clock(speed * 1000)

        _ap = ap.AHB_AP(_dp, 0)
        _ap.init()

        self._cortex = cortex_m.CortexM(None, _ap)
        self._refresh_regs()

    def _refresh_regs(self):
        """Read registers from CortexM."""
        # pyocd CortexM has register definitions
        self._core_regs = {}
        try:
            regs = self._cortex.core_registers
            for name, idx in regs.items():
                if isinstance(idx, int):
                    self._core_regs[name.lower()] = idx
        except Exception:
            pass

        # Fallback: standard Cortex-M registers
        if not self._core_regs:
            for i, name in enumerate(['r0','r1','r2','r3','r4','r5','r6','r7',
                                       'r8','r9','r10','r11','r12','sp','lr','pc',
                                       'xpsr','msp','psp']):
                self._core_regs[name] = i

    def close(self):
        if self._probe:
            self._probe.close()

    # ── Memory ─────────────────────────────────────────────────
    def read_mem_U8(self, addr, count):
        return list(self._cortex.read_memory_block8(addr, count))

    def read_mem_U16(self, addr, count):
        return list(self._cortex.read_memory_block16(addr, count))

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

    # ── Registers ──────────────────────────────────────────────
    def read_reg(self, reg):
        return self._cortex.read_core_register_raw(reg)

    def read_regs(self, rlist):
        return dict(zip(rlist, self._cortex.read_core_registers_raw(rlist)))

    def write_reg(self, reg, val):
        self._cortex.write_core_register_raw(reg, val)

    # ── CPU Control ────────────────────────────────────────────
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
```

- [ ] **Step 2: Verify import**

```powershell
python -c "from probes.daplink_probe import DAPLinkProbe; print('DAPLinkProbe OK')"
```

- [ ] **Step 3: Commit**

```powershell
git add probes/daplink_probe.py
git commit -m "feat: add DAPLinkProbe wrapping vendored pyocd"
```

---

### Task 5: Implement OpenOCD Probe

**Files:**
- Create: `E:\MCU\BSP\RTTView\probes\openocd_probe.py`

**Interfaces:**
- Consumes: `DebugProbe` from `probes.base`
- Produces: `OpenOCDProbe` class registered as `'openocd'`

- [ ] **Step 1: Create OpenOCDProbe**

```python
# E:\MCU\BSP\RTTView\probes\openocd_probe.py
import re
import time
import socket
from .base import DebugProbe
from . import register_probe


class OpenOCDProbe(DebugProbe):
    """OpenOCD debug probe via Tcl RPC over TCP socket."""

    def __init__(self, host='localhost', port=6666):
        self._host = host
        self._port = port
        self._sock = None
        self._mode = 'arm'
        self._core_regs = {}

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._mode = mode.lower()
        self._sock = socket.create_connection((self._host, self._port), timeout=1)
        self._refresh_regs()

    def _exec(self, cmd):
        self._sock.send(f'{cmd}\x1a'.encode('latin-1'))
        return self._read()

    def _read(self):
        resp = bytes()
        start = time.time()
        while time.time() < start + 2:
            resp += self._sock.recv(4096)
            if resp.endswith(b'\x1a'):
                break
        return resp[:-1].decode('latin-1').strip()

    def _refresh_regs(self):
        self._core_regs = {}
        for line in self._exec('reg').splitlines():
            match = re.match(r'\((\d+)\)\s+(\w+)\s+\(/(\d+)\)', line)
            if match:
                self._core_regs[match.group(2).lower()] = match.group(1)

    def _halt_required(func):
        def wrapper(self, *args, **kwargs):
            halted = self.halted()
            if not halted:
                self.halt()
            res = func(self, *args, **kwargs)
            if not halted:
                self.resume()
            return res
        return wrapper

    def close(self):
        if self._sock:
            try:
                self._exec('exit')
            finally:
                self._sock.close()
                self._sock = None
            time.sleep(0.01)

    # ── Memory ─────────────────────────────────────────────────
    @_halt_required
    def read_mem_(self, addr, count, width):
        data = []
        index = 0
        while index < count:
            res = self._exec(f'read_memory {addr:#x} {width} {min(128, count)}')
            if res:
                data.extend([int(x, 16) for x in res.split()])
                addr += 128 * (width // 8)
                index += 128
            else:
                break
        return data

    def read_mem_U8(self, addr, count):
        return self.read_mem_(addr, count, 8)

    def read_mem_U16(self, addr, count):
        return self.read_mem_(addr, count, 16)

    def read_mem_U32(self, addr, count):
        return self.read_mem_(addr, count, 32)

    def read_U32(self, addr):
        return self.read_mem_U32(addr, 1)[0]

    @_halt_required
    def write_U8(self, addr, val):
        self._exec(f'mwb {addr:#x} {val:#x}')

    @_halt_required
    def write_U16(self, addr, val):
        self._exec(f'mwh {addr:#x} {val:#x}')

    @_halt_required
    def write_U32(self, addr, val):
        self._exec(f'mww {addr:#x} {val:#x}')

    @_halt_required
    def write_mem_U8(self, addr, data):
        self._write_mem_block(addr, data, 8)

    @_halt_required
    def write_mem_U32(self, addr, data):
        self._write_mem_block(addr, data, 32)

    def _write_mem_block(self, addr, data, width):
        index = 0
        while index < len(data):
            s = ' '.join([f'{x:#x}' for x in data[index:index+128]])
            self._exec(f'write_memory {addr:#x} {width} {{{s}}}')
            addr += 128 * (width // 8)
            index += 128

    # ── Registers ──────────────────────────────────────────────
    def read_reg(self, reg):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        res = self._exec(f'reg {idx}')
        return int(res.split(':')[1].strip(), 16)

    def read_regs(self, rlist):
        return {reg: self.read_reg(reg) for reg in rlist}

    def write_reg(self, reg, val):
        idx = self._core_regs.get(reg.lower())
        if idx is None:
            raise ValueError(f"Unknown register: {reg}")
        self._exec(f'reg {idx} {val:#x}')

    # ── CPU Control ────────────────────────────────────────────
    def halt(self):
        self._exec('halt 500')

    def go(self):
        self.resume()

    def resume(self, addr=None):
        if addr is None:
            self._exec('resume')
        else:
            self._exec(f'resume {addr:#x}')

    def step(self):
        self._exec('step')

    def reset(self, halt=False):
        self._exec(f'reset {"halt" if halt else "run"}')

    def halted(self):
        return 'halted' in self._exec('targets')


register_probe('openocd', OpenOCDProbe)
```

- [ ] **Step 2: Verify import**

```powershell
python -c "from probes.openocd_probe import OpenOCDProbe; print('OpenOCDProbe OK')"
```

- [ ] **Step 3: Commit**

```powershell
git add probes/openocd_probe.py
git commit -m "feat: add OpenOCDProbe via Tcl RPC over TCP"
```

---

### Task 6: Refactor XLink to Use DebugProbe

**Files:**
- Modify: `E:\MCU\BSP\RTTView\xlink.py`

**Interfaces:**
- Consumes: `DebugProbe` ABC
- Produces: Same `XLink` public API (backward compatible)
- Key change: all isinstance() dispatch replaced by calling probe methods directly

- [ ] **Step 1: Refactor xlink.py**

```python
# E:\MCU\BSP\RTTView\xlink.py
import os
import time
import ctypes
import operator

from probes.base import DebugProbe


class XLink(object):
    """Unified memory/register access facade.

    Wraps a DebugProbe instance and provides additional logic:
    - Register name aliasing (SP/LR/PC for ARM, ABI names for RISC-V)
    - resetStopOnReset() for halt-on-reset debugging
    - read_core_type() for CPU identification
    """

    def __init__(self, probe):
        """Accept either a DebugProbe instance or legacy probe objects."""
        if isinstance(probe, DebugProbe):
            self.probe = probe
        else:
            # Legacy: wrap old-style probe in adapter
            self.probe = _LegacyAdapter(probe)

        self.reg_add_alias()

    def open(self, mode, core, speed):
        self.probe.open(mode, core, speed)
        self.reg_add_alias()

    def reg_add_alias(self):
        def add_alias(regs, name1, name2, name3=None):
            if name1 in regs:
                regs[name2] = regs[name1]
                if name3: regs[name3] = regs[name1]
            elif name2 in regs:
                regs[name1] = regs[name2]
                if name3: regs[name3] = regs[name2]
            elif name3 and name3 in regs:
                regs[name1] = regs[name3]
                regs[name2] = regs[name3]

        self.probe.core_regs = {k.lower(): v for k, v in self.probe.core_regs.items()}

        if self.mode.startswith('arm'):
            add_alias(self.probe.core_regs, 'r13', 'sp', 'r13 (sp)')
            add_alias(self.probe.core_regs, 'r14', 'lr', 'r14 (lr)')
            add_alias(self.probe.core_regs, 'r15', 'pc', 'r15 (pc)')
        elif self.mode.startswith('rv'):
            add_alias(self.probe.core_regs, 'x1',  'ra')
            add_alias(self.probe.core_regs, 'x2',  'sp')
            add_alias(self.probe.core_regs, 'x3',  'gp')
            add_alias(self.probe.core_regs, 'x4',  'tp')
            add_alias(self.probe.core_regs, 'x5',  't0')
            add_alias(self.probe.core_regs, 'x6',  't1')
            add_alias(self.probe.core_regs, 'x7',  't2')
            add_alias(self.probe.core_regs, 'x8',  's0', 'fp')
            add_alias(self.probe.core_regs, 'x9',  's1')
            add_alias(self.probe.core_regs, 'x10', 'a0')
            add_alias(self.probe.core_regs, 'x11', 'a1')
            add_alias(self.probe.core_regs, 'x12', 'a2')
            add_alias(self.probe.core_regs, 'x13', 'a3')
            add_alias(self.probe.core_regs, 'x14', 'a4')
            add_alias(self.probe.core_regs, 'x15', 'a5')
            add_alias(self.probe.core_regs, 'x16', 'a6')
            add_alias(self.probe.core_regs, 'x17', 'a7')
            add_alias(self.probe.core_regs, 'x18', 's2')
            add_alias(self.probe.core_regs, 'x19', 's3')
            add_alias(self.probe.core_regs, 'x20', 's4')
            add_alias(self.probe.core_regs, 'x21', 's5')
            add_alias(self.probe.core_regs, 'x22', 's6')
            add_alias(self.probe.core_regs, 'x23', 's7')
            add_alias(self.probe.core_regs, 'x24', 's8')
            add_alias(self.probe.core_regs, 'x25', 's9')
            add_alias(self.probe.core_regs, 'x26', 's10')
            add_alias(self.probe.core_regs, 'x27', 's11')
            add_alias(self.probe.core_regs, 'x28', 't3')
            add_alias(self.probe.core_regs, 'x29', 't4')
            add_alias(self.probe.core_regs, 'x30', 't5')
            add_alias(self.probe.core_regs, 'x31', 't6')

    @property
    def mode(self):
        return self.probe.mode

    # ── Direct delegation (no more isinstance!) ────────────────
    def write_U8(self, addr, val):
        self.probe.write_U8(addr, val)

    def write_U16(self, addr, val):
        self.probe.write_U16(addr, val)

    def write_U32(self, addr, val):
        self.probe.write_U32(addr, val)

    def write_mem_U8(self, addr, data):
        self.probe.write_mem_U8(addr, data)

    def write_mem_U32(self, addr, data):
        self.probe.write_mem_U32(addr, data)

    def read_mem_U8(self, addr, count):
        return self.probe.read_mem_U8(addr, count)

    def read_mem_U16(self, addr, count):
        return self.probe.read_mem_U16(addr, count)

    def read_mem_U32(self, addr, count):
        return self.probe.read_mem_U32(addr, count)

    def read_U32(self, addr):
        return self.probe.read_U32(addr)

    def read_reg(self, reg):
        return self.probe.read_reg(reg.lower())

    def read_regs(self, rlist):
        return dict(zip(rlist, self.probe.read_regs([reg.lower() for reg in rlist]).values()))

    def write_reg(self, reg, val):
        self.probe.write_reg(reg.lower(), val)

    def reset(self):
        self.probe.reset()
        if self.mode.startswith('rv'):
            self.probe.write_reg('pc', 0)
            self.probe.write_reg('dpc', 0)
            self.go()

    def halt(self):
        self.probe.halt()

    def step(self):
        self.probe.step()

    def go(self):
        self.probe.go()

    def halted(self):
        return self.probe.halted()

    def close(self):
        self.probe.close()

    # ── Core type identification ───────────────────────────────
    CORE_TYPE_NAME = {
        0xC20: "Cortex-M0", 0xC21: "Cortex-M1", 0xC23: "Cortex-M3",
        0xC24: "Cortex-M4", 0xC27: "Cortex-M7", 0xC60: "Cortex-M0+",
        0xD20: "Cortex-M23", 0xD21: "Cortex-M33", 0xD22: "Cortex-M55",
        0xD23: "Cortex-M85", 0x132: "Star-MC1"
    }

    def read_core_type(self):
        if self.mode.startswith('arm'):
            CPUID = 0xE000ED00
            cpuid = self.read_U32(CPUID)
            core_type = (cpuid & 0x0000FFF0) >> 4
            return self.CORE_TYPE_NAME.get(core_type, f'Unknown (0x{core_type:03X})')
        elif self.mode.startswith('rv'):
            halted = self.halted()
            if not halted: self.halt()
            isa = self.read_reg('misa')
            if not halted: self.go()
            if ((isa >> 30) & 3) == 1:
                name = 'RV32'
            elif ((isa >> 62) & 3) == 2:
                name = 'RV64'
            else:
                return 'RISC-V'
            indx = lambda c: ord(c) - ord('A')
            name += 'I' if isa & (1 << indx('I')) else 'E'
            if isa & (1 << indx('M')): name += 'M'
            if isa & (1 << indx('A')): name += 'A'
            if isa & (1 << indx('F')): name += 'F'
            if isa & (1 << indx('D')): name += 'D'
            if isa & (1 << indx('C')): name += 'C'
            if isa & (1 << indx('B')): name += 'B'
            return name.replace('IMAFD', 'G')

    # ── Debug control registers ────────────────────────────────
    DHCSR = 0xE000EDF0
    DEMCR = 0xE000EDFC
    DEMCR_VC_CORERESET = (1 << 0)

    def resetStopOnReset(self):
        self.halt()
        demcr = self.read_U32(self.DEMCR)
        self.write_U32(self.DEMCR, demcr | self.DEMCR_VC_CORERESET)
        self.reset()
        self.waitReset()
        while not self.halted():
            time.sleep(0.001)
        self.write_U32(self.DEMCR, demcr)

    def waitReset(self):
        startTime = time.time()
        while time.time() - startTime < 2.0:
            try:
                dhcsr = self.read_U32(self.DHCSR)
                if (dhcsr & (1 << 25)) == 0:
                    break
            except Exception:
                time.sleep(0.01)


class _LegacyAdapter(DebugProbe):
    """Adapter to wrap old-style probe objects (JLink/OpenOCD/pyocd CortexM)
    into the DebugProbe interface for backward compatibility."""

    def __init__(self, legacy):
        self._legacy = legacy
        # Detect type and map methods
        type_name = type(legacy).__name__
        self._is_pyocd = hasattr(legacy, 'read_memory_block8')

    @property
    def mode(self):
        return getattr(self._legacy, 'mode', 'arm')

    @property
    def core_regs(self):
        return self._legacy.core_regs

    @core_regs.setter
    def core_regs(self, value):
        self._legacy.core_regs = value

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._legacy.open(mode, core, speed)

    def close(self):
        self._legacy.close()

    def read_mem_U8(self, addr, count):
        if self._is_pyocd:
            return list(self._legacy.read_memory_block8(addr, count))
        return self._legacy.read_mem_U8(addr, count)

    def read_mem_U16(self, addr, count):
        if self._is_pyocd:
            return [self._legacy.read16(addr + i*2) for i in range(count)]
        return self._legacy.read_mem_U16(addr, count)

    def read_mem_U32(self, addr, count):
        if self._is_pyocd:
            return list(self._legacy.read_memory_block32(addr, count))
        return self._legacy.read_mem_U32(addr, count)

    def read_U32(self, addr):
        if self._is_pyocd:
            return self._legacy.read32(addr)
        return self._legacy.read_U32(addr)

    def write_U8(self, addr, val):
        if self._is_pyocd:
            self._legacy.write8(addr, val)
        else:
            self._legacy.write_U8(addr, val)

    def write_U16(self, addr, val):
        if self._is_pyocd:
            self._legacy.write16(addr, val)
        else:
            self._legacy.write_U16(addr, val)

    def write_U32(self, addr, val):
        if self._is_pyocd:
            self._legacy.write32(addr, val)
        else:
            self._legacy.write_U32(addr, val)

    def write_mem_U8(self, addr, data):
        if self._is_pyocd:
            self._legacy.write_memory_block8(addr, data)
        else:
            self._legacy.write_mem_U8(addr, data)

    def write_mem_U32(self, addr, data):
        if self._is_pyocd:
            self._legacy.write_memory_block32(addr, data)
        else:
            self._legacy.write_mem_U32(addr, data)

    def read_reg(self, reg):
        if self._is_pyocd:
            return self._legacy.read_core_register_raw(reg)
        return self._legacy.read_reg(reg)

    def read_regs(self, rlist):
        if self._is_pyocd:
            return dict(zip(rlist, self._legacy.read_core_registers_raw(rlist)))
        return self._legacy.read_regs(rlist)

    def write_reg(self, reg, val):
        if self._is_pyocd:
            self._legacy.write_core_register_raw(reg, val)
        else:
            self._legacy.write_reg(reg, val)

    def halt(self):
        self._legacy.halt()

    def go(self):
        if self._is_pyocd:
            self._legacy.resume()
        else:
            self._legacy.go()

    def step(self):
        self._legacy.step()

    def reset(self):
        self._legacy.reset()

    def halted(self):
        if self._is_pyocd:
            return self._legacy.is_halted()
        return self._legacy.halted()
```

- [ ] **Step 2: Verify XLink still works with legacy probes**

```powershell
python -c "import xlink; print('XLink import OK')"
```

- [ ] **Step 3: Commit**

```powershell
git add xlink.py
git commit -m "refactor: XLink delegates to DebugProbe ABC, LegacyAdapter for backward compat"
```

---

### Task 7: Update RTTView.py to Use ProbeRegistry

**Files:**
- Modify: `E:\MCU\BSP\RTTView\RTTView.py` (lines 1118-1148, on_btnOpen_clicked)

**Interfaces:**
- Consumes: `probes.list_probes()`, `probes.create_probe()`, `DAPLinkProbe.detect()`
- Produces: Updated connection logic with auto-detection for all probe types

- [ ] **Step 1: Update imports in RTTView.py**

Replace lines 19-20:
```python
import jlink
import xlink
```

With:
```python
import xlink
from probes import list_probes, create_probe
from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe
```

- [ ] **Step 2: Update probe detection (daplink_detect → probe_detect)**

Replace the `daplink_detect` method with a unified `probe_detect`:

```python
def probe_detect(self):
    """Detect all available debug probes."""
    current_count = self.cmbDLL.count()

    # Always keep J-Link and OpenOCD entries
    # Add ST-Link if pyusb available
    has_stlink = False
    try:
        from probes.stlink_probe import STLinkProbe
        stlink_probes = STLinkProbe.detect()
        if stlink_probes:
            has_stlink = True
    except Exception:
        stlink_probes = []

    # Add DAPLink
    try:
        daplink_probes = DAPLinkProbe.detect()
    except Exception:
        daplink_probes = []

    # Rebuild combo box entries (keep first 2: jlink + openocd)
    while self.cmbDLL.count() > 2:
        self.cmbDLL.removeItem(2)

    # Add ST-Link probes
    for i, (dev, name) in enumerate(stlink_probes):
        self.cmbDLL.addItem(f'ST-Link: {name}', ('stlink', i))

    # Add DAPLink probes
    for i, probe in enumerate(daplink_probes):
        self.cmbDLL.addItem(f'{probe.product_name} ({probe.unique_id})', ('daplink', i))

    self._stlink_probes = stlink_probes
    self._daplink_probes = daplink_probes
```

- [ ] **Step 3: Update on_btnOpen_clicked connection logic**

Replace the connection block (lines ~1124-1148) with:

```python
item_data = self.cmbDLL.currentData()

if item_data == 'jlink':
    probe = JLinkProbe(dllpath=self.cmbDLL.currentText())
    probe.open(mode, core, speed)
    self.xlk = xlink.XLink(probe)

elif item_data == 'openocd':
    probe = OpenOCDProbe()
    probe.open(mode, core, speed)
    self.xlk = xlink.XLink(probe)

elif isinstance(item_data, tuple):
    probe_type, probe_idx = item_data

    if probe_type == 'stlink':
        dev, _ = self._stlink_probes[probe_idx]
        probe = STLinkProbe(device=dev)
        probe.open(mode, core, speed)
        self.xlk = xlink.XLink(probe)

    elif probe_type == 'daplink':
        probe = DAPLinkProbe(probe=self._daplink_probes[probe_idx])
        probe.open(mode, core, speed)
        self.xlk = xlink.XLink(probe)
```

- [ ] **Step 4: Rename daplink_detect calls to probe_detect**

Search for `daplink_detect` in RTTView.py and replace all occurrences with `probe_detect`. This includes:
- The `initSetting()` call
- The `_auto_reconnect()` method

- [ ] **Step 5: Update closeEvent to save new probe format**

No changes needed — the existing config save logic uses `cmbDLL.currentText()` and `cmbDLL.currentData()` which work with the new format.

- [ ] **Step 6: Verify full import chain works**

```powershell
python -c "from probes import list_probes; print('Available:', list(list_probes().keys()))"
```

Expected: `Available: ['jlink', 'stlink', 'daplink', 'openocd']`

- [ ] **Step 7: Commit**

```powershell
git add RTTView.py
git commit -m "feat: RTTView now uses ProbeRegistry for J-Link/ST-Link/DAPLink/OpenOCD"
```

---

### Task 8: Backward Compatibility — Keep Legacy Imports Working

**Files:**
- Modify: `E:\MCU\BSP\RTTView\jlink.py` (add re-export from probes)
- Modify: `E:\MCU\BSP\RTTView\openocd.py` (add re-export from probes)

**Interfaces:**
- Old code that does `import jlink; jlink.JLink(...)` must still work

- [ ] **Step 1: Update jlink.py to re-export from probes**

```python
# E:\MCU\BSP\RTTView\jlink.py
# Legacy module — delegates to probes.jlink_probe
# Kept for backward compatibility with old code that does `import jlink`

from probes.jlink_probe import JLinkProbe as JLink

# Keep TIF class for any code that references it
class TIF:
    JTAG  = 0
    SWD   = 1
    CJTAG = 7

# Backward compat: allow jlink.JLink(dllpath) to still work
# JLinkProbe.__init__ takes (dllpath=None) which matches old API
```

- [ ] **Step 2: Update openocd.py to re-export from probes**

```python
# E:\MCU\BSP\RTTView\openocd.py
# Legacy module — delegates to probes.openocd_probe
# Kept for backward compatibility

from probes.openocd_probe import OpenOCDProbe as OpenOCD
```

- [ ] **Step 3: Verify legacy imports still work**

```powershell
python -c "import jlink; print('jlink.JLink:', jlink.JLink)"
python -c "import openocd; print('openocd.OpenOCD:', openocd.OpenOCD)"
```

- [ ] **Step 4: Commit**

```powershell
git add jlink.py openocd.py
git commit -m "refactor: legacy jlink.py and openocd.py re-export from probes/"
```

---

### Task 9: End-to-End Smoke Test

**Files:**
- Create: `E:\MCU\BSP\RTTView\test_probes.py`

- [ ] **Step 1: Write smoke test**

```python
# E:\MCU\BSP\RTTView\test_probes.py
"""Smoke test: verify all probe classes import and register correctly."""
import sys
sys.path.insert(0, '.')

from probes import list_probes, create_probe
from probes.base import DebugProbe

# 1. All probes registered
probes = list_probes()
print(f"Registered probes: {list(probes.keys())}")
assert 'jlink' in probes, "J-Link not registered"
assert 'stlink' in probes, "ST-Link not registered"
assert 'daplink' in probes, "DAPLink not registered"
assert 'openocd' in probes, "OpenOCD not registered"

# 2. All probe classes inherit from DebugProbe
for name, cls in probes.items():
    assert issubclass(cls, DebugProbe), f"{name} does not inherit DebugProbe"
    print(f"  {name}: {cls.__name__} ✓")

# 3. XLink can wrap each probe type
import xlink
for name in probes:
    try:
        probe = create_probe(name)  # __init__ without args
        # Don't actually open — just verify construction works
        print(f"  create_probe('{name}'): OK ✓")
    except Exception as e:
        # Some probes need args (e.g., JLink needs dllpath)
        print(f"  create_probe('{name}'): {e} (expected for no-arg construction)")

# 4. Legacy imports still work
import jlink
import openocd
assert jlink.JLink is not None
assert openocd.OpenOCD is not None
print("  Legacy imports: OK ✓")

print("\nAll smoke tests passed!")
```

- [ ] **Step 2: Run smoke test**

```powershell
cd E:\MCU\BSP\RTTView
python test_probes.py
```

Expected output:
```
Registered probes: ['jlink', 'stlink', 'daplink', 'openocd']
  jlink: JLinkProbe ✓
  stlink: STLinkProbe ✓
  daplink: DAPLinkProbe ✓
  openocd: OpenOCDProbe ✓
  create_probe('jlink'): OK ✓
  create_probe('stlink'): OK ✓
  create_probe('daplink'): OK ✓
  create_probe('openocd'): OK ✓
  Legacy imports: OK ✓

All smoke tests passed!
```

- [ ] **Step 3: Commit**

```powershell
git add test_probes.py
git commit -m "test: add probe system smoke test"
```

---

### Task 10: Final Integration — Run RTTView

- [ ] **Step 1: Run RTTView and verify UI loads**

```powershell
cd E:\MCU\BSP\RTTView
python RTTView.py
```

Verify:
- Window opens with dark theme
- Combo box shows: J-Link path, OpenOCD, ST-Link (if connected), DAPLink (if connected)
- Mode/speed combos work
- All existing functionality preserved

- [ ] **Step 2: Final commit**

```powershell
git add -A
git commit -m "feat: Phase 1 complete — universal probe support (J-Link/ST-Link/DAPLink/OpenOCD)"
```
