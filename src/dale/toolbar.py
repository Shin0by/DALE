"""Native, code-drawn toolbar icons and consistent visible tool button styling."""

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionToolButton,
    QStylePainter,
    QToolBar,
    QToolButton,
)

from dale.localization import format_tooltip


def tool_icon(name):
    name = {
        "Contours": "Select regions",
        "Select figures": "Select regions",
        "Move figures": "Move regions",
        "Rotate figures": "Rotate regions",
        "Figure point alignment": "Region point alignment",
        "Figure guide alignment": "Region guide alignment",
    }.get(name, name)
    name = {"Vertices": "Edit points", "Regions": "Select regions", "Raster": "Erase"}.get(
        name, name
    )
    if name == "Select raster regions":
        name = "Select regions"
    canvas = QPixmap(24, 24)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(
            QColor("#f1f6ff"),
            1.8,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )

    def line(a, b):
        painter.drawLine(QPointF(*a), QPointF(*b))

    def circle(x, y, r=2):
        painter.drawEllipse(QPointF(x, y), r, r)

    if name == "Select all contour lines":
        painter.drawRect(QRectF(2, 2, 20, 20))
        for y in (7, 12, 17):
            line((6, y), (18, y))
        painter.setBrush(QColor("#58d9ec"))
        for y in (7, 12, 17):
            circle(6, y, 1.4)
            circle(18, y, 1.4)
    elif name == "Dataset manager":
        painter.drawRect(QRectF(3, 5, 13, 15))
        painter.drawRect(QRectF(7, 2, 13, 15))
        line((10, 7), (17, 7))
        line((10, 11), (17, 11))
    elif name in ("Open scene", "Open project"):
        painter.drawRoundedRect(QRectF(3, 7, 18, 13), 2, 2)
        line((4, 7), (4, 4))
        line((4, 4), (11, 4))
        line((11, 4), (13, 7))
        if name == "Open scene":
            line((6, 17), (10, 12))
            line((10, 12), (14, 16))
            circle(17, 11, 1)
        else:
            line((9, 12), (15, 12))
            line((9, 16), (17, 16))
    elif name in ("Save project", "Save project as…"):
        painter.drawRoundedRect(QRectF(4, 3, 16, 18), 1, 1)
        painter.drawRect(QRectF(8, 3, 8, 6))
        painter.drawRect(QRectF(8, 14, 8, 7))
        if name == "Save project as…":
            line((16, 12), (22, 12))
            line((19, 9), (19, 15))
    elif name in ("Export PNGs", "Export selected regions"):
        line((4, 13), (4, 20))
        line((4, 20), (20, 20))
        line((20, 20), (20, 13))
        line((12, 16), (12, 3))
        line((12, 3), (7, 8))
        line((12, 3), (17, 8))
    elif name in ("Close scene", "Remove inside"):
        circle(12, 12, 9) if name == "Close scene" else painter.drawRect(QRectF(4, 4, 16, 16))
        line((8, 8), (16, 16))
        line((8, 16), (16, 8))
    elif name in ("Undo", "Redo"):
        painter.translate(24, 0) if name == "Redo" else None
        painter.scale(-1, 1) if name == "Redo" else None
        line((4, 9), (17, 9))
        line((17, 9), (20, 12))
        line((20, 12), (20, 19))
        line((4, 9), (9, 4))
        line((4, 9), (9, 14))
    elif name in ("Pan", "Move regions"):
        line((12, 3), (12, 21))
        line((3, 12), (21, 12))
        for a, b in [
            ((12, 3), (9, 6)),
            ((12, 3), (15, 6)),
            ((3, 12), (6, 9)),
            ((3, 12), (6, 15)),
            ((21, 12), (18, 9)),
            ((21, 12), (18, 15)),
            ((12, 21), (9, 18)),
            ((12, 21), (15, 18)),
        ]:
            line(a, b)
    elif name == "Rotate regions":
        painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 280 * 16)
        line((18, 17), (18, 12))
        line((18, 17), (23, 16))
        painter.setBrush(QColor("#58d9ec"))
        circle(12, 12, 2)
    elif name == "Fit":
        for x, y, sx, sy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            line((x, y + sy * 5), (x, y))
            line((x, y), (x + sx * 5, y))
    elif name == "Show contours":
        painter.drawRoundedRect(QRectF(3, 7, 18, 11), 6, 6)
        circle(12, 12.5, 3)
    elif name == "Clear selection":
        painter.setPen(QPen(QColor("#f1f6ff"), 1.5, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(3, 3, 16, 16))
        painter.setPen(QPen(QColor("#f1f6ff"), 1.8))
        line((14, 14), (22, 22))
        line((14, 22), (22, 14))
    elif name == "Settings":
        circle(12, 12, 6)
        circle(12, 12, 2)
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(12, 12)
            painter.rotate(angle)
            line((0, -6), (0, -10))
            painter.restore()
    elif name in ("Auto-close", "Close all contours"):
        painter.drawPolyline(
            QPolygonF([QPointF(4, 9), QPointF(4, 19), QPointF(20, 19), QPointF(20, 9)])
        )
        painter.setPen(QPen(QColor("#58d9ec"), 1.8, Qt.PenStyle.DashLine))
        line((4, 9), (20, 9))
        if name == "Close all contours":
            painter.setPen(QPen(QColor("#f1f6ff"), 1.5))
            circle(12, 14, 3)
    elif name in ("New line", "Edit points"):
        points = [(4, 18), (20, 6)]
        if name == "Edit points":
            points.insert(1, (12, 12))
        painter.drawPolyline(QPolygonF([QPointF(*p) for p in points]))
        painter.setBrush(QColor("#58d9ec"))
        for x, y in points:
            circle(x, y)
        if name == "New line":
            line((17, 18), (23, 18))
            line((20, 15), (20, 21))
    elif name == "Rename…":
        painter.drawPolygon(
            QPolygonF([QPointF(5, 15), QPointF(16, 4), QPointF(20, 8), QPointF(9, 19)])
        )
        line((5, 15), (4, 20))
        line((4, 20), (9, 19))
        line((13, 7), (17, 11))
    elif name == "New rectangle":
        painter.drawRect(QRectF(3, 5, 18, 14))
        painter.setBrush(QColor("#58d9ec"))
        circle(3, 5, 2)
        circle(21, 19, 2)
    elif name == "New circle":
        circle(12, 12, 9)
        painter.setBrush(QColor("#58d9ec"))
        circle(12, 12, 2)
        line((12, 12), (19, 7))
    elif name in ("Erase", "Restore", "Erase lines", "Erase vertices", "Delete region"):
        if name == "Delete region":
            painter.setPen(QPen(QColor("#58d9ec"), 1.2, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(1, 1, 21, 21))
            painter.setPen(QPen(QColor("#f1f6ff"), 1.8))
            painter.setBrush(QColor("#303030"))
        painter.drawPolygon(
            QPolygonF(
                [QPointF(4, 14), QPointF(13, 4), QPointF(21, 11), QPointF(12, 21), QPointF(10, 21)]
            )
        )
        line((8, 10), (16, 17))
        if name == "Restore":
            line((16, 20), (22, 20))
            line((19, 17), (19, 23))
        elif name == "Erase vertices":
            painter.setBrush(QColor("#ff0000"))
            circle(19, 19, 3)
        elif name == "Erase lines":
            painter.setPen(QPen(QColor("#ff0000"), 2))
            line((16, 22), (23, 15))
    elif name == "Remove outside":
        painter.drawRect(QRectF(7, 7, 10, 10))
        for a, b in [
            ((3, 3), (5, 5)),
            ((19, 3), (21, 5)),
            ((3, 19), (5, 21)),
            ((19, 19), (21, 21)),
        ]:
            line(a, b)
    elif name in ("Snap", "Snapping (px)", "Region point alignment"):
        painter.setBrush(QColor("#58d9ec"))
        circle(5, 19, 3)
        circle(19, 5, 3)
        line((10, 14), (14, 10))
        line((14, 10), (10, 10))
        line((14, 10), (14, 14))
    elif name == "Right-angle alignment":
        line((4, 4), (4, 20))
        line((4, 20), (21, 20))
        painter.setPen(QPen(QColor("#58d9ec"), 1.6))
        line((4, 13), (11, 13))
        line((11, 13), (11, 20))
    elif name in ("Contour alignment", "Region guide alignment"):
        painter.drawPolyline(
            QPolygonF([QPointF(4, 17), QPointF(8, 5), QPointF(20, 9), QPointF(20, 17)])
        )
        painter.setPen(QPen(QColor("#58d9ec"), 1.2, Qt.PenStyle.DashLine))
        line((4, 17), (20, 17))
        painter.setBrush(QColor("#58d9ec"))
        circle(4, 17, 2)
        circle(20, 17, 2)
    elif name == "Select regions":
        painter.setBrush(QColor(88, 217, 236, 90))
        painter.drawPolygon(
            QPolygonF(
                [QPointF(3, 4), QPointF(16, 4), QPointF(20, 13), QPointF(8, 20), QPointF(3, 4)]
            )
        )
        painter.setBrush(QColor("#f1f6ff"))
        painter.drawPolygon(
            QPolygonF([QPointF(12, 11), QPointF(22, 17), QPointF(17, 18), QPointF(15, 23)])
        )
    elif name == "Artwork offset (px)":
        painter.setBrush(QColor(88, 217, 236, 90))
        painter.drawRect(QRectF(7, 7, 10, 10))
        painter.setPen(QPen(QColor("#58d9ec"), 1.2, Qt.PenStyle.DashLine))
        painter.drawRect(QRectF(2, 2, 20, 20))
    elif name == "Brush diameter":
        circle(12, 12, 9)
        line((5, 12), (19, 12))
        line((5, 12), (8, 9))
        line((5, 12), (8, 15))
        line((19, 12), (16, 9))
        line((19, 12), (16, 15))
    else:
        painter.drawRect(QRectF(5, 5, 14, 14))
    painter.end()
    return QIcon(canvas)


STYLE = """
QToolBar { background: #303030; border: 1px solid #494949; spacing: 4px; padding: 4px; }
QToolBar QLabel { color: #dedede; background: transparent; padding: 0 3px; }
QToolBar QToolButton { background: #3b3b3b; color: #ededed; border: 1px solid #606060;
    border-radius: 2px; padding: 4px 7px; }
QToolBar QToolButton:hover { background: #484848; border-color: #8a8a8a; }
QToolBar QToolButton:checked { background: #485966; border: 2px solid #9aafbd; padding: 3px 6px; }
QToolBar QToolButton:pressed { background: #252d34; }
QToolBar QToolButton:disabled { color: #888888; background: #303030; border-color: #454545; }
QToolBar QSpinBox, QToolBar QDoubleSpinBox, QToolBar QComboBox {
    background: #252525; color: #e5e5e5; border: 1px solid #5a5a5a;
    border-radius: 2px; padding: 3px; min-height: 20px; }
QToolBar::separator { background: #555555; width: 1px; margin: 4px; }
"""

COMMAND_STYLE = (
    STYLE
    + """
QToolBar { border: 0; border-bottom: 1px solid #494949; }
QToolBar QToolButton { background: transparent; border: 0; padding: 5px 8px; }
QToolBar QToolButton:hover { background: #464646; border: 0; }
QToolBar QToolButton:pressed { background: #242424; }
QToolBar QToolButton:disabled { background: transparent; border: 0; }
"""
)


class ToolSpinBox(QSpinBox):
    """Keep the editor usable with Qt's styled, buttonless spin-box layout."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_editor()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_editor()

    def fit_editor(self):
        self.lineEdit().setGeometry(3, 2, max(1, self.width() - 6), self.height() - 4)


class SizedToolButton(QToolButton):
    """A 48 x 72 tool button with its diameter caption and small side arrows inside."""

    def __init__(self, editor, action):
        super().__init__()
        self.editor_widget = editor
        self.setDefaultAction(action)
        self.setFixedSize(48, 72)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(24, 24))
        editor.setParent(self)
        editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.lineEdit().setTextMargins(0, 0, 0, 0)
        editor.setStyleSheet("""
            QSpinBox { background: transparent; color: #dedede; border: 0; padding: 0;
                font-size: 10px; min-height: 0; }
            QLineEdit { background: transparent; border: 0; padding: 0; font-size: 10px; }
        """)
        editor.ensurePolished()
        editor.setFixedSize(34, 18)
        editor.move(7, 49)
        self.decrease_button, self.increase_button = QToolButton(self), QToolButton(self)
        for button, x, arrow, amount in (
            (self.decrease_button, 0, Qt.ArrowType.LeftArrow, -1),
            (self.increase_button, 41, Qt.ArrowType.RightArrow, 1),
        ):
            button.setArrowType(arrow)
            button.setFixedSize(7, 18)
            button.move(x, 49)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("""
                QToolButton { color: #969696; background: transparent; border: 0; padding: 0; }
                QToolButton:hover { color: #cccccc; background: #505050; }
                QToolButton:pressed { background: #252525; }
            """)
            button.clicked.connect(lambda checked=False, amount=amount: editor.stepBy(amount))
        self.help_language = None
        action.changed.connect(self.refresh_help)

    def refresh_help(self):
        if self.help_language and self.defaultAction().property("dale_tooltip_parts"):
            self.set_help(self.help_language)

    def editor(self):
        return self.editor_widget

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        self.icon().paint(
            painter,
            QRect(12, 12, 24, 24),
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
            QIcon.State.On if self.isChecked() else QIcon.State.Off,
        )

    def set_help(self, language):
        self.help_language = language
        tool_name = self.defaultAction().property("dale_tool_key")
        tool_name = {
            "Figure point alignment": "Region point alignment",
            "Figure guide alignment": "Region guide alignment",
        }.get(tool_name, tool_name)
        value_help = {
            "Right-angle alignment": "Number: snap distance to a right angle, in screen pixels.",
            "Contour alignment": (
                "Number: snap distance to horizontal/vertical guides, in screen pixels."
            ),
            "Region guide alignment": (
                "Number: snap distance to horizontal/vertical guides, in screen pixels."
            ),
            "Region point alignment": (
                "Number: snap distance in screen pixels; 0 disables snapping."
            ),
            "Erase lines": "Number: brush diameter in screen pixels.",
            "Erase vertices": "Number: brush diameter in screen pixels.",
            "Auto-close": "Number: maximum endpoint movement, in screen pixels.",
            "Close all contours": "Number: maximum endpoint movement, in screen pixels.",
            "Erase": "Number: brush diameter in original image pixels.",
            "Restore": "Number: brush diameter in original image pixels.",
            "Snapping (px)": "Number: snap distance in screen pixels; 0 disables snapping.",
            "Artwork offset (px)": (
                "Number: original image pixels; positive expands, negative cuts inward."
            ),
        }[tool_name]
        modifier = "Ctrl+wheel: change this value."
        editor_parts = [value_help]
        action = self.defaultAction()
        parts = [*action.property("dale_tooltip_parts"), value_help]
        keys = [*(action.property("dale_tooltip_keys") or []), modifier]
        condition = action.property("dale_tooltip_condition")
        self.setProperty("dale_tooltip_parts", parts)
        self.setProperty("dale_tooltip_condition", condition)
        self.setProperty("dale_tooltip_keys", keys)
        self.setToolTip(
            format_tooltip(parts, language, condition=condition, keys=keys, title=action.text())
        )
        for control in (self.editor(), self.editor().lineEdit()):
            control.setProperty("dale_tooltip_parts", editor_parts)
            control.setProperty("dale_tooltip_keys", [modifier])
            control.setProperty(
                "dale_tooltip_title", action.property("dale_display_key") or tool_name
            )
            control.setToolTip(
                format_tooltip(editor_parts, language, keys=[modifier], title=action.text())
            )
        for button, description in (
            (self.decrease_button, "Decrease by 1 px."),
            (self.increase_button, "Increase by 1 px."),
        ):
            parts = [description]
            button.setProperty("dale_tooltip_parts", parts)
            button.setProperty("dale_tooltip_keys", [modifier])
            title = "Decrease value" if button is self.decrease_button else "Increase value"
            button.setProperty("dale_tooltip_title", title)
            button.setToolTip(format_tooltip(parts, language, keys=[modifier], title=title))


PANEL_HELP = {
    "General": "Open, save, close, export, and navigate projects.",
    "Sections": "Choose which tools appear to the left of the scene image.",
    "Main": "Common navigation, selection, visibility, and settings controls.",
    "Tool size": "Size of the geometry eraser or pixel brush. Ctrl+wheel adjusts sizes.",
    "Snapping": "Configure snapping to existing vertices and line interiors.",
}


def apply_theme(app):
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#2b2b2b",
        QPalette.ColorRole.WindowText: "#dedede",
        QPalette.ColorRole.PlaceholderText: "#929292",
        QPalette.ColorRole.Base: "#202020",
        QPalette.ColorRole.AlternateBase: "#303030",
        QPalette.ColorRole.Text: "#e5e5e5",
        QPalette.ColorRole.Button: "#383838",
        QPalette.ColorRole.ButtonText: "#e5e5e5",
        QPalette.ColorRole.Highlight: "#4f718c",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: "#444444",
        QPalette.ColorRole.ToolTipText: "#eeeeee",
        QPalette.ColorRole.Light: "#555555",
        QPalette.ColorRole.Dark: "#181818",
        QPalette.ColorRole.Mid: "#404040",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(
        "QToolTip { color: #eeeeee; background: #444444; border: 1px solid #777777; padding: 5px; }"
    )


def make_toolbar(window, title, new_row=False, vertical=False):
    if new_row and not vertical:
        window.addToolBarBreak()
    bar = QToolBar(title, window)
    bar.setObjectName(title)
    bar.setMovable(False)
    bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    bar.setIconSize(QSize(22, 22))
    bar.setStyleSheet(STYLE)
    bar.setToolTip(PANEL_HELP.get(title, title))
    if vertical:
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        bar.setIconSize(QSize(24, 24))
        bar.setFixedWidth(60)
        bar.setStyleSheet(
            STYLE + "QToolBar { spacing: 3px; } QToolBar::separator { height: 1px; width: 38px; }"
        )
    elif title == "General":
        bar.setStyleSheet(COMMAND_STYLE)
    elif title != "General":
        heading = QLabel(title)
        heading.setToolTip(PANEL_HELP.get(title, title))
        heading.setStyleSheet("font-weight: 600; padding: 0 3px;")
        bar.addWidget(heading)
    if not vertical:
        window.addToolBar(bar)
    return bar
