#! python3
import os
import re
import sys
import ctypes
import struct
import datetime
import collections
import configparser

# Switch to script directory so all relative paths work correctly
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt
from PyQt5.QtWidgets import QApplication, QWidget, QDialog, QFileDialog, QTableWidgetItem
from PyQt5.QtChart import QChart, QChartView, QLineSeries

import jlink
import xlink


os.environ['PATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libusb-1.0.24/MinGW64/dll') + os.pathsep + os.environ['PATH']


class RingBuffer(ctypes.Structure):
    _fields_ = [
        ('sName',        ctypes.c_uint),    # ctypes.POINTER(ctypes.c_char)，64位Python中 ctypes.POINTER 是64位的，与目标芯片不符
        ('pBuffer',      ctypes.c_uint),    # ctypes.POINTER(ctypes.c_byte)
        ('SizeOfBuffer', ctypes.c_uint),
        ('WrOff',        ctypes.c_uint),    # Position of next item to be written. 对于aUp：   芯片更新WrOff，主机更新RdOff
        ('RdOff',        ctypes.c_uint),    # Position of next item to be read.    对于aDown： 主机更新WrOff，芯片更新RdOff
        ('Flags',        ctypes.c_uint),
    ]

# These should match SEGGER_RTT_MAX_NUM_UP_BUFFERS / SEGGER_RTT_MAX_NUM_DOWN_BUFFERS in firmware
RTT_MAX_NUM_UP_BUFFERS = 3
RTT_MAX_NUM_DOWN_BUFFERS = 3

class SEGGER_RTT_CB(ctypes.Structure):      # Control Block
    _fields_ = [
        ('acID',              ctypes.c_char * 16),
        ('MaxNumUpBuffers',   ctypes.c_uint),
        ('MaxNumDownBuffers', ctypes.c_uint),
        ('aUp',               RingBuffer * RTT_MAX_NUM_UP_BUFFERS),
        ('aDown',             RingBuffer * RTT_MAX_NUM_DOWN_BUFFERS),
    ]


Variable = collections.namedtuple('Variable', 'name addr size')                 # variable from *.elf file
Valuable = collections.namedtuple('Valuable', 'name addr size typ fmt show')    # variable to read and display

zero_if = lambda i: 0 if i == -1 else i

'''
from RTTView_UI import Ui_RTTView
class RTTView(QWidget, Ui_RTTView):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        self.setupUi(self)
'''
class RTTView(QWidget):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        uic.loadUi('RTTView.ui', self)

        self.resize(960, 700)

        self.hWidget2.setVisible(False)

        self.tblVar.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        self.Vars = {}  # {name: Variable}
        self.Vals = {}  # {row:  Valuable}

        self.initSetting()

        self.initQwtPlot()

        self.auto_scroll = True
        self.txtMain_font_size = 14
        self.applyDarkTheme()

        self.rcvbuff = b''
        self.rcvfile = None

        self.elffile = None

        self.tmrRTT = QtCore.QTimer()
        self.tmrRTT.setInterval(10)
        self.tmrRTT.timeout.connect(self.on_tmrRTT_timeout)
        self.tmrRTT.start()

        self.tmrRTT_Cnt = 0
        self.rtt_fail_count = 0  # consecutive read failure counter (for auto-reconnect)
        self.rtt_reconnecting = False  # flag to prevent multiple reconnect attempts
        self._expected_RdOff = 0  # tracks the RdOff value we last wrote to MCU
        self.auto_scroll = True  # auto-scroll enabled by default

        # Install event filter for Ctrl+wheel zoom
        self.txtMain.installEventFilter(self)

        # Add auto-scroll checkbox programmatically
        self.chkAutoScroll = QtWidgets.QCheckBox('自动滚动', self)
        self.chkAutoScroll.setChecked(True)
        self.chkAutoScroll.stateChanged.connect(self.on_chkAutoScroll_stateChanged)
        self.gLayout1.addWidget(self.chkAutoScroll, 0, 4, 1, 1)

        # Modernize UI labels (keep Chinese)
        self.setWindowTitle('RTTView - SEGGER RTT 查看器')
        self.btnOpen.setText('打开连接')
        self.btnClear.setText('清除显示')
        self.btnDLL.setText('浏览')
        self.btnAddr.setText('浏览')
        self.btnFile.setText('浏览')
        self.btnSend.setText('发送')
        self.chkWave.setText('波形显示')
        self.chkSave.setText('保存接收')
        self.lblDLL.setText('接口：')
        self.lblAddr.setText('地址：')
        self.cmbICode.setToolTip('接收内容编码')
        self.cmbOCode.setToolTip('发送内容编码')
        self.cmbEnter.setToolTip('发送回车编码')

        # Track connection state instead of relying on button text
        self._connected = False
    
    def initSetting(self):
        if not os.path.exists('setting.ini'):
            open('setting.ini', 'w', encoding='utf-8')
        
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

        self.cmbMode.setCurrentIndex(zero_if(self.cmbMode.findText(self.conf.get('link', 'mode'))))
        self.cmbSpeed.setCurrentIndex(zero_if(self.cmbSpeed.findText(self.conf.get('link', 'speed'))))

        self.cmbDLL.addItem(self.conf.get('link', 'jlink'), 'jlink')
        self.cmbDLL.addItem('OpenOCD Tcl RPC (6666)', 'openocd')
        self.daplink_detect()    # add DAPLink

        self.cmbDLL.setCurrentIndex(zero_if(self.cmbDLL.findText(self.conf.get('link', 'select'))))

        self.cmbAddr.addItems(eval(self.conf.get('link', 'address')))

        self.Vals = eval(self.conf.get('link', 'variable'))

        if not self.conf.has_section('encode'):
            self.conf.add_section('encode')
            self.conf.set('encode', 'input', 'ASCII')
            self.conf.set('encode', 'output', 'ASCII')
            self.conf.set('encode', 'oenter', r'\r\n')  # output enter (line feed)

            self.conf.add_section('display')
            self.conf.set('display', 'ncurve', '4')     # max curve number supported
            self.conf.set('display', 'npoint', '1000')

            self.conf.add_section('others')
            self.conf.set('others', 'history', '11 22 33 AA BB CC')
            self.conf.set('others', 'savfile', os.path.join(os.getcwd(), 'rtt_data.txt'))

        self.cmbICode.setCurrentIndex(zero_if(self.cmbICode.findText(self.conf.get('encode', 'input'))))
        self.cmbOCode.setCurrentIndex(zero_if(self.cmbOCode.findText(self.conf.get('encode', 'output'))))
        self.cmbEnter.setCurrentIndex(zero_if(self.cmbEnter.findText(self.conf.get('encode', 'oenter'))))

        self.N_CURVE = int(self.conf.get('display', 'ncurve'), 10)
        self.N_POINT = int(self.conf.get('display', 'npoint'), 10)

        self.linFile.setText(self.conf.get('others', 'savfile'))

        self.txtSend.setPlainText(self.conf.get('others', 'history'))

    def initQwtPlot(self):
        self.PlotData  = [[0]*self.N_POINT for i in range(self.N_CURVE)]
        self.PlotPoint = [[QtCore.QPointF(j, 0) for j in range(self.N_POINT)] for i in range(self.N_CURVE)]

        self.PlotChart = QChart()

        self.ChartView = QChartView(self.PlotChart)
        self.ChartView.setVisible(False)
        self.vLayout.insertWidget(0, self.ChartView)
        
        self.PlotCurve = [QLineSeries() for i in range(self.N_CURVE)]

    def applyDarkTheme(self):
        """Apply JLink-style dark theme to the entire application."""
        dark_qss = """
            QWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QMainWindow, QWidget {
                background-color: #1E1E1E;
            }
            QTextEdit, QPlainTextEdit {
                background-color: #1E1E1E;
                border: 1px solid #3C3C3C;
                font-family: Consolas, 'Courier New', monospace;
                selection-background-color: #264F78;
            }
            QTextEdit#txtMain {
                font-size: 14pt;
                line-height: 1.2;
            }
            QTextEdit#txtSend {
                font-size: 10pt;
            }
            QComboBox {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                padding: 2px 6px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #D4D4D4;
                margin-right: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                selection-background-color: #264F78;
            }
            QPushButton {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                padding: 4px 12px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #4C4C4C;
                border-color: #666666;
            }
            QPushButton:pressed {
                background-color: #2C2C2C;
            }
            QTableWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                gridline-color: #3C3C3C;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QTableWidget::item:selected {
                background-color: #264F78;
            }
            QHeaderView::section {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                padding: 2px 4px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QCheckBox {
                color: #D4D4D4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
                spacing: 6px;
            }
            QLabel {
                color: #D4D4D4;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QGroupBox {
                color: #D4D4D4;
                border: 1px solid #3C3C3C;
                margin-top: 8px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
            }
            QScrollBar:vertical {
                background-color: #1E1E1E;
                width: 10px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666666;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #1E1E1E;
                height: 10px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background-color: #555555;
                min-width: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #666666;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
            QMenu {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
            QMenu::item:selected {
                background-color: #264F78;
            }
            QFileDialog, QDialog {
                background-color: #1E1E1E;
                color: #D4D4D4;
            }
            QLineEdit {
                background-color: #3C3C3C;
                color: #D4D4D4;
                border: 1px solid #555555;
                padding: 2px 6px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 10pt;
            }
        """
        self.setStyleSheet(dark_qss)

        # Set Consolas font on txtMain
        self.txtMain_font = QtGui.QFont('Consolas', self.txtMain_font_size)
        self.txtMain.setFont(self.txtMain_font)

        # Set default text color via palette (lower priority than QTextCharFormat, so ANSI colors will override)
        palette = self.txtMain.palette()
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor('#D4D4D4'))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor('#1E1E1E'))
        self.txtMain.setPalette(palette)

    # ── ANSI Parser ──────────────────────────────────────────────
    # 256-color palette (indexes 16-231: 6x6x6 cube, 232-255: grayscale)
    _ansi_16 = [
        (0, 0, 0),       (197, 15, 31),   (19, 161, 14),   (193, 156, 0),
        (0, 55, 218),    (136, 23, 152),  (58, 150, 221),  (204, 204, 204),
        (118, 118, 118), (231, 72, 86),   (22, 198, 12),   (249, 241, 165),
        (59, 120, 255),  (180, 0, 158),   (97, 214, 214),  (255, 255, 255),
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
        """Full ANSI parser: converts ANSI escapes to HTML spans for reliable color rendering."""
        if not text:
            return

        self._ansi_clear = False
        encoded = text.encode('utf-8', errors='replace')
        spans = self._parse_ansi(encoded)

        if self._ansi_clear:
            self.txtMain.clear()
        if not spans:
            return

        # Build HTML from spans
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
            self.txtMain.verticalScrollBar().setValue(
                self.txtMain.verticalScrollBar().maximum()
            )

    def _parse_ansi(self, data: bytes) -> list:
        """State-machine parser yielding (text, format_dict) pairs.

        format_dict keys: 'fg' (r,g,b), 'bg' (r,g,b), 'bold' (bool), 'italic' (bool)
        """
        results = []
        text_buf = []
        bold = False
        italic = False
        fg = None
        bg = None

        def _make_fmt():
            return dict(fg=fg, bg=bg, bold=bold, italic=italic)

        def _color256(n):
            n = max(0, min(255, n))
            return self._palette256[n]

        def _parse_sgr(params):
            nonlocal bold, italic, fg, bg
            if not params:
                params = [0]
            # Check if this is a mixed sequence like [36;0m where 0 shouldn't fully reset
            has_color = any(30 <= p <= 37 or 90 <= p <= 97 or p in (38, 48)
                           or 40 <= p <= 47 or 100 <= p <= 107 for p in params)
            has_zero = 0 in params
            i = 0
            while i < len(params):
                code = params[i]
                if code == 0:
                    # In mixed sequences like [36;0m, firmware uses 0 as "normal style"
                    # not full reset. Only full-reset when 0 is alone.
                    if has_color and has_zero:
                        bold = False; italic = False  # keep fg/bg
                    else:
                        bold = False; italic = False; fg = None; bg = None
                elif code == 1:
                    bold = True
                elif code == 2:
                    bold = False  # dim
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

        state = 0  # 0=normal, 1=ESC, 2=CSI
        csi_buf = ''

        for byte_val in data:
            if state == 0:
                if byte_val == 0x1B:
                    _flush(); state = 1; csi_buf = ''
                elif byte_val == 0x0A:
                    _flush(); results.append(('\n', _make_fmt()))
                elif byte_val == 0x0D:
                    pass  # discard \r, HTML uses <br> for line breaks only
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

    def _apply_timestamp(self, text):
        """Prepend timestamp to text if chkTime is enabled."""
        if self.chkTime.isChecked():
            now = datetime.datetime.now()
            ts = now.strftime('%H:%M:%S.') + f'{now.microsecond // 1000:03d}'
            lines = text.split('\n')
            if lines:
                lines[0] = f'[{ts}] {lines[0]}'
            return '\n'.join(lines)
        return text

    def eventFilter(self, obj, event):
        """Handle Ctrl+wheel for font zoom in/out."""
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

    def daplink_detect(self):
        try:
            from pyocd.probe import aggregator
            self.daplinks = aggregator.DebugProbeAggregator.get_all_connected_probes()
        except Exception as e:
            self.daplinks = []

        if len(self.daplinks) != self.cmbDLL.count() - 2:
            for i in range(2, self.cmbDLL.count()):
                self.cmbDLL.removeItem(2)

            for i, daplink in enumerate(self.daplinks):
                self.cmbDLL.addItem(f'{daplink.product_name} ({daplink.unique_id})', i)
    
    @pyqtSlot()
    def on_btnOpen_clicked(self):
        if not self._connected:
            mode = self.cmbMode.currentText()
            mode = mode.replace(' SWD', '').replace(' cJTAG', '').replace(' JTAG', 'J').lower()
            core = 'Cortex-M0' if mode.startswith('arm') else 'RISC-V'
            speed= int(self.cmbSpeed.currentText().split()[0]) * 1000 # KHz
            try:
                item_data = self.cmbDLL.currentData()

                if item_data == 'jlink':
                    self.xlk = xlink.XLink(jlink.JLink(self.cmbDLL.currentText(), mode, core, speed))
                
                elif item_data == 'openocd':
                    import openocd
                    self.xlk = xlink.XLink(openocd.OpenOCD(mode=mode, core=core, speed=speed))
                
                else:
                    from pyocd.coresight import dap, ap, cortex_m
                    daplink = self.daplinks[item_data]
                    daplink.open()

                    _dp = dap.DebugPort(daplink, None)
                    _dp.init()
                    _dp.power_up_debug()
                    _dp.set_clock(speed * 1000)

                    _ap = ap.AHB_AP(_dp, 0)
                    _ap.init()

                    self.xlk = xlink.XLink(cortex_m.CortexM(None, _ap))
                
                if self.chkSave.isChecked():
                    savfile, ext = os.path.splitext(self.linFile.text())
                    savfile = f'{savfile}_{datetime.datetime.now().strftime("%y%m%d%H%M%S")}{ext}'

                    self.rcvfile = open(savfile, 'w')

                if re.match(r'0[xX][0-9a-fA-F]{8}', self.cmbAddr.currentText()):
                    addr = int(self.cmbAddr.currentText(), 16)
                    for i in range(64):
                        data = self.xlk.read_mem_U8(addr + 1024 * i, 1024 + 32) # 多读32字节，防止搜索内容在边界处
                        index = bytes(data).find(b'SEGGER RTT')
                        if index != -1:
                            self.RTTAddr = addr + 1024 * i + index

                            data = self.xlk.read_mem_U8(self.RTTAddr, ctypes.sizeof(SEGGER_RTT_CB))

                            rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(data))
                            self.aUpAddr = self.RTTAddr + 16 + 4 + 4
                            self.aDownAddr = self.aUpAddr + ctypes.sizeof(RingBuffer) * rtt_cb.MaxNumUpBuffers

                            self.txtMain.append(f'\n_SEGGER_RTT @ 0x{self.RTTAddr:08X} with {rtt_cb.MaxNumUpBuffers} aUp and {rtt_cb.MaxNumDownBuffers} aDown\n')
                            break
                        
                    else:
                        raise Exception('Can not find _SEGGER_RTT')

                    self.rtt_cb = True

                else:
                    self.rtt_cb = False

            except Exception as e:
                self.txtMain.append(f'\nerror: {str(e)}\n')

                try:
                    self.xlk.close()
                except:
                    try:
                        daplink.close()
                    except:
                        pass

            else:
                self.cmbDLL.setEnabled(False)
                self.btnDLL.setEnabled(False)
                self.cmbAddr.setEnabled(False)
                self.chkSave.setEnabled(False)
                self.btnOpen.setText('关闭连接')
                self._connected = True

        else:
            if self.rcvfile and not self.rcvfile.closed:
                self.rcvfile.close()

            self.xlk.close()

            self.rtt_fail_count = 0
            self.rtt_reconnecting = False
            self.cmbDLL.setEnabled(True)
            self.btnDLL.setEnabled(True)
            self.cmbAddr.setEnabled(True)
            self.chkSave.setEnabled(True)
            self.btnOpen.setText('打开连接')
            self._connected = False
    
    def aUpRead(self):
        data = self.xlk.read_mem_U8(self.aUpAddr, ctypes.sizeof(RingBuffer))

        aUp = RingBuffer.from_buffer(bytearray(data))

        # Validate RingBuffer data: during MCU reset, SWD reads return garbage.
        # A valid RingBuffer has: SizeOfBuffer=2048, WrOff/RdOff < SizeOfBuffer,
        # pBuffer in RAM range, Flags in {0,1,2}.
        if not (aUp.SizeOfBuffer == 2048
                and aUp.WrOff < aUp.SizeOfBuffer
                and aUp.RdOff < aUp.SizeOfBuffer
                and 0x20000000 <= aUp.pBuffer <= 0x20210000
                and aUp.Flags <= 2):
            # Garbage data - MCU is resetting or SWD connection is unstable
            raise Exception('Invalid RingBuffer data (garbage read during MCU reset)')

        # Detect MCU reset by comparing actual RdOff from MCU with what we last wrote.
        # MCU never modifies RdOff on its own - only RTTView updates it.
        # If MCU was reset, _DoInit() re-initializes the entire CB including RdOff=0.
        # So if actual RdOff != our expected value, MCU was reset.
        # We also check WrOff: after reset, WrOff starts from 0 and grows.
        if hasattr(self, '_expected_RdOff') and self._expected_RdOff > 64:
            # We previously wrote a non-trivial RdOff value.
            # If MCU's RdOff is now significantly different, it was reset.
            # After reset: RdOff=0 (re-initialized), WrOff is small (new data)
            if aUp.RdOff == 0 and aUp.WrOff < 512:
                # MCU was reset and re-initialized RTT
                self._expected_RdOff = 0
                self.rtt_fail_count = 0
                self.rcvbuff = b''  # discard stale receive buffer
                self.txtMain.append('\n[!] 检测到 MCU 复位，已重置缓冲区\n')
                return b''

        if aUp.RdOff <= aUp.WrOff:
            cnt = aUp.WrOff - aUp.RdOff

        else:
            # Wrap-around: read from RdOff to end, then from start to WrOff
            cnt1 = aUp.SizeOfBuffer - aUp.RdOff
            cnt2 = aUp.WrOff
            cnt = cnt1 + cnt2

        if 0 < cnt < 1024*1024:
            bufAddr = ctypes.cast(aUp.pBuffer, ctypes.c_void_p).value

            if aUp.RdOff <= aUp.WrOff:
                # Normal case: single read
                data = self.xlk.read_mem_U8(bufAddr + aUp.RdOff, cnt)
            else:
                # Wrap-around: two reads
                part1 = self.xlk.read_mem_U8(bufAddr + aUp.RdOff, cnt1)
                part2 = self.xlk.read_mem_U8(bufAddr, cnt2)
                data = part1 + part2

            aUp.RdOff = (aUp.RdOff + cnt) % aUp.SizeOfBuffer

            self.xlk.write_U32(self.aUpAddr + 4*4, aUp.RdOff)
            self._expected_RdOff = aUp.RdOff  # track what we wrote

        else:
            data = []

        return bytes(data)

    def _auto_reconnect(self):
        """Auto-reconnect after MCU reset. Re-establishes SWD link and re-scans for _SEGGER_RTT."""
        try:
            self.xlk.close()
        except:
            pass
        self.daplink_detect()

        from pyocd.coresight import dap, ap, cortex_m

        daplink_index = None
        for i in range(self.cmbDLL.count()):
            if self.cmbDLL.itemData(i) not in ('jlink', 'openocd'):
                daplink_index = i
                break
        if daplink_index is None:
            raise Exception('No DAPLink found')

        self.cmbDLL.setCurrentIndex(daplink_index)
        daplink = self.daplinks[self.cmbDLL.currentData()]
        daplink.open()

        _dp = dap.DebugPort(daplink, None)
        _dp.init()
        _dp.power_up_debug()

        _ap = ap.AHB_AP(_dp, 0)
        _ap.init()

        self.xlk = xlink.XLink(cortex_m.CortexM(None, _ap))

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
                return

        raise Exception('Can not find _SEGGER_RTT after reconnect')

    def aDownWrite(self, bytes):
        data = self.xlk.read_mem_U8(self.aDownAddr, ctypes.sizeof(RingBuffer))

        aDown = RingBuffer.from_buffer(bytearray(data))
        
        if aDown.WrOff >= aDown.RdOff:
            if aDown.RdOff != 0: cnt = min(aDown.SizeOfBuffer - aDown.WrOff, len(bytes))
            else:                cnt = min(aDown.SizeOfBuffer - 1 - aDown.WrOff, len(bytes))   # 写入操作不能使得 aDown.WrOff == aDown.RdOff，以区分满和空
            self.xlk.write_mem(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, bytes[:cnt])
            
            aDown.WrOff += cnt
            if aDown.WrOff == aDown.SizeOfBuffer: aDown.WrOff = 0

            bytes = bytes[cnt:]

        if bytes and aDown.RdOff != 0 and aDown.RdOff != 1:        # != 0 确保 aDown.WrOff 折返回 0，!= 1 确保有空间可写入
            cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(bytes))   # - 1 确保写入操作不导致WrOff与RdOff指向同一位置
            self.xlk.write_mem(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, bytes[:cnt])

            aDown.WrOff += cnt

        self.xlk.write_U32(self.aDownAddr + 4*3, aDown.WrOff)
    
    def on_tmrRTT_timeout(self):
        self.tmrRTT_Cnt += 1
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

            except Exception as e:
                rcvdbytes = b''
                self.rtt_fail_count += 1

                # Auto-reconnect after 50 consecutive failures (~500ms)
                if self.rtt_fail_count >= 50 and not self.rtt_reconnecting:
                    self.rtt_reconnecting = True
                    self.txtMain.append('\n[!] 连接断开，正在自动重连...\n')
                    try:
                        self._auto_reconnect()
                    except Exception as e2:
                        self.txtMain.append(f'[!] 自动重连失败: {str(e2)}\n')
                    finally:
                        self.rtt_reconnecting = False
                        self.rtt_fail_count = 0

            if rcvdbytes:
                self.rtt_fail_count = 0  # reset failure counter on successful read
                if self.rcvfile and not self.rcvfile.closed:
                    self.rcvfile.write(rcvdbytes.decode('latin-1'))

                self.rcvbuff += rcvdbytes
                
                if self.chkWave.isChecked():
                    if b',' in self.rcvbuff:
                        try:
                            d = self.rcvbuff[0:self.rcvbuff.rfind(b',')].split(b',')        # [b'12', b'34'] or [b'12 34', b'56 78']
                            if self.cmbICode.currentText() != 'HEX':
                                d = [[float(x)   for x in X.strip().split()] for X in d]    # [[12], [34]]   or [[12, 34], [56, 78]]
                            else:
                                d = [[int(x, 16) for x in X.strip().split()] for X in d]    # for example, d = [b'12', b'AA', b'5A5A']
                            for arr in d:
                                for i, x in enumerate(arr):
                                    if i == self.N_CURVE: break

                                    self.PlotData[i].pop(0)
                                    self.PlotData[i].append(x)
                                    self.PlotPoint[i].pop(0)
                                    self.PlotPoint[i].append(QtCore.QPointF(999, x))
                            
                            self.rcvbuff = self.rcvbuff[self.rcvbuff.rfind(b',')+1:]

                            if self.tmrRTT_Cnt % 4 == 0:
                                if len(d[-1]) != len([series for series in self.PlotChart.series() if series.isVisible()]):
                                    for series in self.PlotChart.series():
                                        self.PlotChart.removeSeries(series)
                                    for i in range(min(len(d[-1]), self.N_CURVE)):
                                        self.PlotCurve[i].setName(f'Curve {i+1}')
                                        self.PlotChart.addSeries(self.PlotCurve[i])
                                    self.PlotChart.createDefaultAxes()

                                for i in range(len(self.PlotChart.series())):
                                    for j, point in enumerate(self.PlotPoint[i]):
                                        point.setX(j)
                                
                                    self.PlotCurve[i].replace(self.PlotPoint[i])
                            
                                miny = min([min(d) for d in self.PlotData[:len(self.PlotChart.series())]])
                                maxy = max([max(d) for d in self.PlotData[:len(self.PlotChart.series())]])
                                self.PlotChart.axisY().setRange(miny, maxy)
                                self.PlotChart.axisX().setRange(0000, self.N_POINT)
            
                        except Exception as e:
                            self.rcvbuff = b''
                            print(e)

                else:
                    text = ''
                    if self.cmbICode.currentText() == 'ASCII':
                        text = ''.join([chr(x) for x in self.rcvbuff])
                        self.rcvbuff = b''

                    elif self.cmbICode.currentText() == 'HEX':
                        text = ' '.join([f'{x:02X}' for x in self.rcvbuff]) + ' '
                        self.rcvbuff = b''

                    elif self.cmbICode.currentText() == 'GBK':
                        while len(self.rcvbuff):
                            if self.rcvbuff[0:1].decode('GBK', 'ignore'):
                                text += self.rcvbuff[0:1].decode('GBK')
                                self.rcvbuff = self.rcvbuff[1:]

                            elif len(self.rcvbuff) > 1 and self.rcvbuff[0:2].decode('GBK', 'ignore'):
                                text += self.rcvbuff[0:2].decode('GBK')
                                self.rcvbuff = self.rcvbuff[2:]

                            elif len(self.rcvbuff) > 1:
                                text += chr(self.rcvbuff[0])
                                self.rcvbuff = self.rcvbuff[1:]

                            else:
                                break

                    elif self.cmbICode.currentText() == 'UTF-8':
                        while len(self.rcvbuff):
                            if self.rcvbuff[0:1].decode('UTF-8', 'ignore'):
                                text += self.rcvbuff[0:1].decode('UTF-8')
                                self.rcvbuff = self.rcvbuff[1:]

                            elif len(self.rcvbuff) > 1 and self.rcvbuff[0:2].decode('UTF-8', 'ignore'):
                                text += self.rcvbuff[0:2].decode('UTF-8')
                                self.rcvbuff = self.rcvbuff[2:]

                            elif len(self.rcvbuff) > 2 and self.rcvbuff[0:3].decode('UTF-8', 'ignore'):
                                text += self.rcvbuff[0:3].decode('UTF-8')
                                self.rcvbuff = self.rcvbuff[3:]

                            elif len(self.rcvbuff) > 3 and self.rcvbuff[0:4].decode('UTF-8', 'ignore'):
                                text += self.rcvbuff[0:4].decode('UTF-8')
                                self.rcvbuff = self.rcvbuff[4:]

                            elif len(self.rcvbuff) > 3:
                                text += chr(self.rcvbuff[0])
                                self.rcvbuff = self.rcvbuff[1:]

                            else:
                                break

                    if len(self.txtMain.toPlainText()) > 25000: self.txtMain.clear()
                    text = self._apply_timestamp(text)
                    self._render_ansi_text(text)

        else:
            if self.tmrRTT_Cnt % 100 == 1:
                self.daplink_detect()

            if self.tmrRTT_Cnt % 100 == 2:
                path = self.cmbAddr.currentText()
                if os.path.exists(path) and os.path.isfile(path):
                    if self.elffile != (path, os.path.getmtime(path)):
                        self.elffile = (path, os.path.getmtime(path))

                        self.parse_elffile(path)

    @pyqtSlot()
    def on_btnSend_clicked(self):
        if self._connected:
            text = self.txtSend.toPlainText()

            if self.cmbOCode.currentText() == 'HEX':
                try:
                    self.aDownWrite(bytes([int(x, 16) for x in text.split()]))
                except Exception as e:
                    print(e)

            else:
                if self.cmbEnter.currentText() == r'\r\n':
                    text = text.replace('\n', '\r\n')
                
                try:
                    self.aDownWrite(text.encode(self.cmbOCode.currentText()))
                except Exception as e:
                    print(e)

    @pyqtSlot()
    def on_btnDLL_clicked(self):
        dllpath, filter = QFileDialog.getOpenFileName(caption='JLink_x64.dll path', filter='动态链接库文件 (*.dll *.so)', directory=self.cmbDLL.itemText(0))
        if dllpath != '':
            self.cmbDLL.setItemText(0, dllpath)

    @pyqtSlot()
    def on_btnAddr_clicked(self):
        elfpath, filter = QFileDialog.getOpenFileName(caption='elf file path', filter='elf file (*.elf *.axf *.out)', directory=self.cmbAddr.currentText())
        if elfpath != '':
            self.cmbAddr.insertItem(0, elfpath)
            self.cmbAddr.setCurrentIndex(0)

    @pyqtSlot(str)
    def on_cmbAddr_currentIndexChanged(self, text):
        if re.match(r'0[xX][0-9a-fA-F]{8}', text):
            self.tblVar.setVisible(False)
            self.gLayout2.removeWidget(self.tblVar)

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

            self.gLayout2.addWidget(self.tblVar, 0, 0, 5, 2)
            self.tblVar.setVisible(True)

    @pyqtSlot(int)
    def on_chkSave_stateChanged(self, state):
        self.hWidget2.setVisible(state == Qt.Checked)
    
    @pyqtSlot()
    def on_btnFile_clicked(self):
        savfile, filter = QFileDialog.getSaveFileName(caption='数据保存文件路径', filter='文本文件 (*.txt)', directory=self.linFile.text())
        if savfile:
            self.linFile.setText(savfile)

    def parse_elffile(self, path):
        try:
            from elftools.elf.elffile import ELFFile
            elffile = ELFFile(open(path, 'rb'))

            self.Vars = {}
            for sym in elffile.get_section_by_name('.symtab').iter_symbols():
                if sym.entry['st_info']['type'] == 'STT_OBJECT' and sym.entry['st_size'] in (1, 2, 4, 8):
                    self.Vars[sym.name] = Variable(sym.name, sym.entry['st_value'], sym.entry['st_size'])

        except Exception as e:
            print(f'parse elf file fail: {e}')

        else:
            Vals = {row: val for row, val in self.Vals.items() if val.name in self.Vars}
            self.Vals = {i: val for i, val in enumerate(Vals.values())}

            for row, val in self.Vals.items():
                var = self.Vars[val.name]
                if val.addr != var.addr:
                    self.Vals[row] = self.Vals[row]._replace(addr = var.addr)
                if val.size != var.size:
                    typ, fmt = self.len2type[var.size][0]
                    self.Vals[row] = self.Vals[row]._replace(size = var.size, typ = typ, fmt = fmt)

            self.tblVar_redraw()

    len2type = {
        1: [('int8',  'b'), ('uint8',  'B')],
        2: [('int16', 'h'), ('uint16', 'H')],
        4: [('int32', 'i'), ('uint32', 'I'), ('float',  'f')],
        8: [('int64', 'q'), ('uint64', 'Q'), ('double', 'd')]
    }

    def tblVar_redraw(self):
        while self.tblVar.rowCount():
            self.tblVar.removeRow(0)

        for series in self.PlotChart.series():
            self.PlotChart.removeSeries(series)

        for row, val in self.Vals.items():
            self.tblVar.insertRow(row)
            self.tblVar_setRow(row, val)

        if self.tblVar.rowCount() < self.N_CURVE:
            self.tblVar.insertRow(self.tblVar.rowCount())

    def tblVar_setRow(self, row: int, val: Valuable):
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
    def on_tblVar_cellDoubleClicked(self, row, column):
        if self._connected: return

        if column < 3:
            dlg = VarDialog(self, row)
            if dlg.exec() == QDialog.Accepted:
                var = self.Vars[dlg.cmbName.currentText()]
                typ, fmt = dlg.cmbType.currentText(), dlg.cmbType.currentData()

                self.Vals[row] = Valuable(var.name, var.addr, var.size, typ, fmt, True)

                self.tblVar_setRow(row, self.Vals[row])

                if self.tblVar.rowCount() < self.N_CURVE and row == self.tblVar.rowCount() - 1:
                    self.tblVar.insertRow(self.tblVar.rowCount())
        
        elif column == 3:
            if self.tblVar.item(row, 3):
                self.Vals[row] = self.Vals[row]._replace(show = not self.Vals[row].show)

                self.tblVar.item(row, 3).setText('显示' if self.Vals[row].show else '不显示')

                self.PlotCurve[row].setVisible(self.Vals[row].show)

        elif column == 4:
            if self.tblVar.item(row, 4):
                self.Vals.pop(row)
                self.Vals = {i: val for i, val in enumerate(self.Vals.values())}

                self.tblVar_redraw()

    @pyqtSlot(int)
    def on_chkWave_stateChanged(self, state):
        self.ChartView.setVisible(state == Qt.Checked)
        self.txtMain.setVisible(state == Qt.Unchecked)

    @pyqtSlot(int)
    def on_chkAutoScroll_stateChanged(self, state):
        self.auto_scroll = (state == Qt.Checked)

    @pyqtSlot()
    def on_btnClear_clicked(self):
        self.txtMain.clear()
    
    def closeEvent(self, evt):
        if self.rcvfile and not self.rcvfile.closed:
            self.rcvfile.close()

        self.conf.set('link',   'mode',   self.cmbMode.currentText())
        self.conf.set('link',   'speed',  self.cmbSpeed.currentText())
        self.conf.set('link',   'jlink',  self.cmbDLL.itemText(0))
        self.conf.set('link',   'select', self.cmbDLL.currentText())
        self.conf.set('encode', 'input',  self.cmbICode.currentText())
        self.conf.set('encode', 'output', self.cmbOCode.currentText())
        self.conf.set('encode', 'oenter', self.cmbEnter.currentText())
        self.conf.set('others', 'history', self.txtSend.toPlainText())
        self.conf.set('others', 'savfile', self.linFile.text())

        addrs = [self.cmbAddr.currentText()] + [self.cmbAddr.itemText(i) for i in range(self.cmbAddr.count())]
        self.conf.set('link',   'address', repr(list(collections.OrderedDict.fromkeys(addrs))))   # 保留顺序去重

        self.conf.set('link',   'variable', repr(self.Vals))

        self.conf.write(open('setting.ini', 'w', encoding='utf-8'))
        


from PyQt5.QtWidgets import QSizePolicy, QDialogButtonBox

class VarDialog(QDialog):
    def __init__(self, parent, row):
        super(VarDialog, self).__init__(parent)

        self.resize(400, 100)
        self.setWindowTitle('VarDialog')

        self.cmbType = QtWidgets.QComboBox(self)
        self.cmbType.setMinimumSize(QtCore.QSize(80, 0))

        self.cmbName = QtWidgets.QComboBox(self)
        self.cmbName.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmbName.currentTextChanged.connect(self.on_cmbName_currentTextChanged)
        
        self.hLayout = QtWidgets.QHBoxLayout()
        self.hLayout.addWidget(QtWidgets.QLabel('变量：', self))
        self.hLayout.addWidget(self.cmbName)
        self.hLayout.addWidget(QtWidgets.QLabel('    ', self))
        self.hLayout.addWidget(QtWidgets.QLabel('类型：', self))
        self.hLayout.addWidget(self.cmbType)

        self.btnBox = QtWidgets.QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.btnBox.accepted.connect(self.accept)
        self.btnBox.rejected.connect(self.reject)
        
        self.vLayout = QtWidgets.QVBoxLayout(self)
        self.vLayout.addLayout(self.hLayout)
        self.vLayout.addItem(QtWidgets.QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.vLayout.addWidget(self.btnBox)

        self.cmbName.addItems(parent.Vars.keys())

        if parent.tblVar.item(row, 0):
            self.cmbName.setCurrentText(parent.tblVar.item(row, 0).text())
            self.cmbType.setCurrentText(parent.tblVar.item(row, 2).text())

    @pyqtSlot(str)
    def on_cmbName_currentTextChanged(self, name):
        size = self.parent().Vars[name].size

        self.cmbType.clear()
        for typ, fmt in self.parent().len2type[size]:
            self.cmbType.addItem(typ, fmt)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    rtt = RTTView()
    rtt.show()
    app.exec()
