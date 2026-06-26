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

    Uses pyusb for direct ST-Link communication -- no OpenOCD server needed.
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

    # -- DAP Register access (via ST-Link commands) ----------------
    def _dap_read(self, addr):
        """Read 32-bit word via DAP."""
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

    # -- Memory ----------------------------------------------------
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

    # -- Registers -------------------------------------------------
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

    # -- CPU Control -----------------------------------------------
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
