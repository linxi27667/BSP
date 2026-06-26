"""OpenOCD debug probe via Tcl RPC over TCP socket."""

import re
import time
import socket

from .base import DebugProbe
from . import register_probe


def _halt_required(func):
    """Decorator: halt target before func, restore run-state after.

    Skipped when probe.auto_halt is False (e.g. oscilloscope live sampling).
    """
    def wrapper(self, *args, **kwargs):
        if not getattr(self, 'auto_halt', True):
            return func(self, *args, **kwargs)
        was_halted = self.halted()
        if not was_halted:
            self.halt()
        try:
            result = func(self, *args, **kwargs)
        finally:
            if not was_halted:
                self.resume()
        return result
    return wrapper


class OpenOCDProbe(DebugProbe):
    """OpenOCD debug probe via Tcl RPC over TCP socket (localhost:6666)."""

    def __init__(self, host='localhost', port=6666):
        self._host = host
        self._port = port
        self._sock = None
        self._mode = 'arm'
        self._core_regs = {}
        self.auto_halt = True  # set False for live monitoring (oscilloscope)

    # -- Lifecycle ------------------------------------------------

    def open(self, mode='arm', core='Cortex-M0', speed=4000):
        self._mode = mode.lower()
        self._sock = socket.create_connection(
            (self._host, self._port), timeout=1
        )
        self._refresh_regs()

    def close(self):
        if self._sock:
            try:
                self._exec('exit')
            finally:
                self._sock.close()
                self._sock = None
            time.sleep(0.01)

    # -- Low-level Tcl RPC ----------------------------------------

    def _exec(self, cmd):
        """Send a Tcl command and return the response string."""
        self._sock.send('{}\x1a'.format(cmd).encode('latin-1'))
        return self._read()

    def _read(self):
        """Read a Tcl RPC response (terminated by \\x1a)."""
        resp = bytes()
        start = time.time()
        while time.time() < start + 2:
            resp += self._sock.recv(4096)
            if resp.endswith(b'\x1a'):
                break
        return resp[:-1].decode('latin-1').strip()

    def _refresh_regs(self):
        """Read register names/indices from OpenOCD."""
        self._core_regs = {}
        for line in self._exec('reg').splitlines():
            match = re.match(r'\((\d+)\)\s+(\w+)\s+\(/(\d+)\)', line)
            if match:
                self._core_regs[match.group(2)] = match.group(1)

    # -- Memory Access --------------------------------------------

    @_halt_required
    def read_mem_U8(self, addr, count):
        return self._read_mem(addr, count, 8)

    @_halt_required
    def read_mem_U16(self, addr, count):
        return self._read_mem(addr, count, 16)

    @_halt_required
    def read_mem_U32(self, addr, count):
        return self._read_mem(addr, count, 32)

    def _read_mem(self, addr, count, width):
        data = []
        index = 0
        while index < count:
            batch = min(128, count - index)
            res = self._exec('read_memory {:#x} {} {}'.format(addr, width, batch))
            if res:
                data.extend([int(x, 16) for x in res.split()])
                addr += 128 * (width // 8)
                index += 128
            else:
                break
        return data

    @_halt_required
    def read_U32(self, addr):
        return self.read_mem_U32(addr, 1)[0]

    @_halt_required
    def write_U8(self, addr, val):
        self._exec('mwb {:#x} {:#x}'.format(addr, val))

    @_halt_required
    def write_U16(self, addr, val):
        self._exec('mwh {:#x} {:#x}'.format(addr, val))

    @_halt_required
    def write_U32(self, addr, val):
        self._exec('mww {:#x} {:#x}'.format(addr, val))

    @_halt_required
    def write_mem_U8(self, addr, data):
        self._write_mem(addr, data, 8)

    @_halt_required
    def write_mem_U32(self, addr, data):
        self._write_mem(addr, data, 32)

    def _write_mem(self, addr, data, width):
        index = 0
        while index < len(data):
            chunk = data[index:index + 128]
            values = ' '.join(['{:#x}'.format(x) for x in chunk])
            self._exec('write_memory {:#x} {} {{{}}}'.format(addr, width, values))
            addr += 128 * (width // 8)
            index += 128

    # -- Register Access ------------------------------------------

    def read_reg(self, reg):
        res = self._exec('reg {}'.format(self._core_regs[reg]))
        return int(res.split(':')[1].strip(), 16)

    def read_regs(self, rlist):
        return {reg: self.read_reg(reg) for reg in rlist}

    def write_reg(self, reg, val):
        self._exec('reg {} {:#x}'.format(self._core_regs[reg], val))

    # -- CPU Control ----------------------------------------------

    def halt(self):
        self._exec('halt 500')

    def go(self):
        self.resume()

    def step(self):
        self._exec('step')

    def reset(self):
        self._exec('reset run')

    def halted(self):
        res = self._exec('targets')
        return 'halted' in res

    # -- Internal helpers -----------------------------------------

    def resume(self):
        self._exec('resume')


register_probe('openocd', OpenOCDProbe)
