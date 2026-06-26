"""Post-mortem crash analyzer for ARM Cortex-M targets."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QTextEdit, QLabel, QFileDialog, QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont

import bisect
import struct

# -- Cortex-M fault register addresses ----------------------------------------
_CFSR  = 0xE000ED28
_HFSR  = 0xE000ED2C
_MMFAR = 0xE000ED34
_BFAR  = 0xE000ED38
_DFSR  = 0xE000ED30
_AFSR  = 0xE000ED3C
_DHCSR = 0xE000EDF0

# Flash region for call-stack scanning (STM32 default)
_FLASH_BASE = 0x08000000
_FLASH_END  = 0x08200000

# -- Color constants (dark theme) ---------------------------------------------
_COLOR_HEADER = '#569CD6'
_COLOR_REG    = '#DCDCAA'
_COLOR_VALUE  = '#B5CEA8'
_COLOR_ERROR  = '#FF6B6B'
_COLOR_DESC   = '#6A9955'
_COLOR_WARN   = '#CE9178'
_COLOR_DIM    = '#808080'


class CrashAnalyzer(QWidget):
    """Widget that captures and decodes crash information from ARM Cortex-M."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._elf_symbols: dict[int, str] = {}  # addr -> symbol name
        self._sorted_addrs: list[int] = []  # sorted for bisect lookup
        self._init_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Toolbar ----------------------------------------------------
        toolbar = QHBoxLayout()

        self.btn_capture = QPushButton("Capture Crash Info")
        self.btn_capture.setFixedWidth(160)
        self.btn_capture.clicked.connect(self._on_capture)
        self.btn_capture.setEnabled(False)
        toolbar.addWidget(self.btn_capture)

        self.chk_auto = QCheckBox("Auto-capture on crash")
        self.chk_auto.setChecked(False)
        toolbar.addWidget(self.chk_auto)

        toolbar.addStretch()

        self.btn_load_elf = QPushButton("Load ELF")
        self.btn_load_elf.setFixedWidth(100)
        self.btn_load_elf.clicked.connect(self._on_load_elf)
        toolbar.addWidget(self.btn_load_elf)

        layout.addLayout(toolbar)

        # -- Report display ---------------------------------------------
        report_group = QGroupBox("Crash Report")
        report_layout = QVBoxLayout(report_group)
        report_layout.setContentsMargins(4, 4, 4, 4)

        self.txt_report = QTextEdit()
        self.txt_report.setReadOnly(True)
        self.txt_report.setFont(QFont("Consolas", 11))
        self.txt_report.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        report_layout.addWidget(self.txt_report)
        layout.addWidget(report_group)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe
        self.btn_capture.setEnabled(probe is not None)

    def load_elf(self, path: str):
        """Load ELF file and extract symbol table for address resolution."""
        self._elf_symbols.clear()
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self._parse_elf_symbols(data)
            self._log_info(f"Loaded {len(self._elf_symbols)} symbols from {path}")
        except Exception as e:
            self._log_error(f"Failed to load ELF: {e}")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_capture(self):
        """Capture crash info from the MCU."""
        if not self._probe:
            self._log_error("No probe connected.")
            return
        self._capture_crash()

    @pyqtSlot()
    def _on_load_elf(self):
        """Open file dialog to select an ELF file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load ELF File", "", "ELF Files (*.elf *.axf);;All Files (*)"
        )
        if path:
            self.load_elf(path)

    # ------------------------------------------------------------------
    # Crash capture
    # ------------------------------------------------------------------
    def _capture_crash(self):
        """Read registers, fault status, and build crash report."""
        report: list[str] = []
        report.append("=" * 60)
        report.append("  CRASH ANALYSIS REPORT")
        report.append("=" * 60)
        report.append("")

        # -- Core registers ---------------------------------------------
        report.append("--- Core Registers ---")
        arm_reg_names = [
            'R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7',
            'R8', 'R9', 'R10', 'R11', 'R12', 'SP', 'LR', 'PC', 'xPSR',
        ]
        reg_values: dict[str, int] = {}
        for name in arm_reg_names:
            try:
                val = self._probe.read_reg(name)
                reg_values[name] = val
                sym = self._resolve_symbol(val)
                sym_str = f"  ({sym})" if sym else ""
                report.append(f"  {name:>5s} = 0x{val:08X}{sym_str}")
            except Exception as e:
                report.append(f"  {name:>5s} = <read error: {e}>")
        report.append("")

        # -- xPSR decode ------------------------------------------------
        if 'xPSR' in reg_values:
            xpsr = reg_values['xPSR']
            report.append("--- xPSR Decode ---")
            exc_num = xpsr & 0x1FF
            report.append(f"  Exception Number: {exc_num} ({_exception_name(exc_num)})")
            report.append(f"  Thumb bit [24]  : {(xpsr >> 24) & 1}")
            report.append(f"  N/Z/C/V flags   : {(xpsr>>31)&1}/{(xpsr>>30)&1}/{(xpsr>>29)&1}/{(xpsr>>28)&1}")
            report.append("")

        # -- Fault registers --------------------------------------------
        report.append("--- Fault Registers ---")
        fault_regs = [
            ('CFSR',  _CFSR),
            ('HFSR',  _HFSR),
            ('MMFAR', _MMFAR),
            ('BFAR',  _BFAR),
            ('AFSR',  _AFSR),
            ('DHCSR', _DHCSR),
        ]
        fault_values: dict[str, int] = {}
        for name, addr in fault_regs:
            try:
                val = self._probe.read_U32(addr)
                fault_values[name] = val
                report.append(f"  {name:>5s} ({addr:#010x}) = 0x{val:08X}")
            except Exception as e:
                report.append(f"  {name:>5s} ({addr:#010x}) = <read error: {e}>")
        report.append("")

        # -- CFSR decode ------------------------------------------------
        if 'CFSR' in fault_values:
            cfsr = fault_values['CFSR']
            report.append("--- CFSR Decode ---")
            self._decode_cfsr(cfsr, report)
            report.append("")

        # -- HFSR decode ------------------------------------------------
        if 'HFSR' in fault_values:
            hfsr = fault_values['HFSR']
            report.append("--- HFSR Decode ---")
            self._decode_hfsr(hfsr, report)
            report.append("")

        # -- MMFAR / BFAR detail ----------------------------------------
        if 'CFSR' in fault_values:
            cfsr = fault_values['CFSR']
            if cfsr & (1 << 7):  # MMARVALID
                mmfar = fault_values.get('MMFAR', 0)
                sym = self._resolve_symbol(mmfar)
                sym_str = f" ({sym})" if sym else ""
                report.append(f"  MMFAR (fault address) = 0x{mmfar:08X}{sym_str}")
            if cfsr & (1 << 15):  # BFARVALID
                bfar = fault_values.get('BFAR', 0)
                sym = self._resolve_symbol(bfar)
                sym_str = f" ({sym})" if sym else ""
                report.append(f"  BFAR  (fault address) = 0x{bfar:08X}{sym_str}")
            report.append("")

        # -- Call stack walk --------------------------------------------
        report.append("--- Call Stack (heuristic) ---")
        self._walk_stack(reg_values, report)
        report.append("")

        report.append("=" * 60)

        self.txt_report.setText("\n".join(report))

    # ------------------------------------------------------------------
    # CFSR decode
    # ------------------------------------------------------------------
    def _decode_cfsr(self, cfsr: int, report: list[str]):
        """Decode Configurable Fault Status Register."""
        # MemManage faults (bits 0-7)
        mm_flags = []
        if cfsr & (1 << 0):  mm_flags.append("IACCVIOL")
        if cfsr & (1 << 1):  mm_flags.append("DACCVIOL")
        if cfsr & (1 << 3):  mm_flags.append("MUNSTKERR")
        if cfsr & (1 << 4):  mm_flags.append("MSTKERR")
        if cfsr & (1 << 5):  mm_flags.append("MLSPERR")
        if cfsr & (1 << 7):  mm_flags.append("MMARVALID")
        report.append(f"  MemManage: {', '.join(mm_flags) if mm_flags else 'None'}")

        # BusFault (bits 8-15)
        bf_flags = []
        if cfsr & (1 << 8):  bf_flags.append("IBUSERR")
        if cfsr & (1 << 9):  bf_flags.append("PRECISERR")
        if cfsr & (1 << 10): bf_flags.append("IMPRECISERR")
        if cfsr & (1 << 11): bf_flags.append("UNSTKERR")
        if cfsr & (1 << 12): bf_flags.append("STKERR")
        if cfsr & (1 << 13): bf_flags.append("LSPERR")
        if cfsr & (1 << 15): bf_flags.append("BFARVALID")
        report.append(f"  BusFault : {', '.join(bf_flags) if bf_flags else 'None'}")

        # UsageFault (bits 16-25)
        uf_flags = []
        if cfsr & (1 << 16): uf_flags.append("UNDEFINST")
        if cfsr & (1 << 17): uf_flags.append("INVSTATE")
        if cfsr & (1 << 18): uf_flags.append("INVPC")
        if cfsr & (1 << 19): uf_flags.append("NOCP")
        if cfsr & (1 << 24): uf_flags.append("UNALIGNED")
        if cfsr & (1 << 25): uf_flags.append("DIVBYZERO")
        report.append(f"  UsageFault: {', '.join(uf_flags) if uf_flags else 'None'}")

    # ------------------------------------------------------------------
    # HFSR decode
    # ------------------------------------------------------------------
    def _decode_hfsr(self, hfsr: int, report: list[str]):
        """Decode HardFault Status Register."""
        flags = []
        if hfsr & (1 << 1):  flags.append("VECTTBL (vector table read fault)")
        if hfsr & (1 << 30): flags.append("FORCED  (escalated from configurable fault)")
        if hfsr & (1 << 31): flags.append("DEBUGEVT (debug event)")
        report.append(f"  {' | '.join(flags) if flags else 'No flags set'}")

    # ------------------------------------------------------------------
    # Stack walk
    # ------------------------------------------------------------------
    def _walk_stack(self, reg_values: dict[str, int], report: list[str]):
        """Heuristic stack walk: scan stack for flash addresses."""
        if not self._probe:
            report.append("  <no probe>")
            return

        sp = reg_values.get('SP', 0)
        if sp == 0:
            report.append("  <SP not available>")
            return

        # Read 1KB of stack
        stack_size = 1024
        try:
            stack_data = self._probe.read_mem_U8(sp, stack_size)
        except Exception as e:
            report.append(f"  <stack read error: {e}>")
            return

        if not stack_data:
            report.append("  <no stack data>")
            return

        # Look for values that look like flash addresses (return addresses)
        found: list[tuple[int, int]] = []  # (stack_offset, address)
        for i in range(0, len(stack_data) - 3, 4):
            val = struct.unpack_from('<I', stack_data, i)[0]
            # Thumb addresses have bit 0 set
            if val & 1:
                addr = val & ~1
            else:
                addr = val
            if _FLASH_BASE <= addr < _FLASH_END:
                found.append((i, val))

        if not found:
            report.append("  No flash addresses found in stack.")
            return

        # Show up to 16 entries
        for offset, val in found[:16]:
            addr = val & ~1
            sym = self._resolve_symbol(addr)
            sym_str = f" ({sym})" if sym else ""
            report.append(f"  SP+0x{offset:04X}: 0x{val:08X}{sym_str}")

    # ------------------------------------------------------------------
    # ELF symbol extraction
    # ------------------------------------------------------------------
    def _parse_elf_symbols(self, data: bytes):
        """Parse ELF symbol table for address->name mapping."""
        if len(data) < 16 or data[:4] != b'\x7fELF':
            self._log_error("Not a valid ELF file.")
            return

        is_64 = data[4] == 2
        is_le = data[5] == 1  # little-endian

        if is_64:
            self._log_error("64-bit ELF not supported (ARM Cortex-M only).")
            return

        if not is_le:
            self._log_error("Big-endian ELF not supported.")
            return

        # ELF32 header parsing
        e_shoff = struct.unpack_from('<I', data, 32)[0]
        e_shentsize = struct.unpack_from('<H', data, 46)[0]
        e_shnum = struct.unpack_from('<H', data, 48)[0]
        e_shstrndx = struct.unpack_from('<H', data, 50)[0]

        # Read section headers
        def read_shdr(idx):
            off = e_shoff + idx * e_shentsize
            return struct.unpack_from('<IIIIIIIIII', data, off)

        # Get section name string table
        if e_shstrndx >= e_shnum:
            return
        shstr_shdr = read_shdr(e_shstrndx)
        shstr_off = shstr_shdr[4]
        shstr_size = shstr_shdr[5]
        shstr_data = data[shstr_off:shstr_off + shstr_size]

        def section_name(idx):
            shdr = read_shdr(idx)
            name_off = shdr[0]
            end = shstr_data.find(b'\x00', name_off)
            if end == -1:
                return ''
            return shstr_data[name_off:end].decode('ascii', errors='replace')

        # Find .symtab and .strtab
        symtab_idx = -1
        strtab_idx = -1
        for i in range(e_shnum):
            name = section_name(i)
            if name == '.symtab':
                symtab_idx = i
            elif name == '.strtab':
                strtab_idx = i

        if symtab_idx < 0 or strtab_idx < 0:
            self._log_info("No symbol table found in ELF.")
            return

        symtab_shdr = read_shdr(symtab_idx)
        strtab_shdr = read_shdr(strtab_idx)

        sym_off = symtab_shdr[4]
        sym_size = symtab_shdr[5]
        sym_entsize = symtab_shdr[9] if symtab_shdr[9] else 16

        str_off = strtab_shdr[4]
        str_size = strtab_shdr[5]
        str_data = data[str_off:str_off + str_size]

        # Parse symbols
        count = sym_size // sym_entsize
        for i in range(count):
            ent = struct.unpack_from('<IIIIBBH', data, sym_off + i * sym_entsize)
            st_name, st_value, st_size, st_info, st_other, st_shndx = ent
            st_type = st_info & 0xF

            # Only function symbols (STT_FUNC = 2) and global/local with value
            if st_type == 2 and st_value != 0 and st_shndx != 0:
                end = str_data.find(b'\x00', st_name)
                if end == -1:
                    continue
                sym_name = str_data[st_name:end].decode('ascii', errors='replace')
                if sym_name:
                    self._elf_symbols[st_value] = sym_name

        # Pre-sort addresses for bisect-based lookup
        self._sorted_addrs = sorted(self._elf_symbols.keys())

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------
    def _resolve_symbol(self, addr: int) -> str:
        """Resolve an address to the nearest symbol name (O(log N) via bisect)."""
        if not self._elf_symbols:
            return ""
        if addr in self._elf_symbols:
            return self._elf_symbols[addr]
        # Find the nearest symbol <= addr
        idx = bisect.bisect_right(self._sorted_addrs, addr) - 1
        if idx < 0:
            return ""
        sym_addr = self._sorted_addrs[idx]
        if addr - sym_addr < 0x1000:
            return f"{self._elf_symbols[sym_addr]}+0x{addr - sym_addr:X}"
        return ""

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def _log_info(self, msg: str):
        self.txt_report.append(f"[INFO] {msg}")

    def _log_error(self, msg: str):
        self.txt_report.append(
            f'<span style="color:{_COLOR_ERROR};">[ERROR] {msg}</span>'
        )


# -- Module-level helpers -----------------------------------------------------

def _exception_name(num: int) -> str:
    """Map ARM Cortex-M exception number to name."""
    names = {
        0: 'Thread mode', 1: 'Reset', 2: 'NMI', 3: 'HardFault',
        4: 'MemManage', 5: 'BusFault', 6: 'UsageFault', 7: 'SecureFault',
        11: 'SVCall', 12: 'Debug Monitor', 14: 'PendSV', 15: 'SysTick',
    }
    if 16 <= num <= 255:
        return f"IRQ {num - 16}"
    return names.get(num, 'Unknown')
