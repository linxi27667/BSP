"""Register-based oscilloscope widget — reads MCU memory addresses
directly and plots waveforms in real time without firmware changes."""

import struct

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QSpinBox, QDoubleSpinBox, QLabel, QGroupBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis


# -- Channel colors (dark-theme friendly) ------------------------------------
CHANNEL_COLORS = [
    '#4FC3F7',  # blue
    '#81C784',  # green
    '#FFB74D',  # orange
    '#E57373',  # red
    '#CE93D8',  # purple
    '#4DB6AC',  # teal
    '#FFF176',  # yellow
    '#B0BEC5',  # grey
]

# -- Style constants ---------------------------------------------------------
COLOR_CHANGED = '#FF6B6B'
COLOR_DESC    = '#6A9955'
COLOR_VALUE   = '#B5CEA8'

TIMEBASE_ITEMS = [
    ("1 ms/div",    1),
    ("2 ms/div",    2),
    ("5 ms/div",    5),
    ("10 ms/div",  10),
    ("20 ms/div",  20),
    ("50 ms/div",  50),
    ("100 ms/div", 100),
    ("200 ms/div", 200),
    ("500 ms/div", 500),
    ("1 s/div",   1000),
    ("2 s/div",   2000),
    ("5 s/div",   5000),
    ("10 s/div", 10000),
]

TYPE_CONVERSIONS = {
    "uint32": lambda raw: raw,
    "int32":  lambda raw: struct.unpack('<i', struct.pack('<I', raw))[0],
    "float":  lambda raw: struct.unpack('<f', struct.pack('<I', raw))[0],
    "uint16": lambda raw: raw & 0xFFFF,
    "int16":  lambda raw: struct.unpack('<h', struct.pack('<H', raw & 0xFFFF))[0],
}

SAMPLE_INTERVAL_MS = 10   # 100 Hz sampling
DIVISIONS = 10            # 10 horizontal divisions


class Oscilloscope(QWidget):
    """Register-based oscilloscope — plots any MCU memory address as a waveform."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._running = False
        self._single_shot_pending = False
        self._single_shot_samples = 0
        self._sample_count = 0
        self._channels = []       # list of dicts: {addr, type, scale, series}
        self._mem_channels = []   # memory channel configs from table
        self._x_pos = 0           # rolling x position

        self._init_ui()
        self._init_chart()
        self._init_timer()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Control bar --------------------------------------------------
        ctrl = QHBoxLayout()

        self.btn_start = QPushButton("Start")
        self.btn_start.setFixedWidth(70)
        self.btn_start.clicked.connect(self._toggle_running)

        self.btn_single = QPushButton("Single")
        self.btn_single.setFixedWidth(70)
        self.btn_single.clicked.connect(self._single_shot)

        # Trigger group
        lbl_trig = QLabel("Trigger:")
        self.cmb_trig_mode = QComboBox()
        self.cmb_trig_mode.addItems(["Free", "Rising", "Falling"])
        self.cmb_trig_mode.setFixedWidth(75)

        self.cmb_trig_ch = QComboBox()
        for i in range(8):
            self.cmb_trig_ch.addItem(f"CH{i}")
        self.cmb_trig_ch.setFixedWidth(60)

        self.spin_trig_level = QDoubleSpinBox()
        self.spin_trig_level.setRange(-1e9, 1e9)
        self.spin_trig_level.setDecimals(2)
        self.spin_trig_level.setFixedWidth(100)
        self.spin_trig_level.setPrefix("Lvl: ")

        # Timebase
        lbl_tb = QLabel("Timebase:")
        self.cmb_timebase = QComboBox()
        for label, _ in TIMEBASE_ITEMS:
            self.cmb_timebase.addItem(label)
        self.cmb_timebase.setCurrentIndex(3)  # 10 ms/div default
        self.cmb_timebase.setFixedWidth(100)

        # Channel count
        lbl_ch = QLabel("Channels:")
        self.spin_ch_count = QSpinBox()
        self.spin_ch_count.setRange(1, 8)
        self.spin_ch_count.setValue(1)
        self.spin_ch_count.setFixedWidth(50)

        for w in (self.btn_start, self.btn_single,
                  lbl_trig, self.cmb_trig_mode, self.cmb_trig_ch,
                  self.spin_trig_level, lbl_tb, self.cmb_timebase,
                  lbl_ch, self.spin_ch_count):
            ctrl.addWidget(w)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # -- Memory channel config ----------------------------------------
        ch_group = QGroupBox("Memory Channels (MCU Address Reader)")
        ch_layout = QVBoxLayout(ch_group)
        ch_layout.setContentsMargins(4, 4, 4, 4)

        self.tbl_channels = QTableWidget(0, 5)
        self.tbl_channels.setHorizontalHeaderLabels(
            ["Address", "Type", "Scale", "Label", ""]
        )
        self.tbl_channels.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )
        self.tbl_channels.verticalHeader().setVisible(False)
        self.tbl_channels.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_channels.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._apply_table_style()
        ch_layout.addWidget(self.tbl_channels)

        btn_add = QPushButton("Add Memory Channel")
        btn_add.setFixedWidth(180)
        btn_add.clicked.connect(self._add_mem_channel)
        ch_layout.addWidget(btn_add)

        layout.addWidget(ch_group)

        # -- Measurement panel --------------------------------------------
        meas = QHBoxLayout()
        self.lbl_freq = QLabel("Freq: --")
        self.lbl_vpp  = QLabel("Vpp: --")
        self.lbl_vmin = QLabel("Vmin: --")
        self.lbl_vmax = QLabel("Vmax: --")
        for lbl in (self.lbl_freq, self.lbl_vpp, self.lbl_vmin, self.lbl_vmax):
            lbl.setStyleSheet(
                f"color: {COLOR_VALUE}; font-family: Consolas, monospace;"
                " font-size: 12px; padding: 2px 8px;"
            )
            meas.addWidget(lbl)
        meas.addStretch()
        layout.addLayout(meas)

        # -- Chart (most of the space) ------------------------------------
        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        layout.addWidget(self.chart_view, stretch=1)

    def _apply_table_style(self):
        self.tbl_channels.setStyleSheet("""
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

    # ------------------------------------------------------------------
    # Chart init
    # ------------------------------------------------------------------
    def _init_chart(self):
        self.chart = QChart()
        self.chart.setBackgroundBrush(QColor("#1E1E1E"))
        self.chart.setTitleBrush(QColor("#D4D4D4"))
        self.chart.setTitle("Oscilloscope")
        self.chart.legend().setLabelColor(QColor("#D4D4D4"))
        self.chart.legend().setVisible(True)
        self.chart.setAnimationOptions(QChart.NoAnimation)

        # Axes
        self._axis_x = QValueAxis()
        self._axis_x.setTitleText("Samples")
        self._axis_x.setTitleBrush(QColor("#D4D4D4"))
        self._axis_x.setLabelsBrush(QColor("#D4D4D4"))
        self._axis_x.setGridLineColor(QColor("#3C3C3C"))
        self._axis_x.setRange(0, DIVISIONS * 100)

        self._axis_y = QValueAxis()
        self._axis_y.setTitleText("Value")
        self._axis_y.setTitleBrush(QColor("#D4D4D4"))
        self._axis_y.setLabelsBrush(QColor("#D4D4D4"))
        self._axis_y.setGridLineColor(QColor("#3C3C3C"))
        self._axis_y.setRange(-100, 100)

        self.chart.addAxis(self._axis_x, Qt.AlignBottom)
        self.chart.addAxis(self._axis_y, Qt.AlignLeft)

        # Series (create up to 8, attach only those in use)
        self._series_list = []
        for i in range(8):
            series = QLineSeries()
            series.setName(f"CH{i}")
            series.setColor(QColor(CHANNEL_COLORS[i]))
            pen = series.pen()
            pen.setWidth(2)
            series.setPen(pen)
            self.chart.addSeries(series)
            series.attachAxis(self._axis_x)
            series.attachAxis(self._axis_y)
            self._series_list.append(series)

        self.chart_view.setChart(self.chart)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------
    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._sample)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe

    # ------------------------------------------------------------------
    # Slots: control bar
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _toggle_running(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self):
        if not self._probe:
            return
        self._running = True
        self._single_shot_pending = False
        self.btn_start.setText("Stop")
        self._timer.start()

    def _stop(self):
        self._running = False
        self._single_shot_pending = False
        self.btn_start.setText("Start")
        self._timer.stop()

    @pyqtSlot()
    def _single_shot(self):
        """Capture one full screen of samples, then stop."""
        if not self._probe:
            return
        self._single_shot_pending = True
        self._single_shot_samples = DIVISIONS * 100
        self._running = True
        self.btn_start.setText("Stop")
        # Clear existing data for a clean capture
        self._clear_series()
        self._x_pos = 0
        self._timer.start()

    # ------------------------------------------------------------------
    # Slots: memory channel table
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _add_mem_channel(self):
        """Add a row to the memory channel configuration table."""
        row = self.tbl_channels.rowCount()
        self.tbl_channels.insertRow(row)

        # Address column — editable hex placeholder
        addr_item = QTableWidgetItem("0x20000000")
        self.tbl_channels.setItem(row, 0, addr_item)

        # Type combo (embedded in cell via setCellWidget)
        from PyQt5.QtWidgets import QComboBox as CellCombo
        type_combo = CellCombo()
        type_combo.addItems(list(TYPE_CONVERSIONS.keys()))
        type_combo.setCurrentText("uint32")
        self.tbl_channels.setCellWidget(row, 1, type_combo)

        # Scale
        scale_item = QTableWidgetItem("1.0")
        self.tbl_channels.setItem(row, 2, scale_item)

        # Label
        label_item = QTableWidgetItem(f"CH{row}")
        self.tbl_channels.setItem(row, 3, label_item)

        # Delete button
        from PyQt5.QtWidgets import QPushButton as CellBtn
        btn_del = CellBtn("X")
        btn_del.setFixedWidth(30)
        btn_del.clicked.connect(lambda _, r=row: self._delete_mem_channel(r))
        self.tbl_channels.setCellWidget(row, 4, btn_del)

    def _delete_mem_channel(self, row):
        self.tbl_channels.removeRow(row)
        # Re-wire delete buttons since row indices changed
        for r in range(self.tbl_channels.rowCount()):
            btn = self.tbl_channels.cellWidget(r, 4)
            if btn:
                try:
                    btn.clicked.disconnect()
                except TypeError:
                    pass
                btn.clicked.connect(lambda _, rr=r: self._delete_mem_channel(rr))

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    def _sample(self):
        """Called by QTimer — read memory channels and update chart."""
        if not self._probe:
            return

        data = self._read_mem_channels()
        if not data:
            return

        # Append points to series
        num_active = min(len(data), self.spin_ch_count.value())
        for i in range(num_active):
            self._series_list[i].append(self._x_pos, data[i])

        self._x_pos += 1

        # Rolling window: keep ~screen worth of points
        max_points = DIVISIONS * 100
        if self._x_pos > max_points:
            x_min = self._x_pos - max_points
            self._axis_x.setRange(x_min, self._x_pos)
            # Trim old points from all series
            for i in range(num_active):
                s = self._series_list[i]
                while s.count() > 0 and s.at(0).x() < x_min:
                    s.remove(0)
        else:
            self._axis_x.setRange(0, max_points)

        # Auto-scale Y
        self._auto_scale_y(data[:num_active])

        # Update measurements
        self._update_measurements(data[:num_active])

        # Single-shot: stop after enough samples
        if self._single_shot_pending:
            self._single_shot_samples -= 1
            if self._single_shot_samples <= 0:
                self._single_shot_pending = False
                self._stop()

    def _read_mem_channels(self):
        """Read all configured memory addresses. Returns list[float]."""
        values = []
        rows = self.tbl_channels.rowCount()
        for r in range(rows):
            addr_text = self.tbl_channels.item(r, 0).text().strip()
            type_combo = self.tbl_channels.cellWidget(r, 1)
            scale_text = self.tbl_channels.item(r, 2).text().strip()

            try:
                addr = int(addr_text, 0)  # supports 0x prefix
            except ValueError:
                values.append(0.0)
                continue

            try:
                raw = self._probe.read_U32(addr)
            except Exception:
                values.append(0.0)
                continue

            type_name = type_combo.currentText() if type_combo else "uint32"
            convert = TYPE_CONVERSIONS.get(type_name, TYPE_CONVERSIONS["uint32"])
            converted = convert(raw)

            try:
                scale = float(scale_text)
            except ValueError:
                scale = 1.0

            values.append(converted * scale)

        return values

    def _auto_scale_y(self, data):
        """Adjust Y axis range to fit current data with some margin."""
        if not data:
            return
        y_min = min(data)
        y_max = max(data)
        margin = max(abs(y_max - y_min) * 0.1, 1.0)
        self._axis_y.setRange(y_min - margin, y_max + margin)

    def _update_measurements(self, data):
        """Update Vpp, Vmin, Vmax labels from latest sample window."""
        if not data:
            return

        # Gather recent points for each active channel
        num_active = len(data)
        for i in range(num_active):
            s = self._series_list[i]
            if s.count() < 2:
                continue
            vals = [s.at(j).y() for j in range(max(0, s.count() - 500), s.count())]
            if not vals:
                continue
            vmin = min(vals)
            vmax = max(vals)
            vpp = vmax - vmin
            self.lbl_vmin.setText(f"Vmin: {vmin:.2f}")
            self.lbl_vmax.setText(f"Vmax: {vmax:.2f}")
            self.lbl_vpp.setText(f"Vpp: {vpp:.2f}")

            # Simple zero-crossing frequency estimate
            crossings = 0
            mid = (vmin + vmax) / 2
            for k in range(1, len(vals)):
                if (vals[k - 1] < mid <= vals[k]) or (vals[k - 1] > mid >= vals[k]):
                    crossings += 1
            # Each full cycle has 2 crossings
            sample_period = SAMPLE_INTERVAL_MS / 1000.0  # seconds
            duration = len(vals) * sample_period
            if crossings >= 2 and duration > 0:
                freq = crossings / (2 * duration)
                self.lbl_freq.setText(f"Freq: {freq:.1f} Hz")
            else:
                self.lbl_freq.setText("Freq: --")
            break  # show measurements for first active channel only

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _clear_series(self):
        for s in self._series_list:
            s.clear()
