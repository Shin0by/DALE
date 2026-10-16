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

from dale.localization import translate


def tool_icon(name):
    name = {"Contours": "Edit points", "Regions": "Select regions", "Raster": "Erase"}.get(
        name, name
    )
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

    if name in ("Open pair", "Open project"):
        painter.drawRoundedRect(QRectF(3, 7, 18, 13), 2, 2)
        line((4, 7), (4, 4))
        line((4, 4), (11, 4))
        line((11, 4), (13, 7))
        if name == "Open pair":
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
    elif name in ("Close map", "Remove inside"):
        circle(12, 12, 9) if name == "Close map" else painter.drawRect(QRectF(4, 4, 16, 16))
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
    elif name == "Show walls":
        painter.drawRoundedRect(QRectF(3, 7, 18, 11), 6, 6)
        circle(12, 12.5, 3)
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
    elif name in ("Erase", "Restore", "Erase lines", "Erase vertices"):
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
    elif name in ("Snap", "Snapping (px)"):
        painter.setBrush(QColor("#58d9ec"))
        circle(5, 19, 3)
        circle(19, 5, 3)
        line((10, 14), (14, 10))
        line((14, 10), (10, 10))
        line((14, 10), (14, 14))
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
    elif name == "Export padding (px)":
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
        editor.setFixedSize(28, 18)
        editor.move(10, 49)
        self.decrease_button, self.increase_button = QToolButton(self), QToolButton(self)
        for button, x, arrow, amount in (
            (self.decrease_button, 1, Qt.ArrowType.LeftArrow, -1),
            (self.increase_button, 38, Qt.ArrowType.RightArrow, 1),
        ):
            button.setArrowType(arrow)
            button.setFixedSize(9, 18)
            button.move(x, 49)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("""
                QToolButton { color: #969696; background: transparent; border: 0; padding: 0; }
                QToolButton:hover { color: #cccccc; background: #505050; }
                QToolButton:pressed { background: #252525; }
            """)
            button.clicked.connect(lambda checked=False, amount=amount: editor.stepBy(amount))

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
        tool_name = self.defaultAction().property("dale_tooltip_parts")[0]
        title, description, modifier = {
            "Erase lines": (
                "Line eraser diameter (px)",
                "This tool keeps its own diameter in screen pixels.",
                "Ctrl+wheel: change this tool's diameter.",
            ),
            "Erase vertices": (
                "Vertex eraser diameter (px)",
                "This tool keeps its own diameter in screen pixels.",
                "Ctrl+wheel: change this tool's diameter.",
            ),
            "Auto-close": (
                "Auto-close distance (px)",
                "Independent distance in screen pixels; ordinary snapping is unchanged.",
                "Ctrl+wheel: change the auto-close distance.",
            ),
            "Close all contours": (
                "Whole-map close distance (px)",
                "Extend eligible lines across the whole map after confirmation. "
                "Distance uses screen pixels.",
                "Ctrl+wheel: change this value.",
            ),
            "Erase": (
                "Pixel eraser diameter (px)",
                "Diameter in original image pixels. Ctrl+wheel changes it.",
                "Ctrl+wheel: change this tool's diameter.",
            ),
            "Restore": (
                "Restore brush diameter (px)",
                "Diameter in original image pixels. Ctrl+wheel changes it.",
                "Ctrl+wheel: change this tool's diameter.",
            ),
            "Snapping (px)": (
                "Snapping (px)",
                (
                    "Distance to existing vertices or lines. Vertices take priority. Click "
                    "the icon to toggle snapping."
                ),
                "Ctrl+wheel: change this value.",
            ),
            "Export padding (px)": (
                "Export padding (px)",
                (
                    "Additional transparent pixels around each region box, beyond the manda"
                    "tory 3 px guard."
                ),
                "Ctrl+wheel: change this value.",
            ),
        }[tool_name]
        parts = [*self.defaultAction().property("dale_tooltip_parts"), title, description]
        if modifier not in parts:
            parts.append(modifier)
        for control in (self, self.editor(), self.editor().lineEdit()):
            control.setProperty("dale_tooltip_parts", parts)
            control.setToolTip("\n".join(translate(part, language) for part in parts))
        for button, description in (
            (self.decrease_button, "Decrease by 1 px."),
            (self.increase_button, "Increase by 1 px."),
        ):
            parts = [tool_name, description, modifier]
            button.setProperty("dale_tooltip_parts", parts)
            button.setToolTip("\n".join(translate(part, language) for part in parts))


PANEL_HELP = {
    "General": "Open, save, close, export, and navigate projects.",
    "Tool sets": "Choose which tools appear to the left of the map.",
    "Tool size": "Size of the geometry eraser or pixel brush. Ctrl+wheel adjusts sizes.",
    "Snapping": "Configure snapping to existing vertices and line interiors.",
}


def apply_theme(app):
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: "#2b2b2b",
        QPalette.ColorRole.WindowText: "#dedede",
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
        bar.setStyleSheet(STYLE + "QToolBar::separator { height: 1px; width: 38px; }")
    elif title == "General":
        bar.setStyleSheet(COMMAND_STYLE)
    elif title != "General":
        heading = QLabel(title)
        heading.setToolTip(PANEL_HELP.get(title, title))
        heading.setStyleSheet("font-weight: 600; padding: 0 7px;")
        bar.addWidget(heading)
    if not vertical:
        window.addToolBar(bar)
    return bar
