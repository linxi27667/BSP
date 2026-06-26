"""Flash programmer widget for STM32 / ARM Cortex-M targets."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QCheckBox, QLabel, QGroupBox, QProgressBar,
    QComboBox, QFileDialog,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont

import struct
import os

# -- Color constants (dark theme) ---------------------------------------------
_COLOR_HEADER = '#569CD6'
_COLOR_VALUE  = '#B5CEA8'
_COLOR_ERROR  = '#FF6B6B'
_COLOR_OK     = '#4EC9B0'
_COLOR_DIM    = '#808080'


class FlashProgrammer(QWidget):
    """Widget for erasing, flashing, and verifying MCU firmware."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._init_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- File selection ---------------------------------------------
        file_group = QGroupBox("Firmware File")
        file_layout = QHBoxLayout(file_group)
        file_layout.setContentsMargins(4, 4, 4, 4)

        file_layout.addWidget(QLabel("File:"))
        self.txt_file = QLineEdit()
        self.txt_file.setPlaceholderText("Select firmware file...")
        self.txt_file.setFont(QFont("Consolas", 11))
        self.txt_file.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; "
            "border: 1px solid #3C3C3C; padding: 2px;"
        )
        file_layout.addWidget(self.txt_file)

        self.btn_browse = QPushButton("Browse")
        self.btn_browse.setFixedWidth(80)
        self.btn_browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self.btn_browse)

        layout.addWidget(file_group)

        # -- Address and format -----------------------------------------
        addr_row = QHBoxLayout()

        addr_row.addWidget(QLabel("Base Address:"))
        self.txt_addr = QLineEdit("0x08000000")
        self.txt_addr.setFixedWidth(120)
        self.txt_addr.setFont(QFont("Consolas", 11))
        self.txt_addr.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; "
            "border: 1px solid #3C3C3C; padding: 2px;"
        )
        addr_row.addWidget(self.txt_addr)

        addr_row.addWidget(QLabel("Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems(["Auto", "BIN", "HEX", "ELF"])
        self.combo_format.setFixedWidth(80)
        addr_row.addWidget(self.combo_format)

        addr_row.addStretch()
        layout.addLayout(addr_row)

        # -- Operation buttons ------------------------------------------
        btn_row = QHBoxLayout()

        self.btn_erase = QPushButton("Reset MCU")
        self.btn_erase.setFixedWidth(100)
        self.btn_erase.clicked.connect(self._on_erase)
        self.btn_erase.setEnabled(False)
        btn_row.addWidget(self.btn_erase)

        self.btn_flash = QPushButton("Flash")
        self.btn_flash.setFixedWidth(100)
        self.btn_flash.clicked.connect(self._on_flash)
        self.btn_flash.setEnabled(False)
        btn_row.addWidget(self.btn_flash)

        self.btn_verify = QPushButton("Verify")
        self.btn_verify.setFixedWidth(100)
        self.btn_verify.clicked.connect(self._on_verify)
        self.btn_verify.setEnabled(False)
        btn_row.addWidget(self.btn_verify)

        self.chk_reset = QCheckBox("Reset after flash")
        self.chk_reset.setChecked(True)
        btn_row.addWidget(self.chk_reset)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # -- Progress bar -----------------------------------------------
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: #1E1E1E;
                border: 1px solid #3C3C3C;
                text-align: center;
                color: #D4D4D4;
            }
            QProgressBar::chunk {
                background-color: #0E7A0D;
            }
        """)
        layout.addWidget(self.progress)

        # -- Log --------------------------------------------------------
        log_group = QGroupBox("Operation Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(4, 4, 4, 4)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 11))
        self.txt_log.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        log_layout.addWidget(self.txt_log)
        layout.addWidget(log_group)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe
        enabled = probe is not None
        self.btn_erase.setEnabled(enabled)
        self.btn_flash.setEnabled(enabled)
        self.btn_verify.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_browse(self):
        """Open file dialog to select firmware file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Firmware File", "",
            "Firmware Files (*.bin *.hex *.elf *.axf);;All Files (*)"
        )
        if path:
            self.txt_file.setText(path)
            # Auto-detect format
            ext = os.path.splitext(path)[1].lower()
            fmt_map = {'.bin': 'BIN', '.hex': 'HEX', '.elf': 'ELF', '.axf': 'ELF'}
            if ext in fmt_map:
                idx = self.combo_format.findText(fmt_map[ext])
                if idx >= 0:
                    self.combo_format.setCurrentIndex(idx)

    @pyqtSlot()
    def _on_erase(self):
        """Reset MCU via AIRCR SYSRESETREQ (Cortex-M standard)."""
        if not self._probe:
            self._log("No probe connected.", error=True)
            return
        self._log("Resetting MCU via SYSRESETREQ...")
        try:
            # AIRCR: Application Interrupt and Reset Control Register
            # VECTKEY=0x05FA, SYSRESETREQ=bit 2
            self._probe.write_U32(0xE000ED0C, 0x05FA0004)
            self._log("MCU reset complete.", ok=True)
        except Exception as e:
            self._log(f"Reset failed: {e}", error=True)

    @pyqtSlot()
    def _on_flash(self):
        """Flash firmware to MCU."""
        if not self._probe:
            self._log("No probe connected.", error=True)
            return
        self._flash()

    @pyqtSlot()
    def _on_verify(self):
        """Verify firmware on MCU."""
        if not self._probe:
            self._log("No probe connected.", error=True)
            return
        self._verify()

    # ------------------------------------------------------------------
    # Flash operation
    # ------------------------------------------------------------------
    def _flash(self):
        """Parse firmware file and write to MCU in 256-byte chunks."""
        path = self.txt_file.text().strip()
        if not path or not os.path.isfile(path):
            self._log("No valid firmware file selected.", error=True)
            return

        # Parse base address
        try:
            base_addr = int(self.txt_addr.text().strip(), 0)
        except ValueError:
            self._log("Invalid base address.", error=True)
            return

        # Load firmware data
        fmt = self.combo_format.currentText()
        try:
            if fmt == "HEX":
                data, start_addr = self._parse_ihex(path)
                if start_addr is not None:
                    base_addr = start_addr
            elif fmt == "ELF":
                data, start_addr = self._parse_elf(path)
                if start_addr is not None:
                    base_addr = start_addr
            elif fmt == "BIN":
                with open(path, 'rb') as f:
                    data = f.read()
            else:  # Auto
                ext = os.path.splitext(path)[1].lower()
                if ext == '.hex':
                    data, start_addr = self._parse_ihex(path)
                    if start_addr is not None:
                        base_addr = start_addr
                elif ext in ('.elf', '.axf'):
                    data, start_addr = self._parse_elf(path)
                    if start_addr is not None:
                        base_addr = start_addr
                else:
                    with open(path, 'rb') as f:
                        data = f.read()
        except Exception as e:
            self._log(f"Failed to parse firmware: {e}", error=True)
            return

        if not data:
            self._log("No data to flash.", error=True)
            return

        self._log(f"Flashing {len(data)} bytes to 0x{base_addr:08X}...")
        self.progress.setMaximum(len(data))
        self.progress.setValue(0)

        # Write in 256-byte chunks
        chunk_size = 256
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + chunk_size]
            try:
                self._probe.write_mem_U8(base_addr + offset, list(chunk))
            except Exception as e:
                self._log(f"Write error at offset 0x{offset:X}: {e}", error=True)
                return
            offset += len(chunk)
            self.progress.setValue(offset)

        self._log(f"Flash complete: {len(data)} bytes written.", ok=True)

        # Reset after flash
        if self.chk_reset.isChecked():
            self._log("Resetting MCU...")
            try:
                self._probe.reset()
                self._log("Reset complete.", ok=True)
            except Exception as e:
                self._log(f"Reset failed: {e}", error=True)

    # ------------------------------------------------------------------
    # Verify operation
    # ------------------------------------------------------------------
    def _verify(self):
        """Read back flashed data and compare with source."""
        path = self.txt_file.text().strip()
        if not path or not os.path.isfile(path):
            self._log("No valid firmware file selected.", error=True)
            return

        try:
            base_addr = int(self.txt_addr.text().strip(), 0)
        except ValueError:
            self._log("Invalid base address.", error=True)
            return

        # Load firmware data (same logic as flash)
        fmt = self.combo_format.currentText()
        try:
            if fmt == "HEX":
                data, start_addr = self._parse_ihex(path)
                if start_addr is not None:
                    base_addr = start_addr
            elif fmt == "ELF":
                data, start_addr = self._parse_elf(path)
                if start_addr is not None:
                    base_addr = start_addr
            elif fmt == "BIN":
                with open(path, 'rb') as f:
                    data = f.read()
            else:
                ext = os.path.splitext(path)[1].lower()
                if ext == '.hex':
                    data, start_addr = self._parse_ihex(path)
                    if start_addr is not None:
                        base_addr = start_addr
                elif ext in ('.elf', '.axf'):
                    data, start_addr = self._parse_elf(path)
                    if start_addr is not None:
                        base_addr = start_addr
                else:
                    with open(path, 'rb') as f:
                        data = f.read()
        except Exception as e:
            self._log(f"Failed to parse firmware: {e}", error=True)
            return

        if not data:
            self._log("No data to verify.", error=True)
            return

        self._log(f"Verifying {len(data)} bytes at 0x{base_addr:08X}...")
        self.progress.setMaximum(len(data))
        self.progress.setValue(0)

        # Read back in 256-byte chunks and compare
        chunk_size = 256
        offset = 0
        mismatches = 0
        while offset < len(data):
            expected = data[offset:offset + chunk_size]
            try:
                actual = self._probe.read_mem_U8(base_addr + offset, len(expected))
            except Exception as e:
                self._log(f"Read error at offset 0x{offset:X}: {e}", error=True)
                return

            if isinstance(actual, list):
                for i, (a, e) in enumerate(zip(actual, expected)):
                    if a != e:
                        mismatches += 1
                        if mismatches <= 10:
                            self._log(
                                f"  Mismatch at 0x{base_addr + offset + i:08X}: "
                                f"expected 0x{e:02X}, got 0x{a:02X}", error=True
                            )

            offset += len(expected)
            self.progress.setValue(offset)

        if mismatches == 0:
            self._log("Verification passed: all bytes match.", ok=True)
        else:
            self._log(f"Verification FAILED: {mismatches} mismatched bytes.", error=True)

    # ------------------------------------------------------------------
    # Intel HEX parser
    # ------------------------------------------------------------------
    def _parse_ihex(self, path: str) -> tuple[bytes, int | None]:
        """Parse Intel HEX file. Returns (data, start_address)."""
        records: list[tuple[int, bytes]] = []
        ext_addr = 0  # Extended linear address

        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line.startswith(':'):
                    continue
                byte_count = int(line[1:3], 16)
                address = int(line[3:7], 16)
                rec_type = int(line[7:9], 16)
                data_hex = line[9:9 + byte_count * 2]

                if rec_type == 0x00:  # Data record
                    full_addr = ext_addr + address
                    data_bytes = bytes.fromhex(data_hex)
                    records.append((full_addr, data_bytes))
                elif rec_type == 0x02:  # Extended segment address
                    ext_addr = int(data_hex, 16) << 4
                elif rec_type == 0x04:  # Extended linear address
                    ext_addr = int(data_hex, 16) << 16
                elif rec_type == 0x01:  # End of file
                    break

        if not records:
            return b'', None

        # Merge into contiguous block
        min_addr = min(addr for addr, _ in records)
        max_addr = max(addr + len(data) for addr, data in records)
        result = bytearray(max_addr - min_addr)
        for addr, data in records:
            result[addr - min_addr:addr - min_addr + len(data)] = data

        return bytes(result), min_addr

    # ------------------------------------------------------------------
    # ELF parser (PT_LOAD segments)
    # ------------------------------------------------------------------
    def _parse_elf(self, path: str) -> tuple[bytes, int | None]:
        """Extract PT_LOAD segments from ELF file."""
        with open(path, 'rb') as f:
            data = f.read()

        if len(data) < 16 or data[:4] != b'\x7fELF':
            raise ValueError("Not a valid ELF file.")

        is_64 = data[4] == 2
        is_le = data[5] == 1

        if is_64:
            raise ValueError("64-bit ELF not supported.")
        if not is_le:
            raise ValueError("Big-endian ELF not supported.")

        # ELF32 header
        e_phoff = struct.unpack_from('<I', data, 28)[0]
        e_phentsize = struct.unpack_from('<H', data, 42)[0]
        e_phnum = struct.unpack_from('<H', data, 44)[0]

        # PT_LOAD = 1
        PT_LOAD = 1
        segments: list[tuple[int, int, int]] = []  # (p_offset, p_paddr, p_filesz)

        for i in range(e_phnum):
            off = e_phoff + i * e_phentsize
            p_type = struct.unpack_from('<I', data, off)[0]
            if p_type == PT_LOAD:
                p_offset = struct.unpack_from('<I', data, off + 4)[0]
                p_paddr = struct.unpack_from('<I', data, off + 12)[0]
                p_filesz = struct.unpack_from('<I', data, off + 16)[0]
                if p_filesz > 0:
                    segments.append((p_offset, p_paddr, p_filesz))

        if not segments:
            raise ValueError("No PT_LOAD segments found.")

        # Merge segments into contiguous block
        min_addr = min(p_paddr for _, p_paddr, _ in segments)
        max_addr = max(p_paddr + p_filesz for _, p_paddr, p_filesz in segments)
        result = bytearray(max_addr - min_addr)

        for p_offset, p_paddr, p_filesz in segments:
            chunk = data[p_offset:p_offset + p_filesz]
            result[p_paddr - min_addr:p_paddr - min_addr + p_filesz] = chunk

        return bytes(result), min_addr

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _log(self, msg: str, error: bool = False, ok: bool = False):
        """Append a message to the log."""
        if error:
            self.txt_log.append(
                f'<span style="color:{_COLOR_ERROR};">{msg}</span>'
            )
        elif ok:
            self.txt_log.append(
                f'<span style="color:{_COLOR_OK};">{msg}</span>'
            )
        else:
            self.txt_log.append(msg)
