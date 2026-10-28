"""A passive, click-through illustration of normalized object height selection."""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class SliceIndicator(QWidget):
    # Tight opaque silhouette bounds, excluding the asset's transparent edge halo.
    SOURCES = {
        "tree": (32, 62, 435, 925),
        "bush": (544, 65, 460, 921),
        "rock": (1099, 63, 396, 921),
    }

    def __init__(self, owner, parent=None):
        super().__init__(
            parent or owner,
            Qt.WindowType.Widget
            if parent is not None
            else Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setObjectName("alchemistSliceIndicator")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if parent is None:
            self.setFixedSize(290, 440)
        else:
            self.setMinimumHeight(270)
            self.setMaximumHeight(405)
        self.owner = owner
        self.category, self.value = "tree", -1
        self.upper, self.between = 10, False
        self.picture = QPixmap(str(Path(__file__).parent / "assets/alchemist-slicing.png"))

    def level_y(self, level):
        model = self.model_rect()
        return model.bottom() - level * model.height() / 10

    def model_rect(self):
        """Fit the illustration first; height marks follow its actual endpoints."""
        area = QRectF(44, 12, max(1, self.width() - 56), max(1, self.height() - 24))
        source = QRectF(*self.SOURCES.get(self.category, (0, 0, 180, 260)))
        scale = min(area.width() / source.width(), area.height() / source.height())
        width, height = source.width() * scale, source.height() * scale
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def range_rect(self):
        lower = min(9, max(0, self.value))
        upper = min(10, max(lower + 1, self.upper))
        top, bottom = self.level_y(upper), self.level_y(lower)
        return QRectF(38, top, self.width() - 50, bottom - top)

    def display(self, category, value, screen):
        self.category, self.value = category, value
        area = screen.availableGeometry()
        self.resize(min(290, area.width() - 16), min(440, area.height() - 16))
        self.move(area.right() - self.width() - 7, area.top() + 8)
        self.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#292929"))
        ground = self.level_y(3.5)
        painter.fillRect(
            QRectF(1, ground, self.width() - 2, self.height() - ground - 1), QColor("#342c25")
        )
        frame = self.model_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.category in self.SOURCES:
            source = QRectF(*self.SOURCES[self.category])
            painter.drawPixmap(frame, self.picture, source)
        else:
            painter.fillRect(frame, QColor("#777c83"))
        if self.between:
            painter.fillRect(self.range_rect(), QColor(88, 217, 236, 75))
        for level in range(11):
            y = self.level_y(level)
            selected = self.value == level or (self.between and self.upper == level)
            painter.setPen(
                QPen(QColor("#58d9ec" if selected else "#898989"), 2 if selected else 0.7)
            )
            painter.drawLine(QPointF(38, y), QPointF(self.width() - 12, y))
            painter.drawText(
                QRectF(12, y - 9, 24, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(level),
            )
        automatic = self.value == -1
        painter.setPen(
            QPen(
                QColor("#f1c65b" if automatic else "#ba9677"),
                2 if automatic else 1,
                Qt.PenStyle.DashLine,
            )
        )
        painter.drawLine(QPointF(38, ground), QPointF(self.width() - 12, ground))
        caption = self.owner.t("-1 Ground (automatic)")
        rect = QRectF(
            12,
            ground - 9,
            min(self.width() - 24, painter.fontMetrics().horizontalAdvance(caption) + 4),
            18,
        )
        painter.fillRect(rect, QColor(41, 41, 41, 215))
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, caption)
        painter.setPen(QColor("#777777"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
