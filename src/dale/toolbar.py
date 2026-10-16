"""Native, code-drawn toolbar icons and consistent visible tool button styling."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QLabel, QToolBar


def tool_icon(name):
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
    elif name == "Export PNGs":
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
    elif name == "Pan":
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
    elif name == "Fit":
        for x, y, sx, sy in ((3, 3, 1, 1), (21, 3, -1, 1), (3, 21, 1, -1), (21, 21, -1, -1)):
            line((x, y + sy * 5), (x, y))
            line((x, y), (x + sx * 5, y))
    elif name == "Show walls":
        painter.drawRoundedRect(QRectF(3, 7, 18, 11), 6, 6)
        circle(12, 12.5, 3)
    elif name in ("New line", "Edit points", "Closure"):
        points = [(4, 18), (12, 6), (20, 14)] if name == "Closure" else [(4, 18), (20, 6)]
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
            painter.setBrush(QColor("#ff454f"))
            circle(19, 19, 3)
        elif name == "Erase lines":
            painter.setPen(QPen(QColor("#ff454f"), 2))
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
    elif name == "Snap":
        painter.drawArc(QRectF(4, 4, 16, 16), 180 * 16, 180 * 16)
        line((4, 12), (4, 5))
        line((20, 12), (20, 5))
        line((2, 5), (6, 5))
        line((18, 5), (22, 5))
    else:
        painter.drawRect(QRectF(5, 5, 14, 14))
    painter.end()
    return QIcon(canvas)


STYLE = """
QToolBar { background: #223044; border: 1px solid #52647c; spacing: 5px; padding: 5px; }
QToolBar QLabel { color: #edf4ff; background: transparent; padding: 0 3px; }
QToolBar QToolButton { background: #35465c; color: #f5f8ff; border: 1px solid #6d7f98;
    border-radius: 4px; padding: 5px 7px; }
QToolBar QToolButton:hover { background: #48617e; border-color: #a9d4ff; }
QToolBar QToolButton:checked { background: #17699e; border: 2px solid #73ccff; padding: 4px 6px; }
QToolBar QToolButton:pressed { background: #164f7d; }
QToolBar QToolButton:disabled { color: #9aa8ba; background: #2c384a; border-color: #46566b; }
QToolBar QSpinBox, QToolBar QDoubleSpinBox, QToolBar QComboBox {
    background: #f3f7fd; color: #172538; border: 1px solid #9dadc2;
    border-radius: 3px; padding: 4px; min-height: 20px; }
QToolBar::separator { background: #60718a; width: 1px; margin: 4px; }
"""


def make_toolbar(window, title, new_row=False):
    if new_row:
        window.addToolBarBreak()
    bar = QToolBar(title, window)
    bar.setObjectName(title)
    bar.setMovable(False)
    bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    bar.setIconSize(QSize(22, 22))
    bar.setStyleSheet(STYLE)
    heading = QLabel(title)
    heading.setStyleSheet("font-weight: 600; padding: 0 7px;")
    bar.addWidget(heading)
    window.addToolBar(bar)
    return bar
