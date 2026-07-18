#! python3
"""RTTView — Modern SEGGER RTT Viewer with Codex-style dark UI."""
import os
import re
import sys
import ctypes
import struct
import datetime
import collections
import configparser

# PyInstaller: use exe directory for writable files, _MEIPASS for bundled data
if getattr(sys, 'frozen', False):
    _APP_DIR = os.path.dirname(sys.executable)
    _DATA_DIR = sys._MEIPASS
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _DATA_DIR = _APP_DIR

os.chdir(_APP_DIR)

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QDialog, QFileDialog,
    QTableWidgetItem, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QTextEdit,
    QLineEdit, QTableWidget, QFrame, QStackedWidget, QSizePolicy,
    QDialogButtonBox, QGroupBox,
)
from PyQt5.QtChart import QChart, QChartView, QLineSeries

import ast
from core import xlink
from probes.jlink_probe import JLinkProbe
from probes.stlink_probe import STLinkProbe
from probes.daplink_probe import DAPLinkProbe
from probes.openocd_probe import OpenOCDProbe

os.environ['PATH'] = os.path.join(_DATA_DIR,
                                   'libusb-1.0.24/MinGW64/dll') + os.pathsep + os.environ['PATH']

# ─── RTT structures ───────────────────────────────────────────────────────────

class RingBuffer(ctypes.Structure):
    _fields_ = [
        ('sName',        ctypes.c_uint),
        ('pBuffer',      ctypes.c_uint),
        ('SizeOfBuffer', ctypes.c_uint),
        ('WrOff',        ctypes.c_uint),
        ('RdOff',        ctypes.c_uint),
        ('Flags',        ctypes.c_uint),
    ]

RTT_MAX_NUM_UP_BUFFERS = 3
RTT_MAX_NUM_DOWN_BUFFERS = 3

class SEGGER_RTT_CB(ctypes.Structure):
    _fields_ = [
        ('acID',              ctypes.c_char * 16),
        ('MaxNumUpBuffers',   ctypes.c_uint),
        ('MaxNumDownBuffers', ctypes.c_uint),
        ('aUp',               RingBuffer * RTT_MAX_NUM_UP_BUFFERS),
        ('aDown',             RingBuffer * RTT_MAX_NUM_DOWN_BUFFERS),
    ]

Variable = collections.namedtuple('Variable', 'name addr size')
Valuable = collections.namedtuple('Valuable', 'name addr size typ fmt show')
zero_if = lambda i: 0 if i == -1 else i

# ─── Color palette ────────────────────────────────────────────────────────────

C = {
    'bg':          '#0D1117',
    'bg_panel':    '#161B22',
    'bg_input':    '#0D1117',
    'bg_hover':    '#1C2333',
    'bg_active':   '#1F6FEB',
    'border':      '#30363D',
    'border_focus':'#58A6FF',
    'text':        '#C9D1D9',
    'text_dim':    '#8B949E',
    'text_bright': '#F0F6FC',
    'green':       '#3FB950',
    'red':         '#F85149',
    'orange':      '#D29922',
    'blue':        '#58A6FF',
    'purple':      '#BC8CFF',
    'cyan':        '#39D2C0',
    'sidebar_bg':  '#010409',
    'sidebar_icon':'#8B949E',
    'sidebar_active':'#58A6FF',
}

# ─── QSS theme ────────────────────────────────────────────────────────────────

GLOBAL_QSS = f"""
* {{
    font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
    font-size: 13px;
    color: {C['text']};
}}
QWidget {{
    background-color: {C['bg']};
}}
QMainWindow {{
    background-color: {C['bg']};
}}
QTextEdit, QPlainTextEdit {{
    background-color: {C['bg_panel']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {C['bg_active']};
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {C['border_focus']};
}}
QLineEdit {{
    background-color: {C['bg_input']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 28px;
}}
QLineEdit:focus {{
    border-color: {C['border_focus']};
}}
QPushButton {{
    background-color: {C['bg_panel']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 5px 14px;
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {C['bg_hover']};
    border-color: {C['text_dim']};
}}
QPushButton:pressed {{
    background-color: {C['bg_active']};
    color: {C['text_bright']};
}}
QPushButton:disabled {{
    color: {C['text_dim']};
    border-color: {C['border']};
    background-color: {C['bg']};
}}
QComboBox {{
    background-color: {C['bg_input']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 4px 10px;
    min-height: 28px;
}}
QComboBox:hover {{ border-color: {C['text_dim']}; }}
QComboBox:focus {{ border-color: {C['border_focus']}; }}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C['text_dim']};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C['bg_panel']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    selection-background-color: {C['bg_active']};
    selection-color: {C['text_bright']};
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 28px;
    padding: 4px 8px;
    border-radius: 4px;
}}
QCheckBox {{
    color: {C['text']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {C['border']};
    border-radius: 4px;
    background-color: {C['bg_input']};
}}
QCheckBox::indicator:hover {{ border-color: {C['border_focus']}; }}
QCheckBox::indicator:checked {{
    background-color: {C['bg_active']};
    border-color: {C['bg_active']};
}}
QLabel {{ color: {C['text']}; }}
QGroupBox {{
    color: {C['text_dim']};
    border: 1px solid {C['border']};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 14px;
    font-size: 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: {C['text_dim']};
}}
QTableWidget, QTreeWidget {{
    background-color: {C['bg_panel']};
    color: {C['text']};
    gridline-color: {C['border']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    font-size: 12px;
}}
QTableWidget::item, QTreeWidget::item {{
    padding: 3px 6px;
}}
QTableWidget::item:selected, QTreeWidget::item:selected {{
    background-color: {C['bg_active']};
}}
QHeaderView::section {{
    background-color: {C['bg_panel']};
    color: {C['text_dim']};
    border: none;
    border-bottom: 1px solid {C['border']};
    padding: 5px 8px;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {C['border']};
    min-height: 30px;
    border-radius: 5px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {C['text_dim']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {C['border']};
    min-width: 30px;
    border-radius: 5px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {C['text_dim']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QMenu {{
    background-color: {C['bg_panel']};
    color: {C['text']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 20px 5px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {C['bg_active']}; color: {C['text_bright']}; }}
QMenu::separator {{ height: 1px; background-color: {C['border']}; margin: 4px 8px; }}
QProgressBar {{
    background-color: {C['bg_input']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    text-align: center;
    color: {C['text']};
    font-size: 11px;
}}
QProgressBar::chunk {{
    background-color: {C['green']};
    border-radius: 3px;
}}
QTabWidget::pane {{
    border: 1px solid {C['border']};
    background-color: {C['bg']};
    border-radius: 6px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {C['text_dim']};
    border: none;
    padding: 6px 14px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {C['text_bright']};
    border-bottom: 2px solid {C['blue']};
}}
QTabBar::tab:hover:!selected {{ color: {C['text']}; }}
"""


# ─── Main Window ──────────────────────────────────────────────────────────────

class RTTView(QMainWindow):
    """Modern Codex-style SEGGER RTT Viewer."""

    SIDEBAR_ITEMS = [
        ('RTT',  '终端'),
        ('REG',  '寄存器'),
        ('MEM',  '内存'),
        ('CPU',  '核心'),
        ('OSC',  '示波器'),
        ('SWO',  'SWO'),
        ('RTOS', 'RTOS'),
        ('CRSH', '崩溃'),
        ('FLSH', '烧录'),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle('RTTView')
        self.resize(1100, 750)
        self.setMinimumSize(800, 500)

        icon_path = os.path.join(_DATA_DIR, 'Image', 'serial.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QtGui.QIcon(icon_path))

        self._connected = False
        self.rcvbuff = b''
        self.rcvfile = None
        self._rx_bytes = 0
        self.elffile = None
        self.Vars = {}
        self.Vals = {}
        self.auto_scroll = True
        self.txtMain_font_size = 11
        self._expected_RdOff = 0
        self.rtt_fail_count = 0
        self.rtt_reconnecting = False

        self._init_settings()
        self._init_ui()
        self._init_plot()
        self._init_timer()

    # ─── Settings ─────────────────────────────────────────────────────────

    def _init_settings(self):
        if not os.path.exists('setting.ini'):
            with open('setting.ini', 'w', encoding='utf-8'):
                pass
        self.conf = configparser.ConfigParser()
        self.conf.read('setting.ini', encoding='utf-8')

        if not self.conf.has_section('link'):
            self.conf.add_section('link')
            self.conf.set('link', 'mode', 'ARM SWD')
            self.conf.set('link', 'speed', '4 MHz')
            self.conf.set('link', 'jlink', 'path/to/JLink_x64.dll')
            self.conf.set('link', 'select', '')
            self.conf.set('link', 'address', '["0x20000000"]')
            self.conf.set('link', 'variable', '{}')

        if not self.conf.has_section('encode'):
            self.conf.add_section('encode')
            self.conf.set('encode', 'input', 'ASCII')
            self.conf.set('encode', 'output', 'ASCII')
            self.conf.set('encode', 'oenter', r'\r\n')
            self.conf.add_section('display')
            self.conf.set('display', 'ncurve', '4')
            self.conf.set('display', 'npoint', '1000')
            self.conf.add_section('others')
            self.conf.set('others', 'history', '11 22 33 AA BB CC')
            self.conf.set('others', 'savfile', os.path.join(os.getcwd(), 'rtt_data.txt'))

        self.N_CURVE = int(self.conf.get('display', 'ncurve'), 10)
        self.N_POINT = int(self.conf.get('display', 'npoint'), 10)
        self.Vals = ast.literal_eval(self.conf.get('link', 'variable'))

    # ─── UI ───────────────────────────────────────────────────────────────

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar)

        # Content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Stacked pages
        self._stack = QStackedWidget()

        # Build all pages
        self._build_rtt_page()
        self._build_placeholder_pages()

        content_layout.addWidget(self._stack)

        # Status bar
        status = self._build_status_bar()
        content_layout.addWidget(status)

        main_layout.addWidget(content)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setFixedWidth(56)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['sidebar_bg']};
                border-right: 1px solid {C['border']};
            }}
        """)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)

        self._sidebar_btns = []
        for i, (code, label) in enumerate(self.SIDEBAR_ITEMS):
            btn = QPushButton(code)
            btn.setFixedSize(44, 44)
            btn.setToolTip(label)
            btn.setCursor(QtGui.QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {C['sidebar_icon']};
                    border: none;
                    border-radius: 8px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {C['bg_hover']};
                    color: {C['text']};
                }}
            """)
            btn.clicked.connect(lambda checked, idx=i: self._switch_page(idx))
            layout.addWidget(btn, alignment=Qt.AlignHCenter)
            self._sidebar_btns.append(btn)

        layout.addStretch()

        # Version label
        ver = QLabel('v2.0')
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet(f'color: {C["text_dim"]}; font-size: 9px; background: transparent;')
        layout.addWidget(ver)

        self._highlight_sidebar(0)
        return sidebar

    def _highlight_sidebar(self, idx):
        for i, btn in enumerate(self._sidebar_btns):
            if i == idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {C['bg_panel']};
                        color: {C['sidebar_active']};
                        border: none;
                        border-radius: 8px;
                        font-size: 10px;
                        font-weight: bold;
                        border-left: 2px solid {C['sidebar_active']};
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: {C['sidebar_icon']};
                        border: none;
                        border-radius: 8px;
                        font-size: 10px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background-color: {C['bg_hover']};
                        color: {C['text']};
                    }}
                """)

    def _switch_page(self, idx):
        self._stack.setCurrentIndex(idx)
        self._highlight_sidebar(idx)

    # ─── RTT Terminal Page ────────────────────────────────────────────────

    def _build_rtt_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 0)
        layout.setSpacing(8)

        # Connection bar
        conn_bar = self._build_conn_bar()
        layout.addWidget(conn_bar)

        # Terminal display
        self.txtMain = QTextEdit()
        self.txtMain.setReadOnly(True)
        self.txtMain.setAcceptRichText(True)
        self.txtMain_font = QtGui.QFont('Cascadia Code', self.txtMain_font_size)
        self.txtMain.setFont(self.txtMain_font)
        self.txtMain.installEventFilter(self)
        layout.addWidget(self.txtMain, stretch=1)

        # Wave chart (hidden by default)
        self.PlotChart = QChart()
        self.ChartView = QChartView(self.PlotChart)
        self.ChartView.setVisible(False)
        layout.addWidget(self.ChartView)

        # Save file row (hidden by default)
        self._save_row = self._build_save_row()
        self._save_row.setVisible(False)
        layout.addWidget(self._save_row)

        # Send bar
        send_bar = self._build_send_bar()
        layout.addWidget(send_bar)

        # Variable table (hidden by default)
        self.tblVar = QTableWidget(0, 5)
        self.tblVar.setHorizontalHeaderLabels(['Name', 'Address', 'Type', 'Show', 'Del'])
        self.tblVar.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tblVar.verticalHeader().setVisible(False)
        self.tblVar.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tblVar.setVisible(False)
        self.tblVar.cellDoubleClicked.connect(self._on_tblVar_cellDoubleClicked)
        layout.addWidget(self.tblVar)

        self._stack.addWidget(page)

    def _build_conn_bar(self):
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_panel']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        grid = QGridLayout(bar)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        # Row 0: Probe | Browse | Connect | Wave | Save | AutoScroll
        grid.addWidget(QLabel('接口:'), 0, 0)

        self.cmbDLL = QComboBox()
        self.cmbDLL.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addWidget(self.cmbDLL, 0, 1)

        self.btnDLL = QPushButton('...')
        self.btnDLL.setFixedWidth(36)
        self.btnDLL.clicked.connect(self._on_btnDLL)
        grid.addWidget(self.btnDLL, 0, 2)

        self.btnOpen = QPushButton('打开连接')
        self.btnOpen.setFixedWidth(100)
        self.btnOpen.setStyleSheet(f"""
            QPushButton {{
                background-color: #1A3A2A;
                color: {C['green']};
                border: 1px solid #2A5A3A;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #2A4A3A;
            }}
        """)
        self.btnOpen.clicked.connect(self._on_btnOpen)
        grid.addWidget(self.btnOpen, 0, 3)

        self.chkWave = QCheckBox('波形')
        self.chkWave.stateChanged.connect(self._on_chkWave)
        grid.addWidget(self.chkWave, 0, 4)

        self.chkSave = QCheckBox('保存')
        self.chkSave.stateChanged.connect(self._on_chkSave)
        grid.addWidget(self.chkSave, 0, 5)

        self.chkAutoScroll = QCheckBox('自动滚动')
        self.chkAutoScroll.setChecked(True)
        self.chkAutoScroll.stateChanged.connect(
            lambda s: setattr(self, 'auto_scroll', s == Qt.Checked)
        )
        grid.addWidget(self.chkAutoScroll, 0, 6)

        # Row 1: Address | Browse | Clear | Mode | Speed | Timestamp
        grid.addWidget(QLabel('地址:'), 1, 0)

        self.cmbAddr = QComboBox()
        self.cmbAddr.setEditable(True)
        self.cmbAddr.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmbAddr.currentIndexChanged.connect(self._on_cmbAddr_changed)
        grid.addWidget(self.cmbAddr, 1, 1)

        self.btnAddr = QPushButton('...')
        self.btnAddr.setFixedWidth(36)
        self.btnAddr.clicked.connect(self._on_btnAddr)
        grid.addWidget(self.btnAddr, 1, 2)

        self.btnClear = QPushButton('清除')
        self.btnClear.setFixedWidth(100)
        self.btnClear.clicked.connect(lambda: self.txtMain.clear())
        grid.addWidget(self.btnClear, 1, 3)

        self.cmbMode = QComboBox()
        self.cmbMode.addItems(['ARM SWD', 'ARM JTAG', 'RV cJTAG', 'RV JTAG'])
        self.cmbMode.setFixedWidth(100)
        grid.addWidget(self.cmbMode, 1, 4)

        self.cmbSpeed = QComboBox()
        self.cmbSpeed.addItems([
            '1 MHz', '2 MHz', '4 MHz', '5 MHz',
            '8 MHz', '10 MHz', '20 MHz', '40 MHz', '50 MHz', '80 MHz',
        ])
        self.cmbSpeed.setFixedWidth(90)
        grid.addWidget(self.cmbSpeed, 1, 5)

        self.chkTime = QCheckBox('时间戳')
        grid.addWidget(self.chkTime, 1, 6)

        # Load settings into combos
        self.cmbMode.setCurrentIndex(zero_if(self.cmbMode.findText(self.conf.get('link', 'mode'))))
        self.cmbSpeed.setCurrentIndex(zero_if(self.cmbSpeed.findText(self.conf.get('link', 'speed'))))

        self.cmbDLL.addItem(self.conf.get('link', 'jlink'), 'jlink')
        self.cmbDLL.addItem('OpenOCD Tcl RPC (6666)', 'openocd')
        self._probe_detect()
        self.cmbDLL.setCurrentIndex(zero_if(self.cmbDLL.findText(self.conf.get('link', 'select'))))

        self.cmbAddr.blockSignals(True)
        self.cmbAddr.addItems(ast.literal_eval(self.conf.get('link', 'address')))
        self.cmbAddr.blockSignals(False)

        return bar

    def _build_save_row(self):
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        h.addWidget(QLabel('文件:'))
        self.linFile = QLineEdit(self.conf.get('others', 'savfile'))
        h.addWidget(self.linFile)
        btnFile = QPushButton('...')
        btnFile.setFixedWidth(36)
        btnFile.clicked.connect(self._on_btnFile)
        h.addWidget(btnFile)

        return row

    def _build_send_bar(self):
        bar = QFrame()
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['bg_panel']};
                border: 1px solid {C['border']};
                border-radius: 8px;
            }}
        """)
        grid = QGridLayout(bar)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        self.txtSend = QTextEdit()
        self.txtSend.setMaximumHeight(60)
        self.txtSend.setPlaceholderText('输入要发送的数据...')
        self.txtSend.setPlainText(self.conf.get('others', 'history'))
        grid.addWidget(self.txtSend, 0, 0, 3, 1)

        self.btnSend = QPushButton('发送')
        self.btnSend.setFixedWidth(70)
        self.btnSend.setMinimumHeight(50)
        self.btnSend.setStyleSheet(f"""
            QPushButton {{
                background-color: {C['bg_active']};
                color: {C['text_bright']};
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #388BFD; }}
        """)
        self.btnSend.clicked.connect(self._on_btnSend)
        grid.addWidget(self.btnSend, 0, 1, 3, 1)

        grid.addWidget(QLabel('接收:'), 0, 2)
        self.cmbICode = QComboBox()
        self.cmbICode.addItems(['ASCII', 'HEX', 'GBK', 'UTF-8'])
        self.cmbICode.setCurrentIndex(zero_if(self.cmbICode.findText(self.conf.get('encode', 'input'))))
        self.cmbICode.setFixedWidth(80)
        grid.addWidget(self.cmbICode, 0, 3)

        grid.addWidget(QLabel('发送:'), 1, 2)
        self.cmbOCode = QComboBox()
        self.cmbOCode.addItems(['ASCII', 'HEX', 'GBK', 'UTF-8'])
        self.cmbOCode.setCurrentIndex(zero_if(self.cmbOCode.findText(self.conf.get('encode', 'output'))))
        self.cmbOCode.setFixedWidth(80)
        grid.addWidget(self.cmbOCode, 1, 3)

        grid.addWidget(QLabel('换行:'), 2, 2)
        self.cmbEnter = QComboBox()
        self.cmbEnter.addItems([r'\r\n', r'\n'])
        self.cmbEnter.setCurrentIndex(zero_if(self.cmbEnter.findText(self.conf.get('encode', 'oenter'))))
        self.cmbEnter.setFixedWidth(80)
        grid.addWidget(self.cmbEnter, 2, 3)

        return bar

    # ─── Status Bar ───────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = QFrame()
        bar.setFixedHeight(30)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {C['sidebar_bg']};
                border-top: 1px solid {C['border']};
            }}
        """)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(8)

        self._statusLED = QLabel()
        self._statusLED.setFixedSize(8, 8)
        self._statusLED.setStyleSheet(f'background-color: {C["text_dim"]}; border-radius: 4px;')
        h.addWidget(self._statusLED)

        self._statusText = QLabel('未连接')
        self._statusText.setStyleSheet(f'color: {C["text_dim"]}; font-size: 11px;')
        h.addWidget(self._statusText)

        h.addStretch()

        self._statusRate = QLabel('0 B/s')
        self._statusRate.setStyleSheet(f'color: {C["text_dim"]}; font-size: 11px;')
        h.addWidget(self._statusRate)

        author = QLabel('RTTView v2.0')
        author.setStyleSheet(f'color: {C["text_dim"]}; font-size: 11px;')
        h.addWidget(author)

        return bar

    # ─── Placeholder pages for tools ──────────────────────────────────────

    def _build_placeholder_pages(self):
        from widgets.register_viewer import RegisterViewer
        from widgets.memory_viewer import MemoryViewer
        from widgets.core_register_viewer import CoreRegisterViewer
        from widgets.oscilloscope import Oscilloscope
        from widgets.swo_console import SWOConsole
        from widgets.task_viewer import TaskViewer
        from widgets.crash_analyzer import CrashAnalyzer
        from widgets.flash_programmer import FlashProgrammer

        self._regViewer = RegisterViewer()
        self._stack.addWidget(self._regViewer)

        self._memViewer = MemoryViewer()
        self._stack.addWidget(self._memViewer)

        self._coreRegViewer = CoreRegisterViewer()
        self._stack.addWidget(self._coreRegViewer)

        self._oscilloscope = Oscilloscope()
        self._stack.addWidget(self._oscilloscope)

        self._swoConsole = SWOConsole()
        self._stack.addWidget(self._swoConsole)

        self._taskViewer = TaskViewer()
        self._stack.addWidget(self._taskViewer)

        self._crashAnalyzer = CrashAnalyzer()
        self._stack.addWidget(self._crashAnalyzer)

        self._flashProgrammer = FlashProgrammer()
        self._stack.addWidget(self._flashProgrammer)

    # ─── Plot init ────────────────────────────────────────────────────────

    def _init_plot(self):
        self.PlotData = [[0] * self.N_POINT for _ in range(self.N_CURVE)]
        self.PlotPoint = [[QtCore.QPointF(j, 0) for j in range(self.N_POINT)] for _ in range(self.N_CURVE)]
        self.PlotCurve = [QLineSeries() for _ in range(self.N_CURVE)]

    # ─── Timer ────────────────────────────────────────────────────────────

    def _init_timer(self):
        self.tmrRTT = QtCore.QTimer()
        self.tmrRTT.setInterval(10)
        self.tmrRTT.timeout.connect(self._on_timer)
        self.tmrRTT.start()
        self.tmrRTT_Cnt = 0

    # ─── Probe detect ─────────────────────────────────────────────────────

    def _probe_detect(self):
        try:
            self._stlink_probes = STLinkProbe.detect()
        except Exception:
            self._stlink_probes = []
        try:
            self._daplink_probes = DAPLinkProbe.detect()
        except Exception:
            self._daplink_probes = []

        expected = 2 + len(self._stlink_probes) + len(self._daplink_probes)
        if expected != self.cmbDLL.count():
            while self.cmbDLL.count() > 2:
                self.cmbDLL.removeItem(2)
            for i, (dev, name) in enumerate(self._stlink_probes):
                self.cmbDLL.addItem(name, ('stlink', i))
            for i, probe in enumerate(self._daplink_probes):
                self.cmbDLL.addItem(f'{probe.product_name} ({probe.unique_id})', ('daplink', i))

    # ─── Probe wiring ─────────────────────────────────────────────────────

    def _wire_probe(self, probe, mode=None):
        from widgets.core_register_viewer import CoreRegisterViewer
        from widgets.task_viewer import TaskViewer
        from widgets.crash_analyzer import CrashAnalyzer
        for i in range(self._stack.count()):
            widget = self._stack.widget(i)
            if hasattr(widget, 'set_probe'):
                if isinstance(widget, (CoreRegisterViewer, TaskViewer, CrashAnalyzer)):
                    arch_mode = 'arm' if mode and mode.startswith('arm') else 'rv'
                    widget.set_probe(probe, mode=arch_mode)
                else:
                    widget.set_probe(probe)

    # ─── Connection ───────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_btnOpen(self):
        if not self._connected:
            self._do_connect()
        else:
            self._do_disconnect()

    def _do_connect(self):
        mode = self.cmbMode.currentText()
        mode = mode.replace(' SWD', '').replace(' cJTAG', '').replace(' JTAG', 'J').lower()
        core = 'Cortex-M0' if mode.startswith('arm') else 'RISC-V'
        speed = int(self.cmbSpeed.currentText().split()[0]) * 1000

        try:
            item_data = self.cmbDLL.currentData()
            probe = None

            if item_data == 'jlink':
                probe = JLinkProbe(dllpath=self.cmbDLL.currentText())
            elif item_data == 'openocd':
                probe = OpenOCDProbe()
            elif isinstance(item_data, tuple) and item_data[0] == 'stlink':
                dev = self._stlink_probes[item_data[1]][0]
                probe = STLinkProbe(device=dev)
            elif isinstance(item_data, tuple) and item_data[0] == 'daplink':
                raw_probe = self._daplink_probes[item_data[1]]
                probe = DAPLinkProbe(probe=raw_probe)

            if probe is None:
                raise Exception('未选择探针或探针类型不支持')

            probe.open(mode=mode, core=core, speed=speed)
            self.xlk = xlink.XLink(probe)

            if self.chkSave.isChecked():
                savfile, ext = os.path.splitext(self.linFile.text())
                savfile = f'{savfile}_{datetime.datetime.now().strftime("%y%m%d%H%M%S")}{ext}'
                self.rcvfile = open(savfile, 'w')

            if re.match(r'0[xX][0-9a-fA-F]{8}', self.cmbAddr.currentText()):
                addr = int(self.cmbAddr.currentText(), 16)
                for i in range(64):
                    data = self.xlk.read_mem_U8(addr + 1024 * i, 1024 + 32)
                    index = bytes(data).find(b'SEGGER RTT')
                    if index != -1:
                        self.RTTAddr = addr + 1024 * i + index
                        data = self.xlk.read_mem_U8(self.RTTAddr, ctypes.sizeof(SEGGER_RTT_CB))
                        rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(data))
                        self.aUpAddr = self.RTTAddr + 16 + 4 + 4
                        self.aDownAddr = self.aUpAddr + ctypes.sizeof(RingBuffer) * rtt_cb.MaxNumUpBuffers
                        self.txtMain.append(f'\n_SEGGER_RTT @ 0x{self.RTTAddr:08X}\n')
                        break
                else:
                    raise Exception('Can not find _SEGGER_RTT')
                self.rtt_cb = True
            else:
                self.rtt_cb = False

        except Exception as e:
            self.txtMain.append(f'\nerror: {str(e)}\n')
            try:
                if hasattr(self, 'xlk') and self.xlk:
                    self.xlk.close()
                elif probe:
                    probe.close()
            except:
                pass
            return

        self._connected = True
        self._update_status(True)
        self._wire_probe(probe, mode)

    def _do_disconnect(self):
        if self.rcvfile and not self.rcvfile.closed:
            self.rcvfile.close()
        self.xlk.close()
        self.rtt_fail_count = 0
        self.rtt_reconnecting = False
        self._connected = False
        self._update_status(False)
        self._wire_probe(None)

    def _update_status(self, connected):
        if connected:
            self._statusLED.setStyleSheet(f'background-color: {C["green"]}; border-radius: 4px;')
            self._statusText.setText('已连接')
            self._statusText.setStyleSheet(f'color: {C["green"]}; font-size: 11px;')
            self.btnOpen.setText('关闭连接')
            self.btnOpen.setStyleSheet(f"""
                QPushButton {{
                    background-color: #3A1A1A;
                    color: {C['red']};
                    border: 1px solid #5A2A2A;
                    border-radius: 6px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #4A2A2A; }}
            """)
        else:
            self._statusLED.setStyleSheet(f'background-color: {C["text_dim"]}; border-radius: 4px;')
            self._statusText.setText('未连接')
            self._statusText.setStyleSheet(f'color: {C["text_dim"]}; font-size: 11px;')
            self._statusRate.setText('0 B/s')
            self.btnOpen.setText('打开连接')
            self.btnOpen.setStyleSheet(f"""
                QPushButton {{
                    background-color: #1A3A2A;
                    color: {C['green']};
                    border: 1px solid #2A5A3A;
                    border-radius: 6px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background-color: #2A4A3A; }}
            """)

    # ─── RTT Read/Write ───────────────────────────────────────────────────

    def aUpRead(self):
        data = self.xlk.read_mem_U8(self.aUpAddr, ctypes.sizeof(RingBuffer))
        aUp = RingBuffer.from_buffer(bytearray(data))

        if not (aUp.SizeOfBuffer == 2048
                and aUp.WrOff < aUp.SizeOfBuffer
                and aUp.RdOff < aUp.SizeOfBuffer
                and 0x20000000 <= aUp.pBuffer <= 0x20210000
                and aUp.Flags <= 2):
            raise Exception('Invalid RingBuffer data')

        if hasattr(self, '_expected_RdOff') and self._expected_RdOff > 64:
            if aUp.RdOff == 0 and aUp.WrOff < 512:
                self._expected_RdOff = 0
                self.rtt_fail_count = 0
                self.rcvbuff = b''
                self.txtMain.append('\n[!] MCU 复位，已重置缓冲区\n')
                return b''

        if aUp.RdOff <= aUp.WrOff:
            cnt = aUp.WrOff - aUp.RdOff
        else:
            cnt1 = aUp.SizeOfBuffer - aUp.RdOff
            cnt2 = aUp.WrOff
            cnt = cnt1 + cnt2

        if 0 < cnt < 1024 * 1024:
            bufAddr = ctypes.cast(aUp.pBuffer, ctypes.c_void_p).value
            if aUp.RdOff <= aUp.WrOff:
                data = self.xlk.read_mem_U8(bufAddr + aUp.RdOff, cnt)
            else:
                part1 = self.xlk.read_mem_U8(bufAddr + aUp.RdOff, cnt1)
                part2 = self.xlk.read_mem_U8(bufAddr, cnt2)
                data = part1 + part2

            aUp.RdOff = (aUp.RdOff + cnt) % aUp.SizeOfBuffer
            self.xlk.write_U32(self.aUpAddr + 4 * 4, aUp.RdOff)
            self._expected_RdOff = aUp.RdOff
        else:
            data = []

        return bytes(data)

    def aDownWrite(self, data_bytes):
        raw = self.xlk.read_mem_U8(self.aDownAddr, ctypes.sizeof(RingBuffer))
        aDown = RingBuffer.from_buffer(bytearray(raw))

        if aDown.WrOff >= aDown.RdOff:
            if aDown.RdOff != 0:
                cnt = min(aDown.SizeOfBuffer - aDown.WrOff, len(data_bytes))
            else:
                cnt = min(aDown.SizeOfBuffer - 1 - aDown.WrOff, len(data_bytes))
            self.xlk.write_mem(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, data_bytes[:cnt])
            aDown.WrOff += cnt
            if aDown.WrOff == aDown.SizeOfBuffer:
                aDown.WrOff = 0
            data_bytes = data_bytes[cnt:]

        if data_bytes and aDown.RdOff != 0 and aDown.RdOff != 1:
            cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(data_bytes))
            self.xlk.write_mem(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, data_bytes[:cnt])
            aDown.WrOff += cnt

        self.xlk.write_U32(self.aDownAddr + 4 * 3, aDown.WrOff)

    # ─── Auto-reconnect ───────────────────────────────────────────────────

    def _auto_reconnect(self):
        try:
            self.xlk.close()
        except:
            pass

        mode = self.cmbMode.currentText()
        mode = mode.replace(' SWD', '').replace(' cJTAG', '').replace(' JTAG', 'J').lower()
        core = 'Cortex-M0' if mode.startswith('arm') else 'RISC-V'
        speed = int(self.cmbSpeed.currentText().split()[0]) * 1000

        self._probe_detect()
        item_data = self.cmbDLL.currentData()

        if item_data == 'jlink':
            probe = JLinkProbe(dllpath=self.cmbDLL.currentText())
        elif item_data == 'openocd':
            probe = OpenOCDProbe()
        elif isinstance(item_data, tuple) and item_data[0] == 'stlink':
            dev = self._stlink_probes[item_data[1]][0]
            probe = STLinkProbe(device=dev)
        elif isinstance(item_data, tuple) and item_data[0] == 'daplink':
            raw_probe = self._daplink_probes[item_data[1]]
            probe = DAPLinkProbe(probe=raw_probe)
        else:
            raise Exception('No probe available')

        probe.open(mode=mode, core=core, speed=speed)
        self.xlk = xlink.XLink(probe)

        search_addr_text = self.cmbAddr.currentText()
        if re.match(r'0[xX][0-9a-fA-F]{8}', search_addr_text):
            addr = int(search_addr_text, 16)
        else:
            raise Exception('Invalid search address')

        for i in range(64):
            data = self.xlk.read_mem_U8(addr + 1024 * i, 1024 + 32)
            index = bytes(data).find(b'SEGGER RTT')
            if index != -1:
                self.RTTAddr = addr + 1024 * i + index
                data = self.xlk.read_mem_U8(self.RTTAddr, ctypes.sizeof(SEGGER_RTT_CB))
                rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(data))
                self.aUpAddr = self.RTTAddr + 16 + 4 + 4
                self.aDownAddr = self.aUpAddr + ctypes.sizeof(RingBuffer) * rtt_cb.MaxNumUpBuffers
                self.txtMain.append(f'[+] 重连成功: _SEGGER_RTT @ 0x{self.RTTAddr:08X}\n')
                self.rtt_cb = True
                self.rtt_fail_count = 0
                self._wire_probe(probe, mode)
                return

        raise Exception('Can not find _SEGGER_RTT after reconnect')

    # ─── Timer callback ───────────────────────────────────────────────────

    def _on_timer(self):
        self.tmrRTT_Cnt += 1

        if self._connected and self.tmrRTT_Cnt % 50 == 0:
            rate = self._rx_bytes / 0.5
            if rate < 1024:
                self._statusRate.setText(f'{rate:.0f} B/s')
            else:
                self._statusRate.setText(f'{rate / 1024:.1f} KB/s')
            self._rx_bytes = 0

        if self._connected:
            try:
                if self.rtt_cb:
                    rcvdbytes = self.aUpRead()
                else:
                    vals = []
                    for name, addr, size, typ, fmt, show in self.Vals.values():
                        if show:
                            buf = self.xlk.read_mem_U8(addr, size)
                            vals.append(struct.unpack(fmt, bytes(buf))[0])
                    rcvdbytes = b'\t'.join(f'{val}'.encode() for val in vals) + b',\n'
            except Exception:
                rcvdbytes = b''
                self.rtt_fail_count += 1
                if self.rtt_fail_count >= 50 and not self.rtt_reconnecting:
                    self.rtt_reconnecting = True
                    self.txtMain.append('\n[!] 连接断开，正在自动重连...\n')
                    try:
                        self._auto_reconnect()
                    except Exception as e2:
                        self.txtMain.append(f'[!] 自动重连失败: {str(e2)}\n')
                        self._connected = False
                        self._update_status(False)
                    finally:
                        self.rtt_reconnecting = False
                        self.rtt_fail_count = 0

            if rcvdbytes:
                self.rtt_fail_count = 0
                self._rx_bytes += len(rcvdbytes)
                if self.rcvfile and not self.rcvfile.closed:
                    self.rcvfile.write(rcvdbytes.decode('latin-1'))

                self.rcvbuff += rcvdbytes

                if self.chkWave.isChecked():
                    self._process_wave_data()
                else:
                    self._process_text_data()
        else:
            if self.tmrRTT_Cnt % 100 == 1:
                self._probe_detect()
            if self.tmrRTT_Cnt % 100 == 2:
                path = self.cmbAddr.currentText()
                if os.path.exists(path) and os.path.isfile(path):
                    if self.elffile != (path, os.path.getmtime(path)):
                        self.elffile = (path, os.path.getmtime(path))
                        self._parse_elffile(path)

    def _process_wave_data(self):
        if b',' not in self.rcvbuff:
            return
        try:
            d = self.rcvbuff[0:self.rcvbuff.rfind(b',')].split(b',')
            if self.cmbICode.currentText() != 'HEX':
                d = [[float(x) for x in X.strip().split()] for X in d]
            else:
                d = [[int(x, 16) for x in X.strip().split()] for X in d]
            for arr in d:
                for i, x in enumerate(arr):
                    if i == self.N_CURVE:
                        break
                    self.PlotData[i].pop(0)
                    self.PlotData[i].append(x)
                    self.PlotPoint[i].pop(0)
                    self.PlotPoint[i].append(QtCore.QPointF(999, x))

            self.rcvbuff = self.rcvbuff[self.rcvbuff.rfind(b',') + 1:]

            if self.tmrRTT_Cnt % 4 == 0:
                if len(d[-1]) != len([s for s in self.PlotChart.series() if s.isVisible()]):
                    for s in list(self.PlotChart.series()):
                        self.PlotChart.removeSeries(s)
                    for i in range(min(len(d[-1]), self.N_CURVE)):
                        self.PlotCurve[i].setName(f'Curve {i + 1}')
                        self.PlotChart.addSeries(self.PlotCurve[i])
                    self.PlotChart.createDefaultAxes()

                for i in range(len(self.PlotChart.series())):
                    for j, point in enumerate(self.PlotPoint[i]):
                        point.setX(j)
                    self.PlotCurve[i].replace(self.PlotPoint[i])

                miny = min([min(dd) for dd in self.PlotData[:len(self.PlotChart.series())]])
                maxy = max([max(dd) for dd in self.PlotData[:len(self.PlotChart.series())]])
                self.PlotChart.axisY().setRange(miny, maxy)
                self.PlotChart.axisX().setRange(0, self.N_POINT)
        except Exception:
            self.rcvbuff = b''

    def _process_text_data(self):
        encoding = self.cmbICode.currentText()
        if encoding == 'ASCII':
            text = ''.join([chr(x) for x in self.rcvbuff])
            self.rcvbuff = b''
            if len(self.txtMain.toPlainText()) > 25000:
                self.txtMain.clear()
            text = self._apply_timestamp(text)
            self._render_ansi_text(text)
        elif encoding == 'HEX':
            text = ' '.join([f'{x:02X}' for x in self.rcvbuff]) + ' '
            self.rcvbuff = b''
            if len(self.txtMain.toPlainText()) > 25000:
                self.txtMain.clear()
            self.txtMain.append(text)
        else:
            text, code_list = self._process_rtt_bytes(self.rcvbuff, encoding)
            self.rcvbuff = b''
            if len(self.txtMain.toPlainText()) > 25000:
                self.txtMain.clear()
            text = self._apply_timestamp(text)
            self._render_ansi_codes(text, code_list)

    # ─── ANSI Parser ──────────────────────────────────────────────────────

    _ansi_16 = [
        (0, 0, 0), (197, 15, 31), (19, 161, 14), (193, 156, 0),
        (0, 55, 218), (136, 23, 152), (58, 150, 221), (204, 204, 204),
        (118, 118, 118), (231, 72, 86), (22, 198, 12), (249, 241, 165),
        (59, 120, 255), (180, 0, 158), (97, 214, 214), (255, 255, 255),
    ]
    _palette256 = list(_ansi_16)
    for r in (0, 95, 135, 175, 215, 255):
        for g in (0, 95, 135, 175, 215, 255):
            for b in (0, 95, 135, 175, 215, 255):
                _palette256.append((r, g, b))
    for i in range(24):
        v = 8 + i * 10
        _palette256.append((v, v, v))

    def _render_ansi_text(self, text):
        if not text:
            return
        self._ansi_clear = False
        encoded = text.encode('utf-8', errors='replace')
        spans = self._parse_ansi(encoded)
        if self._ansi_clear:
            self.txtMain.clear()
        if not spans:
            return

        html_parts = []
        for txt, fmt in spans:
            escaped = txt.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            lines = escaped.split('\n')
            for idx, line in enumerate(lines):
                if idx > 0:
                    html_parts.append('<br>')
                if not line:
                    continue
                style_parts = []
                if fmt.get('fg'):
                    r, g, b = fmt['fg']
                    style_parts.append(f'color:#{r:02X}{g:02X}{b:02X}')
                if fmt.get('bg'):
                    r, g, b = fmt['bg']
                    style_parts.append(f'background-color:#{r:02X}{g:02X}{b:02X}')
                if fmt.get('bold'):
                    style_parts.append('font-weight:bold')
                if fmt.get('italic'):
                    style_parts.append('font-style:italic')
                if style_parts:
                    html_parts.append(f'<span style="{";".join(style_parts)}">{line}</span>')
                else:
                    html_parts.append(line)

        html = ''.join(html_parts)
        cursor = self.txtMain.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertHtml(html)
        cursor.endEditBlock()

        if self.auto_scroll:
            self.txtMain.verticalScrollBar().setValue(self.txtMain.verticalScrollBar().maximum())

    def _parse_ansi(self, data: bytes) -> list:
        results = []
        text_buf = []
        bold = False
        italic = False
        fg = None
        bg = None

        def _make_fmt():
            return dict(fg=fg, bg=bg, bold=bold, italic=italic)

        def _color256(n):
            return self._palette256[max(0, min(255, n))]

        def _parse_sgr(params):
            nonlocal bold, italic, fg, bg
            if not params:
                params = [0]
            has_color = any(30 <= p <= 37 or 90 <= p <= 97 or p in (38, 48)
                           or 40 <= p <= 47 or 100 <= p <= 107 for p in params)
            has_zero = 0 in params
            i = 0
            while i < len(params):
                code = params[i]
                if code == 0:
                    if has_color and has_zero:
                        bold = False; italic = False
                    else:
                        bold = False; italic = False; fg = None; bg = None
                elif code == 1:
                    bold = True
                elif code == 2:
                    bold = False
                elif code == 3:
                    italic = True
                elif 30 <= code <= 37:
                    fg = self._ansi_16[code - 30]
                elif 90 <= code <= 97:
                    fg = self._ansi_16[code - 90 + 8]
                elif code == 38:
                    if i + 1 < len(params):
                        if params[i + 1] == 5 and i + 2 < len(params):
                            fg = _color256(params[i + 2]); i += 2
                        elif params[i + 1] == 2 and i + 4 < len(params):
                            fg = (params[i + 2], params[i + 3], params[i + 4]); i += 4
                elif 40 <= code <= 47:
                    bg = self._ansi_16[code - 40]
                elif 100 <= code <= 107:
                    bg = self._ansi_16[code - 100 + 8]
                elif code == 48:
                    if i + 1 < len(params):
                        if params[i + 1] == 5 and i + 2 < len(params):
                            bg = _color256(params[i + 2]); i += 2
                        elif params[i + 1] == 2 and i + 4 < len(params):
                            bg = (params[i + 2], params[i + 3], params[i + 4]); i += 4
                i += 1

        def _flush():
            if text_buf:
                results.append((''.join(text_buf), _make_fmt()))
                text_buf.clear()

        state = 0
        csi_buf = ''
        for byte_val in data:
            if state == 0:
                if byte_val == 0x1B:
                    _flush(); state = 1; csi_buf = ''
                elif byte_val == 0x0A:
                    _flush(); results.append(('\n', _make_fmt()))
                elif byte_val == 0x0D:
                    pass
                elif byte_val >= 0x20:
                    text_buf.append(chr(byte_val))
            elif state == 1:
                if byte_val == ord('['):
                    state = 2; csi_buf = ''
                elif byte_val == ord('J'):
                    self._ansi_clear = True; state = 0
                else:
                    state = 0
            elif state == 2:
                if 0x30 <= byte_val <= 0x3F or 0x20 <= byte_val <= 0x2F:
                    csi_buf += chr(byte_val)
                elif 0x40 <= byte_val <= 0x7E:
                    state = 0
                    params = []
                    if csi_buf:
                        for part in csi_buf.split(';'):
                            if part:
                                try:
                                    params.append(int(part))
                                except ValueError:
                                    params.append(0)
                    if chr(byte_val) == 'm':
                        _parse_sgr(params)
                    elif chr(byte_val) == 'J':
                        if not params or params[0] == 2:
                            self._ansi_clear = True
                else:
                    state = 0

        _flush()
        return results

    def _process_rtt_bytes(self, data: bytes, encoding: str):
        if not data:
            return '', []
        boundaries = []
        i = 0
        while i < len(data):
            if data[i] == 0x1B:
                seq_start = i
                i += 1
                if i < len(data) and data[i] == ord('['):
                    i += 1
                    while i < len(data) and data[i] != ord('m'):
                        i += 1
                    if i < len(data):
                        i += 1
                boundaries.append((seq_start, i))
            else:
                i += 1

        chunks = []
        prev = 0
        for (s, e) in boundaries:
            if s > prev:
                chunks.append((data[prev:s], None))
            chunks.append((None, data[s:e]))
            prev = e
        if prev < len(data):
            chunks.append((data[prev:], None))

        text_parts = []
        code_list = []
        text_byte_pos = 0
        for (t, a) in chunks:
            if a is not None:
                code_list.append((a.decode('ascii', errors='ignore'), text_byte_pos))
            if t is not None:
                decoded = ''
                j = 0
                while j < len(t):
                    for span in range(min(4, len(t) - j), 0, -1):
                        try:
                            chunk = t[j:j + span]
                            decoded += chunk.decode(encoding)
                            text_byte_pos += len(chunk)
                            j += span
                            break
                        except UnicodeDecodeError:
                            if span == 1:
                                decoded += chr(t[j])
                                text_byte_pos += 1
                                j += 1
                    text_parts.append(decoded)

        return ''.join(text_parts), code_list

    def _render_ansi_codes(self, text, code_list):
        if not text:
            return
        self._ansi_clear = False
        encoded = text.encode('utf-8', errors='replace')

        sgr_entries = []
        for (code_str, text_pos) in code_list:
            if len(code_str) >= 2 and code_str[0] == '\x1b' and code_str[1] == '[':
                inner = code_str[2:-1] if code_str.endswith('m') else code_str[2:]
                params = []
                if inner:
                    for part in inner.split(';'):
                        if part:
                            try:
                                params.append(int(part))
                            except ValueError:
                                params.append(0)
                sgr_entries.append((text_pos, params))

        bold, italic, fg, bg = False, False, None, None
        byte_formats = [None] * len(encoded)
        sgr_idx = 0

        def _color256(n):
            return self._palette256[max(0, min(255, n))]

        def _parse_sgr(params):
            nonlocal bold, italic, fg, bg
            if not params:
                params = [0]
            has_color = any(30 <= p <= 37 or 90 <= p <= 97 or p in (38, 48)
                           or 40 <= p <= 47 or 100 <= p <= 107 for p in params)
            has_zero = 0 in params
            i = 0
            while i < len(params):
                code = params[i]
                if code == 0:
                    if has_color and has_zero:
                        bold = False; italic = False
                    else:
                        bold = False; italic = False; fg = None; bg = None
                elif code == 1:
                    bold = True
                elif code == 2:
                    bold = False
                elif code == 3:
                    italic = True
                elif 30 <= code <= 37:
                    fg = self._ansi_16[code - 30]
                elif 90 <= code <= 97:
                    fg = self._ansi_16[code - 90 + 8]
                elif code == 38:
                    if i + 1 < len(params):
                        if params[i + 1] == 5 and i + 2 < len(params):
                            fg = _color256(params[i + 2]); i += 2
                        elif params[i + 1] == 2 and i + 4 < len(params):
                            fg = (params[i + 2], params[i + 3], params[i + 4]); i += 4
                elif 40 <= code <= 47:
                    bg = self._ansi_16[code - 40]
                elif 100 <= code <= 107:
                    bg = self._ansi_16[code - 100 + 8]
                elif code == 48:
                    if i + 1 < len(params):
                        if params[i + 1] == 5 and i + 2 < len(params):
                            bg = _color256(params[i + 2]); i += 2
                        elif params[i + 1] == 2 and i + 4 < len(params):
                            bg = (params[i + 2], params[i + 3], params[i + 4]); i += 4
                i += 1

        for byte_idx, byte_val in enumerate(encoded):
            while sgr_idx < len(sgr_entries) and sgr_entries[sgr_idx][0] <= byte_idx:
                _parse_sgr(sgr_entries[sgr_idx][1])
                sgr_idx += 1
            byte_formats[byte_idx] = (fg, bg, bold, italic)

        html_parts = []
        i = 0
        while i < len(encoded):
            bv = encoded[i]
            if bv == 0x0A:
                html_parts.append('<br>')
                i += 1
                continue
            elif bv == 0x0D or bv < 0x20:
                i += 1
                continue

            fmt = byte_formats[i]
            start = i
            while i < len(encoded) and byte_formats[i] == fmt:
                bv2 = encoded[i]
                if bv2 == 0x0A or bv2 == 0x0D or bv2 < 0x20:
                    break
                i += 1

            if i > start:
                chars = ''.join(chr(b) for b in encoded[start:i])
                escaped = chars.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                f_fg, f_bg, f_bold, f_italic = fmt
                style_parts = []
                if f_fg is not None:
                    r, g, b = f_fg
                    style_parts.append(f'color:#{r:02X}{g:02X}{b:02X}')
                if f_bg is not None:
                    r, g, b = f_bg
                    style_parts.append(f'background-color:#{r:02X}{g:02X}{b:02X}')
                if f_bold:
                    style_parts.append('font-weight:bold')
                if f_italic:
                    style_parts.append('font-style:italic')
                if style_parts:
                    html_parts.append(f'<span style="{";".join(style_parts)}">{escaped}</span>')
                else:
                    html_parts.append(escaped)

        if not html_parts:
            return

        html = ''.join(html_parts)
        cursor = self.txtMain.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertHtml(html)
        cursor.endEditBlock()

        if self.auto_scroll:
            self.txtMain.verticalScrollBar().setValue(self.txtMain.verticalScrollBar().maximum())

    def _apply_timestamp(self, text):
        if self.chkTime.isChecked():
            now = datetime.datetime.now()
            ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
            lines = text.split('\n')
            return '\n'.join(
                f'[{ts}] {line}' if line else line for line in lines
            )
        return text

    # ─── Event filter (Ctrl+Wheel zoom) ───────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.txtMain_font_size = min(32, self.txtMain_font_size + 1)
                else:
                    self.txtMain_font_size = max(6, self.txtMain_font_size - 1)
                self.txtMain_font.setPointSize(self.txtMain_font_size)
                self.txtMain.setFont(self.txtMain_font)
                return True
        return super().eventFilter(obj, event)

    # ─── Send ─────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_btnSend(self):
        if not self._connected:
            return
        text = self.txtSend.toPlainText()
        if self.cmbOCode.currentText() == 'HEX':
            try:
                self.aDownWrite(bytes([int(x, 16) for x in text.split()]))
            except Exception:
                pass
        else:
            if self.cmbEnter.currentText() == r'\r\n':
                text = text.replace('\n', '\r\n')
            try:
                self.aDownWrite(text.encode(self.cmbOCode.currentText()))
            except Exception:
                pass

    # ─── Browse buttons ───────────────────────────────────────────────────

    @pyqtSlot()
    def _on_btnDLL(self):
        dllpath, _ = QFileDialog.getOpenFileName(
            self, 'JLink_x64.dll path', self.cmbDLL.currentText(),
            '动态链接库文件 (*.dll *.so)')
        if dllpath:
            self.cmbDLL.setItemText(0, dllpath)

    @pyqtSlot()
    def _on_btnAddr(self):
        elfpath, _ = QFileDialog.getOpenFileName(
            self, 'elf file path', self.cmbAddr.currentText(),
            'elf file (*.elf *.axf *.out)')
        if elfpath:
            self.cmbAddr.insertItem(0, elfpath)
            self.cmbAddr.setCurrentIndex(0)

    @pyqtSlot()
    def _on_btnFile(self):
        savfile, _ = QFileDialog.getSaveFileName(
            self, '数据保存文件路径', self.linFile.text(), '文本文件 (*.txt)')
        if savfile:
            self.linFile.setText(savfile)

    # ─── Address mode switch ──────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_cmbAddr_changed(self, index):
        text = self.cmbAddr.currentText()
        if re.match(r'0[xX][0-9a-fA-F]{8}', text):
            self.tblVar.setVisible(False)
            self.txtSend.setVisible(True)
            self.btnSend.setVisible(True)
            self.cmbICode.setEnabled(True)
            self.cmbOCode.setEnabled(True)
            self.cmbEnter.setEnabled(True)
        else:
            self.txtSend.setVisible(False)
            self.btnSend.setVisible(False)
            self.cmbICode.setEnabled(False)
            self.cmbOCode.setEnabled(False)
            self.cmbEnter.setEnabled(False)
            self.tblVar.setVisible(True)

    # ─── Checkboxes ───────────────────────────────────────────────────────

    @pyqtSlot(int)
    def _on_chkSave(self, state):
        self._save_row.setVisible(state == Qt.Checked)

    @pyqtSlot(int)
    def _on_chkWave(self, state):
        self.ChartView.setVisible(state == Qt.Checked)
        self.txtMain.setVisible(state == Qt.Unchecked)

    # ─── ELF parsing ──────────────────────────────────────────────────────

    len2type = {
        1: [('int8', 'b'), ('uint8', 'B')],
        2: [('int16', 'h'), ('uint16', 'H')],
        4: [('int32', 'i'), ('uint32', 'I'), ('float', 'f')],
        8: [('int64', 'q'), ('uint64', 'Q'), ('double', 'd')],
    }

    def _parse_elffile(self, path):
        try:
            from elftools.elf.elffile import ELFFile
            with open(path, 'rb') as f:
                elffile = ELFFile(f)
                self.Vars = {}
                for sym in elffile.get_section_by_name('.symtab').iter_symbols():
                    if sym.entry['st_info']['type'] == 'STT_OBJECT' and sym.entry['st_size'] in (1, 2, 4, 8):
                        self.Vars[sym.name] = Variable(sym.name, sym.entry['st_value'], sym.entry['st_size'])
        except Exception:
            pass
        else:
            Vals = {row: val for row, val in self.Vals.items() if val.name in self.Vars}
            self.Vals = {i: val for i, val in enumerate(Vals.values())}
            for row, val in self.Vals.items():
                var = self.Vars[val.name]
                if val.addr != var.addr:
                    self.Vals[row] = self.Vals[row]._replace(addr=var.addr)
                if val.size != var.size:
                    typ, fmt = self.len2type[var.size][0]
                    self.Vals[row] = self.Vals[row]._replace(size=var.size, typ=typ, fmt=fmt)
            self._tblVar_redraw()

    def _tblVar_redraw(self):
        while self.tblVar.rowCount():
            self.tblVar.removeRow(0)
        for s in list(self.PlotChart.series()):
            self.PlotChart.removeSeries(s)
        for row, val in self.Vals.items():
            self.tblVar.insertRow(row)
            self._tblVar_setRow(row, val)
        if self.tblVar.rowCount() < self.N_CURVE:
            self.tblVar.insertRow(self.tblVar.rowCount())

    def _tblVar_setRow(self, row: int, val: Valuable):
        self.tblVar.setItem(row, 0, QTableWidgetItem(val.name))
        self.tblVar.setItem(row, 1, QTableWidgetItem(f'{val.addr:08X}'))
        self.tblVar.setItem(row, 2, QTableWidgetItem(val.typ))
        self.tblVar.setItem(row, 3, QTableWidgetItem('显示' if val.show else '不显示'))
        self.tblVar.setItem(row, 4, QTableWidgetItem('删除'))
        self.PlotCurve[row].setName(val.name)
        self.PlotCurve[row].setVisible(val.show)
        if self.PlotCurve[row] not in self.PlotChart.series():
            self.PlotChart.addSeries(self.PlotCurve[row])
            self.PlotChart.createDefaultAxes()

    @pyqtSlot(int, int)
    def _on_tblVar_cellDoubleClicked(self, row, column):
        if self._connected:
            return
        if column < 3:
            dlg = VarDialog(self, row)
            if dlg.exec() == QDialog.Accepted:
                var = self.Vars[dlg.cmbName.currentText()]
                typ, fmt = dlg.cmbType.currentText(), dlg.cmbType.currentData()
                self.Vals[row] = Valuable(var.name, var.addr, var.size, typ, fmt, True)
                self._tblVar_setRow(row, self.Vals[row])
                if self.tblVar.rowCount() < self.N_CURVE and row == self.tblVar.rowCount() - 1:
                    self.tblVar.insertRow(self.tblVar.rowCount())
        elif column == 3:
            if self.tblVar.item(row, 3):
                self.Vals[row] = self.Vals[row]._replace(show=not self.Vals[row].show)
                self.tblVar.item(row, 3).setText('显示' if self.Vals[row].show else '不显示')
                self.PlotCurve[row].setVisible(self.Vals[row].show)
        elif column == 4:
            if self.tblVar.item(row, 4):
                self.Vals.pop(row)
                self.Vals = {i: val for i, val in enumerate(self.Vals.values())}
                self._tblVar_redraw()

    # ─── Close ────────────────────────────────────────────────────────────

    def closeEvent(self, evt):
        if self.rcvfile and not self.rcvfile.closed:
            self.rcvfile.close()

        self.conf.set('link', 'mode', self.cmbMode.currentText())
        self.conf.set('link', 'speed', self.cmbSpeed.currentText())
        self.conf.set('link', 'jlink', self.cmbDLL.itemText(0))
        self.conf.set('link', 'select', self.cmbDLL.currentText())
        self.conf.set('encode', 'input', self.cmbICode.currentText())
        self.conf.set('encode', 'output', self.cmbOCode.currentText())
        self.conf.set('encode', 'oenter', self.cmbEnter.currentText())
        self.conf.set('others', 'history', self.txtSend.toPlainText())
        self.conf.set('others', 'savfile', self.linFile.text())

        addrs = [self.cmbAddr.currentText()] + [self.cmbAddr.itemText(i) for i in range(self.cmbAddr.count())]
        self.conf.set('link', 'address', repr(list(collections.OrderedDict.fromkeys(addrs))))
        self.conf.set('link', 'variable', repr(self.Vals))
        with open('setting.ini', 'w', encoding='utf-8') as f:
            self.conf.write(f)


# ─── Variable Dialog ──────────────────────────────────────────────────────────

class VarDialog(QDialog):
    def __init__(self, parent, row):
        super().__init__(parent)
        self.resize(400, 100)
        self.setWindowTitle('变量配置')

        self.cmbType = QComboBox()
        self.cmbType.setMinimumSize(QtCore.QSize(80, 0))

        self.cmbName = QComboBox()
        self.cmbName.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmbName.currentTextChanged.connect(self._on_name_changed)

        hLayout = QHBoxLayout()
        hLayout.addWidget(QLabel('变量:'))
        hLayout.addWidget(self.cmbName)
        hLayout.addWidget(QLabel('    '))
        hLayout.addWidget(QLabel('类型:'))
        hLayout.addWidget(self.cmbType)

        btnBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btnBox.accepted.connect(self.accept)
        btnBox.rejected.connect(self.reject)

        vLayout = QVBoxLayout(self)
        vLayout.addLayout(hLayout)
        vLayout.addItem(QtWidgets.QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        vLayout.addWidget(btnBox)

        self.cmbName.addItems(parent.Vars.keys())
        if parent.tblVar.item(row, 0):
            self.cmbName.setCurrentText(parent.tblVar.item(row, 0).text())
            self.cmbType.setCurrentText(parent.tblVar.item(row, 2).text())

    @pyqtSlot(str)
    def _on_name_changed(self, name):
        size = self.parent().Vars[name].size
        self.cmbType.clear()
        for typ, fmt in self.parent().len2type[size]:
            self.cmbType.addItem(typ, fmt)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback
    try:
        app = QApplication(sys.argv)
        app.setStyleSheet(GLOBAL_QSS)

        # High DPI support
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        rtt = RTTView()
        rtt.show()
        sys.exit(app.exec())
    except Exception as e:
        # Write crash log next to exe so user can report
        log_path = os.path.join(_APP_DIR, 'rttview_crash.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(f'RTTView startup crash: {e}\n\n')
            traceback.print_exc(file=f)
        # Also show a message box if possible
        try:
            from PyQt5.QtWidgets import QMessageBox, QApplication as QA
            _app = QA.instance() or QA(sys.argv)
            QMessageBox.critical(None, 'RTTView Error',
                                 f'Startup failed:\n{e}\n\nLog: {log_path}')
        except Exception:
            pass
        sys.exit(1)
