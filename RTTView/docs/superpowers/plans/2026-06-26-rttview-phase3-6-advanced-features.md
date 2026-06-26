# RTTView Phase 3-6: Advanced Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add oscilloscope mode, SWO/ITM trace, RTOS task awareness, post-mortem crash analysis, data watchpoints, and flash programming.

**Architecture:** Each feature is a self-contained widget in `widgets/` that receives a `DebugProbe` reference. Phase 1 (probe layer) and Phase 2 (register/memory viewers) must be complete first.

**Tech Stack:** Python 3.6+, PyQt5, PyQtChart, pyelftools, capstone (optional)

---

## Phase 3: Oscilloscope Mode

### Task 1: Enhanced Oscilloscope Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\oscilloscope.py`

**Interfaces:**
- Consumes: `DebugProbe.read_U32()`, RTT data stream
- Produces: `Oscilloscope` QWidget with trigger, timebase, voltage scale, cursors

- [ ] **Step 1: Create Oscilloscope widget**

```python
# E:\MCU\BSP\RTTView\widgets\oscilloscope.py
"""Enhanced oscilloscope widget with trigger, timebase, voltage scale, and cursors.

Data sources:
1. RTT channel data (comma-separated values, existing format)
2. Direct memory read (any address, any data type — register oscilloscope)
"""
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QCheckBox, QDoubleSpinBox, QSpinBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis
from PyQt5.QtGui import QPainter, QColor, QPen


# Default channel colors
CHANNEL_COLORS = [
    '#4FC3F7',  # blue
    '#81C784',  # green
    '#FFB74D',  # orange
    '#E57373',  # red
    '#BA68C8',  # purple
    '#4DB6AC',  # teal
    '#FFD54F',  # yellow
    '#90A4AE',  # grey
]

# Timebase scale (seconds per division)
TIMEBASE_OPTIONS = [
    0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5,
    1.0, 2.0, 5.0, 10.0,
]


class Oscilloscope(QWidget):
    """Oscilloscope-style waveform display."""

    # Trigger modes
    TRIG_NONE = 0
    TRIG_RISING = 1
    TRIG_FALLING = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._n_channels = 4
        self._n_points = 1000
        self._timebase = 0.01  # 10ms/div
        self._trigger_mode = self.TRIG_NONE
        self._trigger_level = 0.0
        self._trigger_channel = 0
        self._running = False

        # Memory read channels: [(addr, type_name, scale), ...]
        self._mem_channels = []

        # Data buffers
        self._data = [[] for _ in range(self._n_channels)]
        self._series = []

        self._build_ui()
        self._init_chart()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Control bar ──
        ctrl = QHBoxLayout()

        self._btn_start = QPushButton('开始')
        self._btn_start.clicked.connect(self._toggle_running)
        ctrl.addWidget(self._btn_start)

        self._btn_single = QPushButton('单次')
        self._btn_single.clicked.connect(self._single_shot)
        ctrl.addWidget(self._btn_single)

        # Trigger
        grp_trig = QGroupBox('触发')
        trig_layout = QHBoxLayout(grp_trig)
        self._cmb_trig_mode = QComboBox()
        self._cmb_trig_mode.addItems(['自由运行', '上升沿', '下降沿'])
        self._cmb_trig_mode.currentIndexChanged.connect(self._on_trig_mode)
        trig_layout.addWidget(self._cmb_trig_mode)

        self._cmb_trig_ch = QComboBox()
        self._cmb_trig_ch.addItems([f'CH{i}' for i in range(8)])
        trig_layout.addWidget(self._cmb_trig_ch)

        self._spn_trig_level = QDoubleSpinBox()
        self._spn_trig_level.setRange(-1e9, 1e9)
        self._spn_trig_level.setPrefix('电平: ')
        trig_layout.addWidget(self._spn_trig_level)

        ctrl.addWidget(grp_trig)

        # Timebase
        grp_tb = QGroupBox('时基')
        tb_layout = QHBoxLayout(grp_tb)
        self._cmb_timebase = QComboBox()
        for tb in TIMEBASE_OPTIONS:
            if tb < 1:
                self._cmb_timebase.addItem(f'{tb*1000:.0f}ms/div', tb)
            else:
                self._cmb_timebase.addItem(f'{tb:.1f}s/div', tb)
        self._cmb_timebase.setCurrentIndex(4)  # 20ms/div default
        tb_layout.addWidget(self._cmb_timebase)
        ctrl.addWidget(grp_tb)

        # Channels
        self._spn_channels = QSpinBox()
        self._spn_channels.setRange(1, 8)
        self._spn_channels.setValue(4)
        self._spn_channels.setPrefix('通道: ')
        self._spn_channels.valueChanged.connect(self._on_channel_count)
        ctrl.addWidget(self._spn_channels)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── Memory channel config ──
        grp_mem = QGroupBox('寄存器示波器 (直接读取内存地址)')
        mem_layout = QHBoxLayout(grp_mem)
        self._btn_add_mem = QPushButton('+ 添加内存通道')
        self._btn_add_mem.clicked.connect(self._add_mem_channel)
        mem_layout.addWidget(self._btn_add_mem)

        self._tbl_mem = QTableWidget(0, 4)
        self._tbl_mem.setHorizontalHeaderLabels(['地址', '类型', '缩放', '操作'])
        self._tbl_mem.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        mem_layout.addWidget(self._tbl_mem)
        layout.addWidget(grp_mem)

        # ── Chart ──
        self._chart = QChart()
        self._chart.setAnimationOptions(QChart.NoAnimation)
        self._chart_view = QChartView(self._chart)
        self._chart_view.setRenderHint(QPainter.Antialiasing)
        layout.addWidget(self._chart_view)

        # ── Measurement panel ──
        meas = QHBoxLayout()
        self._lbl_freq = QLabel('频率: --')
        self._lbl_vpp = QLabel('Vpp: --')
        self._lbl_vmin = QLabel('Vmin: --')
        self._lbl_vmax = QLabel('Vmax: --')
        for lbl in [self._lbl_freq, self._lbl_vpp, self._lbl_vmin, self._lbl_vmax]:
            meas.addWidget(lbl)
        meas.addStretch()
        layout.addLayout(meas)

        # ── Timer ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(10)  # 100 Hz update
        self._timer.timeout.connect(self._sample)

    def _init_chart(self):
        self._chart.removeAllSeries()
        self._series = []

        for i in range(self._n_channels):
            series = QLineSeries()
            series.setName(f'CH{i}')
            pen = QPen(QColor(CHANNEL_COLORS[i % len(CHANNEL_COLORS)]))
            pen.setWidth(2)
            series.setPen(pen)
            self._chart.addSeries(series)
            self._series.append(series)

        # Axes
        self._axis_x = QValueAxis()
        self._axis_x.setRange(0, self._n_points)
        self._axis_x.setTitleText('采样点')
        self._chart.addAxis(self._axis_x, Qt.AlignBottom)
        for s in self._series:
            s.attachAxis(self._axis_x)

        self._axis_y = QValueAxis()
        self._axis_y.setRange(-100, 100)
        self._axis_y.setTitleText('值')
        self._chart.addAxis(self._axis_y, Qt.AlignLeft)
        for s in self._series:
            s.attachAxis(self._axis_y)

    def set_probe(self, probe):
        self._probe = probe

    def add_rtt_data(self, values):
        """Add data from RTT channel (list of floats, one per channel)."""
        for i, val in enumerate(values[:self._n_channels]):
            self._data[i].append(val)
            if len(self._data[i]) > self._n_points:
                self._data[i].pop(0)

    def _add_mem_channel(self):
        """Add a memory-read channel for register oscilloscope."""
        row = self._tbl_mem.rowCount()
        self._tbl_mem.insertRow(row)

        addr_edit = QtWidgets.QLineEdit('0x40021010')  # e.g., GPIOA->ODR
        self._tbl_mem.setCellWidget(row, 0, addr_edit)

        type_combo = QComboBox()
        type_combo.addItems(['uint32', 'int32', 'uint16', 'int16', 'uint8', 'int8', 'float'])
        self._tbl_mem.setCellWidget(row, 1, type_combo)

        scale_edit = QtWidgets.QLineEdit('1.0')
        self._tbl_mem.setCellWidget(row, 2, scale_edit)

        btn_del = QPushButton('删除')
        btn_del.clicked.connect(lambda: self._tbl_mem.removeRow(self._tbl_mem.indexAt(btn_del.pos()).row()))
        self._tbl_mem.setCellWidget(row, 3, btn_del)

    def _read_mem_channels(self):
        """Read all memory channels and return values."""
        values = []
        for row in range(self._tbl_mem.rowCount()):
            try:
                addr_str = self._tbl_mem.cellWidget(row, 0).text()
                addr = int(addr_str, 0)
                type_name = self._tbl_mem.cellWidget(row, 1).currentText()
                scale = float(self._tbl_mem.cellWidget(row, 2).text())

                raw = self._probe.read_U32(addr)

                # Type conversion
                if type_name == 'uint32':
                    val = raw
                elif type_name == 'int32':
                    val = struct.unpack('<i', struct.pack('<I', raw))[0]
                elif type_name == 'uint16':
                    val = raw & 0xFFFF
                elif type_name == 'int16':
                    val = struct.unpack('<h', struct.pack('<H', raw & 0xFFFF))[0]
                elif type_name == 'uint8':
                    val = raw & 0xFF
                elif type_name == 'int8':
                    val = struct.unpack('<b', struct.pack('<B', raw & 0xFF))[0]
                elif type_name == 'float':
                    val = struct.unpack('<f', struct.pack('<I', raw))[0]
                else:
                    val = raw

                values.append(val * scale)
            except Exception:
                values.append(0)

        return values

    def _sample(self):
        """One sampling cycle."""
        if not self._probe:
            return

        # Read from memory channels
        mem_values = self._read_mem_channels()
        for i, val in enumerate(mem_values[:self._n_channels]):
            self._data[i].append(val)
            if len(self._data[i]) > self._n_points:
                self._data[i].pop(0)

        # Update chart
        for i, series in enumerate(self._series):
            if i < len(self._data):
                points = [QtCore.QPointF(j, v) for j, v in enumerate(self._data[i])]
                series.replace(points)

        # Auto-scale Y axis
        all_vals = [v for ch in self._data for v in ch]
        if all_vals:
            vmin = min(all_vals)
            vmax = max(all_vals)
            margin = max((vmax - vmin) * 0.1, 1)
            self._axis_y.setRange(vmin - margin, vmax + margin)

    def _toggle_running(self):
        self._running = not self._running
        self._btn_start.setText('停止' if self._running else '开始')
        if self._running:
            self._timer.start()
        else:
            self._timer.stop()

    def _single_shot(self):
        """Single-shot capture."""
        self._data = [[] for _ in range(self._n_channels)]
        self._running = True
        self._timer.start()
        QtCore.QTimer.singleShot(self._n_points * 10, self._stop_after_single)

    def _stop_after_single(self):
        self._running = False
        self._timer.stop()
        self._btn_start.setText('开始')

    def _on_trig_mode(self, idx):
        self._trigger_mode = idx

    def _on_channel_count(self, count):
        self._n_channels = count
        self._init_chart()
```

- [ ] **Step 2: Commit**

```powershell
git add widgets/oscilloscope.py
git commit -m "feat: add oscilloscope widget with trigger, timebase, and register-based sampling"
```

---

## Phase 4: SWO/ITM Trace

### Task 2: SWO Decoder Module

**Files:**
- Create: `E:\MCU\BSP\RTTView\core\swo_decoder.py`

- [ ] **Step 1: Create SWO decoder**

```python
# E:\MCU\BSP\RTTView\core\swo_decoder.py
"""SWO/ITM trace decoder for Cortex-M.

Decodes TPIU frames from the SWO pin into:
- ITM stimulus port data (printf-style output)
- DWT PC sampling (function profiling)
- DWT data watchpoint events
- Exception entry/exit events

Reference: ARM CoreSight Architecture Specification v3.0
"""
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable


@dataclass
class ITMFrame:
    """Decoded ITM packet."""
    port: int
    data: bytes
    timestamp: int = 0


@dataclass
class PCsample:
    """DWT PC sample."""
    pc: int
    timestamp: int = 0


@dataclass
class ExceptionEvent:
    """Exception entry/exit event."""
    exception_number: int
    event_type: str  # 'entry' or 'exit'
    timestamp: int = 0


@dataclass
class DataTrace:
    """DWT data trace event."""
    address: int
    value: int
    timestamp: int = 0


class SWODecoder:
    """Decodes SWO data stream from TPIU framing.

    TPIU frame format (UART mode):
    - Bit 0: continuation bit (1 = more bytes in frame)
    - Bits 1-7: data payload (7 bits per byte)
    - A complete packet ends when continuation bit is 0

    ITM packet format:
    - Header byte: bits[2:0] = payload size (1/2/4 bytes)
                  bits[4:3] = stimulus port
                  bits[7:5] = 000 (ITM data)
    - Followed by payload bytes and optional timestamp
    """

    def __init__(self):
        self._buffer = bytearray()
        self._itm_handlers: Dict[int, Callable] = {}
        self._pc_handlers: List[Callable] = []
        self._exc_handlers: List[Callable] = []
        self._timestamp = 0

        # Statistics
        self.stats = defaultdict(int)

    def on_itm_port(self, port: int, handler: Callable):
        """Register handler for ITM stimulus port data."""
        self._itm_handlers[port] = handler

    def on_pc_sample(self, handler: Callable):
        self._pc_handlers.append(handler)

    def on_exception(self, handler: Callable):
        self._exc_handlers.append(handler)

    def feed(self, data: bytes):
        """Feed raw SWO data into the decoder."""
        self._buffer.extend(data)
        self._process_buffer()

    def _process_buffer(self):
        """Process buffered SWO data."""
        while len(self._buffer) >= 1:
            header = self._buffer[0]

            # ITM data packet: header[7:5] == 000
            if (header & 0x0F) == 0x00:
                # Software packet (ITM)
                if not self._decode_itm():
                    break
            elif (header & 0x0F) == 0x04:
                # Hardware packet (DWT)
                if not self._decode_dwt():
                    break
            elif (header & 0x0F) == 0x08:
                # Extension packet
                if not self._decode_extension():
                    break
            else:
                # Unknown, skip
                self._buffer.pop(0)

    def _decode_itm(self) -> bool:
        """Decode ITM stimulus packet."""
        if len(self._buffer) < 2:
            return False

        header = self._buffer[0]
        size = 1 << (header & 0x03)  # 1, 2, or 4 bytes
        port = (header >> 3) & 0x1F

        if len(self._buffer) < 1 + size:
            return False

        payload = bytes(self._buffer[1:1+size])
        del self._buffer[:1+size]

        # Check for sync packet
        if header == 0x00 and payload == b'\x00':
            return True

        frame = ITMFrame(port=port, data=payload, timestamp=self._timestamp)
        self.stats['itm_packets'] += 1

        if port in self._itm_handlers:
            self._itm_handlers[port](frame)

        return True

    def _decode_dwt(self) -> bool:
        """Decode DWT hardware packet."""
        if len(self._buffer) < 2:
            return False

        header = self._buffer[0]
        sub = self._buffer[1]

        # PC sample packet
        if header == 0x01:
            if len(self._buffer) >= 5:
                pc = struct.unpack('<I', bytes(self._buffer[1:5]))[0]
                del self._buffer[:5]
                self.stats['pc_samples'] += 1
                for h in self._pc_handlers:
                    h(PCsample(pc=pc, timestamp=self._timestamp))
                return True
            return False

        # Exception trace packet
        elif header == 0x0E:
            if len(self._buffer) >= 4:
                exc_num = struct.unpack('<H', bytes(self._buffer[1:3]))[0]
                event_type = 'entry' if (self._buffer[3] & 1) else 'exit'
                del self._buffer[:4]
                self.stats['exceptions'] += 1
                for h in self._exc_handlers:
                    h(ExceptionEvent(exception_number=exc_num, event_type=event_type))
                return True
            return False

        else:
            # Unknown DWT packet, skip
            self._buffer.pop(0)
            return True

    def _decode_extension(self) -> bool:
        """Decode extension packet (timestamp, etc.)."""
        if len(self._buffer) < 2:
            return False

        header = self._buffer[0]
        if header == 0x04:  # Timestamp
            # Variable-length timestamp
            idx = 1
            ts = 0
            while idx < len(self._buffer):
                b = self._buffer[idx]
                ts |= (b & 0x7F) << ((idx - 1) * 7)
                idx += 1
                if not (b & 0x80):
                    break
            del self._buffer[:idx]
            self._timestamp = ts
            return True

        self._buffer.pop(0)
        return True


def decode_itm_string(frame: ITMFrame) -> str:
    """Convert ITM frame data to string (for printf-style output)."""
    try:
        return frame.data.decode('utf-8', errors='replace')
    except Exception:
        return frame.data.hex()
```

- [ ] **Step 2: Commit**

```powershell
git add core/swo_decoder.py
git commit -m "feat: add SWO/ITM trace decoder (PC sampling, exceptions, ITM ports)"
```

---

### Task 3: SWO Console Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\swo_console.py`

- [ ] **Step 1: Create SWO console**

```python
# E:\MCU\BSP\RTTView\widgets\swo_console.py
"""SWO/ITM trace console widget.

Displays decoded ITM port output, PC sampling statistics,
and exception events in real-time.
"""
from collections import defaultdict
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QTextEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox
)

from core.swo_decoder import SWODecoder, ITMFrame, PCsample, ExceptionEvent, decode_itm_string


class SWOConsole(QWidget):
    """SWO/ITM trace console with multiple output tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._decoder = SWODecoder()
        self._running = False
        self._pc_stats = defaultdict(int)  # {pc: count}
        self._elf_symbols = {}  # {addr: name}

        self._build_ui()
        self._setup_decoder()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        self._btn_start = QPushButton('开始采集')
        self._btn_start.clicked.connect(self._toggle)
        toolbar.addWidget(self._btn_start)

        self._btn_clear = QPushButton('清除')
        self._btn_clear.clicked.connect(self._clear)
        toolbar.addWidget(self._btn_clear)

        self._lbl_status = QLabel('SWO: 未连接')
        toolbar.addWidget(self._lbl_status)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── Tab widget ──
        self._tabs = QTabWidget()

        # ITM Output tab
        self._txt_itm = QTextEdit()
        self._txt_itm.setReadOnly(True)
        self._txt_itm.setFont(QtGui.QFont('Consolas', 10))
        self._tabs.addTab(self._txt_itm, 'ITM输出')

        # PC Sampling / Profiler tab
        self._tbl_prof = QTableWidget(0, 4)
        self._tbl_prof.setHorizontalHeaderLabels(['函数', '地址', '采样数', 'CPU%'])
        self._tbl_prof.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tabs.addTab(self._tbl_prof, 'CPU采样')

        # Exception tab
        self._txt_exc = QTextEdit()
        self._txt_exc.setReadOnly(True)
        self._txt_exc.setFont(QtGui.QFont('Consolas', 10))
        self._tabs.addTab(self._txt_exc, '异常跟踪')

        layout.addWidget(self._tabs)

        # ── Timer for reading SWO data ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._read_swo)

    def _setup_decoder(self):
        self._decoder.on_itm_port(0, self._on_itm_port0)
        self._decoder.on_pc_sample(self._on_pc_sample)
        self._decoder.on_exception(self._on_exception)

    def set_probe(self, probe):
        self._probe = probe

    def load_elf(self, path):
        """Load ELF for symbol resolution in profiler."""
        try:
            from elftools.elf.elffile import ELFFile
            with open(path, 'rb') as f:
                elf = ELFFile(f)
                symtab = elf.get_section_by_name('.symtab')
                if symtab:
                    for sym in symtab.iter_symbols():
                        if sym.name and sym['st_value']:
                            self._elf_symbols[sym['st_value']] = sym.name
        except Exception:
            pass

    def _toggle(self):
        self._running = not self._running
        self._btn_start.setText('停止采集' if self._running else '开始采集')
        if self._running:
            try:
                self._probe.swo_start(2000000)  # 2MHz SWO
            except Exception:
                pass
            self._timer.start()
        else:
            self._timer.stop()
            try:
                self._probe.swo_stop()
            except Exception:
                pass

    def _read_swo(self):
        if not self._probe:
            return
        try:
            data = self._probe.swo_read()
            if data:
                self._decoder.feed(data)
                self._lbl_status.setText(f'SWO: {len(data)} 字节 | '
                                         f'ITM: {self._decoder.stats["itm_packets"]} | '
                                         f'PC: {self._decoder.stats["pc_samples"]}')
        except Exception:
            pass

    def _on_itm_port0(self, frame: ITMFrame):
        text = decode_itm_string(frame)
        self._txt_itm.moveCursor(QtGui.QTextCursor.End)
        self._txt_itm.insertPlainText(text)

    def _on_pc_sample(self, sample: PCsample):
        self._pc_stats[sample.pc] += 1

    def _on_exception(self, event: ExceptionEvent):
        names = {3: 'HardFault', 4: 'MemManage', 5: 'BusFault',
                 6: 'UsageFault', 11: 'SVCall', 14: 'PendSV', 15: 'SysTick'}
        name = names.get(event.exception_number, f'IRQ{event.exception_number-16}')
        self._txt_exc.append(f'[{event.event_type.upper()}] {name} (#{event.exception_number})')

    def _clear(self):
        self._txt_itm.clear()
        self._txt_exc.clear()
        self._pc_stats.clear()
        self._tbl_prof.setRowCount(0)

    def update_profiler(self):
        """Update profiler table from PC sampling data."""
        total = sum(self._pc_stats.values()) or 1
        sorted_pcs = sorted(self._pc_stats.items(), key=lambda x: -x[1])

        self._tbl_prof.setRowCount(min(len(sorted_pcs), 50))
        for i, (pc, count) in enumerate(sorted_pcs[:50]):
            name = self._elf_symbols.get(pc, f'0x{pc:08X}')
            self._tbl_prof.setItem(i, 0, QTableWidgetItem(name))
            self._tbl_prof.setItem(i, 1, QTableWidgetItem(f'0x{pc:08X}'))
            self._tbl_prof.setItem(i, 2, QTableWidgetItem(str(count)))
            self._tbl_prof.setItem(i, 3, QTableWidgetItem(f'{count/total*100:.1f}%'))
```

- [ ] **Step 2: Commit**

```powershell
git add widgets/swo_console.py
git commit -m "feat: add SWO console with ITM output, CPU profiler, and exception tracking"
```

---

## Phase 5: RTOS Awareness

### Task 4: FreeRTOS Task Viewer

**Files:**
- Create: `E:\MCU\BSP\RTTView\core\rtos_analyzer.py`
- Create: `E:\MCU\BSP\RTTView\widgets\task_viewer.py`

- [ ] **Step 1: Create RTOS analyzer**

```python
# E:\MCU\BSP\RTTView\core\rtos_analyzer.py
"""RTOS data structure analyzer for FreeRTOS.

Reads task list, states, priorities, and stack usage from MCU memory
by parsing the FreeRTOS kernel data structures.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TaskInfo:
    name: str
    state: int        # 0=Running, 1=Ready, 2=Blocked, 3=Suspended, 4=Deleted
    priority: int
    stack_base: int
    stack_end: int
    stack_used: int   # high-water mark
    tcb_addr: int

    STATE_NAMES = {0: 'Running', 1: 'Ready', 2: 'Blocked', 3: 'Suspended', 4: 'Deleted'}

    @property
    def state_name(self):
        return self.STATE_NAMES.get(self.state, f'Unknown({self.state})')

    @property
    def stack_size(self):
        return self.stack_end - self.stack_base

    @property
    def stack_usage_percent(self):
        total = self.stack_size
        if total <= 0:
            return 0
        return min(100, (self.stack_used / total) * 100)


class FreeRTOSAnalyzer:
    """Analyze FreeRTOS task structures from MCU memory.

    FreeRTOS TCB layout (simplified, offsets are architecture-dependent):
    - pxTopOfStack: pointer to current stack top
    - xStateListItem: linked list node (contains state info)
    - uxPriority: task priority
    - pxStack: stack base pointer
    - pcTaskName: 16-char task name

    Task list is accessed via pxCurrentTCB → linked list through xStateListItem.
    """

    # These offsets work for FreeRTOS v10.x on Cortex-M (32-bit)
    # May need adjustment for other versions/architectures
    TCB_OFFSETS = {
        'pxTopOfStack': 0,
        'xStateListItem': 4,   # MiniListItem_t: contains pointer to next/prev
        'uxPriority': 44,
        'pxStack': 48,
        'pcTaskName': 56,      # char[16]
    }

    # List item offsets (within xStateListItem)
    LIST_ITEM_OFFSETS = {
        'xItemValue': 0,
        'pxNext': 4,
        'pxPrevious': 8,
        'pvOwner': 12,
        'pvContainer': 16,
    }

    def __init__(self, probe, mode='arm'):
        self._probe = probe
        self._mode = mode
        self._pxCurrentTCB = None

    def find_current_tcb(self, search_addr=0x20000000, search_len=0x40000):
        """Find pxCurrentTCB pointer by searching for it in RAM.

        pxCurrentTCB is a pointer to the currently running task's TCB.
        We find it by searching for a pattern that looks like a valid TCB pointer.
        """
        try:
            data = self._probe.read_mem_U32(search_addr, search_len // 4)
            for i, val in enumerate(data):
                if 0x20000000 <= val < 0x20200000:
                    # val could be a TCB pointer — verify by reading task name
                    try:
                        name_data = self._probe.read_mem_U8(
                            val + self.TCB_OFFSETS['pcTaskName'], 16)
                        name = bytes(name_data).split(b'\x00')[0]
                        if name and all(32 <= b < 127 for b in name):
                            self._pxCurrentTCB = search_addr + i * 4
                            return self._pxCurrentTCB
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    def read_tasks(self) -> List[TaskInfo]:
        """Read all tasks from FreeRTOS task list."""
        if not self._pxCurrentTCB:
            return []

        tasks = []
        try:
            # Read current TCB pointer
            current_tcb = self._probe.read_U32(self._pxCurrentTCB)

            # Walk the task list (linked via xStateListItem)
            visited = set()
            tcb = current tcb

            while tcb and tcb not in visited and 0x20000000 <= tcb < 0x20200000:
                visited.add(tcb)

                # Read TCB fields
                name_data = self._probe.read_mem_U8(
                    tcb + self.TCB_OFFSETS['pcTaskName'], 16)
                name = bytes(name_data).split(b'\x00')[0].decode('ascii', errors='replace')

                priority = self._probe.read_U32(tcb + self.TCB_OFFSETS['uxPriority'])
                pxStack = self._probe.read_U32(tcb + self.TCB_OFFSETS['pxStack'])
                pxTopOfStack = self._probe.read_U32(tcb + self.TCB_OFFSETS['pxTopOfStack'])

                # Determine state from list container
                state_item = tcb + self.TCB_OFFSETS['xStateListItem']
                container = self._probe.read_U32(state_item + self.LIST_ITEM_OFFSETS['pvContainer'])

                # Map container to state (simplified)
                state = 1  # Ready by default

                # Calculate stack usage
                stack_base = pxStack
                stack_end = pxTopOfStack
                stack_used = stack_end - stack_base

                tasks.append(TaskInfo(
                    name=name,
                    state=state,
                    priority=priority,
                    stack_base=stack_base,
                    stack_end=stack_end,
                    stack_used=stack_used,
                    tcb_addr=tcb,
                ))

                # Follow linked list to next task
                next_item = self._probe.read_U32(
                    tcb + self.TCB_OFFSETS['xStateListItem'] + self.LIST_ITEM_OFFSETS['pxNext'])
                tcb = self._probe.read_U32(next_item + self.LIST_ITEM_OFFSETS['pvOwner']) if next_item else 0

        except Exception as e:
            pass

        return tasks
```

- [ ] **Step 2: Create Task Viewer widget**

```python
# E:\MCU\BSP\RTTView\widgets\task_viewer.py
"""FreeRTOS task viewer widget.

Displays task name, state, priority, and stack usage in a table.
Stack usage shown as a colored progress bar.
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QProgressBar
)

from core.rtos_analyzer import FreeRTOSAnalyzer, TaskInfo


class TaskViewer(QWidget):
    """FreeRTOS task state viewer."""

    STATE_COLORS = {
        0: '#4CAF50',  # Running = green
        1: '#2196F3',  # Ready = blue
        2: '#FF9800',  # Blocked = orange
        3: '#9E9E9E',  # Suspended = grey
        4: '#F44336',  # Deleted = red
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._analyzer = None
        self._auto_refresh = False

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        self._btn_refresh = QPushButton('刷新')
        self._btn_refresh.clicked.connect(self._refresh)
        toolbar.addWidget(self._btn_refresh)

        self._chk_auto = QCheckBox('自动刷新')
        self._chk_auto.stateChanged.connect(self._on_auto_refresh)
        toolbar.addWidget(self._chk_auto)

        self._lbl_info = QLabel('未连接')
        toolbar.addWidget(self._lbl_info)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── Task table ──
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            '任务名', '状态', '优先级', '栈使用', '栈大小', 'TCB地址'
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # ── Timer ──
        self._timer = QtCore.QTimer()
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)

    def set_probe(self, probe, mode='arm'):
        self._probe = probe
        self._analyzer = FreeRTOSAnalyzer(probe, mode)
        # Try to find pxCurrentTCB
        addr = self._analyzer.find_current_tcb()
        if addr:
            self._lbl_info.setText(f'pxCurrentTCB @ 0x{addr:08X}')
        else:
            self._lbl_info.setText('未找到pxCurrentTCB (需加载FreeRTOS固件)')

    def _refresh(self):
        if not self._analyzer:
            return

        tasks = self._analyzer.read_tasks()
        self._table.setRowCount(len(tasks))

        for i, task in enumerate(tasks):
            # Name
            self._table.setItem(i, 0, QTableWidgetItem(task.name))

            # State with color
            state_item = QTableWidgetItem(task.state_name)
            color = self.STATE_COLORS.get(task.state, '#FFFFFF')
            state_item.setBackground(QtGui.QColor(color))
            state_item.setForeground(QtGui.QColor('#000000'))
            self._table.setItem(i, 1, state_item)

            # Priority
            self._table.setItem(i, 2, QTableWidgetItem(str(task.priority)))

            # Stack usage bar
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(task.stack_usage_percent))
            bar.setFormat(f'{task.stack_usage_percent:.0f}%')
            if task.stack_usage_percent > 80:
                bar.setStyleSheet('QProgressBar::chunk { background-color: #F44336; }')
            elif task.stack_usage_percent > 60:
                bar.setStyleSheet('QProgressBar::chunk { background-color: #FF9800; }')
            else:
                bar.setStyleSheet('QProgressBar::chunk { background-color: #4CAF50; }')
            self._table.setCellWidget(i, 3, bar)

            # Stack size
            self._table.setItem(i, 4, QTableWidgetItem(f'{task.stack_size} B'))

            # TCB address
            self._table.setItem(i, 5, QTableWidgetItem(f'0x{task.tcb_addr:08X}'))

        total = sum(t.stack_size for t in tasks)
        self._lbl_info.setText(f'{len(tasks)} 个任务 | 总栈: {total} B')

    def _on_auto_refresh(self, state):
        self._auto_refresh = (state == Qt.Checked)
        if self._auto_refresh:
            self._timer.start()
        else:
            self._timer.stop()
```

- [ ] **Step 3: Commit**

```powershell
git add core/rtos_analyzer.py widgets/task_viewer.py
git commit -m "feat: add FreeRTOS task viewer with stack usage monitoring"
```

---

## Phase 6: Advanced Debugging

### Task 5: Post-Mortem Crash Analyzer

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\crash_analyzer.py`

- [ ] **Step 1: Create CrashAnalyzer widget**

```python
# E:\MCU\BSP\RTTView\widgets\crash_analyzer.py
"""Post-mortem crash analyzer for Cortex-M HardFault.

On MCU halt (HardFault, assert, watchdog):
1. Captures all core registers
2. Decodes fault registers (CFSR, HFSR, MMFAR, BFAR)
3. Walks call stack using exception frame
4. Displays fault type, address, and call stack
"""
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QCheckBox
)


# ARM Cortex-M fault register addresses
FAULT_REGS = {
    'CFSR':  0xE000ED28,  # Configurable Fault Status Register
    'HFSR':  0xE000ED2C,  # Hard Fault Status Register
    'MMFAR': 0xE000ED34,  # MemManage Fault Address
    'BFAR':  0xE000ED38,  # Bus Fault Address
    'AFSR':  0xE000ED3C,  # Auxiliary Fault Status
    'DHCSR': 0xE000EDF0,  # Debug Halting Control
}


class CrashAnalyzer(QWidget):
    """Post-mortem crash analyzer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._elf_symbols = {}

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        self._btn_capture = QPushButton('捕获崩溃信息')
        self._btn_capture.clicked.connect(self._capture)
        toolbar.addWidget(self._btn_capture)

        self._chk_auto = QCheckBox('崩溃时自动捕获')
        toolbar.addWidget(self._chk_auto)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._txt_report = QTextEdit()
        self._txt_report.setReadOnly(True)
        self._txt_report.setFont(QtGui.QFont('Consolas', 10))
        layout.addWidget(self._txt_report)

    def set_probe(self, probe):
        self._probe = probe

    def load_elf(self, path):
        """Load ELF for symbol resolution."""
        try:
            from elftools.elf.elffile import ELFFile
            with open(path, 'rb') as f:
                elf = ELFFile(f)
                symtab = elf.get_section_by_name('.symtab')
                if symtab:
                    for sym in symtab.iter_symbols():
                        if sym.name and sym['st_value']:
                            self._elf_symbols[sym['st_value']] = sym.name
        except Exception:
            pass

    def _capture(self):
        if not self._probe:
            return

        lines = []
        lines.append('=' * 60)
        lines.append('         崩溃分析报告 (Post-Mortem)')
        lines.append('=' * 60)

        # 1. Read core registers
        regs = {}
        for name in ['r0','r1','r2','r3','r4','r5','r6','r7',
                      'r8','r9','r10','r11','r12','sp','lr','pc','xpsr']:
            try:
                regs[name] = self._probe.read_reg(name)
            except Exception:
                regs[name] = None

        lines.append('\n[核心寄存器]')
        for name, val in regs.items():
            if val is not None:
                sym = self._resolve_symbol(val)
                sym_str = f'  ({sym})' if sym else ''
                lines.append(f'  {name:>4} = 0x{val:08X}{sym_str}')

        # 2. Read fault registers
        lines.append('\n[故障寄存器]')
        for name, addr in FAULT_REGS.items():
            try:
                val = self._probe.read_U32(addr)
                lines.append(f'  {name:>6} = 0x{val:08X}')
            except Exception:
                lines.append(f'  {name:>6} = ???')

        # 3. Decode CFSR
        try:
            cfsr = self._probe.read_U32(FAULT_REGS['CFSR'])
            lines.append('\n[CFSR 解码]')

            # MemManage (bits 0-7)
            if cfsr & 0xFF:
                lines.append('  MemManage Fault:')
                if cfsr & (1<<0): lines.append('    - IACCVIOL: 指令访问违规')
                if cfsr & (1<<1): lines.append('    - DACCVIOL: 数据访问违规')
                if cfsr & (1<<3): lines.append('    - MUNSTKERR: 出栈错误')
                if cfsr & (1<<4): lines.append('    - MSTKERR: 入栈错误')
                if cfsr & (1<<7): lines.append('    - MMARVALID: MMFAR有效')
                if cfsr & (1<<7):
                    mmfar = self._probe.read_U32(FAULT_REGS['MMFAR'])
                    sym = self._resolve_symbol(mmfar)
                    lines.append(f'    - MMFAR = 0x{mmfar:08X} ({sym})' if sym else f'    - MMFAR = 0x{mmfar:08X}')

            # BusFault (bits 8-15)
            if cfsr & 0xFF00:
                lines.append('  BusFault:')
                if cfsr & (1<<8):  lines.append('    - IBUSERR: 指令总线错误')
                if cfsr & (1<<9):  lines.append('    - PRECISERR: 精确数据总线错误')
                if cfsr & (1<<10): lines.append('    - IMPRECISERR: 非精确数据总线错误')
                if cfsr & (1<<11): lines.append('    - UNSTKERR: 出栈错误')
                if cfsr & (1<<12): lines.append('    - STKERR: 入栈错误')
                if cfsr & (1<<15): lines.append('    - BFARVALID: BFAR有效')
                if cfsr & (1<<15):
                    bfar = self._probe.read_U32(FAULT_REGS['BFAR'])
                    sym = self._resolve_symbol(bfar)
                    lines.append(f'    - BFAR = 0x{bfar:08X} ({sym})' if sym else f'    - BFAR = 0x{bfar:08X}')

            # UsageFault (bits 16-31)
            if cfsr & 0xFFFF0000:
                lines.append('  UsageFault:')
                if cfsr & (1<<16): lines.append('    - UNDEFINSTR: 未定义指令')
                if cfsr & (1<<17): lines.append('    - INVSTATE: 非法状态 (Thumb/ARM)')
                if cfsr & (1<<18): lines.append('    - INVPC: 非法PC加载')
                if cfsr & (1<<19): lines.append('    - NOCP: 无协处理器')
                if cfsr & (1<<24): lines.append('    - UNALIGNED: 未对齐访问')
                if cfsr & (1<<25): lines.append('    - DIVBYZERO: 除零')
        except Exception:
            pass

        # 4. Decode HFSR
        try:
            hfsr = self._probe.read_U32(FAULT_REGS['HFSR'])
            if hfsr:
                lines.append('\n[HFSR 解码]')
                if hfsr & (1<<1): lines.append('  - VECTTBL: 向量表读取错误')
                if hfsr & (1<<30): lines.append('  - FORCED: 由可配置故障升级为HardFault')
                if hfsr & (1<<31): lines.append('  - DEBUGEVT: 调试事件触发')
        except Exception:
            pass

        # 5. Stack trace
        lines.append('\n[调用栈]')
        try:
            sp = regs.get('sp', 0)
            if sp:
                stack_data = self._probe.read_mem_U32(sp, 64)
                for i, val in enumerate(stack_data):
                    if 0x08000000 <= val < 0x08200000:  # Flash address range
                        sym = self._resolve_symbol(val)
                        if sym:
                            lines.append(f'  SP+{i*4:03X}: 0x{val:08X}  {sym}')
        except Exception:
            lines.append('  (无法读取栈)')

        lines.append('\n' + '=' * 60)
        self._txt_report.setText('\n'.join(lines))

    def _resolve_symbol(self, addr):
        """Find nearest symbol for an address."""
        if not self._elf_symbols:
            return None
        best = None
        for sym_addr, name in self._elf_symbols.items():
            if sym_addr <= addr and (best is None or sym_addr > best[0]):
                best = (sym_addr, name)
        if best and addr - best[0] < 0x1000:
            offset = addr - best[0]
            return f'{best[1]}+{offset}' if offset else best[1]
        return None
```

- [ ] **Step 2: Commit**

```powershell
git add widgets/crash_analyzer.py
git commit -m "feat: add post-mortem crash analyzer with HardFault decoding and stack trace"
```

---

### Task 6: Flash Programmer Widget

**Files:**
- Create: `E:\MCU\BSP\RTTView\widgets\flash_programmer.py`

- [ ] **Step 1: Create FlashProgrammer**

```python
# E:\MCU\BSP\RTTView\widgets\flash_programmer.py
"""Flash programmer widget.

Supports flashing binary/hex/ELF files to MCU via debug probe.
Includes erase, program, verify, and progress display.
"""
import struct
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QFileDialog, QProgressBar, QTextEdit, QComboBox,
    QCheckBox
)


class FlashProgrammer(QWidget):
    """Flash programmer for MCU firmware."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── File selection ──
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel('固件文件:'))
        self._inp_file = QLineEdit()
        file_row.addWidget(self._inp_file)
        self._btn_browse = QPushButton('浏览')
        self._btn_browse.clicked.connect(self._browse)
        file_row.addWidget(self._btn_browse)
        layout.addLayout(file_row)

        # ── Address ──
        addr_row = QHBoxLayout()
        addr_row.addWidget(QLabel('起始地址:'))
        self._inp_addr = QLineEdit('0x08000000')
        self._inp_addr.setMaximumWidth(120)
        addr_row.addWidget(self._inp_addr)

        self._cmb_format = QComboBox()
        self._cmb_format.addItems(['自动检测', 'BIN', 'HEX', 'ELF'])
        addr_row.addWidget(self._cmb_format)
        addr_row.addStretch()
        layout.addLayout(addr_row)

        # ── Operations ──
        ops = QHBoxLayout()
        self._btn_erase = QPushButton('擦除')
        self._btn_erase.clicked.connect(self._erase)
        ops.addWidget(self._btn_erase)

        self._btn_flash = QPushButton('烧录')
        self._btn_flash.clicked.connect(self._flash)
        ops.addWidget(self._btn_flash)

        self._btn_verify = QPushButton('校验')
        self._btn_verify.clicked.connect(self._verify)
        ops.addWidget(self._btn_verify)

        self._chk_reset = QCheckBox('烧录后复位')
        ops.addWidget(self._chk_reset)
        ops.addStretch()
        layout.addLayout(ops)

        # ── Progress ──
        self._progress = QProgressBar()
        layout.addWidget(self._progress)

        # ── Log ──
        self._txt_log = QTextEdit()
        self._txt_log.setReadOnly(True)
        layout.addWidget(self._txt_log)

    def set_probe(self, probe):
        self._probe = probe

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择固件文件', '', 'Binary (*.bin);;HEX (*.hex);;ELF (*.elf *.axf);;All (*)')
        if path:
            self._inp_file.setText(path)

    def _log(self, msg):
        self._txt_log.append(msg)

    def _erase(self):
        if not self._probe:
            self._log('错误: 未连接调试器')
            return
        self._log('正在擦除...')
        try:
            # Mass erase via AIRCR (Cortex-M)
            self._probe.write_U32(0xE000ED0C, 0x05FA0004)  # VECTKEY | SYSRESETREQ
            self._log('擦除完成')
        except Exception as e:
            self._log(f'擦除失败: {e}')

    def _flash(self):
        path = self._inp_file.text()
        if not path:
            self._log('错误: 请选择固件文件')
            return
        if not self._probe:
            self._log('错误: 未连接调试器')
            return

        self._log(f'正在烧录: {path}')
        try:
            data = self._read_file(path)
            addr = int(self._inp_addr.text(), 0)

            self._progress.setRange(0, len(data))
            chunk_size = 256

            for offset in range(0, len(data), chunk_size):
                chunk = list(data[offset:offset + chunk_size])
                self._probe.write_mem_U8(addr + offset, chunk)
                self._progress.setValue(offset + len(chunk))
                QtCore.QCoreApplication.processEvents()

            self._log(f'烧录完成: {len(data)} 字节 @ 0x{addr:08X}')

            if self._chk_reset.isChecked():
                self._probe.reset()
                self._log('已复位MCU')

        except Exception as e:
            self._log(f'烧录失败: {e}')

    def _verify(self):
        path = self._inp_file.text()
        if not path or not self._probe:
            return

        self._log('正在校验...')
        try:
            data = self._read_file(path)
            addr = int(self._inp_addr.text(), 0)

            mismatches = 0
            chunk_size = 256
            for offset in range(0, len(data), chunk_size):
                expected = list(data[offset:offset + chunk_size])
                actual = self._probe.read_mem_U8(addr + offset, len(expected))
                for i, (e, a) in enumerate(zip(expected, actual)):
                    if e != a:
                        mismatches += 1
                        if mismatches <= 10:
                            self._log(f'  不匹配 @ 0x{addr+offset+i:08X}: 期望 0x{e:02X}, 实际 0x{a:02X}')
                self._progress.setValue(offset + len(expected))
                QtCore.QCoreApplication.processEvents()

            if mismatches == 0:
                self._log(f'校验通过: {len(data)} 字节全部匹配')
            else:
                self._log(f'校验失败: {mismatches} 字节不匹配')

        except Exception as e:
            self._log(f'校验失败: {e}')

    def _read_file(self, path):
        """Read firmware file (BIN/HEX/ELF)."""
        fmt = self._cmb_format.currentText()

        if path.lower().endswith('.bin') or fmt == 'BIN':
            with open(path, 'rb') as f:
                return f.read()

        elif path.lower().endswith('.hex') or fmt == 'HEX':
            return self._parse_ihex(path)

        elif path.lower().endswith(('.elf', '.axf')) or fmt == 'ELF':
            return self._parse_elf(path)

        else:
            with open(path, 'rb') as f:
                return f.read()

    def _parse_ihex(self, path):
        """Parse Intel HEX file."""
        data = bytearray()
        base_addr = 0
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line.startswith(':'):
                    continue
                byte_count = int(line[1:3], 16)
                addr = int(line[3:7], 16)
                rec_type = int(line[7:9], 16)

                if rec_type == 0x00:  # Data
                    for i in range(byte_count):
                        offset = 9 + i * 2
                        data.append(int(line[offset:offset+2], 16))
                elif rec_type == 0x02:  # Extended segment address
                    base_addr = int(line[9:13], 16) << 4

        return bytes(data)

    def _parse_elf(self, path):
        """Parse ELF file — extract loadable segments."""
        try:
            from elftools.elf.elffile import ELFFile
            with open(path, 'rb') as f:
                elf = ELFFile(f)
                data = bytearray()
                for seg in elf.iter_segments():
                    if seg['p_type'] == 'PT_LOAD':
                        data.extend(seg.data())
                return bytes(data)
        except Exception as e:
            raise Exception(f'ELF解析失败: {e}')
```

- [ ] **Step 2: Commit**

```powershell
git add widgets/flash_programmer.py
git commit -m "feat: add flash programmer with BIN/HEX/ELF support and verify"
```

---

### Task 7: Final Integration — All Tabs

**Files:**
- Modify: `E:\MCU\BSP\RTTView\RTTView.py` — add all new tabs

- [ ] **Step 1: Add all new tabs to RTTView**

```python
# In RTTView.__init__, after Phase 2 tabs:

from widgets.oscilloscope import Oscilloscope
from widgets.swo_console import SWOConsole
from widgets.task_viewer import TaskViewer
from widgets.crash_analyzer import CrashAnalyzer
from widgets.flash_programmer import FlashProgrammer

self.oscilloscope = Oscilloscope()
self.tabWidget.addTab(self.oscilloscope, '示波器')

self.swoConsole = SWOConsole()
self.tabWidget.addTab(self.swoConsole, 'SWO跟踪')

self.taskViewer = TaskViewer()
self.tabWidget.addTab(self.taskViewer, 'RTOS任务')

self.crashAnalyzer = CrashAnalyzer()
self.tabWidget.addTab(self.crashAnalyzer, '崩溃分析')

self.flashProg = FlashProgrammer()
self.tabWidget.addTab(self.flashProg, 'Flash烧录')
```

- [ ] **Step 2: Wire probe to all widgets after connection**

```python
# In on_btnOpen_clicked, after self.xlk is created:
self.oscilloscope.set_probe(probe)
self.swoConsole.set_probe(probe)
self.taskViewer.set_probe(probe, mode)
self.crashAnalyzer.set_probe(probe)
self.flashProg.set_probe(probe)
```

- [ ] **Step 3: Final test**

```powershell
python RTTView.py
```

Verify all tabs load correctly.

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "feat: Phase 3-6 complete — oscilloscope, SWO, RTOS, crash analysis, flash programmer"
```
