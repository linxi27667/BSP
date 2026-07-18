"""SWO/ITM trace console widget — real-time SWO trace display
with ITM text output, CPU sampling profiler, and exception tracking."""

from collections import defaultdict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTabWidget, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QColor

from core.swo_decoder import SWODecoder, decode_itm_string
from widgets.styles import (
    BG_DARK, BG_HEADER, BORDER, TEXT,
    NUMBER, COMMENT, RED, CYAN,
    FONT_MONO, FONT_SIZE,
    toolbar_style, table_style, text_edit_style,
)

SWO_POLL_MS = 10  # 10ms polling interval
MAX_ITM_LINES = 5000  # max lines in ITM output
MAX_EXC_LINES = 5000  # max lines in exception output
TOP_FUNCTIONS = 50  # top N functions in profiler


class SWOConsole(QWidget):
    """SWO trace display — ITM text, CPU profiler, exception tracker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe = None
        self._running = False
        self._decoder = SWODecoder()
        self._itm_text_buf = []   # buffered ITM text chunks
        self._exc_text_buf = []   # buffered exception text chunks
        self._pc_counts = defaultdict(int)  # addr -> sample count
        self._total_samples = 0
        self._elf_symbols = {}    # addr -> (name, size)
        self._elf_sorted = []     # sorted [(addr, name, size), ...]
        self._poll_counter = 0

        self._register_decoder_callbacks()
        self._init_ui()
        self._init_timer()

    # ------------------------------------------------------------------
    # Decoder callbacks
    # ------------------------------------------------------------------

    def _register_decoder_callbacks(self):
        self._decoder.on_itm_port(0, self._on_itm_port0)
        self._decoder.on_pc_sample(self._on_pc_sample)
        self._decoder.on_exception(self._on_exception)

    def _on_itm_port0(self, frame):
        """ITM port 0 data received — buffer text for UI update."""
        text = decode_itm_string(frame)
        if text:
            self._itm_text_buf.append(text)

    def _on_pc_sample(self, sample):
        """DWT PC sample received — accumulate for profiler."""
        if sample.pc != 0:
            self._pc_counts[sample.pc] += 1
            self._total_samples += 1

    def _on_exception(self, event):
        """DWT exception event received — buffer text for UI update."""
        name = self._exception_name(event.exception_number)
        direction = ">>>" if event.event_type == 'entry' else "<<<"
        text = f"{direction} {name} (#{event.exception_number})"
        self._exc_text_buf.append(text)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # -- Toolbar ----------------------------------------------------
        toolbar = QHBoxLayout()

        self.btn_start = QPushButton("开始")
        self.btn_start.setFixedWidth(70)
        self.btn_start.clicked.connect(self._toggle_running)

        self.btn_clear = QPushButton("清空")
        self.btn_clear.setFixedWidth(70)
        self.btn_clear.clicked.connect(self._clear_all)

        self.btn_load_elf = QPushButton("加载ELF...")
        self.btn_load_elf.setFixedWidth(80)
        self.btn_load_elf.clicked.connect(self._load_elf_dialog)

        self.lbl_status = QLabel("SWO: 已停止")
        self.lbl_status.setStyleSheet(
            f"color: {COMMENT}; font-size: 12px; padding: 2px 8px;"
        )

        self.lbl_stats = QLabel("")
        self.lbl_stats.setStyleSheet(
            f"color: {NUMBER}; font-family: {FONT_MONO}, monospace;"
            f" font-size: {FONT_SIZE}; padding: 2px 8px;"
        )

        for w in (self.btn_start, self.btn_clear, self.btn_load_elf,
                  self.lbl_status, self.lbl_stats):
            toolbar.addWidget(w)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # -- Tabs -------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self._tab_style())

        # Tab 1: ITM Output
        self.txt_itm = QTextEdit()
        self.txt_itm.setReadOnly(True)
        self.txt_itm.setStyleSheet(text_edit_style())
        self.tabs.addTab(self.txt_itm, "SWO控制台")

        # Tab 2: CPU Sampling
        self.tbl_profiler = QTableWidget(0, 4)
        self.tbl_profiler.setHorizontalHeaderLabels(
            ["函数", "地址", "采样数", "CPU%"]
        )
        self.tbl_profiler.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.tbl_profiler.verticalHeader().setVisible(False)
        self.tbl_profiler.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_profiler.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_profiler.setStyleSheet(table_style())
        self.tabs.addTab(self.tbl_profiler, "CPU分析")

        # Tab 3: Exception Tracking
        self.txt_exc = QTextEdit()
        self.txt_exc.setReadOnly(True)
        self.txt_exc.setStyleSheet(text_edit_style())
        self.tabs.addTab(self.txt_exc, "异常跟踪")

        layout.addWidget(self.tabs, stretch=1)

    @staticmethod
    def _tab_style():
        return f"""
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                background-color: {BG_DARK};
            }}
            QTabBar::tab {{
                background-color: {BG_HEADER};
                color: {TEXT};
                padding: 6px 16px;
                border: 1px solid {BORDER};
                border-bottom: none;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {BG_DARK};
                border-bottom: 2px solid {CYAN};
            }}
            QTabBar::tab:hover {{
                background-color: #383838;
            }}
        """

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def _init_timer(self):
        self._timer = QTimer(self)
        self._timer.setInterval(SWO_POLL_MS)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_probe(self, probe):
        """Receive the DebugProbe instance after MCU connection.

        Parameters
        ----------
        probe : DebugProbe
            A connected debug probe with SWO support.
        """
        self._probe = probe

    def load_elf(self, path: str):
        """Load an ELF file for symbol resolution in the profiler.

        Parameters
        ----------
        path : str
            Path to an ELF file (.elf / .out).
        """
        self._elf_symbols.clear()
        self._elf_sorted.clear()

        try:
            import struct as _struct
            with open(path, 'rb') as f:
                data = f.read()

            if len(data) < 16 or data[:4] != b'\x7fELF':
                return

            is_64 = data[4] == 2
            is_le = data[5] == 1

            if is_64 or not is_le:
                return  # Only 32-bit little-endian supported

            # ELF32 header
            e_shoff = _struct.unpack_from('<I', data, 32)[0]
            e_shentsize = _struct.unpack_from('<H', data, 46)[0]
            e_shnum = _struct.unpack_from('<H', data, 48)[0]
            e_shstrndx = _struct.unpack_from('<H', data, 50)[0]

            def read_shdr(idx):
                off = e_shoff + idx * e_shentsize
                return _struct.unpack_from('<IIIIIIIIII', data, off)

            if e_shstrndx >= e_shnum:
                return

            # Section name string table
            shstr_shdr = read_shdr(e_shstrndx)
            shstr_off = shstr_shdr[4]
            shstr_size = shstr_shdr[5]
            shstr_data = data[shstr_off:shstr_off + shstr_size]

            def section_name(idx):
                shdr = read_shdr(idx)
                name_off = shdr[0]
                end = shstr_data.find(b'\x00', name_off)
                if end == -1:
                    return ''
                return shstr_data[name_off:end].decode('ascii', errors='replace')

            # Find .symtab and .strtab
            symtab_idx = strtab_idx = -1
            for i in range(e_shnum):
                name = section_name(i)
                if name == '.symtab':
                    symtab_idx = i
                elif name == '.strtab':
                    strtab_idx = i

            if symtab_idx < 0 or strtab_idx < 0:
                return

            symtab_shdr = read_shdr(symtab_idx)
            strtab_shdr = read_shdr(strtab_idx)

            sym_off = symtab_shdr[4]
            sym_size = symtab_shdr[5]
            sym_entsize = symtab_shdr[9] if symtab_shdr[9] else 16

            str_off = strtab_shdr[4]
            str_size = strtab_shdr[5]
            str_data = data[str_off:str_off + str_size]

            # Parse function symbols
            count = sym_size // sym_entsize
            for i in range(count):
                ent = _struct.unpack_from('<IIIIBBH', data, sym_off + i * sym_entsize)
                st_name, st_value, st_size, st_info, st_other, st_shndx = ent
                st_type = st_info & 0xF

                # Only function symbols (STT_FUNC = 2) with size > 0
                if st_type == 2 and st_value != 0 and st_size > 0 and st_shndx != 0:
                    end = str_data.find(b'\x00', st_name)
                    if end == -1:
                        continue
                    sym_name = str_data[st_name:end].decode('ascii', errors='replace')
                    if sym_name:
                        self._elf_symbols[st_value] = (sym_name, st_size)
                        self._elf_sorted.append((st_value, sym_name, st_size))

            self._elf_sorted.sort(key=lambda x: x[0])
        except Exception:
            pass  # Symbol resolution disabled on error

    # ------------------------------------------------------------------
    # Control
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
        try:
            self._probe.swo_start(speed=2000000)  # 2 MHz default
        except NotImplementedError:
            self.lbl_status.setText("SWO: 探针不支持")
            return
        except Exception:
            self.lbl_status.setText("SWO: 启动失败")
            return

        self._running = True
        self.btn_start.setText("停止")
        self.lbl_status.setText("SWO: 运行中")
        self._timer.start()

    def _stop(self):
        self._running = False
        self._timer.stop()
        self.btn_start.setText("开始")
        self.lbl_status.setText("SWO: 已停止")
        if self._probe:
            try:
                self._probe.swo_stop()
            except Exception:
                pass

    @pyqtSlot()
    def _clear_all(self):
        """Clear all trace buffers and displays."""
        self.txt_itm.clear()
        self.txt_exc.clear()
        self._itm_text_buf.clear()
        self._exc_text_buf.clear()
        self._pc_counts.clear()
        self._total_samples = 0
        self._update_profiler_table()
        self._decoder.stats = {
            'itm': 0, 'dwt_pc': 0, 'dwt_exc': 0,
            'sync': 0, 'unknown': 0, 'errors': 0,
        }

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll(self):
        """Read SWO data from probe and feed to decoder."""
        if not self._probe or not self._running:
            return

        try:
            data = self._probe.swo_read()
        except Exception:
            return

        if data:
            self._decoder.feed(data)

        self._flush_buffers()
        self._update_stats()

    def _flush_buffers(self):
        """Push buffered text to UI widgets."""
        # ITM output
        if self._itm_text_buf:
            text = ''.join(self._itm_text_buf)
            self._itm_text_buf.clear()
            cursor = self.txt_itm.textCursor()
            cursor.movePosition(cursor.End)
            cursor.insertText(text)
            self.txt_itm.setTextCursor(cursor)
            self.txt_itm.ensureCursorVisible()
            # Trim if too many lines
            doc = self.txt_itm.document()
            if doc.blockCount() > MAX_ITM_LINES:
                cursor.movePosition(cursor.Start)
                cursor.movePosition(
                    cursor.Down, cursor.KeepAnchor,
                    doc.blockCount() - MAX_ITM_LINES,
                )
                cursor.removeSelectedText()

        # Exception output
        if self._exc_text_buf:
            lines = '\n'.join(self._exc_text_buf) + '\n'
            self._exc_text_buf.clear()
            cursor = self.txt_exc.textCursor()
            cursor.movePosition(cursor.End)
            cursor.insertText(lines)
            self.txt_exc.setTextCursor(cursor)
            self.txt_exc.ensureCursorVisible()
            doc = self.txt_exc.document()
            if doc.blockCount() > MAX_EXC_LINES:
                cursor.movePosition(cursor.Start)
                cursor.movePosition(
                    cursor.Down, cursor.KeepAnchor,
                    doc.blockCount() - MAX_EXC_LINES,
                )
                cursor.removeSelectedText()

        # Profiler table (update less frequently — every ~500ms via counter)
        self._poll_counter += 1
        if self._poll_counter >= 50:  # 50 * 10ms = 500ms
            self._poll_counter = 0
            self._update_profiler_table()

    def _update_stats(self):
        """Update the stats label in the toolbar."""
        s = self._decoder.stats
        self.lbl_stats.setText(
            f"ITM:{s['itm']}  PC:{s['dwt_pc']}  EXC:{s['dwt_exc']}  "
            f"Err:{s['errors']}"
        )

    # ------------------------------------------------------------------
    # Profiler table
    # ------------------------------------------------------------------

    def _update_profiler_table(self):
        """Rebuild the CPU sampling profiler table."""
        if self._total_samples == 0:
            self.tbl_profiler.setRowCount(0)
            return

        # Build list: (address, count)
        items = sorted(self._pc_counts.items(), key=lambda x: -x[1])

        # Limit to top N
        items = items[:TOP_FUNCTIONS]
        self.tbl_profiler.setRowCount(len(items))

        for row, (addr, count) in enumerate(items):
            pct = 100.0 * count / self._total_samples

            # Resolve symbol name
            name = self._resolve_symbol(addr)

            # Function name
            name_item = QTableWidgetItem(name)
            name_item.setForeground(QColor(CYAN))
            self.tbl_profiler.setItem(row, 0, name_item)

            # Address
            addr_item = QTableWidgetItem(f"0x{addr:08X}")
            addr_item.setForeground(QColor(NUMBER))
            addr_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_profiler.setItem(row, 1, addr_item)

            # Samples
            count_item = QTableWidgetItem(str(count))
            count_item.setForeground(QColor(NUMBER))
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_profiler.setItem(row, 2, count_item)

            # CPU%
            pct_item = QTableWidgetItem(f"{pct:.1f}%")
            pct_item.setForeground(
                QColor(RED if pct > 50 else NUMBER)
            )
            pct_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_profiler.setItem(row, 3, pct_item)

        self.tbl_profiler.resizeColumnsToContents()

    def _resolve_symbol(self, addr: int) -> str:
        """Look up the function name for an address from ELF symbols."""
        if not self._elf_sorted:
            return "N/A"

        # Binary search for the function containing addr
        lo, hi = 0, len(self._elf_sorted) - 1
        result = None
        while lo <= hi:
            mid = (lo + hi) // 2
            sym_addr, sym_name, sym_size = self._elf_sorted[mid]
            if sym_addr <= addr < sym_addr + sym_size:
                return sym_name
            elif sym_addr < addr:
                result = mid
                lo = mid + 1
            else:
                hi = mid - 1

        # addr falls between symbols — return nearest lower
        if result is not None:
            sym_addr, sym_name, _ = self._elf_sorted[result]
            return f"{sym_name}+0x{addr - sym_addr:X}"
        return "N/A"

    # ------------------------------------------------------------------
    # Load ELF dialog
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _load_elf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载ELF文件", "",
            "ELF Files (*.elf *.out *.axf);;All Files (*)",
        )
        if path:
            self.load_elf(path)
            count = len(self._elf_symbols)
            self.lbl_status.setText(f"ELF: 已加载 {count} 个符号")

    # ------------------------------------------------------------------
    # Exception name lookup
    # ------------------------------------------------------------------

    @staticmethod
    def _exception_name(num: int) -> str:
        """Map ARM Cortex-M exception number to its name."""
        names = {
            0: 'Thread mode', 1: 'Reset', 2: 'NMI',
            3: 'HardFault', 4: 'MemManage', 5: 'BusFault',
            6: 'UsageFault', 7: 'SecureFault',
            11: 'SVCall', 12: 'Debug Monitor',
            14: 'PendSV', 15: 'SysTick',
        }
        if 16 <= num <= 255:
            return f"IRQ {num - 16}"
        return names.get(num, f"Unknown({num})")
