"""Shared style constants and QSS helpers for all RTTView widgets.

Import this module instead of duplicating color hex values in each widget::

    from widgets.styles import *
"""

# ---- Core palette (VS Code dark) ----
BG_DARK = "#1E1E1E"
BG_INPUT = "#252526"
BG_HEADER = "#2D2D2D"
BORDER = "#3C3C3C"
TEXT = "#D4D4D4"
TEXT_DIM = "#808080"
ACCENT = "#007ACC"
SELECTION = "#264F78"

# ---- Semantic colors ----
GREEN = "#4CAF50"
ORANGE = "#FF9800"
RED = "#F44336"
YELLOW = "#FFC107"
CYAN = "#4FC1FF"
TEAL = "#4EC9B0"
PURPLE = "#C586C0"
NUMBER = "#B5CEA8"     # numeric literal green
STRING = "#CE9178"     # string orange
COMMENT = "#6A9955"    # comment green

# ---- Stack usage colors ----
STACK_GREEN = GREEN
STACK_ORANGE = ORANGE
STACK_RED = RED

# ---- Font ----
FONT_MONO = "Consolas"
FONT_SIZE = "11px"
FONT_SIZE_LARGE = "13px"

# ---- Common QSS fragments ----

def mono_font(size=FONT_SIZE):
    return f'font-family: "{FONT_MONO}"; font-size: {size};'

def toolbar_style():
    return f"""
        QPushButton {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 3px;
            padding: 4px 12px;
            font-size: {FONT_SIZE};
        }}
        QPushButton:hover {{
            background-color: {BORDER};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT};
        }}
        QPushButton:disabled {{
            color: {TEXT_DIM};
            border-color: #2A2A2A;
        }}
        QLabel {{
            color: {TEXT};
            font-size: {FONT_SIZE};
        }}
        QLineEdit {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 3px;
            padding: 3px 6px;
            font-family: "{FONT_MONO}";
            font-size: {FONT_SIZE};
        }}
        QComboBox {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 3px;
            padding: 3px 6px;
            font-size: {FONT_SIZE};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox QAbstractItemView {{
            background-color: {BG_INPUT};
            color: {TEXT};
            selection-background-color: {SELECTION};
        }}
    """

def table_style():
    return f"""
        QTableWidget, QTreeWidget {{
            background-color: {BG_DARK};
            color: {TEXT};
            gridline-color: {BORDER};
            border: 1px solid {BORDER};
            font-family: "{FONT_MONO}";
            font-size: {FONT_SIZE};
        }}
        QTableWidget::item, QTreeWidget::item {{
            padding: 2px 6px;
        }}
        QTableWidget::item:selected, QTreeWidget::item:selected {{
            background-color: {SELECTION};
        }}
        QHeaderView::section {{
            background-color: {BG_HEADER};
            color: {TEXT};
            border: 1px solid {BORDER};
            padding: 4px 6px;
            font-size: {FONT_SIZE};
        }}
    """

def text_edit_style():
    return f"""
        QTextEdit, QPlainTextEdit {{
            background-color: {BG_DARK};
            color: {TEXT};
            border: 1px solid {BORDER};
            font-family: "{FONT_MONO}";
            font-size: {FONT_SIZE};
        }}
    """

def progress_bar_style():
    return f"""
        QProgressBar {{
            background-color: {BG_INPUT};
            border: 1px solid {BORDER};
            border-radius: 3px;
            text-align: center;
            color: {TEXT};
            font-size: 10px;
        }}
        QProgressBar::chunk {{
            background-color: {GREEN};
            border-radius: 2px;
        }}
    """

def status_label(ok=True):
    """Return styled status text (HTML)."""
    color = GREEN if ok else RED
    dot = f'<span style="color:{color};">&#9679;</span>'
    return dot

def spinbox_style():
    return f"""
        QSpinBox {{
            background-color: {BG_INPUT};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 3px;
            padding: 2px 4px;
            font-size: {FONT_SIZE};
        }}
    """
