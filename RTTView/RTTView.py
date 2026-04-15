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

        self.hWidget2.setVisible(False)

        self.tblVar.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

        self.Vars = {}  # {name: Variable}
        self.Vals = {}  # {row:  Valuable}

        self.initSetting()

        self.initQwtPlot()

        self.auto_scroll = True
        self.txtMain_font_size = 10
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
        # Place it near the existing controls in the bottom bar
        self.gLayout1.addWidget(self.chkAutoScroll, 0, 4, 1, 1)
    
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
                font-size: 10pt;
                selection-background-color: #264F78;
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

    # ANSI SGR color codes mapping
    _ansi_colors = {
        30: '#808080',  # Black   -> gray (on dark bg)
        31: '#FF6B6B',  # Red
        32: '#6BCB6B',  # Green
        33: '#FFD76B',  # Yellow
        34: '#6B9FFF',  # Blue
        35: '#D06BFF',  # Magenta
        36: '#6BFFFF',  # Cyan
        37: '#D4D4D4',  # White   -> light gray
        90: '#555555',  # Bright Black
        91: '#FF8888',  # Bright Red
        92: '#88FF88',  # Bright Green
        93: '#FFFF88',  # Bright Yellow
        94: '#88BBFF',  # Bright Blue
        95: '#FF88FF',  # Bright Magenta
        96: '#88FFFF',  # Bright Cyan
        97: '#FFFFFF',  # Bright White
    }

    def _insert_ansi_colored_text(self, text):
        """Parse ANSI SGR escape sequences and insert colored text using QTextCharFormat.

        Handles sequences like: ESC[31;2m (red), ESC[36;2m (cyan), ESC[0m (reset), etc.
        Uses QTextCursor.insertText() with character format for reliable color rendering.
        """
        if not text:
            return

        # State machine: parse text and track current color
        spans = []  # list of (color_hex_str, plain_text) tuples
        current_color = None
        i = 0
        n = len(text)
        current_text = []

        while i < n:
            if text[i] == '\x1b' and i + 1 < n and text[i + 1] == '[':
                if current_text:
                    spans.append((current_color, ''.join(current_text)))
                    current_text = []

                i += 2  # skip ESC + '['
                params = []
                param_buf = ''
                found_terminator = False
                while i < n:
                    c = text[i]
                    if c.isdigit():
                        param_buf += c
                    elif c == ';':
                        if param_buf:
                            params.append(int(param_buf))
                            param_buf = ''
                    elif c.isalpha():
                        if param_buf:
                            params.append(int(param_buf))
                        cmd = c
                        found_terminator = True
                        i += 1
                        break
                    else:
                        break
                    i += 1

                if not found_terminator:
                    # Incomplete sequence (split across chunks), keep for next time
                    current_text.append('\x1b[')
                    continue

                # Process SGR parameters (only for 'm' terminator)
                if cmd == 'm':
                    if not params:
                        current_color = None
                    else:
                        for p in params:
                            if p == 0:
                                current_color = None
                            elif 30 <= p <= 37:
                                current_color = self._ansi_colors.get(p, '#D4D4D4')
                            elif 90 <= p <= 97:
                                current_color = self._ansi_colors.get(p, '#D4D4D4')
                            elif p == 38:
                                idx = params.index(38)
                                if idx + 2 < len(params):
                                    c256 = params[idx + 2]
                                    current_color = self._ansi_colors.get(c256, '#D4D4D4')
                continue

            current_text.append(text[i])
            i += 1

        if current_text:
            spans.append((current_color, ''.join(current_text)))

        if not spans:
            return

        # Insert using QTextCharFormat and setTextCursor to ensure widget updates
        cursor = self.txtMain.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)

        for color, txt in spans:
            fmt = QtGui.QTextCharFormat()
            if color:
                fmt.setForeground(QtGui.QColor(color))
            else:
                fmt.setForeground(QtGui.QColor('#D4D4D4'))
            cursor.insertText(txt, fmt)

        self.txtMain.setTextCursor(cursor)

        # Auto-scroll
        if self.auto_scroll:
            self.txtMain.verticalScrollBar().setValue(
                self.txtMain.verticalScrollBar().maximum()
            )

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
        if self.btnOpen.text() == '打开连接':
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
        if self.btnOpen.text() == '关闭连接':
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
                    # Use ANSI color rendering for text output
                    self._insert_ansi_colored_text(text)

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
        if self.btnOpen.text() == '关闭连接':
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
        if self.btnOpen.text() == '关闭连接': return

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
