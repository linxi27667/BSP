"""SVD-based peripheral register viewer with live MCU value reading."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QTreeWidget, QTreeWidgetItem, QCheckBox, QSplitter, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QFont

from core.svd_parser import parse_svd, Device, Peripheral, Register, Field


# -- Color constants (dark-theme friendly) ------------------------------------
COLOR_CHANGED  = '#FF6B6B'   # red   - value changed since last read
COLOR_PERIPH   = '#DCDCAA'   # yellow - peripheral names
COLOR_REG      = '#D4D4D4'   # light grey - register names
COLOR_FIELD    = '#9CDCFE'   # blue  - field names
COLOR_ADDR     = '#808080'   # grey  - address column
COLOR_VALUE    = '#B5CEA8'   # green - value column
COLOR_DESC     = '#6A9955'   # dim green - description column


class RegisterViewer(QWidget):
    """Widget that displays SVD peripheral registers with live MCU values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._device: Device | None = None
        self._prev_values: dict[tuple[str, str], int] = {}  # (periph, reg) -> value

        self._init_ui()
        self._init_timer()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Toolbar row -------------------------------------------------
        toolbar = QHBoxLayout()
        self.btn_load = QPushButton("Load SVD...")
        self.btn_load.setFixedWidth(110)
        self.btn_load.clicked.connect(self._on_load_svd)

        self.lbl_device = QLabel("No SVD loaded")
        self.lbl_device.setStyleSheet(f"color: {COLOR_DESC}; padding-left: 8px;")

        self.chk_auto = QCheckBox("Auto Refresh")
        self.chk_auto.setChecked(False)
        self.chk_auto.stateChanged.connect(self._on_auto_toggle)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(80)
        self.btn_refresh.clicked.connect(self._refresh_all)
        self.btn_refresh.setEnabled(False)

        toolbar.addWidget(self.btn_load)
        toolbar.addWidget(self.lbl_device)
        toolbar.addStretch()
        toolbar.addWidget(self.chk_auto)
        toolbar.addWidget(self.btn_refresh)
        layout.addLayout(toolbar)

        # -- Splitter: tree (top) + detail (bottom) ----------------------
        splitter = QSplitter(Qt.Vertical)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Address", "Value", "Description"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 120)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._on_item_selected)
        self._apply_tree_style()
        splitter.addWidget(self.tree)

        # Detail panel
        detail_group = QGroupBox("Register Detail")
        detail_layout = QVBoxLayout(detail_group)
        detail_layout.setContentsMargins(4, 4, 4, 4)

        self.lbl_detail_desc = QLabel("Select a register to view details.")
        self.lbl_detail_desc.setWordWrap(True)
        self.lbl_detail_desc.setStyleSheet(f"color: {COLOR_DESC};")
        detail_layout.addWidget(self.lbl_detail_desc)

        self.tbl_fields = QTableWidget(0, 5)
        self.tbl_fields.setHorizontalHeaderLabels(
            ["Field", "Bits", "Access", "Value", "Description"]
        )
        self.tbl_fields.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch
        )
        self.tbl_fields.verticalHeader().setVisible(False)
        self.tbl_fields.setEditTriggers(QTableWidget.NoEditTriggers)
        self._apply_table_style()
        detail_layout.addWidget(self.tbl_fields)

        splitter.addWidget(detail_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def _apply_tree_style(self):
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 2px;
            }
            QTreeWidget::item:selected {
                background-color: #264F78;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                padding: 4px;
            }
        """)

    def _apply_table_style(self):
        self.tbl_fields.setStyleSheet("""
            QTableWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                font-family: Consolas, monospace;
                font-size: 12px;
                gridline-color: #3C3C3C;
            }
            QTableWidget::item:selected {
                background-color: #264F78;
            }
            QHeaderView::section {
                background-color: #252526;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                padding: 3px;
            }
        """)

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_all)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe
        self.btn_refresh.setEnabled(probe is not None and self._device is not None)

    def load_svd(self, path: str):
        """Parse an SVD file and populate the tree."""
        self._device = parse_svd(path)
        self._prev_values.clear()
        self._build_tree()
        self.lbl_device.setText(
            f"{self._device.name} - {self._device.description}"
        )
        self.btn_refresh.setEnabled(self._probe is not None)
        if self.chk_auto.isChecked() and self._probe:
            self._timer.start()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_load_svd(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SVD File", "", "SVD Files (*.svd);;All Files (*)"
        )
        if path:
            self.load_svd(path)

    @pyqtSlot(int)
    def _on_auto_toggle(self, state):
        if state == Qt.Checked and self._probe and self._device:
            self._timer.start()
        else:
            self._timer.stop()

    @pyqtSlot(QTreeWidgetItem, QTreeWidgetItem)
    def _on_item_selected(self, current, previous):
        if current is None:
            return

        level = current.data(0, Qt.UserRole)
        if level == "peripheral":
            periph: Peripheral = current.data(0, Qt.UserRole + 1)
            self.lbl_detail_desc.setText(periph.description)
            self.tbl_fields.setRowCount(0)
        elif level == "register":
            reg: Register = current.data(0, Qt.UserRole + 1)
            self.lbl_detail_desc.setText(reg.description)
            self._populate_field_table(reg, None)
        elif level == "field":
            field: Field = current.data(0, Qt.UserRole + 1)
            reg: Register = current.data(0, Qt.UserRole + 2)
            self.lbl_detail_desc.setText(field.description)
            self._populate_field_table(reg, field)

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------
    def _build_tree(self):
        self.tree.clear()
        if not self._device:
            return

        peripherals = sorted(self._device.peripherals, key=lambda p: p.base_address)

        for periph in peripherals:
            p_item = QTreeWidgetItem(self.tree)
            p_item.setText(0, periph.name)
            p_item.setText(1, f"0x{periph.base_address:08X}")
            p_item.setText(2, "")
            p_item.setText(3, periph.description)
            p_item.setForeground(0, QColor(COLOR_PERIPH))
            p_item.setData(0, Qt.UserRole, "peripheral")
            p_item.setData(0, Qt.UserRole + 1, periph)

            for reg in periph.registers:
                r_item = QTreeWidgetItem(p_item)
                r_item.setText(0, reg.name)
                addr = periph.base_address + reg.address_offset
                r_item.setText(1, f"0x{addr:08X}")
                r_item.setText(2, "")
                r_item.setText(3, reg.description)
                r_item.setForeground(0, QColor(COLOR_REG))
                r_item.setData(0, Qt.UserRole, "register")
                r_item.setData(0, Qt.UserRole + 1, reg)
                # Store full address for quick reading
                r_item.setData(1, Qt.UserRole, addr)

                for fld in reg.fields:
                    f_item = QTreeWidgetItem(r_item)
                    f_item.setText(0, fld.name)
                    if fld.bit_width == 1:
                        bits_str = str(fld.bit_offset)
                    else:
                        bits_str = f"{fld.bit_offset + fld.bit_width - 1}:{fld.bit_offset}"
                    f_item.setText(1, f"[{bits_str}]")
                    f_item.setText(2, "")
                    f_item.setText(3, fld.description)
                    f_item.setForeground(0, QColor(COLOR_FIELD))
                    f_item.setData(0, Qt.UserRole, "field")
                    f_item.setData(0, Qt.UserRole + 1, fld)
                    f_item.setData(0, Qt.UserRole + 2, reg)

            p_item.setExpanded(True)

    # ------------------------------------------------------------------
    # Live value reading
    # ------------------------------------------------------------------
    def _refresh_all(self):
        """Read register values from MCU and update the tree."""
        if not self._probe or not self._device:
            return

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            p_item = root.child(i)
            periph: Peripheral = p_item.data(0, Qt.UserRole + 1)

            for j in range(p_item.childCount()):
                r_item = p_item.child(j)
                reg: Register = r_item.data(0, Qt.UserRole + 1)
                addr = periph.base_address + reg.address_offset

                try:
                    value = self._probe.read_U32(addr)
                except Exception:
                    r_item.setText(2, "ERR")
                    r_item.setForeground(2, QColor(COLOR_CHANGED))
                    continue

                key = (periph.name, reg.name)
                prev = self._prev_values.get(key)

                # Format value
                hex_str = f"0x{value:08X}"
                r_item.setText(2, hex_str)

                # Highlight if changed
                if prev is not None and prev != value:
                    r_item.setForeground(2, QColor(COLOR_CHANGED))
                    # Also highlight changed fields
                    self._highlight_changed_fields(r_item, prev, value)
                else:
                    r_item.setForeground(2, QColor(COLOR_VALUE))
                    # Clear field highlights on first read or no change
                    if prev is None:
                        self._update_field_values(r_item, value)

                self._prev_values[key] = value

    def _highlight_changed_fields(self, r_item, old_val, new_val):
        """Highlight fields whose extracted value changed."""
        reg: Register = r_item.data(0, Qt.UserRole + 1)
        for k in range(r_item.childCount()):
            f_item = r_item.child(k)
            fld: Field = f_item.data(0, Qt.UserRole + 1)
            old_f = fld.extract(old_val)
            new_f = fld.extract(new_val)
            f_item.setText(2, f"0x{new_f:X}")
            if old_f != new_f:
                f_item.setForeground(2, QColor(COLOR_CHANGED))
            else:
                f_item.setForeground(2, QColor(COLOR_VALUE))

    def _update_field_values(self, r_item, value):
        """Set field values on first read (no previous to compare)."""
        for k in range(r_item.childCount()):
            f_item = r_item.child(k)
            fld: Field = f_item.data(0, Qt.UserRole + 1)
            fv = fld.extract(value)
            f_item.setText(2, f"0x{fv:X}")
            f_item.setForeground(2, QColor(COLOR_VALUE))

    # ------------------------------------------------------------------
    # Detail panel
    # ------------------------------------------------------------------
    def _populate_field_table(self, reg: Register, highlight_field: Field | None):
        """Fill the field table for the given register."""
        self.tbl_fields.setRowCount(len(reg.fields))
        for row, fld in enumerate(reg.fields):
            name_item = QTableWidgetItem(fld.name)
            name_item.setForeground(QColor(COLOR_FIELD))
            self.tbl_fields.setItem(row, 0, name_item)

            if fld.bit_width == 1:
                bits_str = str(fld.bit_offset)
            else:
                bits_str = f"{fld.bit_offset + fld.bit_width - 1}:{fld.bit_offset}"
            self.tbl_fields.setItem(row, 1, QTableWidgetItem(bits_str))

            self.tbl_fields.setItem(row, 2, QTableWidgetItem(fld.access))
            self.tbl_fields.setItem(row, 3, QTableWidgetItem(""))  # value filled on refresh
            self.tbl_fields.setItem(row, 4, QTableWidgetItem(fld.description))

            # Highlight the selected field row
            if highlight_field and fld.name == highlight_field.name:
                for col in range(5):
                    item = self.tbl_fields.item(row, col)
                    if item:
                        item.setBackground(QColor("#264F78"))

        self.tbl_fields.resizeColumnsToContents()
