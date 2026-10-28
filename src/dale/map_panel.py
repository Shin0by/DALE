"""Shared draggable, resizable map panels with viewport-edge snapping."""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QFrame


class MapPanel(QFrame):
    def constrain_position(self, point, *, dock=True):
        viewport = self.map_viewport
        x_max, y_max = (
            max(0, viewport.width() - self.width()),
            max(0, viewport.height() - self.height()),
        )
        x, y = max(0, min(point.x(), x_max)), max(0, min(point.y(), y_max))
        if dock:
            x = 0 if x < 10 else x_max if x_max - x < 10 else x
            y = 0 if y < 10 else y_max if y_max - y < 10 else y
            self.dock_x = -1 if x == 0 else 1 if x == x_max else 0
            self.dock_y = -1 if y == 0 else 1 if y == y_max else 0
        self.viewport_anchor = QPoint(x, y)
        self.move(viewport.pos() + self.viewport_anchor)

    def viewport_position(self):
        return self.pos() - self.map_viewport.pos()

    def fit_size(self):
        self.resize(
            self.requested_size.boundedTo(self.map_viewport.size()).expandedTo(self.minimumSize())
        )

    def set_user_size(self, size):
        self.user_sized = True
        self.requested_size = size.expandedTo(self.minimumSize()).boundedTo(
            self.map_viewport.size()
        )
        self.fit_size()
        self.reposition()

    def reposition(self):
        point = QPoint(self.viewport_anchor)
        if self.dock_x == 1:
            point.setX(self.map_viewport.width() - self.width())
        if self.dock_y == 1:
            point.setY(self.map_viewport.height() - self.height())
        self.constrain_position(point, dock=False)
        if self.isVisible():
            self.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "viewport_anchor"):
            self.reposition()

    def eventFilter(self, watched, event):
        if watched is self.owner.view and event.type() == QEvent.Type.Resize:
            if (
                not (self.dock_x or self.dock_y)
                and event.oldSize().isValid()
                and (
                    event.size().width() < event.oldSize().width()
                    or event.size().height() < event.oldSize().height()
                )
            ):
                self.viewport_anchor.setX(0)
            self.reposition()
        if watched is self.map_viewport and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self.fit_size()
            self.reposition()
        if watched is self.header:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.drag_offset = event.globalPosition().toPoint() - self.mapToGlobal(QPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and self.drag_offset is not None:
                point = event.globalPosition().toPoint() - self.drag_offset
                self.constrain_position(self.map_viewport.mapFromGlobal(point))
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self.drag_offset = None
                return True
        return super().eventFilter(watched, event)
