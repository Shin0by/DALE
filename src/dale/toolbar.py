"""Native, code-drawn toolbar icons and consistent visible tool button styling."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QLabel,
    QScrollArea,
    QSpinBox,
    QToolBar,
    QToolButton,
    QWidget,
)

from dale.localization import format_tooltip


class TopPanelScrollArea(QScrollArea):
    """A single row of complete panels, with a quiet horizontal scrollbar."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("topPanelScrollArea")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(
            "QScrollArea#topPanelScrollArea { background: transparent; border: 0; }"
            "QScrollBar:horizontal { height: 3px; background: transparent; margin: 0; }"
            "QScrollBar::handle:horizontal { background: #505050; min-width: 24px; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }"
        )

    def scroll_wheel(self, event):
        pixels = event.pixelDelta()
        delta = (
            (pixels.x() or pixels.y())
            if not pixels.isNull()
            else (event.angleDelta().y() or event.angleDelta().x())
        )
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - round(delta))
        event.accept()

    def wheelEvent(self, event):
        self.scroll_wheel(event)


def tool_icon(name):
    name = {
        "Move raster regions": "Move regions",
        "Rotate raster regions": "Rotate regions",
        "Preview selected regions": "Show contours",
        "Raster artwork offset": "Artwork offset (px)",
    }.get(name, name)
    square_brush = name in ("Erase square", "Restore square")
    name = {"Erase square": "Erase", "Restore square": "Restore"}.get(name, name)
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

    if name in ("Copy region contours", "Copy contours"):
        painter.drawRect(QRectF(3, 3, 12, 14))
        painter.setBrush(QColor("#383838"))
        painter.drawRect(QRectF(8, 7, 13, 15))
        line((11, 11), (18, 11))
        line((11, 15), (18, 15))
    elif name in ("Delete region", "Delete contours"):
        line((4, 6), (20, 6))
        line((9, 3), (15, 3))
        painter.drawRect(QRectF(6, 6, 12, 15))
        line((10, 10), (10, 17))
        line((14, 10), (14, 17))
    elif name == "Figure extension alignment":
        line((2, 20), (10, 13))
        painter.setPen(QPen(QColor("#f1f6ff"), 1, Qt.PenStyle.DashLine))
        line((10, 13), (22, 3))
        painter.setPen(QPen(QColor("#58d9ec"), 1.8))
        circle(18, 6.3, 2.5)
    elif name == "Native raster resolution":
        painter.drawRect(QRectF(2, 3, 20, 18))
        font = painter.font()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(2, 3, 20, 18), Qt.AlignmentFlag.AlignCenter, "1:1")
    elif name == "Raster crosshair":
        line((12, 1), (12, 23))
        line((1, 12), (23, 12))
        painter.setBrush(QColor("#58d9ec"))
        circle(12, 12, 2)
    elif name == "Raster rulers":
        painter.drawRect(QRectF(2, 2, 20, 5))
        painter.drawRect(QRectF(2, 7, 5, 15))
        for value in (7, 12, 17):
            line((value, 2), (value, 5))
            line((2, value), (5, value))
    elif name == "Scene grid":
        painter.setPen(QPen(QColor("#f1f6ff"), 1.5))
        for value in (3, 9, 15, 21):
            line((value, 3), (value, 21))
            line((3, value), (21, value))
    elif name == "Canvas background":
        painter.drawRect(QRectF(2, 2, 20, 20))
        painter.fillRect(QRectF(3, 3, 9, 9), QColor("#f1f6ff"))
        painter.fillRect(QRectF(12, 12, 9, 9), QColor("#f1f6ff"))
    elif name == "Move guides":
        painter.setPen(QPen(QColor("#73baff"), 1, Qt.PenStyle.DashLine))
        line((8, 2), (8, 22))
        line((2, 16), (22, 16))
        painter.setPen(QPen(QColor("#f1f6ff"), 1.5))
        line((3, 8), (20, 8))
        line((3, 8), (6, 5))
        line((3, 8), (6, 11))
        line((20, 8), (17, 5))
        line((20, 8), (17, 11))
    elif name == "Scale raster regions":
        painter.drawRect(QRectF(3, 10, 11, 11))
        line((9, 15), (21, 3))
        line((15, 3), (21, 3))
        line((21, 3), (21, 9))
    elif name == "Select all contour lines":
        painter.drawRect(QRectF(2, 2, 20, 20))
        for y in (7, 12, 17):
            line((6, y), (18, y))
        painter.setBrush(QColor("#58d9ec"))
        for y in (7, 12, 17):
            circle(6, y, 1.4)
            circle(18, y, 1.4)
    elif name == "Group manager":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1, 1)
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
    elif name == "Pan":
        painter.setPen(
            QPen(
                QColor("#f1f6ff"),
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        hand = QPainterPath(QPointF(9, 16.5))
        hand.lineTo(5.7, 12)
        hand.cubicTo(4, 9.4, 6, 7.6, 8.8, 10.7)
        hand.lineTo(8.8, 3.2)
        hand.cubicTo(8.8, 0.6, 12.3, 0.6, 12.3, 3.2)
        hand.lineTo(12.3, 8.8)
        hand.cubicTo(12.7, 6.8, 15.1, 7.1, 15.1, 9)
        hand.cubicTo(15.8, 7.4, 18, 8.1, 17.9, 10)
        hand.cubicTo(19, 8.6, 20.5, 9.7, 20.3, 11.4)
        hand.lineTo(19.8, 14)
        hand.quadTo(19.5, 15.3, 17.5, 16.5)
        hand.closeSubpath()
        painter.drawPath(hand)
        line((3, 21), (21, 21))
        for x, dx in ((3, 3), (21, -3)):
            line((x, 21), (x + dx, 18.5))
            line((x, 21), (x + dx, 23))
    elif name == "Sorting":
        line((7, 3), (7, 21))
        line((3, 7), (7, 3))
        line((11, 7), (7, 3))
        line((17, 3), (17, 21))
        line((13, 17), (17, 21))
        line((21, 17), (17, 21))
    elif name == "Move regions":
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
    elif name in ("Mirror contours about vertical axis", "Mirror contours about horizontal axis"):
        if name == "Mirror contours about horizontal axis":
            painter.translate(12, 12)
            painter.rotate(90)
            painter.translate(-12, -12)
        painter.setPen(QPen(QColor("#58d9ec"), 1.2, Qt.PenStyle.DashLine))
        line((12, 2), (12, 22))
        painter.setPen(QPen(QColor("#f1f6ff"), 1.5))
        painter.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(8, 19), QPointF(2, 15)]))
        painter.drawPolygon(QPolygonF([QPointF(16, 5), QPointF(16, 19), QPointF(22, 15)]))
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
    if square_brush:
        painter.setPen(QPen(QColor("#58d9ec"), 1))
        painter.setBrush(QColor("#303030"))
        painter.drawRect(QRectF(15, 15, 7, 7))
    painter.end()
    return QIcon(canvas)


STYLE = """
QToolBar { background: #353535; border: 1px solid #494949;
           spacing: 4px; padding: 5px; margin-right: 2px; }
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
        if self.property("dale_compact"):
            self.lineEdit().setGeometry(1, 0, max(1, self.width() - 2), self.height())
            return
        self.lineEdit().setGeometry(3, 2, max(1, self.width() - 6), self.height() - 4)


class SizedToolButton(QToolButton):
    """A square icon tool with its numeric state edited in a settings dialog."""

    def __init__(self, editor, action, *, inline=False, activation_hint=None):
        super().__init__()
        self.editor_widget = editor
        self.setDefaultAction(action)
        self.setFixedSize(48, 48)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(24, 24))
        editor.setParent(self)
        editor.hide()
        self.activation_hint = activation_hint
        if activation_hint is not None:
            self.setFixedSize(48, 60)
            self.setStyleSheet("QToolButton { padding-bottom: 20px; }")
        if inline:
            self.setFixedSize(48, 60)
            self.setStyleSheet("QToolButton { padding-bottom: 20px; }")
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            editor.setProperty("dale_compact", True)
            editor.setStyleSheet("QSpinBox { min-height: 0; padding: 0; font-size: 11px; }")
            editor.lineEdit().setFrame(False)
            editor.lineEdit().setTextMargins(0, 0, 0, 0)
            editor.setFixedSize(30, 16)
            editor.move(9, 41)
            editor.show()
        self.help_language = None
        action.changed.connect(self.refresh_help)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.activation_hint:
            painter = QPainter(self)
            font = self.font()
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(
                self.palette().color(
                    QPalette.ColorGroup.Active
                    if self.isEnabled()
                    else QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.ButtonText,
                )
            )
            painter.drawText(
                QRectF(9, 41, 30, 16), Qt.AlignmentFlag.AlignCenter, self.activation_hint
            )

    def refresh_help(self):
        if self.help_language and self.defaultAction().property("dale_tooltip_parts"):
            self.set_help(self.help_language)

    def editor(self):
        return self.editor_widget

    def set_help(self, language):
        self.help_language = language
        tool_name = self.defaultAction().property("dale_tool_key")
        tool_name = {
            "Figure point alignment": "Region point alignment",
            "Figure guide alignment": "Region guide alignment",
            "Raster artwork offset": "Artwork offset (px)",
        }.get(tool_name, tool_name)
        value_help = {
            "Figure extension alignment": (
                "Number: perpendicular distance to a virtual line, in screen pixels."
            ),
            "Right-angle alignment": "Number: angular deviation from 90 degrees, in degrees.",
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
            "Erase square": "Number: brush diameter in original image pixels.",
            "Restore square": "Number: brush diameter in original image pixels.",
            "Snapping (px)": "Number: snap distance in screen pixels; 0 disables snapping.",
            "Artwork offset (px)": (
                "Number: original image pixels; positive expands, negative cuts inward."
            ),
        }[tool_name]
        modifier = (
            "Ctrl+wheel: change brush diameter."
            if tool_name in ("Erase", "Restore", "Erase square", "Restore square")
            else "Ctrl+wheel: change this value."
        )
        editor_parts = [value_help]
        action = self.defaultAction()
        parts = list(action.property("dale_tooltip_parts"))
        keys = list(
            dict.fromkeys(
                [
                    *(action.property("dale_tooltip_keys") or []),
                    "Right-click: open tool settings.",
                    modifier,
                ]
            )
        )
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


class ToolSettingsCorner(QWidget):
    """Mouse-transparent corner mark for buttons with a settings context action."""

    def __init__(self, button):
        super().__init__(button)
        self.setObjectName("toolSettingsCorner")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(9, 9)
        self.move(button.width() - self.width(), button.height() - self.height())
        self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.ButtonText))
        painter.drawPolygon(QPolygonF([QPointF(9, 0), QPointF(0, 9), QPointF(9, 9)]))


class ModeTabButton(QToolButton):
    """Self-contained tab painting, including a clipped circular active accent."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        left, top, right, bottom = bounds.getCoords()
        path = QPainterPath(QPointF(left, bottom))
        path.lineTo(left, top + 4)
        path.quadTo(left, top, left + 4, top)
        path.lineTo(right - 4, top)
        path.quadTo(right, top, right, top + 4)
        path.lineTo(right, bottom)
        path.closeSubpath()
        active = self.isChecked()
        background = QColor("#4f718c" if active else "#454545" if self.underMouse() else "#383838")
        painter.fillPath(path, background)
        if active:
            # The circle passes through both lower corners; its apex clears the text.
            text_bottom = (self.height() + self.fontMetrics().height()) / 2
            apex = min(bottom - 2, text_bottom + 2)
            cap_height = bottom - apex
            half_width = bounds.width() / 2
            radius = (half_width * half_width + cap_height * cap_height) / (2 * cap_height)
            painter.save()
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 24))
            painter.drawEllipse(QPointF(bounds.center().x(), apex + radius), radius, radius)
            painter.restore()
        painter.setPen(QPen(QColor("#6f91aa" if active else "#555555"), 1))
        painter.drawPath(path)
        painter.setPen(self.palette().color(QPalette.ColorRole.ButtonText))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class ModesToolbar(QToolBar):
    """Bottom-aligned tabs within the same panel frame as the other toolbars."""

    def refresh_tabs(self):
        for action in self.actions():
            button = self.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setFixedHeight(36 if action.isChecked() else 32)
                self.layout().setAlignment(button, Qt.AlignmentFlag.AlignBottom)
                button.update()
        self.update()


PANEL_HELP = {
    "Vertices alignment": "Configure alignment while editing contour vertices and lines.",
    "Contours alignment": "Configure alignment while moving or pasting contours.",
    "Regions alignment": "Configure alignment while moving or pasting regions.",
    "Groups": "Manage dataset selection groups and choose a group to select.",
    "General": "Open, save, close, export, and navigate projects.",
    "Sections": "Choose which tools appear to the left of the scene image.",
    "Modes": "Choose which tools appear to the left of the scene image.",
    "Main": "Navigate, select, copy, delete and configure the current editing mode.",
    "View": "Fit the scene and configure contours, guides, background and image resolution.",
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
        "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 6px; }"
    )


def make_toolbar(window, title, new_row=False, vertical=False):
    if new_row and not vertical:
        window.addToolBarBreak()
    bar = ModesToolbar(title, window) if title == "Modes" else QToolBar(title, window)
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
            STYLE + "QToolBar { spacing: 3px; margin: 0; } "
            "QToolBar::separator { height: 1px; width: 38px; }"
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
        if title in ("Main", "View"):
            bar.setStyleSheet(STYLE + "QToolBar { spacing: 1px; }")
        elif title == "Modes":
            bar.setStyleSheet(
                STYLE + "QToolBar { spacing: 1px; }"
                "QToolBar QToolButton { padding: 4px 3px; }"
                "QToolBar QToolButton:checked { padding: 3px 2px; }"
            )
    return bar
