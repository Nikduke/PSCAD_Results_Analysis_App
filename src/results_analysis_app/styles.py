from __future__ import annotations

from PySide6 import QtWidgets


CHOICE_BUTTON_STYLE = """
QPushButton {
    background-color: #f5f7fa;
    border: 1px solid #9aa4b2;
    border-radius: 4px;
    color: #222;
    font-weight: 600;
    padding: 3px 8px;
}
QPushButton:hover {
    background-color: #edf3f9;
}
QPushButton:pressed {
    background-color: #dee8f3;
}
QPushButton:disabled {
    background-color: #f3f4f6;
    border-color: #d4d7dc;
    color: #888;
}
"""

SECONDARY_BUTTON_STYLE = """
QPushButton {
    background-color: #f6f6f6;
    border: 1px solid #cfd5dc;
    border-radius: 4px;
    color: #222;
    font-weight: 500;
    padding: 3px 8px;
}
QPushButton:hover {
    background-color: #fbfbfb;
}
QPushButton:pressed {
    background-color: #ececec;
}
QPushButton:disabled {
    background-color: #f4f4f4;
    color: #888;
    border-color: #dddddd;
}
"""

RUN_BUTTON_STYLE = """
QPushButton {
    background-color: #9fd7a8;
    border: 1px solid #6aad78;
    border-radius: 4px;
    color: #17351c;
    font-weight: 600;
    padding: 4px 8px;
}
QPushButton:hover {
    background-color: #b0e0b8;
}
QPushButton:pressed {
    background-color: #8ec798;
}
QPushButton:disabled {
    background-color: #f4f4f4;
    border-color: #dddddd;
    color: #888;
}
"""

STOP_BUTTON_STYLE = """
QPushButton {
    background-color: #efb0a6;
    border: 1px solid #cf7d73;
    border-radius: 4px;
    color: #222;
    font-weight: 600;
    padding: 4px 8px;
}
QPushButton:hover {
    background-color: #f2beb5;
}
QPushButton:pressed {
    background-color: #de978b;
}
QPushButton:disabled {
    background-color: #f4f4f4;
    border-color: #dddddd;
    color: #888;
}
"""

PANEL_STYLE = """
QFrame#panel {
    background-color: #ffffff;
    border: 1px solid #d9dee6;
    border-radius: 4px;
}
"""

MUTED_LABEL_STYLE = "color: #555;"
SECTION_LABEL_STYLE = "font-weight: 600; color: #333;"


def apply_choice_button_style(button: QtWidgets.QPushButton) -> None:
    button.setStyleSheet(CHOICE_BUTTON_STYLE)


def apply_secondary_button_style(button: QtWidgets.QPushButton) -> None:
    button.setStyleSheet(SECONDARY_BUTTON_STYLE)


def apply_run_button_style(button: QtWidgets.QPushButton) -> None:
    button.setStyleSheet(RUN_BUTTON_STYLE)


def apply_stop_button_style(button: QtWidgets.QPushButton) -> None:
    button.setStyleSheet(STOP_BUTTON_STYLE)


def make_section_label(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    label.setStyleSheet(SECTION_LABEL_STYLE)
    return label


def make_muted_label(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    label.setStyleSheet(MUTED_LABEL_STYLE)
    return label
