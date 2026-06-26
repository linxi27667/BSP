"""Core register viewer with xPSR / mstatus decoding."""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QTextEdit, QGroupBox, QLabel, QComboBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QFont


# -- Color constants (dark-theme, matching register_viewer.py) ----------------
COLOR_REG_NAME = '#DCDCAA'   # yellow - register names
COLOR_VALUE    = '#B5CEA8'   # green  - hex values
COLOR_DESC     = '#6A9955'   # dim green - descriptions
COLOR_CHANGED  = '#FF6B6B'   # red    - value changed since last read


# -- Register lists per architecture ------------------------------------------
_ARM_REGS = [
    ('R0',   'General purpose'),
    ('R1',   'General purpose'),
    ('R2',   'General purpose'),
    ('R3',   'General purpose'),
    ('R4',   'General purpose'),
    ('R5',   'General purpose'),
    ('R6',   'General purpose'),
    ('R7',   'General purpose'),
    ('R8',   'General purpose'),
    ('R9',   'General purpose'),
    ('R10',  'General purpose'),
    ('R11',  'Frame pointer'),
    ('R12',  'Intra-procedure scratch'),
    ('SP',   'Stack pointer (R13)'),
    ('LR',   'Link register (R14)'),
    ('PC',   'Program counter (R15)'),
    ('xPSR', 'Program status register'),
    ('MSP',  'Main stack pointer'),
    ('PSP',  'Process stack pointer'),
]

_RV_REGS = [
    ('x0',      'Zero (hardwired)'),
    ('x1',      'Return address (ra)'),
    ('x2',      'Stack pointer (sp)'),
    ('x3',      'Global pointer (gp)'),
    ('x4',      'Thread pointer (tp)'),
    ('x5',      'Temp / alternate link (t0)'),
    ('x6',      'Temp (t1)'),
    ('x7',      'Temp (t2)'),
    ('x8',      'Saved / frame pointer (s0/fp)'),
    ('x9',      'Saved (s1)'),
    ('x10',     'Function arg / return (a0)'),
    ('x11',     'Function arg / return (a1)'),
    ('x12',     'Function arg (a2)'),
    ('x13',     'Function arg (a3)'),
    ('x14',     'Function arg (a4)'),
    ('x15',     'Function arg (a5)'),
    ('x16',     'Function arg (a6)'),
    ('x17',     'Function arg (a7)'),
    ('x18',     'Saved (s2)'),
    ('x19',     'Saved (s3)'),
    ('x20',     'Saved (s4)'),
    ('x21',     'Saved (s5)'),
    ('x22',     'Saved (s6)'),
    ('x23',     'Saved (s7)'),
    ('x24',     'Saved (s8)'),
    ('x25',     'Saved (s9)'),
    ('x26',     'Saved (s10)'),
    ('x27',     'Saved (s11)'),
    ('x28',     'Temp (t3)'),
    ('x29',     'Temp (t4)'),
    ('x30',     'Temp (t5)'),
    ('x31',     'Temp (t6)'),
    ('pc',      'Program counter'),
    ('mstatus', 'Machine status'),
    ('mcause',  'Machine exception cause'),
    ('mtval',   'Machine trap value'),
]

# ARM Cortex-M exception numbers -> names
_ARM_EXCEPTIONS = {
    0:  'Thread mode',
    1:  'Reset',
    2:  'NMI',
    3:  'HardFault',
    4:  'MemManage',
    5:  'BusFault',
    6:  'UsageFault',
    7:  'SecureFault',
    8:  'Reserved',
    9:  'Reserved',
    10: 'Reserved',
    11: 'SVCall',
    12: 'Debug Monitor',
    13: 'Reserved',
    14: 'PendSV',
    15: 'SysTick',
}


class CoreRegisterViewer(QWidget):
    """Widget that displays CPU core registers with decoded status fields."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._mode = 'arm'
        self._prev_values: dict[str, int] = {}

        self._init_ui()
        self._init_timer()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Toolbar ----------------------------------------------------
        toolbar = QHBoxLayout()

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(['ARM (Cortex-M)', 'RISC-V'])
        self.combo_mode.setFixedWidth(160)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)

        self.chk_auto = QCheckBox("Auto Refresh")
        self.chk_auto.setChecked(False)
        self.chk_auto.stateChanged.connect(self._on_auto_toggle)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(80)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_refresh.setEnabled(False)

        toolbar.addWidget(QLabel("Architecture:"))
        toolbar.addWidget(self.combo_mode)
        toolbar.addStretch()
        toolbar.addWidget(self.chk_auto)
        toolbar.addWidget(self.btn_refresh)
        layout.addLayout(toolbar)

        # -- Register table ---------------------------------------------
        self.tbl_regs = QTableWidget(0, 3)
        self.tbl_regs.setHorizontalHeaderLabels(["Register", "Value", "Description"])
        self.tbl_regs.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_regs.verticalHeader().setVisible(False)
        self.tbl_regs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_regs.setSelectionBehavior(QTableWidget.SelectRows)
        self._apply_table_style()
        layout.addWidget(self.tbl_regs)

        # -- Status decode panel ----------------------------------------
        decode_group = QGroupBox("Status Decode")
        decode_layout = QVBoxLayout(decode_group)
        decode_layout.setContentsMargins(4, 4, 4, 4)

        self.txt_decode = QTextEdit()
        self.txt_decode.setReadOnly(True)
        self.txt_decode.setFont(QFont("Consolas", 11))
        self.txt_decode.setMaximumHeight(180)
        self.txt_decode.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        decode_layout.addWidget(self.txt_decode)
        layout.addWidget(decode_group)

        # Build initial register list (ARM)
        self._build_register_list()

    def _apply_table_style(self):
        self.tbl_regs.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 13px;
                gridline-color: #3C3C3C;
            }
            QTableWidget::item:selected {
                background-color: #264F78;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                padding: 4px;
            }
        """)

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe, mode='arm'):
        """Receive the DebugProbe instance and architecture mode.

        *mode* must be 'arm' or 'rv'.
        """
        self._probe = probe
        self._mode = mode
        self.btn_refresh.setEnabled(probe is not None)

        # Sync combo box
        idx = 0 if mode == 'arm' else 1
        self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.blockSignals(False)

        self._build_register_list()

    # ------------------------------------------------------------------
    # Register list building
    # ------------------------------------------------------------------
    def _build_register_list(self):
        """Populate table rows based on the current architecture mode."""
        regs = _ARM_REGS if self._mode == 'arm' else _RV_REGS
        self._prev_values.clear()

        self.tbl_regs.setRowCount(len(regs))
        for row, (name, desc) in enumerate(regs):
            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor(COLOR_REG_NAME))
            font = name_item.font()
            font.setBold(True)
            name_item.setFont(font)
            self.tbl_regs.setItem(row, 0, name_item)

            val_item = QTableWidgetItem("---")
            val_item.setForeground(QColor(COLOR_VALUE))
            val_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_regs.setItem(row, 1, val_item)

            desc_item = QTableWidgetItem(desc)
            desc_item.setForeground(QColor(COLOR_DESC))
            self.tbl_regs.setItem(row, 2, desc_item)

        self.tbl_regs.resizeColumnsToContents()
        self.txt_decode.clear()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def _refresh(self):
        """Read all registers via the probe and update the table."""
        if not self._probe:
            return

        regs = _ARM_REGS if self._mode == 'arm' else _RV_REGS
        status_val = None

        for row, (name, _desc) in enumerate(regs):
            try:
                value = self._probe.read_reg(name)
            except Exception:
                item = self.tbl_regs.item(row, 1)
                if item:
                    item.setText("ERR")
                    item.setForeground(QColor(COLOR_CHANGED))
                continue

            item = self.tbl_regs.item(row, 1)
            if item is None:
                continue

            hex_str = f"0x{value:08X}"
            item.setText(hex_str)

            prev = self._prev_values.get(name)
            if prev is not None and prev != value:
                item.setForeground(QColor(COLOR_CHANGED))
            else:
                item.setForeground(QColor(COLOR_VALUE))

            self._prev_values[name] = value

            # Capture status register for decode
            if (self._mode == 'arm' and name == 'xPSR') or \
               (self._mode == 'rv' and name == 'mstatus'):
                status_val = value

        # Decode status register
        if status_val is not None:
            self._decode_status(status_val)

    # ------------------------------------------------------------------
    # Status decoding
    # ------------------------------------------------------------------
    def _decode_status(self, value: int):
        """Decode xPSR (ARM) or mstatus (RISC-V) into human-readable text."""
        if self._mode == 'arm':
            self._decode_xpsr(value)
        else:
            self._decode_mstatus(value)

    def _decode_xpsr(self, value: int):
        """Decode ARM xPSR register fields."""
        lines = [f"xPSR = 0x{value:08X}", ""]

        # Exception number [8:0]
        exc_num = value & 0x1FF
        exc_name = self._exception_name(exc_num)
        lines.append(f"  Exception Number : {exc_num} ({exc_name})")

        # Thumb bit [24]
        thumb = (value >> 24) & 1
        lines.append(f"  Thumb bit [24]   : {thumb} ({'Thumb' if thumb else 'ARM'})")

        # N flag [31]
        n = (value >> 31) & 1
        lines.append(f"  N (Negative) [31]: {n}")

        # Z flag [30]
        z = (value >> 30) & 1
        lines.append(f"  Z (Zero)     [30]: {z}")

        # C flag [29]
        c = (value >> 29) & 1
        lines.append(f"  C (Carry)    [29]: {c}")

        # V flag [28]
        v = (value >> 28) & 1
        lines.append(f"  V (Overflow) [28]: {v}")

        # Q flag [27]
        q = (value >> 27) & 1
        lines.append(f"  Q (Saturation)[27]: {q}")

        self.txt_decode.setText("\n".join(lines))

    def _decode_mstatus(self, value: int):
        """Decode RISC-V mstatus register fields."""
        lines = [f"mstatus = 0x{value:08X}", ""]

        # MIE (bit 3) - Machine Interrupt Enable
        mie = (value >> 3) & 1
        lines.append(f"  MIE  (Machine Interrupt Enable) [3]  : {mie} ({'Enabled' if mie else 'Disabled'})")

        # MPIE (bit 7) - Machine Previous Interrupt Enable
        mpie = (value >> 7) & 1
        lines.append(f"  MPIE (Machine Previous IE)       [7]  : {mpie}")

        # MPP (bits 12:11) - Machine Previous Privilege
        mpp = (value >> 11) & 0x3
        priv_names = {0: 'User', 1: 'Supervisor', 2: 'Reserved', 3: 'Machine'}
        lines.append(f"  MPP  (Machine Previous Privilege)[12:11]: {mpp} ({priv_names.get(mpp, '?')})")

        # SIE (bit 1)
        sie = (value >> 1) & 1
        lines.append(f"  SIE  (Supervisor IE)             [1]  : {sie}")

        # SPIE (bit 5)
        spie = (value >> 5) & 1
        lines.append(f"  SPIE (Supervisor Previous IE)    [5]  : {spie}")

        # SPP (bit 8)
        spp = (value >> 8) & 1
        lines.append(f"  SPP  (Supervisor Previous Priv)  [8]  : {spp}")

        self.txt_decode.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Exception name lookup
    # ------------------------------------------------------------------
    @staticmethod
    def _exception_name(num: int) -> str:
        """Map ARM Cortex-M exception number to its name."""
        if 16 <= num <= 255:
            return f"IRQ {num - 16}"
        return _ARM_EXCEPTIONS.get(num, 'Unknown')

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot(int)
    def _on_mode_changed(self, index):
        self._mode = 'arm' if index == 0 else 'rv'
        self._build_register_list()

    @pyqtSlot(int)
    def _on_auto_toggle(self, state):
        if state == Qt.Checked and self._probe:
            self._timer.start()
        else:
            self._timer.stop()
