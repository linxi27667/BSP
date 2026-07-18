"""ST-Link probe via STM32 ST-LINK Utility CLI (Windows).

Used when pyusb/libusb cannot open the device (Access denied under ST drivers).
Requires ST-LINK_CLI.exe from STM32 ST-LINK Utility.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .base import DebugProbe
from . import register_probe

# Serialize all CLI invocations — ST-LINK_CLI is not multi-session safe
_CLI_LOCK = threading.RLock()

_DEFAULT_CLI_CANDIDATES = [
    r"C:\Program Files (x86)\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
    r"C:\Program Files\STMicroelectronics\STM32 ST-LINK Utility\ST-LINK Utility\ST-LINK_CLI.exe",
    r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
]


def find_stlink_cli() -> str | None:
    env = os.environ.get("STLINK_CLI") or os.environ.get("ST_LINK_CLI")
    if env and os.path.isfile(env):
        return env
    which = shutil.which("ST-LINK_CLI") or shutil.which("ST-LINK_CLI.exe")
    if which:
        return which
    for p in _DEFAULT_CLI_CANDIDATES:
        if os.path.isfile(p) and p.lower().endswith("st-link_cli.exe"):
            return p
    return None


class STLinkCLIProbe(DebugProbe):
    """DebugProbe implemented by shelling out to ST-LINK_CLI.exe."""

    def __init__(self, cli_path=None, sn=None):
        self._cli = cli_path or find_stlink_cli()
        self._sn = sn
        self._mode = "arm"
        self._core_regs = {}
        self._connected = False
        self._info = {}
        # Hint for web layer: spawn-per-call backend is slow
        self.slow_mem = True
        # With batched rtt_poll, short idle gap is fine
        self.rtt_poll_ms = 40
        # Cache ring meta between polls (pBuffer/Size rarely change)
        self._rtt_cache = {}

    @staticmethod
    def available():
        return find_stlink_cli() is not None

    def open(self, mode="arm", core="Cortex-M0", speed=4000):
        if not self._cli or not os.path.isfile(self._cli):
            raise Exception(
                "ST-LINK_CLI.exe not found. Install STM32 ST-LINK Utility "
                "or set STLINK_CLI env to the full path."
            )
        self._mode = (mode or "arm").lower()
        self._speed = int(speed)
        self._refresh_regs()
        self._rtt_cache = {}
        # One CLI: connect + read CPUID + Run (stdin closed so -Run exits)
        out = self._run(
            self._cargs(False) + ["-r32", "0xE000ED00", "1", "-Run"],
            check=False,
            timeout=15,
        )
        if "Connected via SWD" not in out and "Device ID" not in out:
            raise Exception(f"ST-LINK_CLI cannot connect:\n{out[-500:]}")
        if "No ST-LINK" in out or "No st-link" in out.lower():
            raise Exception("ST-LINK_CLI: no probe connected")
        self._connected = True
        self._info = self._parse_connect_info(out)

    def _cargs(self, hotplug=True):
        """Build -c ... tokens. HOTPLUG = attach without halt (for mem/RTT)."""
        args = ["-c"]
        if self._sn:
            args.append(f"SN={self._sn}")
        args.append("SWD")
        if hotplug:
            args.append("HOTPLUG")
        return args

    def _connect_args(self, hotplug=False):
        # Back-compat for any callers expecting a single string
        parts = self._cargs(hotplug)[1:]
        return " ".join(parts)

    def _run(self, args, check=True, timeout=20):
        # ST-LINK_CLI v3: plain args only. Keep timeout tight — hung CLI blocks UI.
        # Global lock: concurrent -c SWD sessions steal the probe from each other.
        # stdin=DEVNULL: -Run prints "run application to exit" and waits for a key.
        cmd = [self._cli] + list(args)
        # CREATE_NO_WINDOW: avoid console flash + slight spawn cost on Windows
        popen_kw = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if os.name == "nt":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with _CLI_LOCK:
            try:
                p = subprocess.Popen(cmd, **popen_kw)
            except FileNotFoundError as e:
                raise Exception(f"ST-LINK_CLI not executable: {e}") from e
            try:
                stdout, stderr = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
                try:
                    stdout, stderr = p.communicate(timeout=3)
                except Exception:
                    stdout, stderr = "", ""
                raise Exception(f"ST-LINK_CLI timeout: {args}") from None

            out = (stdout or "") + (stderr or "")
            if check and re.search(r"No ST-LINK|Can not connect|Cannot connect to the target", out, re.I):
                raise Exception(f"ST-LINK_CLI failed ({p.returncode}): {out[-500:]}")
            return out

    def _parse_connect_info(self, text):
        info = {}
        m = re.search(r"Device ID:\s*(0x[0-9A-Fa-f]+)", text)
        if m:
            info["device_id"] = m.group(1)
        m = re.search(r"Device family:\s*(.+)", text)
        if m:
            info["family"] = m.group(1).strip()
        m = re.search(r"Target voltage\s*=\s*([0-9.]+)", text)
        if m:
            try:
                info["voltage_mv"] = int(float(m.group(1)) * 1000)
            except Exception:
                pass
        m = re.search(r"ST-LINK SN:\s*(\S+)", text)
        if m:
            info["sn"] = m.group(1)
        m = re.search(r"ST-LINK Firmware version:\s*(\S+)", text)
        if m:
            info["fw"] = m.group(1)
        return info

    def close(self):
        self._connected = False

    def _refresh_regs(self):
        regs = [
            "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
            "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc",
            "xpsr", "msp", "psp",
        ]
        for i, name in enumerate(regs):
            self._core_regs[name] = i

    # ---- memory ----
    def _parse_r8(self, text):
        data = []
        for line in text.splitlines():
            m = re.search(r"0x[0-9A-Fa-f]+\s*:\s*(.*)", line)
            if not m:
                continue
            for tok in m.group(1).split():
                if re.fullmatch(r"[0-9A-Fa-f]{2}", tok):
                    data.append(int(tok, 16))
        return data

    def _parse_r32(self, text):
        # CLI prints multiple words per line: "0x2000092C : 47474553  52205245  ..."
        words = []
        for line in text.splitlines():
            m = re.search(r"0x[0-9A-Fa-f]+\s*:\s*(.*)", line)
            if not m:
                continue
            for tok in m.group(1).split():
                if re.fullmatch(r"[0-9A-Fa-f]{1,8}", tok):
                    words.append(int(tok, 16))
        return words

    def read_mem_U32(self, addr, count):
        """Read 32-bit words. Prefer -r8 bulk (complete); never zero-pad short -r32."""
        count = int(count)
        addr = int(addr) & 0xFFFFFFFF
        if count <= 0:
            return []
        # Fast path: one -r8 for the whole span (CLI returns full rows)
        raw = self.read_mem_U8(addr, count * 4)
        if len(raw) < count * 4:
            raise RuntimeError(f"ST-LINK_CLI read_mem_U32 short @ 0x{addr:08X}")
        return list(struct.unpack("<" + "I" * count, bytes(raw)))

    def read_U32(self, addr):
        words = self.read_mem_U32(addr, 1)
        return words[0]

    def read_mem_U8(self, addr, count):
        """Byte read via -r8 HOTPLUG. Chunk large requests; never invent zeros."""
        count = int(count)
        addr = int(addr) & 0xFFFFFFFF
        if count <= 0:
            return []
        out = []
        # Prefer one CLI call when possible — spawn cost >> transfer size
        chunk = 4096 if count >= 512 else max(count, 64)
        chunk = min(chunk, 4096)
        off = 0
        while off < count:
            n = min(chunk, count - off)
            a = (addr + off) & 0xFFFFFFFF
            text = self._run(
                self._cargs(True) + ["-r8", f"0x{a:08X}", str(n)],
                check=False,
                timeout=40,
            )
            data = self._parse_r8(text)
            if len(data) < n:
                if not data:
                    # last resort: single -r32 word for aligned addr
                    if (a & 3) == 0 and n >= 4:
                        t2 = self._run(
                            self._cargs(True) + ["-r32", f"0x{a:08X}", "1"],
                            check=False,
                            timeout=20,
                        )
                        ws = self._parse_r32(t2)
                        if not ws:
                            raise RuntimeError(f"ST-LINK_CLI read_mem_U8 failed @ 0x{a:08X}")
                        data = list(struct.pack("<I", ws[0] & 0xFFFFFFFF))
                    else:
                        raise RuntimeError(f"ST-LINK_CLI read_mem_U8 failed @ 0x{a:08X}")
                # take partial, continue from there
                out.extend(data)
                off += len(data)
                continue
            out.extend(data[:n])
            off += n
        return out

    def read_mem_U16(self, addr, count):
        raw = self.read_mem_U8(addr, int(count) * 2)
        return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]

    def write_U8(self, addr, val):
        self._run(
            self._cargs(True) + ["-w8", f"0x{int(addr):08X}", f"0x{int(val) & 0xFF:02X}"],
            check=False,
        )

    def write_U16(self, addr, val):
        v = int(val) & 0xFFFF
        self.write_U8(addr, v & 0xFF)
        self.write_U8(addr + 1, (v >> 8) & 0xFF)

    def write_U32(self, addr, val):
        self._run(
            self._cargs(True) + ["-w32", f"0x{int(addr):08X}", f"0x{int(val) & 0xFFFFFFFF:08X}"],
            check=False,
        )

    def rtt_poll(self, a_up_addr, max_chunk=1024):
        """One RTT up-buffer poll with minimal CLI spawns.

        Typical path = 2 process launches:
          1) read ring descriptor (24B)
          2) read payload + write new RdOff (chained; wrap = 2×-r8)
        Idle (no data) = 1 launch only.
        Returns bytes (may be empty).
        """
        a_up = int(a_up_addr) & 0xFFFFFFFF
        max_chunk = max(64, min(int(max_chunk), 2048))
        # 1) descriptor
        text = self._run(
            self._cargs(True) + ["-r8", f"0x{a_up:08X}", "24"],
            check=False,
            timeout=15,
        )
        desc = self._parse_r8(text)
        if len(desc) < 24:
            raise RuntimeError(f"RTT desc short @ 0x{a_up:08X}")
        p_buffer = struct.unpack_from("<I", bytes(desc), 4)[0]
        size = struct.unpack_from("<I", bytes(desc), 8)[0]
        wr = struct.unpack_from("<I", bytes(desc), 12)[0]
        rd = struct.unpack_from("<I", bytes(desc), 16)[0]
        flags = struct.unpack_from("<I", bytes(desc), 20)[0]
        if not (0 < size <= 1024 * 1024 and wr < size and rd < size and p_buffer and flags <= 2):
            raise RuntimeError("RTT ring buffer invalid")
        self._rtt_cache[a_up] = (p_buffer, size)
        if rd == wr:
            return b""

        # Build contiguous segments (handle wrap in ONE CLI session)
        if rd < wr:
            segs = [(p_buffer + rd, wr - rd)]
        else:
            segs = [(p_buffer + rd, size - rd)]
            if wr:
                segs.append((p_buffer, wr))

        # Cap total to max_chunk, keep segment order
        remain = max_chunk
        use = []
        total = 0
        for addr, n in segs:
            if remain <= 0:
                break
            take = min(n, remain)
            if take > 0:
                use.append((addr & 0xFFFFFFFF, take))
                total += take
                remain -= take
        if total <= 0:
            return b""
        new_rd = (rd + total) % size

        args = self._cargs(True)
        for addr, n in use:
            args += ["-r8", f"0x{addr:08X}", str(n)]
        args += ["-w32", f"0x{(a_up + 16) & 0xFFFFFFFF:08X}", f"0x{new_rd:08X}"]
        text2 = self._run(args, check=False, timeout=25)
        payload = self._parse_r8(text2)
        if len(payload) < total:
            if not payload:
                return b""
            got = len(payload)
            new_rd = (rd + got) % size
            try:
                self.write_U32(a_up + 16, new_rd)
            except Exception:
                pass
            return bytes(payload[:got])
        return bytes(payload[:total])

    def write_mem_U8(self, addr, data):
        # write file then... CLI has no bulk write of arbitrary bytes easily;
        # use repeated -w8 (slow) or temp bin + -P for large blocks
        data = list(data)
        if len(data) >= 64:
            path = None
            try:
                fd, path = tempfile.mkstemp(suffix=".bin")
                os.close(fd)
                with open(path, "wb") as f:
                    f.write(bytes(b & 0xFF for b in data))
                out = self._run(
                    self._cargs(True) + ["-P", path, f"0x{int(addr):08X}"],
                    check=False,
                )
                if "Error" in out and "complete" not in out.lower():
                    for i, b in enumerate(data):
                        self.write_U8(addr + i, b)
            finally:
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception:
                        pass
        else:
            for i, b in enumerate(data):
                self.write_U8(addr + i, b)

    def write_mem_U32(self, addr, data):
        for i, w in enumerate(data):
            self.write_U32(addr + i * 4, w)

    # ---- registers ----
    def read_reg(self, reg):
        name = reg.lower()
        regs = self.read_regs([name])
        if name not in regs:
            raise ValueError(f"Unknown register: {reg}")
        return regs[name]

    def read_regs(self, rlist):
        # CoreReg needs halt-friendly connect (no HOTPLUG)
        text = self._run(self._cargs(False) + ["-CoreReg"], check=False)
        table = {}
        for line in text.splitlines():
            m = re.search(
                r"\b(R1[0-5]|R[0-9]|MSP|PSP|PSR|XPSR|PC|LR|SP|xPSR|CONTROL)\b\s*[=:]\s*(0x)?([0-9A-Fa-f]+)",
                line,
                re.I,
            )
            if m:
                key = m.group(1).lower()
                if key == "psr":
                    key = "xpsr"
                table[key] = int(m.group(3), 16)
        if "sp" not in table and "msp" in table:
            table["sp"] = table["msp"]
        if "pc" in table:
            table["r15"] = table["pc"]
        if "lr" in table:
            table["r14"] = table["lr"]
        if "sp" in table:
            table["r13"] = table["sp"]
        out = {}
        for reg in rlist:
            k = reg.lower()
            if k in table:
                out[reg] = table[k]
            elif k in ("r13",) and "sp" in table:
                out[reg] = table["sp"]
            elif k in ("r14",) and "lr" in table:
                out[reg] = table["lr"]
            elif k in ("r15",) and "pc" in table:
                out[reg] = table["pc"]
            else:
                out[reg] = table.get(k, 0)
        return out

    def write_reg(self, reg, val):
        raise NotImplementedError(
            "ST-LINK_CLI backend cannot write core registers reliably; use J-Link or pyusb ST-Link"
        )

    # ---- CPU control ----
    def halt(self):
        self._run(self._cargs(False) + ["-Halt"], check=False, timeout=15)

    def go(self):
        # stdin=DEVNULL so -Run does not wait for a keypress
        try:
            self._run(self._cargs(False) + ["-Run"], check=False, timeout=10)
        except Exception:
            pass

    def step(self):
        self._run(self._cargs(False) + ["-Step"], check=False, timeout=15)

    def reset(self):
        # Single CLI: reset + run (stdin closed → -Run returns). Fallback HardRst.
        self._rtt_cache = {}
        try:
            self._run(self._cargs(False) + ["-Rst", "-Run"], check=False, timeout=12)
            return
        except Exception:
            pass
        try:
            self._run(self._cargs(False) + ["-HardRst", "-Run"], check=False, timeout=12)
        except Exception:
            try:
                self._run(self._cargs(False) + ["-HardRst"], check=False, timeout=10)
                self.go()
            except Exception:
                pass

    def halted(self):
        # Prefer DHCSR via HOTPLUG so we do not halt a running target just to query
        try:
            dhcsr = self.read_U32(0xE000EDF0)
            return bool(dhcsr & (1 << 17))
        except Exception:
            pass
        text = self._run(self._cargs(True) + ["-SCore"], check=False)
        if re.search(r"halted|Halt", text, re.I):
            return True
        if re.search(r"running|Run", text, re.I):
            return False
        return False

    def flash_file(self, path, addr=0):
        path = str(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        args = self._cargs(False) + ["-P", path]
        if addr:
            args.append(f"0x{int(addr):08X}")
        args += ["-V", "-Rst", "-Run"]
        out = self._run(args, check=False, timeout=300)
        if re.search(r"Error|Failed|failed", out) and not re.search(
            r"Verification\s+OK|Download verified|successfully", out, re.I
        ):
            raise RuntimeError(f"ST-LINK_CLI flash failed:\n{out[-800:]}")
        return out

    def probe_info(self):
        return {
            "product_name": "ST-Link (CLI)",
            "serial_number": self._info.get("sn"),
            "firmware_version": self._info.get("fw"),
            "voltage_mv": self._info.get("voltage_mv"),
            "device_id": self._info.get("device_id"),
            "family": self._info.get("family"),
            "backend": "ST-LINK_CLI",
            "cli": self._cli,
        }

    def target_voltage(self):
        return self._info.get("voltage_mv")


# Do not register as default 'stlink' — STLinkProbe will delegate.
