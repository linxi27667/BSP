# RTTView Phase 2: Register & Memory Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SVD-based peripheral register viewer, hex memory viewer, and core register display — all reading live data from the MCU via the debug probe.

**Architecture:** SVD parser reads CMSIS-SVD XML files to build a tree of Peripheral → Register → Field. Register viewer widget displays this tree with live values. Memory viewer shows hex dump with color-coded regions. All data comes from the DebugProbe memory-read interface.

**Tech Stack:** Python 3.6+, PyQt5, cmsis-svd (for SVD parsing), xml.etree.ElementTree (stdlib fallback)

## Global Constraints

- All register reads are non-intrusive (via debug interface, no MCU halt required for RTT mode)
- SVD files are read-only; user can browse/download from `svd/` directory
- Existing RTT view must not be affected by new tabs

---

### Task 1: SVD Parser Module

**Files:**
- Create: `E:\MCU\BSP\RTTView\core\__init__.py`
- Create: `E:\MCU\BSP\RTTView\core\svd_parser.py`

**Interfaces:**
- Produces: `SVDParser` class with `parse(path)` → `Device` dataclass tree
- Data model: `Device` → `Peripheral` → `Register` → `Field`

- [ ] **Step 1: Create core package**

```python
# E:\MCU\BSP\RTTView\core\__init__.py
# Core parsing and analysis modules
```

- [ ] **Step 2: Create SVD parser**

```python
# E:\MCU\BSP\RTTView\core\svd_parser.py
"""CMSIS-SVD file parser for peripheral register definitions.

Parses standard SVD XML files from chip vendors (ST, NXP, Nordic, Espressif, etc.)
into a structured tree: Device → Peripheral → Register → Field.

Reference: ARM CMSIS-SVD specification
https://www.keil.com/pack/doc/CMSIS/SVD/html/index.html
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Field:
    """A bit field within a register."""
    name: str
    description: str
    bit_offset: int
    bit_width: int
    access: str  # 'read-only', 'write-only', 'read-write', etc.

    @property
    def bit_mask(self) -> int:
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def extract(self, reg_value: int) -> int:
        return (reg_value >> self.bit_offset) & ((1 << self.bit_width) - 1)

    def insert(self, reg_value: int, field_value: int) -> int:
        cleared = reg_value & ~self.bit_mask
        return cleared | ((field_value << self.bit_offset) & self.bit_mask)


@dataclass
class Register:
    """A peripheral register."""
    name: str
    description: str
    address_offset: int  # relative to peripheral base
    size: int            # in bits (8, 16, 32)
    access: str
    reset_value: int
    fields: List[Field] = field(default_factory=list)

    @property
    def field_count(self) -> int:
        return len(self.fields)


@dataclass
class Peripheral:
    """A peripheral block (e.g., GPIOA, USART1, TIM2)."""
    name: str
    description: str
    base_address: int
    size: int  # in bits
    registers: List[Register] = field(default_factory=list)
    derived_from: Optional[str] = None

    def get_register(self, name: str) -> Optional[Register]:
        for reg in self.registers:
            if reg.name == name:
                return reg
        return None


@dataclass
class Device:
    """The MCU device described by the SVD file."""
    name: str
    description: str
    cpu_name: str
    address_unit_bits: int
    width: int  # default bit width
    peripherals: List[Peripheral] = field(default_factory=list)

    def get_peripheral(self, name: str) -> Optional[Peripheral]:
        for p in self.peripherals:
            if p.name == name:
                return p
        return None

    def get_peripheral_at(self, address: int) -> Optional[Peripheral]:
        for p in self.peripherals:
            if p.base_address == address:
                return p
        return None


def _parse_fields(register_elem) -> List[Field]:
    fields = []
    for f_elem in register_elem.findall('.//field'):
        name = f_elem.findtext('name', '').strip()
        desc = f_elem.findtext('description', '').strip()
        lsb = int(f_elem.findtext('lsb', '0'))
        msb = int(f_elem.findtext('msb', '0'))
        bit_offset_elem = f_elem.find('bitOffset')
        bit_width_elem = f_elem.find('bitWidth')

        if bit_offset_elem is not None:
            bit_offset = int(bit_offset_elem.text)
            bit_width = int(bit_width_elem.text) if bit_width_elem is not None else 1
        else:
            bit_offset = lsb
            bit_width = msb - lsb + 1

        access = f_elem.findtext('access', 'read-write')
        fields.append(Field(name, desc, bit_offset, bit_width, access))
    return fields


def _parse_registers(periph_elem) -> List[Register]:
    registers = []
    for r_elem in periph_elem.findall('.//register'):
        name = r_elem.findtext('name', '').strip()
        desc = r_elem.findtext('description', '').strip()
        offset = int(r_elem.findtext('addressOffset', '0'), 0)
        size = int(r_elem.findtext('size', '32'), 0)
        access = r_elem.findtext('access', 'read-write')
        reset = int(r_elem.findtext('resetValue', '0'), 0)
        fields = _parse_fields(r_elem)
        registers.append(Register(name, desc, offset, size, access, reset, fields))
    return registers


def parse_svd(path: str) -> Device:
    """Parse an SVD file and return a Device tree."""
    tree = ET.parse(path)
    root = tree.getroot()

    device_name = root.findtext('name', 'Unknown')
    device_desc = root.findtext('description', '')
    cpu_elem = root.find('.//cpu')
    cpu_name = cpu_elem.findtext('name', 'Unknown') if cpu_elem is not None else 'Unknown'
    addr_bits = int(root.findtext('addressUnitBits', '8'))
    width = int(root.findtext('width', '32'))

    device = Device(device_name, device_desc, cpu_name, addr_bits, width)

    for p_elem in root.findall('.//peripheral'):
        name = p_elem.findtext('name', '').strip()
        desc = p_elem.findtext('description', '').strip()
        base = int(p_elem.findtext('baseAddress', '0'), 0)
        derived = p_elem.get('derivedFrom')
        size = int(p_elem.findtext('size', '32'), 0) if p_elem.find('size') is not None else 32

        periph = Peripheral(name, desc, base, size, derived_from=derived)

        if derived is None:
            periph.registers = _parse_registers(p_elem)
        else:
            # Will be resolved after all peripherals are parsed
            pass

        device.peripherals.append(periph)

    # Resolve derived peripherals
    for p in device.peripherals:
        if p.derived_from:
            parent = device.get_peripheral(p.derived_from)
            if parent:
                p.registers = parent.registers
                p.size = parent.size

    return device
```

- [ ] **Step 3: Test with a real SVD file**

Download STM32F407 SVD and test:
```powershell
# Create svd directory
mkdir -Force E:\MCU\BSP\RTTView\svd

# Download STM32F407 SVD (if not present)
if (-not (Test-Path "E:\MCU\BSP\RTTView\svd\STM32F407.svd")) {
    Invoke-WebRequest -Uri "https://raw.githubusercontent.com/posborne/cmsis-svd/master/data/STMicro/STM32F407.svd" -OutFile "E:\MCU\BSP\RTTView\svd\STM32F407.svd"
}

# Test parsing
python -c "
from core.svd_parser import parse_svd
d = parse_svd('svd/STM32F407.svd')
print(f'Device: {d.name}')
print(f'Peripherals: {len(d.peripherals)}')
gpio = d.get_peripheral('GPIOA')
print(f'GPIOA: {len(gpio.registers)} registers')
moder = gpio.get_register('MODER')
print(f'MODER: {len(moder.fields)} fields, reset=0x{moder.reset_value:08X}')
for f in moder.fields:
    print(f'  {f.name}: [{f.bit_offset}:{f.bit_offset+f.bit_width-1}] {f.access}')
"
```

Expected:
```
Device: STM32F407xx
Peripherals: ~80
GPIOA: ~10 registers
MODER: 16 fields, reset=0xA8000000
  MODER0: [0:1] read-write
  MODER1: [2:3] read-write
  ...
```

- [ ] **Step 4: Commit**

```powershell
git add core/__init__.py core/svd_parser.py
git commit -m "feat: add CMSIS-SVD parser for peripheral register definitions"
```

---

### Task 2: Register Viewer Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\__init__.py`
- Create: `E:\MCU\BSP\RTTView\widgets\register_viewer.py`

**Interfaces:**
- Consumes: `SVDParser` data model, `DebugProbe.read_U32()`
- Produces: `RegisterViewer` QWidget with tree view + live values

- [ ] **Step 1: Create widgets package**

```python
# E:\MCU\BSP\RTTView\widgets\__init__.py
# UI widget modules for RTTView
```

- [ ] **Step 2: Create RegisterViewer widget**

```python
# E:\MCU\BSP\RTTView\widgets\register_viewer.py
"""SVD-based peripheral register viewer with live values.

Displays a tree: Peripheral → Register → Field
Live values are read from the MCU via debug probe.
Changed bits are highlighted.
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QComboBox, QLabel, QHeaderView, QSplitter, QTextEdit
)


class RegisterViewer(QWidget):
    """Peripheral register viewer with live MCU values."""

    # Colors
    COLOR_CHANGED = '#FF6B6B'    # red for changed bits
    COLOR_UNCHANGED = '#D4D4D4'  # default text
    COLOR_REGISTER = '#4EC9B0'   # teal for register names
    COLOR_PERIPHERAL = '#DCDCAA' # yellow for peripheral names
    COLOR_FIELD = '#9CDCFE'      # blue for field names
    COLOR_VALUE = '#B5CEA8'      # green for values

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._device = None
        self._prev_values = {}  # {(periph, reg): prev_value}
        self._auto_refresh = False

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        self._btn_load = QPushButton('加载SVD')
        self._btn_load.clicked.connect(self._on_load_svd)
        toolbar.addWidget(self._btn_load)

        self._btn_refresh = QPushButton('刷新')
        self._btn_refresh.clicked.connect(self._refresh_all)
        toolbar.addWidget(self._btn_refresh)

        self._chk_auto = QtWidgets.QCheckBox('自动刷新')
        self._chk_auto.stateChanged.connect(self._on_auto_refresh)
        toolbar.addWidget(self._chk_auto)

        self._lbl_status = QLabel('未加载SVD文件')
        toolbar.addWidget(self._lbl_status)
        toolbar.addStretch()

        layout.addLayout(toolbar)

        # ── Splitter: Tree (left) + Detail (right) ──
        splitter = QSplitter(Qt.Horizontal)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(['名称', '地址', '值', '描述'])
        self._tree.setColumnWidth(0, 200)
        self._tree.setColumnWidth(1, 120)
        self._tree.setColumnWidth(2, 120)
        self._tree.setColumnWidth(3, 300)
        self._tree.currentItemChanged.connect(self._on_item_selected)
        splitter.addWidget(self._tree)

        # Detail panel
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(4, 4, 4, 4)

        self._lbl_detail = QLabel('选择一个寄存器查看详情')
        self._lbl_detail.setWordWrap(True)
        detail_layout.addWidget(self._lbl_detail)

        self._txt_fields = QTextEdit()
        self._txt_fields.setReadOnly(True)
        self._txt_fields.setFont(QtGui.QFont('Consolas', 10))
        detail_layout.addWidget(self._txt_fields)

        splitter.addWidget(detail)
        splitter.setSizes([600, 300])

        layout.addWidget(splitter)

        # ── Refresh timer ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)  # 5 Hz refresh
        self._timer.timeout.connect(self._refresh_all)

    def set_probe(self, probe):
        """Set the debug probe for reading registers."""
        self._probe = probe

    def _on_load_svd(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, '选择SVD文件', 'svd/', 'SVD Files (*.svd);;All Files (*)')
        if path:
            self.load_svd(path)

    def load_svd(self, path):
        """Load and parse an SVD file."""
        from core.svd_parser import parse_svd
        try:
            self._device = parse_svd(path)
            self._build_tree()
            self._lbl_status.setText(f'{self._device.name} — {len(self._device.peripherals)} 个外设')
        except Exception as e:
            self._lbl_status.setText(f'加载失败: {e}')

    def _build_tree(self):
        """Build the tree widget from SVD data."""
        self._tree.clear()
        if not self._device:
            return

        for periph in sorted(self._device.peripherals, key=lambda p: p.base_address):
            p_item = QTreeWidgetItem(self._tree)
            p_item.setText(0, periph.name)
            p_item.setText(1, f'0x{periph.base_address:08X}')
            p_item.setText(3, periph.description[:80])
            p_item.setData(0, Qt.UserRole, ('peripheral', periph))

            for reg in periph.registers:
                r_item = QTreeWidgetItem(p_item)
                r_item.setText(0, reg.name)
                r_item.setText(1, f'0x{periph.base_address + reg.address_offset:08X}')
                r_item.setText(3, reg.description[:60])
                r_item.setData(0, Qt.UserRole, ('register', periph, reg))

                for field in reg.fields:
                    f_item = QTreeWidgetItem(r_item)
                    f_item.setText(0, f'{reg.name}.{field.name}')
                    f_item.setText(3, f'[{field.bit_offset}:{field.bit_offset+field.bit_width-1}] {field.access}')
                    f_item.setData(0, Qt.UserRole, ('field', periph, reg, field))

    def _refresh_all(self):
        """Read current register values from MCU and update display."""
        if not self._probe or not self._device:
            return

        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            p_item = root.child(i)
            periph = p_item.data(0, Qt.UserRole)[1]

            for j in range(p_item.childCount()):
                r_item = p_item.child(j)
                reg = r_item.data(0, Qt.UserRole)[2]

                addr = periph.base_address + reg.address_offset
                try:
                    value = self._probe.read_U32(addr)
                except Exception:
                    r_item.setText(2, '???')
                    continue

                key = (periph.name, reg.name)
                prev = self._prev_values.get(key, reg.reset_value)
                self._prev_values[key] = value

                r_item.setText(2, f'0x{value:08X}')

                # Update field values
                for k in range(r_item.childCount()):
                    f_item = r_item.child(k)
                    field = f_item.data(0, Qt.UserRole)[3]
                    fv = field.extract(value)
                    f_item.setText(2, f'0x{fv:X}')

                    # Highlight changed fields
                    pv = field.extract(prev)
                    if fv != pv:
                        f_item.setForeground(2, QtGui.QColor(self.COLOR_CHANGED))
                    else:
                        f_item.setForeground(2, QtGui.QColor(self.COLOR_UNCHANGED))

    def _on_item_selected(self, current, previous):
        """Show detail for selected item."""
        if not current:
            return

        data = current.data(0, Qt.UserRole)
        if not data:
            return

        if data[0] == 'register':
            periph, reg = data[1], data[2]
            addr = periph.base_address + reg.address_offset
            self._lbl_detail.setText(
                f'<b>{periph.name}.{reg.name}</b><br>'
                f'地址: 0x{addr:08X}<br>'
                f'大小: {reg.size}位<br>'
                f'复位值: 0x{reg.reset_value:08X}<br>'
                f'访问: {reg.access}<br><br>'
                f'{reg.description}'
            )

            # Show field table
            lines = [f'{"字段":<20} {"位域":<12} {"访问":<12} {"值":<10}']
            lines.append('─' * 60)
            for field in reg.fields:
                bit_range = f'[{field.bit_offset}:{field.bit_offset+field.bit_width-1}]'
                lines.append(f'{field.name:<20} {bit_range:<12} {field.access:<12}')
            self._txt_fields.setText('\n'.join(lines))

        elif data[0] == 'field':
            periph, reg, field = data[1], data[2], data[3]
            self._lbl_detail.setText(
                f'<b>{periph.name}.{reg.name}.{field.name}</b><br>'
                f'位域: [{field.bit_offset}:{field.bit_offset+field.bit_width-1}]<br>'
                f'宽度: {field.bit_width}位<br>'
                f'访问: {field.access}<br><br>'
                f'{field.description}'
            )
            self._txt_fields.clear()

    def _on_auto_refresh(self, state):
        self._auto_refresh = (state == Qt.Checked)
        if self._auto_refresh:
            self._timer.start()
        else:
            self._timer.stop()
```

- [ ] **Step 3: Verify widget imports**

```powershell
python -c "from widgets.register_viewer import RegisterViewer; print('RegisterViewer OK')"
```

- [ ] **Step 4: Commit**

```powershell
git add widgets/__init__.py widgets/register_viewer.py
git commit -m "feat: add SVD-based register viewer widget with live values"
```

---

### Task 3: Memory Hex Viewer Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\memory_viewer.py`

**Interfaces:**
- Consumes: `DebugProbe.read_mem_U8()`, `DebugProbe.write_U8()`
- Produces: `MemoryViewer` QWidget with hex dump display

- [ ] **Step 1: Create MemoryViewer**

```python
# E:\MCU\BSP\RTTView\widgets\memory_viewer.py
"""Hex memory viewer/editor for MCU memory inspection.

Displays memory as hex dump with address + hex + ASCII columns.
Supports goto address, search, edit, and auto-refresh.
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QComboBox, QCheckBox
)


class MemoryViewer(QWidget):
    """Hex memory viewer with address/hex/ASCII display."""

    BYTES_PER_LINE = 16

    # Region colors
    COLOR_FLASH = '#264F78'
    COLOR_SRAM = '#1E3A1E'
    COLOR_PERIPH = '#3A3A1E'
    COLOR_DEFAULT = '#252526'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._base_addr = 0x20000000
        self._length = 256
        self._data = []
        self._auto_refresh = False

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel('地址:'))
        self._inp_addr = QLineEdit('0x20000000')
        self._inp_addr.setMaximumWidth(120)
        toolbar.addWidget(self._inp_addr)

        toolbar.addWidget(QLabel('长度:'))
        self._inp_len = QLineEdit('256')
        self._inp_len.setMaximumWidth(60)
        toolbar.addWidget(self._inp_len)

        self._btn_go = QPushButton('跳转')
        self._btn_go.clicked.connect(self._on_goto)
        toolbar.addWidget(self._btn_go)

        self._btn_refresh = QPushButton('刷新')
        self._btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self._btn_refresh)

        self._chk_auto = QCheckBox('自动刷新')
        self._chk_auto.stateChanged.connect(self._on_auto_refresh)
        toolbar.addWidget(self._chk_auto)

        # Edit mode
        self._chk_edit = QCheckBox('编辑模式')
        toolbar.addWidget(self._chk_edit)

        toolbar.addStretch()
        self._lbl_status = QLabel('')
        toolbar.addWidget(self._lbl_status)

        layout.addLayout(toolbar)

        # ── Hex display ──
        self._txt_hex = QTextEdit()
        self._txt_hex.setReadOnly(True)
        self._txt_hex.setFont(QtGui.QFont('Consolas', 10))
        self._txt_hex.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        layout.addWidget(self._txt_hex)

        # ── Goto shortcuts ──
        quick = QHBoxLayout()
        for name, addr in [('Flash', '0x08000000'), ('SRAM', '0x20000000'),
                           ('Periph', '0x40000000'), ('Stack', '0x20010000')]:
            btn = QPushButton(name)
            btn.setMaximumWidth(80)
            btn.clicked.connect(lambda _, a=addr: self._goto(a))
            quick.addWidget(btn)
        quick.addStretch()
        layout.addLayout(quick)

        # ── Timer ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)

    def set_probe(self, probe):
        self._probe = probe

    def _goto(self, addr_str):
        self._inp_addr.setText(addr_str)
        self._on_goto()

    @pyqtSlot()
    def _on_goto(self):
        try:
            addr = int(self._inp_addr.text(), 0)
            length = int(self._inp_len.text(), 0)
            self._base_addr = addr
            self._length = min(length, 4096)  # cap at 4KB
            self._refresh()
        except ValueError:
            self._lbl_status.setText('地址格式错误')

    def _refresh(self):
        if not self._probe:
            return

        try:
            self._data = self._probe.read_mem_U8(self._base_addr, self._length)
            self._render()
            self._lbl_status.setText(f'读取 {len(self._data)} 字节')
        except Exception as e:
            self._lbl_status.setText(f'读取失败: {e}')

    def _render(self):
        lines = []
        lines.append(f'<pre style="font-family:Consolas,monospace;font-size:10pt;color:#D4D4D4;">')

        # Header
        header = '<span style="color:#569CD6;">地址       </span>'
        for i in range(self.BYTES_PER_LINE):
            header += f'<span style="color:#569CD6;">{i:02X} </span>'
        header += ' <span style="color:#569CD6;">ASCII</span>'
        lines.append(header)
        lines.append('<span style="color:#3C3C3C;">' + '─' * 75 + '</span>')

        for offset in range(0, len(self._data), self.BYTES_PER_LINE):
            addr = self._base_addr + offset
            chunk = self._data[offset:offset + self.BYTES_PER_LINE]

            # Address
            line = f'<span style="color:#DCDCAA;">{addr:08X}</span>  '

            # Hex bytes
            for i, b in enumerate(chunk):
                # Color by memory region
                abs_addr = addr + i
                if 0x08000000 <= abs_addr < 0x08200000:
                    color = '#4EC9B0'  # flash = teal
                elif 0x20000000 <= abs_addr < 0x20030000:
                    color = '#B5CEA8'  # sram = green
                elif 0x40000000 <= abs_addr < 0x60000000:
                    color = '#CE9178'  # periph = orange
                else:
                    color = '#D4D4D4'

                line += f'<span style="color:{color};">{b:02X}</span> '
                if i == 7:
                    line += ' '

            # Padding if less than 16 bytes
            for i in range(len(chunk), self.BYTES_PER_LINE):
                line += '   '
                if i == 7:
                    line += ' '

            # ASCII
            line += ' <span style="color:#808080;">|</span>'
            ascii_str = ''
            for b in chunk:
                if 32 <= b < 127:
                    ascii_str += chr(b)
                else:
                    ascii_str += '.'
            line += f'<span style="color:#808080;">{ascii_str}</span>'
            line += '<span style="color:#808080;">|</span>'

            lines.append(line)

        lines.append('</pre>')
        self._txt_hex.setHtml('\n'.join(lines))

    def _on_auto_refresh(self, state):
        self._auto_refresh = (state == Qt.Checked)
        if self._auto_refresh:
            self._timer.start()
        else:
            self._timer.stop()
```

- [ ] **Step 2: Verify import**

```powershell
python -c "from widgets.memory_viewer import MemoryViewer; print('MemoryViewer OK')"
```

- [ ] **Step 3: Commit**

```powershell
git add widgets/memory_viewer.py
git commit -m "feat: add hex memory viewer with region coloring and auto-refresh"
```

---

### Task 4: Core Register Viewer Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\core_register_viewer.py`

**Interfaces:**
- Consumes: `DebugProbe.read_reg()`, `DebugProbe.read_regs()`
- Produces: `CoreRegisterViewer` QWidget

- [ ] **Step 1: Create CoreRegisterViewer**

```python
# E:\MCU\BSP\RTTView\widgets\core_register_viewer.py
"""Core register viewer for ARM Cortex-M and RISC-V CPUs.

Displays all CPU registers with decoded status fields.
ARM: R0-R12, SP, LR, PC, xPSR (with ISR number, Thumb bit, etc.)
RISC-V: x0-x31, pc, mstatus, mcause, mtval, etc.
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QCheckBox, QHeaderView, QGroupBox, QTextEdit
)


class CoreRegisterViewer(QWidget):
    """Core register viewer with decoded status fields."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._mode = 'arm'
        self._auto_refresh = False

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        self._btn_refresh = QPushButton('刷新寄存器')
        self._btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self._btn_refresh)

        self._chk_auto = QCheckBox('自动刷新')
        self._chk_auto.stateChanged.connect(self._on_auto_refresh)
        toolbar.addWidget(self._chk_auto)

        self._lbl_cpu = QLabel('CPU: --')
        toolbar.addWidget(self._lbl_cpu)
        toolbar.addStretch()

        layout.addLayout(toolbar)

        # ── Register table ──
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(['寄存器', '值', '说明'])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # ── Status decode panel ──
        self._grp_decode = QGroupBox('状态寄存器解码')
        decode_layout = QVBoxLayout(self._grp_decode)
        self._txt_decode = QTextEdit()
        self._txt_decode.setReadOnly(True)
        self._txt_decode.setFont(QtGui.QFont('Consolas', 10))
        self._txt_decode.setMaximumHeight(180)
        decode_layout.addWidget(self._txt_decode)
        layout.addWidget(self._grp_decode)

        # ── Timer ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(100)  # 10 Hz
        self._timer.timeout.connect(self._refresh)

    def set_probe(self, probe, mode='arm'):
        self._probe = probe
        self._mode = mode.lower()
        self._build_register_list()

    def _build_register_list(self):
        if self._mode.startswith('arm'):
            regs = [
                ('R0', ''), ('R1', ''), ('R2', ''), ('R3', ''),
                ('R4', ''), ('R5', ''), ('R6', ''), ('R7', ''),
                ('R8', ''), ('R9', ''), ('R10', ''), ('R11', ''),
                ('R12', ''), ('SP', '栈指针'), ('LR', '链接寄存器'),
                ('PC', '程序计数器'), ('xPSR', '程序状态'),
                ('MSP', '主栈指针'), ('PSP', '进程栈指针'),
            ]
        else:  # RISC-V
            regs = [
                ('x0', 'zero'), ('x1', 'ra'), ('x2', 'sp'), ('x3', 'gp'),
                ('x4', 'tp'), ('x5', 't0'), ('x6', 't1'), ('x7', 't2'),
                ('x8', 's0/fp'), ('x9', 's1'), ('x10', 'a0'), ('x11', 'a1'),
                ('x12', 'a2'), ('x13', 'a3'), ('x14', 'a4'), ('x15', 'a5'),
                ('x16', 'a6'), ('x17', 'a7'), ('x18', 's2'), ('x19', 's3'),
                ('x20', 's4'), ('x21', 's5'), ('x22', 's6'), ('x23', 's7'),
                ('x24', 's8'), ('x25', 's9'), ('x26', 's10'), ('x27', 's11'),
                ('x28', 't3'), ('x29', 't4'), ('x30', 't5'), ('x31', 't6'),
                ('pc', '程序计数器'), ('mstatus', '机器状态'),
                ('mcause', '异常原因'), ('mtval', '异常值'),
            ]

        self._table.setRowCount(len(regs))
        for i, (name, desc) in enumerate(regs):
            self._table.setItem(i, 0, QTableWidgetItem(name))
            self._table.setItem(i, 1, QTableWidgetItem('--'))
            self._table.setItem(i, 2, QTableWidgetItem(desc))

    def _refresh(self):
        if not self._probe:
            return

        try:
            for row in range(self._table.rowCount()):
                reg_name = self._table.item(row, 0).text()
                try:
                    val = self._probe.read_reg(reg_name.lower())
                    self._table.item(row, 1).setText(f'0x{val:08X}')
                except Exception:
                    self._table.item(row, 1).setText('???')

            # Decode status register
            self._decode_status()
        except Exception:
            pass

    def _decode_status(self):
        if self._mode.startswith('arm'):
            try:
                xpsr = self._probe.read_reg('xpsr')
                isr_num = xpsr & 0x1FF
                thumb = 'Thumb' if (xpsr & (1 << 24)) else 'ARM'
                n = 'N' if (xpsr & (1 << 31)) else '-'
                z = 'Z' if (xpsr & (1 << 30)) else '-'
                c = 'C' if (xpsr & (1 << 29)) else '-'
                v = 'V' if (xpsr & (1 << 28)) else '-'
                q = 'Q' if (xpsr & (1 << 27)) else '-'

                lines = [
                    f'xPSR = 0x{xpsr:08X}',
                    f'  异常号: {isr_num} ({self._exception_name(isr_num)})',
                    f'  指令集: {thumb}',
                    f'  标志位: {n}{z}{c}{v}{q}',
                    f'  ISR号: {(xpsr >> 9) & 0xFF}',
                ]
                self._txt_decode.setText('\n'.join(lines))
            except Exception:
                self._txt_decode.setText('无法读取xPSR')

        else:  # RISC-V
            try:
                mstatus = self._probe.read_reg('mstatus')
                mie = '开' if (mstatus & (1 << 3)) else '关'
                mpie = '1' if (mstatus & (1 << 7)) else '0'
                mpp = (mstatus >> 11) & 3

                lines = [
                    f'mstatus = 0x{mstatus:08X}',
                    f'  中断: {mie}',
                    f'  MPIE: {mpie}',
                    f'  MPP: {mpp}',
                ]
                self._txt_decode.setText('\n'.join(lines))
            except Exception:
                self._txt_decode.setText('无法读取mstatus')

    def _exception_name(self, num):
        names = {
            0: 'Thread', 1: 'Reset', 2: 'NMI', 3: 'HardFault',
            4: 'MemManage', 5: 'BusFault', 6: 'UsageFault',
            11: 'SVCall', 14: 'PendSV', 15: 'SysTick'
        }
        return names.get(num, f'IRQ{num - 16}')

    def _on_auto_refresh(self, state):
        self._auto_refresh = (state == Qt.Checked)
        if self._auto_refresh:
            self._timer.start()
        else:
            self._timer.stop()
```

- [ ] **Step 2: Commit**

```powershell
git add widgets/core_register_viewer.py
git commit -m "feat: add core register viewer with xPSR/mstatus decoding"
```

---

### Task 5: Integrate New Widgets into RTTView

**Files:**
- Modify: `E:\MCU\BSP\RTTView\RTTView.py` — add QTabWidget and new tabs

**Interfaces:**
- Consumes: `RegisterViewer`, `MemoryViewer`, `CoreRegisterViewer`
- Produces: Tab-based UI in main window

- [ ] **Step 1: Add tab widget to RTTView**

In `RTTView.__init__`, after the existing layout setup, add a QTabWidget that wraps the existing content and adds new tabs. The key change is:

```python
# In RTTView.__init__, after self.uic.loadUi('RTTView.ui', self):
# Replace the direct vLayout content with a QTabWidget

from widgets.register_viewer import RegisterViewer
from widgets.memory_viewer import MemoryViewer
from widgets.core_register_viewer import CoreRegisterViewer

# Create tab widget
self.tabWidget = QtWidgets.QTabWidget(self)

# Move existing RTT content into Tab 0
self.rttTab = QWidget()
rtt_layout = QVBoxLayout(self.rttTab)
# ... move existing widgets into rtt_layout ...

# Add new tabs
self.registerViewer = RegisterViewer()
self.tabWidget.addTab(self.registerViewer, '寄存器查看')

self.memoryViewer = MemoryViewer()
self.tabWidget.addTab(self.memoryViewer, '内存查看')

self.coreRegViewer = CoreRegisterViewer()
self.tabWidget.addTab(self.coreRegViewer, '核心寄存器')

# Insert tab widget into main layout
self.vLayout.insertWidget(0, self.tabWidget)
```

- [ ] **Step 2: Wire probe to new widgets after connection**

In `on_btnOpen_clicked`, after `self.xlk = xlink.XLink(probe)`:

```python
# Set probe for new widgets
self.registerViewer.set_probe(probe)
self.memoryViewer.set_probe(probe)
self.coreRegViewer.set_probe(probe, mode)
```

- [ ] **Step 3: Commit**

```powershell
git add RTTView.py
git commit -m "feat: integrate register viewer, memory viewer, and core register tabs"
```
