from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class ThemeColors:
    window: str
    panel: str
    base: str
    alternate_base: str
    input: str
    control: str
    hover: str
    pressed: str
    border: str
    grid: str
    text: str
    muted_text: str
    disabled_background: str
    disabled_text: str
    selection: str
    selected_text: str
    focus: str
    indicator_border: str
    scrollbar_track: str
    scrollbar_handle: str
    scrollbar_hover: str
    scrollbar_pressed: str
    run: str
    run_hover: str
    run_pressed: str
    run_border: str
    run_text: str
    stop: str
    stop_hover: str
    stop_pressed: str
    stop_border: str
    stop_text: str


LIGHT_THEME = ThemeColors(
    window="#f2f4f7",
    panel="#ffffff",
    base="#ffffff",
    alternate_base="#f7f8fa",
    input="#ffffff",
    control="#f5f7fa",
    hover="#e9eef4",
    pressed="#dce5ef",
    border="#c7cdd6",
    grid="#d8dde5",
    text="#202124",
    muted_text="#5f6368",
    disabled_background="#eceff3",
    disabled_text="#858b94",
    selection="#2f6fb0",
    selected_text="#ffffff",
    focus="#2f6fb0",
    indicator_border="#6f7883",
    scrollbar_track="#f1f3f5",
    scrollbar_handle="#7a838e",
    scrollbar_hover="#626c78",
    scrollbar_pressed="#4f5965",
    run="#9fd7a8",
    run_hover="#b0e0b8",
    run_pressed="#8ec798",
    run_border="#6aad78",
    run_text="#17351c",
    stop="#efb0a6",
    stop_hover="#f2beb5",
    stop_pressed="#de978b",
    stop_border="#cf7d73",
    stop_text="#3b1713",
)

DARK_THEME = ThemeColors(
    window="#1e1f22",
    panel="#27282c",
    base="#191a1d",
    alternate_base="#222327",
    input="#1b1c1f",
    control="#303238",
    hover="#3a3d44",
    pressed="#25272b",
    border="#4a4d55",
    grid="#383b42",
    text="#e6e8eb",
    muted_text="#a9afb7",
    disabled_background="#26272b",
    disabled_text="#7d838c",
    selection="#3f78b5",
    selected_text="#ffffff",
    focus="#6ea7e0",
    indicator_border="#7a808b",
    scrollbar_track="#191a1d",
    scrollbar_handle="#696f7a",
    scrollbar_hover="#858c98",
    scrollbar_pressed="#9ba2ad",
    run="#315f3c",
    run_hover="#3c7048",
    run_pressed="#294f32",
    run_border="#4f8a5f",
    run_text="#e7f5e9",
    stop="#6b3936",
    stop_hover="#7d4541",
    stop_pressed="#572f2d",
    stop_border="#a65a54",
    stop_text="#fbe9e7",
)


def _color(value: str) -> QtGui.QColor:
    return QtGui.QColor(value)


class _ThemeProxyStyle(QtWidgets.QProxyStyle):
    """Draw consistent checkbox indicators for widgets and item views."""

    INDICATOR_SIZE = 16

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802 - Qt override
        if metric in (
            QtWidgets.QStyle.PixelMetric.PM_IndicatorWidth,
            QtWidgets.QStyle.PixelMetric.PM_IndicatorHeight,
        ):
            return self.INDICATOR_SIZE
        if metric == QtWidgets.QStyle.PixelMetric.PM_CheckBoxLabelSpacing:
            return 6
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(self, element, option, painter, widget=None):  # noqa: N802 - Qt override
        if element in (
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
        ):
            self._draw_checkbox_indicator(option, painter)
            return
        super().drawPrimitive(element, option, painter, widget)

    @staticmethod
    def _draw_checkbox_indicator(
        option: QtWidgets.QStyleOption,
        painter: QtGui.QPainter,
    ) -> None:
        app = QtWidgets.QApplication.instance()
        dark = bool(app and app.property("colorScheme") == "dark")
        theme = DARK_THEME if dark else LIGHT_THEME
        state = option.state
        enabled = bool(state & QtWidgets.QStyle.StateFlag.State_Enabled)
        checked = bool(state & QtWidgets.QStyle.StateFlag.State_On)
        partial = bool(state & QtWidgets.QStyle.StateFlag.State_NoChange)
        active = checked or partial

        size = min(
            _ThemeProxyStyle.INDICATOR_SIZE,
            option.rect.width(),
            option.rect.height(),
        )
        rect = QtCore.QRectF(0, 0, size - 1, size - 1)
        rect.moveCenter(QtCore.QPointF(option.rect.center()))

        if enabled:
            fill = _color(theme.selection if active else theme.input)
            border = _color(theme.indicator_border)
            mark = _color(theme.selected_text)
            if state & (
                QtWidgets.QStyle.StateFlag.State_MouseOver
                | QtWidgets.QStyle.StateFlag.State_HasFocus
            ):
                border = _color(theme.focus)
                if active:
                    fill = fill.lighter(112)
        else:
            fill = _color(
                theme.disabled_text if active else theme.disabled_background
            )
            border = _color(theme.disabled_text)
            mark = _color(theme.disabled_background)

        if state & QtWidgets.QStyle.StateFlag.State_Selected:
            border = _color(theme.selected_text)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QtGui.QPen(border, 1.4))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 2.5, 2.5)

        if active:
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            pen = QtGui.QPen(mark, max(1.8, size * 0.13))
            pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            if partial:
                y = rect.top() + rect.height() * 0.5
                painter.drawLine(
                    QtCore.QPointF(rect.left() + rect.width() * 0.25, y),
                    QtCore.QPointF(rect.left() + rect.width() * 0.75, y),
                )
            else:
                path = QtGui.QPainterPath()
                path.moveTo(
                    rect.left() + rect.width() * 0.22,
                    rect.top() + rect.height() * 0.53,
                )
                path.lineTo(
                    rect.left() + rect.width() * 0.43,
                    rect.top() + rect.height() * 0.73,
                )
                path.lineTo(
                    rect.left() + rect.width() * 0.80,
                    rect.top() + rect.height() * 0.29,
                )
                painter.drawPath(path)
        painter.restore()


def _install_theme_proxy_style(app: QtWidgets.QApplication) -> None:
    if getattr(app, "_results_analysis_theme_proxy", None) is not None:
        return
    proxy = _ThemeProxyStyle(app.style())
    app._results_analysis_theme_proxy = proxy
    app.setStyle(proxy)


def _application_palette(theme: ThemeColors) -> QtGui.QPalette:
    palette = QtGui.QPalette()
    role_colors = {
        QtGui.QPalette.ColorRole.Window: theme.window,
        QtGui.QPalette.ColorRole.WindowText: theme.text,
        QtGui.QPalette.ColorRole.Base: theme.base,
        QtGui.QPalette.ColorRole.AlternateBase: theme.alternate_base,
        QtGui.QPalette.ColorRole.ToolTipBase: theme.panel,
        QtGui.QPalette.ColorRole.ToolTipText: theme.text,
        QtGui.QPalette.ColorRole.Text: theme.text,
        QtGui.QPalette.ColorRole.Button: theme.control,
        QtGui.QPalette.ColorRole.ButtonText: theme.text,
        QtGui.QPalette.ColorRole.BrightText: theme.selected_text,
        QtGui.QPalette.ColorRole.Highlight: theme.selection,
        QtGui.QPalette.ColorRole.HighlightedText: theme.selected_text,
        QtGui.QPalette.ColorRole.Link: theme.focus,
        QtGui.QPalette.ColorRole.PlaceholderText: theme.muted_text,
        QtGui.QPalette.ColorRole.Light: theme.hover,
        QtGui.QPalette.ColorRole.Midlight: theme.control,
        QtGui.QPalette.ColorRole.Mid: theme.border,
        QtGui.QPalette.ColorRole.Dark: theme.pressed,
        QtGui.QPalette.ColorRole.Shadow: theme.window,
    }
    for role, value in role_colors.items():
        palette.setColor(role, _color(value))
    for role in (
        QtGui.QPalette.ColorRole.WindowText,
        QtGui.QPalette.ColorRole.Text,
        QtGui.QPalette.ColorRole.ButtonText,
        QtGui.QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(
            QtGui.QPalette.ColorGroup.Disabled,
            role,
            _color(theme.disabled_text),
        )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.Button,
        _color(theme.disabled_background),
    )
    palette.setColor(
        QtGui.QPalette.ColorGroup.Disabled,
        QtGui.QPalette.ColorRole.Base,
        _color(theme.disabled_background),
    )
    return palette


def _application_stylesheet(theme: ThemeColors) -> str:
    return f"""
QMainWindow, QDialog {{
    background-color: {theme.window};
    color: {theme.text};
}}
QWidget {{
    color: {theme.text};
}}
QFrame#panel {{
    background-color: {theme.panel};
    border: 1px solid {theme.border};
    border-radius: 4px;
}}
QGroupBox {{
    background-color: {theme.panel};
    border: 1px solid {theme.border};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 8px;
}}
QGroupBox::title {{
    color: {theme.text};
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}}
QLabel[labelRole="section"] {{
    color: {theme.text};
    font-weight: 600;
}}
QLabel[labelRole="muted"] {{
    color: {theme.muted_text};
}}
QTableView, QTreeView, QListView {{
    background-color: {theme.base};
    alternate-background-color: {theme.alternate_base};
    color: {theme.text};
    border: 1px solid {theme.border};
    gridline-color: {theme.grid};
    selection-background-color: {theme.selection};
    selection-color: {theme.selected_text};
}}
QTreeWidget#projectTree::item:selected {{
    background-color: {theme.selection};
    color: {theme.selected_text};
    font-weight: 600;
}}
QTableView:disabled, QTreeView:disabled, QListView:disabled {{
    background-color: {theme.disabled_background};
    color: {theme.disabled_text};
}}
QHeaderView::section, QTableCornerButton::section {{
    background-color: {theme.control};
    color: {theme.text};
    border: 0;
    border-right: 1px solid {theme.border};
    border-bottom: 1px solid {theme.border};
    padding: 4px 6px;
}}
QTabWidget::pane {{
    background-color: {theme.panel};
    border: 1px solid {theme.border};
}}
QTabBar::tab {{
    background-color: {theme.control};
    color: {theme.muted_text};
    border: 1px solid {theme.border};
    border-bottom: 0;
    padding: 5px 10px;
}}
QTabBar::tab:hover {{
    background-color: {theme.hover};
    color: {theme.text};
}}
QTabBar::tab:selected {{
    background-color: {theme.panel};
    color: {theme.text};
    font-weight: 600;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {theme.input};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 3px;
    padding: 3px 5px;
    selection-background-color: {theme.selection};
    selection-color: {theme.selected_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {theme.focus};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background-color: {theme.disabled_background};
    color: {theme.disabled_text};
}}
QPushButton {{
    background-color: {theme.control};
    border: 1px solid {theme.border};
    border-radius: 4px;
    color: {theme.text};
    font-weight: 500;
    padding: 3px 8px;
}}
QPushButton:hover {{
    background-color: {theme.hover};
}}
QPushButton:pressed {{
    background-color: {theme.pressed};
}}
QPushButton:focus {{
    border-color: {theme.focus};
}}
QPushButton:disabled {{
    background-color: {theme.disabled_background};
    border-color: {theme.border};
    color: {theme.disabled_text};
}}
QPushButton[buttonRole="choice"] {{
    font-weight: 600;
}}
QPushButton[buttonRole="run"] {{
    background-color: {theme.run};
    border-color: {theme.run_border};
    color: {theme.run_text};
    font-weight: 600;
    padding: 4px 8px;
}}
QPushButton[buttonRole="run"]:hover {{
    background-color: {theme.run_hover};
}}
QPushButton[buttonRole="run"]:pressed {{
    background-color: {theme.run_pressed};
}}
QPushButton[buttonRole="stop"] {{
    background-color: {theme.stop};
    border-color: {theme.stop_border};
    color: {theme.stop_text};
    font-weight: 600;
    padding: 4px 8px;
}}
QPushButton[buttonRole="stop"]:hover {{
    background-color: {theme.stop_hover};
}}
QPushButton[buttonRole="stop"]:pressed {{
    background-color: {theme.stop_pressed};
}}
QPushButton[buttonRole="run"]:disabled,
QPushButton[buttonRole="stop"]:disabled {{
    background-color: {theme.disabled_background};
    border-color: {theme.border};
    color: {theme.disabled_text};
}}
QCheckBox, QRadioButton {{
    color: {theme.text};
    spacing: 5px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {theme.disabled_text};
}}
QScrollBar:vertical {{
    background: {theme.scrollbar_track};
    width: 12px;
    margin: 0;
    border: 0;
    border-left: 1px solid {theme.grid};
}}
QScrollBar:horizontal {{
    background: {theme.scrollbar_track};
    height: 12px;
    margin: 0;
    border: 0;
    border-top: 1px solid {theme.grid};
}}
QScrollBar::handle:vertical {{
    background: {theme.scrollbar_handle};
    min-height: 28px;
    border: 2px solid {theme.scrollbar_track};
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {theme.scrollbar_handle};
    min-width: 28px;
    border: 2px solid {theme.scrollbar_track};
    border-radius: 5px;
}}
QScrollBar::handle:hover {{
    background: {theme.scrollbar_hover};
}}
QScrollBar::handle:pressed {{
    background: {theme.scrollbar_pressed};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
    border: 0;
    background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background: {theme.scrollbar_track};
    border: 0;
}}
QStatusBar {{
    background-color: {theme.window};
    color: {theme.text};
    border-top: 1px solid {theme.border};
}}
QProgressBar {{
    background-color: {theme.input};
    color: {theme.text};
    border: 1px solid {theme.border};
    border-radius: 3px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {theme.selection};
}}
QSplitter::handle {{
    background-color: {theme.border};
}}
QToolTip {{
    background-color: {theme.panel};
    color: {theme.text};
    border: 1px solid {theme.border};
    padding: 3px;
}}
"""


def system_uses_dark_theme(
    app: QtWidgets.QApplication | None = None,
) -> bool:
    application = app or QtWidgets.QApplication.instance()
    if application is None:
        return False
    return (
        application.styleHints().colorScheme()
        == QtCore.Qt.ColorScheme.Dark
    )


def apply_application_theme(
    app: QtWidgets.QApplication,
    *,
    dark: bool | None = None,
) -> ThemeColors:
    use_dark = system_uses_dark_theme(app) if dark is None else dark
    theme = DARK_THEME if use_dark else LIGHT_THEME
    _install_theme_proxy_style(app)
    app.setPalette(_application_palette(theme))
    app.setStyleSheet(_application_stylesheet(theme))
    app.setProperty("colorScheme", "dark" if use_dark else "light")
    return theme


def install_system_theme(app: QtWidgets.QApplication) -> None:
    apply_application_theme(app)

    def update_theme(scheme: QtCore.Qt.ColorScheme) -> None:
        apply_application_theme(
            app,
            dark=scheme == QtCore.Qt.ColorScheme.Dark,
        )

    app.styleHints().colorSchemeChanged.connect(update_theme)


def _set_widget_role(
    widget: QtWidgets.QWidget,
    property_name: str,
    value: str,
) -> None:
    widget.setProperty(property_name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_choice_button_style(button: QtWidgets.QPushButton) -> None:
    _set_widget_role(button, "buttonRole", "choice")


def apply_secondary_button_style(button: QtWidgets.QPushButton) -> None:
    _set_widget_role(button, "buttonRole", "secondary")


def apply_run_button_style(button: QtWidgets.QPushButton) -> None:
    _set_widget_role(button, "buttonRole", "run")


def apply_stop_button_style(button: QtWidgets.QPushButton) -> None:
    _set_widget_role(button, "buttonRole", "stop")


def make_section_label(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    _set_widget_role(label, "labelRole", "section")
    return label


def make_muted_label(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    _set_widget_role(label, "labelRole", "muted")
    return label
