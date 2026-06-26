"""Hex memory viewer with region coloring and auto-refresh."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QCheckBox, QLabel, QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QFont


# -- Color constants (dark-theme friendly) ------------------------------------
COLOR_FLASH  = '#4EC9B0'   # teal  - Flash region  (0x08000000)
COLOR_SRAM   = '#B5CEA8'   # green - SRAM region   (0x20000000)
COLOR_PERIPH = '#CE9178'   # orange - Peripheral   (0x40000000)
COLOR_HEADER = '#569CD6'   # blue  - column header / address
COLOR_ASCII  = '#D4D4D4'   # grey  - ASCII column
COLOR_LABEL  = '#808080'   # dim grey - labels


def _region_color(addr: int) -> str:
    """Return hex color string based on memory region."""
    if 0x08000000 <= addr < 0x10000000:
        return COLOR_FLASH
    if 0x20000000 <= addr < 0x30000000:
        return COLOR_SRAM
    if 0x40000000 <= addr < 0x60000000:
        return COLOR_PERIPH
    return COLOR_ASCII  # fallback: neutral grey


class MemoryViewer(QWidget):
    """Widget that displays MCU memory as a color-coded hex dump."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._data: list[int] = []  # raw bytes read from MCU

        self._init_ui()
        self._init_timer()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Address / length row -----------------------------------------
        addr_row = QHBoxLayout()

        addr_row.addWidget(QLabel("Address:"))
        self.txt_addr = QLineEdit("0x20000000")
        self.txt_addr.setFixedWidth(120)
        self.txt_addr.setFont(QFont("Consolas", 11))
        self.txt_addr.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; "
            "border: 1px solid #3C3C3C; padding: 2px;"
        )
        addr_row.addWidget(self.txt_addr)

        addr_row.addWidget(QLabel("Length:"))
        self.txt_len = QLineEdit("256")
        self.txt_len.setFixedWidth(80)
        self.txt_len.setFont(QFont("Consolas", 11))
        self.txt_len.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; "
            "border: 1px solid #3C3C3C; padding: 2px;"
        )
        addr_row.addWidget(self.txt_len)

        self.btn_go = QPushButton("Go")
        self.btn_go.setFixedWidth(60)
        self.btn_go.clicked.connect(self._on_goto)
        addr_row.addWidget(self.btn_go)

        self.chk_auto = QCheckBox("Auto 500ms")
        self.chk_auto.setChecked(False)
        self.chk_auto.stateChanged.connect(self._on_auto_toggle)
        addr_row.addWidget(self.chk_auto)

        addr_row.addStretch()
        layout.addLayout(addr_row)

        # -- Quick jump buttons -------------------------------------------
        jump_group = QGroupBox("Quick Jump")
        jump_layout = QHBoxLayout(jump_group)
        jump_layout.setContentsMargins(4, 4, 4, 4)

        jumps = [
            ("Flash",  "0x08000000"),
            ("SRAM",   "0x20000000"),
            ("Periph", "0x40000000"),
            ("Stack",  "0x20010000"),
        ]
        for label, addr in jumps:
            btn = QPushButton(label)
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda checked, a=addr: self._jump_to(a))
            jump_layout.addWidget(btn)

        jump_layout.addStretch()
        layout.addWidget(jump_group)

        # -- Hex display --------------------------------------------------
        self.txt_hex = QTextEdit()
        self.txt_hex.setReadOnly(True)
        self.txt_hex.setFont(QFont("Consolas", 11))
        self.txt_hex.setStyleSheet(
            "background-color: #1E1E1E; color: #D4D4D4; "
            "border: 1px solid #3C3C3C;"
        )
        layout.addWidget(self.txt_hex)

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_goto(self):
        """Read memory from MCU and render hex dump."""
        self._read_and_render()

    @pyqtSlot(int)
    def _on_auto_toggle(self, state):
        if state == Qt.Checked and self._probe:
            self._timer.start()
        else:
            self._timer.stop()

    def _jump_to(self, addr_str: str):
        """Set address field and trigger a read."""
        self.txt_addr.setText(addr_str)
        self._read_and_render()

    def _refresh(self):
        """Called by auto-refresh timer."""
        self._read_and_render()

    # ------------------------------------------------------------------
    # Memory read
    # ------------------------------------------------------------------
    def _read_and_render(self):
        """Parse inputs, read memory via probe, and render."""
        if not self._probe:
            self.txt_hex.setHtml(
                '<pre style="color:#FF6B6B;">No probe connected.</pre>'
            )
            return

        # Parse address
        try:
            addr_text = self.txt_addr.text().strip()
            addr = int(addr_text, 0)  # accepts 0x prefix or plain decimal
        except ValueError:
            self.txt_hex.setHtml(
                '<pre style="color:#FF6B6B;">Invalid address.</pre>'
            )
            return

        # Parse length
        try:
            length = int(self.txt_len.text().strip(), 0)
        except ValueError:
            self.txt_hex.setHtml(
                '<pre style="color:#FF6B6B;">Invalid length.</pre>'
            )
            return

        if length < 1:
            length = 1
        if length > 4096:
            length = 4096
            self.txt_len.setText("4096")

        # Read bytes from MCU
        try:
            self._data = self._probe.read_mem_U8(addr, length)
        except Exception as e:
            self.txt_hex.setHtml(
                f'<pre style="color:#FF6B6B;">Read error: {e}</pre>'
            )
            self._data = []
            return

        self._render()

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------
    def _render(self):
        """Generate HTML hex dump from self._data."""
        if not self._data:
            self.txt_hex.setHtml(
                '<pre style="color:#808080;">No data.</pre>'
            )
            return

        addr = int(self.txt_addr.text().strip(), 0)
        lines: list[str] = []

        # -- Header row ---------------------------------------------------
        header_cells = ['<span style="color:{0};">{0}</span>'.format(COLOR_HEADER)]
        header_cells.append('     ')
        for col in range(16):
            header_cells.append(
                f'<span style="color:{COLOR_HEADER};">{col:02X}</span>'
            )
            if col == 7:
                header_cells.append('  ')
            else:
                header_cells.append(' ')
        lines.append(''.join(header_cells))

        # -- Separator ----------------------------------------------------
        lines.append(
            '<span style="color:#3C3C3C;">' + '-' * 72 + '</span>'
        )

        # -- Data rows ----------------------------------------------------
        data = self._data
        for row_start in range(0, len(data), 16):
            row_addr = addr + row_start
            color = _region_color(row_addr)

            parts: list[str] = []

            # Address
            parts.append(
                f'<span style="color:{COLOR_HEADER};">'
                f'{row_addr:08X}</span>  '
            )

            # Hex bytes
            ascii_chars: list[str] = []
            for col in range(16):
                idx = row_start + col
                if idx < len(data):
                    byte = data[idx]
                    parts.append(
                        f'<span style="color:{color};">{byte:02X}</span> '
                    )
                    # ASCII representation
                    if 0x20 <= byte <= 0x7E:
                        ascii_chars.append(chr(byte))
                    else:
                        ascii_chars.append('.')
                else:
                    parts.append('   ')
                    ascii_chars.append(' ')

                if col == 7:
                    parts.append(' ')

            # ASCII
            ascii_str = ''.join(ascii_chars)
            parts.append(
                f' <span style="color:{COLOR_ASCII};">{ascii_str}</span>'
            )

            lines.append(''.join(parts))

        html = '<pre style="font-family:Consolas,monospace;font-size:13px;">'
        html += '\n'.join(lines)
        html += '</pre>'
        self.txt_hex.setHtml(html)
