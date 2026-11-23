"""Dunkles, modernes Erscheinungsbild."""

ACCENT = "#ff8a1f"
BG = "#0f1115"
SURFACE = "#171a21"
SURFACE_2 = "#1f232c"
BORDER = "#2a2f3a"
TEXT = "#e8eaf0"
MUTED = "#8b93a5"
OK = "#33d17a"
WARN = "#f5c211"
ERROR = "#ff5c5c"

STYLE = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#Root, QDialog, QMessageBox {{ background: {BG}; }}
QFrame#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#Brand {{ font-size: 15pt; font-weight: 700; color: {TEXT}; }}
QLabel#BrandSub {{ color: {ACCENT}; font-weight: 600; letter-spacing: 1px; }}
QLabel#Muted, QLabel#Footer {{ color: {MUTED}; }}
QLabel#PageTitle {{ font-size: 20pt; font-weight: 700; }}
QLabel#PageSub {{ color: {MUTED}; font-size: 10.5pt; }}

QPushButton#Nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    background: transparent; color: {MUTED}; font-size: 10.5pt;
}}
QPushButton#Nav:hover {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton#Nav:checked {{ background: {SURFACE_2}; color: {TEXT}; border-left: 3px solid {ACCENT}; }}

QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 8px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #111; border: none; font-weight: 700; }}
QPushButton#Primary:hover {{ background: #ffa04a; }}
QPushButton#StartButton {{
    background: {ACCENT}; color: #111; border: none; border-radius: 18px;
    font-size: 18pt; font-weight: 800; padding: 22px 40px;
}}
QPushButton#StartButton:hover {{ background: #ffa04a; }}
QPushButton#StartButton[running="true"] {{ background: {ERROR}; color: white; }}
QPushButton#ColorButton {{ border-radius: 8px; min-width: 56px; min-height: 26px; padding: 0; }}

QPushButton#Small {{ padding: 6px 12px; border-radius: 8px; }}
QPushButton#Link {{ background: transparent; border: none; color: {MUTED}; padding: 4px 6px; }}
QPushButton#Link:hover, QPushButton#Link:checked {{ color: {TEXT}; }}
QPushButton#Segment {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; padding: 7px 16px; color: {MUTED};
}}
QPushButton#Segment:hover {{ color: {TEXT}; border-color: {MUTED}; }}
QPushButton#Segment:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #111; font-weight: 700; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#Card[disabled="true"] {{ background: #13151a; }}
QFrame#Inset {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel#CardHeading {{ font-size: 11.5pt; font-weight: 700; }}
QLabel#Tag {{ color: {MUTED}; background: {SURFACE_2}; border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; }}
QLabel#LiveState {{ font-size: 20pt; font-weight: 800; }}
QLabel#CardTitle {{ color: {MUTED}; font-size: 9pt; font-weight: 600; }}
QLabel#CardText {{ font-size: 10.5pt; }}

QTreeWidget, QWidget#Rows {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
QTreeWidget::item {{ padding: 6px 2px; }}
QTreeWidget::item:selected {{ background: {SURFACE_2}; }}
QHeaderView::section {{ background: {SURFACE}; color: {MUTED}; border: none; padding: 6px; }}

QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px 8px; min-height: 22px;
}}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; selection-background-color: {ACCENT}; selection-color: #111; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 6px; background: {SURFACE_2}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
"""
