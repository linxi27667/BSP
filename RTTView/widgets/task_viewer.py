"""FreeRTOS task state viewer with stack usage monitoring."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
    QLabel, QTableWidget, QTableWidgetItem, QProgressBar, QHeaderView,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor, QFont

from core.rtos_analyzer import FreeRTOSAnalyzer, TaskInfo
from widgets.styles import (
    STACK_GREEN, STACK_ORANGE, STACK_RED,
    FONT_MONO, FONT_SIZE,
    table_style, toolbar_style, progress_bar_style,
)

# -- State color / name maps --------------------------------------------------
STATE_COLORS = {
    0: '#4CAF50',   # Running   - green
    1: '#2196F3',   # Ready     - blue
    2: '#FF9800',   # Blocked   - orange
    3: '#9E9E9E',   # Suspended - grey
    4: '#F44336',   # Deleted   - red
}

STATE_NAMES_CN = {
    0: "运行中",
    1: "就绪",
    2: "阻塞",
    3: "挂起",
    4: "已删除",
}


class TaskViewer(QWidget):
    """Widget that displays FreeRTOS task list with stack usage bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._analyzer = None

        self._init_ui()
        self._init_timer()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------
    def _init_ui(self):
        self.setStyleSheet(toolbar_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Toolbar row -------------------------------------------------
        toolbar = QHBoxLayout()

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setFixedWidth(80)
        self.btn_refresh.clicked.connect(self._on_refresh)

        self.chk_auto = QCheckBox("自动刷新")
        self.chk_auto.setChecked(False)
        self.chk_auto.stateChanged.connect(self._on_auto_toggle)

        self.lbl_info = QLabel("未连接探针")
        self.lbl_info.setStyleSheet("color: #808080; padding-left: 8px;")

        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.chk_auto)
        toolbar.addStretch()
        toolbar.addWidget(self.lbl_info)
        layout.addLayout(toolbar)

        # -- Task table --------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "任务名称", "状态", "优先级", "栈使用", "栈大小", "TCB地址"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(table_style())

        layout.addWidget(self.table)

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_refresh)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_probe(self, probe, mode='arm'):
        """Receive the DebugProbe instance after MCU connection."""
        self._probe = probe
        self._analyzer = FreeRTOSAnalyzer(probe, mode) if probe else None
        self.lbl_info.setText("已连接探针" if probe else "未连接探针")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot()
    def _on_refresh(self):
        """Read tasks from MCU and update table."""
        if not self._analyzer:
            self.lbl_info.setText("未连接探针")
            return

        try:
            tasks = self._analyzer.read_tasks()
        except Exception as e:
            self.lbl_info.setText(f"错误: {e}")
            return

        self._populate_table(tasks)
        self.lbl_info.setText(f"发现 {len(tasks)} 个任务")

    @pyqtSlot(int)
    def _on_auto_toggle(self, state):
        if state == Qt.Checked and self._probe:
            self._timer.start()
        else:
            self._timer.stop()

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------
    def _populate_table(self, tasks):
        self.table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            # Task Name
            name_item = QTableWidgetItem(task.name)
            name_item.setFont(QFont(FONT_MONO, 10))
            self.table.setItem(row, 0, name_item)

            # State (color-coded)
            state_cn = STATE_NAMES_CN.get(task.state, task.state_name)
            state_item = QTableWidgetItem(state_cn)
            state_item.setForeground(QColor(STATE_COLORS.get(task.state, '#D4D4D4')))
            state_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, state_item)

            # Priority
            pri_item = QTableWidgetItem(str(task.priority))
            pri_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, pri_item)

            # Stack Usage (progress bar)
            progress = QProgressBar()
            percent = min(100, int(task.stack_usage_percent))
            progress.setValue(percent)
            progress.setFormat(f"{percent}%")
            progress.setAlignment(Qt.AlignCenter)
            progress.setStyleSheet(self._progress_style(percent))
            self.table.setCellWidget(row, 3, progress)

            # Stack Size (total allocation, not just used)
            size_item = QTableWidgetItem(f"{task.stack_size} B")
            size_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, size_item)

            # TCB Address
            addr_item = QTableWidgetItem(f"0x{task.tcb_addr:08X}")
            addr_item.setFont(QFont(FONT_MONO, 10))
            self.table.setItem(row, 5, addr_item)

    def _progress_style(self, percent: int) -> str:
        if percent > 80:
            color = STACK_RED
        elif percent > 60:
            color = STACK_ORANGE
        else:
            color = STACK_GREEN

        base = progress_bar_style()
        return base.replace(
            "background-color: #4CAF50;",
            f"background-color: {color};"
        )
