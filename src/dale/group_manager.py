"""Compact persistent map overlay for editing dataset selection groups."""

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class GroupNameButton(QPushButton):
    rename_requested = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.rename_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class GroupSizeGrip(QWidget):
    """Qt's standard corner grip, targeting only the overlay even in maximized windows."""

    def __init__(self, manager):
        super().__init__(manager)
        self.manager = manager
        self.press_position = None
        self.press_size = None
        self.setObjectName("groupSizeGrip")
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def paintEvent(self, event):
        option = QStyleOptionSizeGrip()
        option.initFrom(self)
        option.corner = Qt.Corner.BottomRightCorner
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_SizeGrip, option, painter, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_position = event.globalPosition().toPoint()
            self.press_size = self.manager.size()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self.press_position is not None:
            delta = event.globalPosition().toPoint() - self.press_position
            self.manager.set_user_size(self.press_size + QSize(delta.x(), delta.y()))
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.press_position is not None:
            self.mouseMoveEvent(event)
            self.press_position = None
            self.press_size = None
            event.accept()
        else:
            event.ignore()


class GroupManager(QFrame):
    """A view-frame child, positioned in viewport pixels without content scrolling."""

    def __init__(self, owner):
        # QGraphicsView scrolls viewport children along with its scene contents.
        # A sibling of the viewport stays fixed while the camera moves.
        super().__init__(owner.view)
        self.owner = owner
        self.map_viewport = owner.view.viewport()
        self.viewport_anchor = QPoint()
        self.requested_size = QSize(318, 112)
        self.user_sized = False
        self.drag_offset = None
        self.dock_x = self.dock_y = 0
        self.setObjectName("groupsManager")
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setStyleSheet(
            "QFrame#groupsManager { background: palette(window); border: 1px solid #606060; }"
        )
        self.setMinimumSize(250, 112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        self.header = QWidget(self)
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(2, 0, 0, 0)
        self.title = QLabel(self.header)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header.addWidget(self.title, 1)
        self.close_button = QToolButton(self)
        self.close_button.setText("X")
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(self.hide)
        header.addWidget(self.close_button)
        layout.addWidget(self.header)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(3)
        self.rows.addStretch()
        self.scroll.setWidget(self.content)
        self.row_controls = {}
        self.scroll_position = None
        self.scroll_restore = QTimer(self)
        self.scroll_restore.setSingleShot(True)
        self.scroll_restore.timeout.connect(self.restore_scroll_position)
        layout.addWidget(self.scroll)
        self.new_button = QPushButton(self)
        self.new_button.clicked.connect(owner.create_selection_group)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addWidget(self.new_button, 1)
        self.size_grip = GroupSizeGrip(self)
        bottom.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(bottom)
        self.header.installEventFilter(self)
        self.map_viewport.installEventFilter(self)
        owner.view.installEventFilter(self)
        self.rebuild()

    def rebuild(self):
        owner, t = self.owner, self.owner.t
        section = owner.tool_set_actions[owner.current_tool_set].text()
        self.title.setText(t("Groups: {section}", section=section))
        self.close_button.setToolTip(
            owner.control_help(
                "Close group mode and restore ordinary selection colors.", title="Close"
            )
        )
        self.new_button.setText("+")
        self.new_button.setToolTip(
            owner.control_help(
                "Create an empty group in this section of the current dataset.", title="+ New group"
            )
        )
        self.size_grip.setAccessibleName(t("Resize group manager"))
        self.size_grip.setToolTip(
            owner.control_help(
                "Change the width and height of the group manager.", title="Resize group manager"
            )
        )
        groups = owner.selection_groups()
        identifiers = {group.id for group in groups}
        if tuple(self.row_controls) != tuple(group.id for group in groups):
            if self.scroll_position is None:
                self.scroll_position = self.scroll.verticalScrollBar().value()
            self.scroll_restore.start(0)
        for index in reversed(range(self.rows.count() - 1)):
            widget = self.rows.itemAt(index).widget()
            if widget.objectName() not in identifiers:
                self.rows.takeAt(index)
                widget.hide()
                widget.deleteLater()
        previous, self.row_controls = self.row_controls, {}
        for index, group in enumerate(groups):
            controls = previous.get(group.id)
            if controls is None:
                row = QFrame(self.content)
                row.setObjectName(group.id)
                cells = QHBoxLayout(row)
                cells.setContentsMargins(3, 3, 3, 3)
                cells.setSpacing(3)
                swatch = QToolButton(row)
                swatch.setFixedSize(24, 26)
                swatch.clicked.connect(
                    lambda checked=False, i=group.id: owner.change_group_color(i)
                )
                name = GroupNameButton(group.name, row)
                name.setFixedHeight(26)
                name.setMinimumWidth(60)
                name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                name.setCheckable(True)
                name.clicked.connect(
                    lambda checked=False, i=group.id: owner.select_selection_group(i)
                )
                name.rename_requested.connect(lambda i=group.id: owner.rename_selection_group(i))
                cells.addWidget(swatch)
                cells.addWidget(name, 1)
                controls = [swatch, name]
                for callback in (
                    lambda i: owner.assign_selection_group(i, True),
                    lambda i: owner.assign_selection_group(i, False),
                    owner.delete_selection_group,
                ):
                    button = QToolButton(row)
                    button.setFixedSize(24, 26)
                    button.clicked.connect(lambda checked=False, i=group.id, cb=callback: cb(i))
                    cells.addWidget(button)
                    controls.append(button)
            else:
                swatch, name, *_ = controls
                row = swatch.parentWidget()
            if self.rows.indexOf(row) != index:
                self.rows.insertWidget(index, row)
            self.row_controls[group.id] = controls
            row.setStyleSheet(
                f"QFrame#{group.id} {{ border: 1px solid #555555; border-radius: 3px; }}"
            )
            swatch.setStyleSheet(
                f"QToolButton {{ background: {group.color}; border: 1px solid #aaaaaa; }}"
            )
            swatch.setToolTip(
                owner.control_help("Choose the color of this group.", title="Group color")
            )
            name.setText(group.name)
            name.setChecked(group.id == owner.active_selection_group())
            name.setToolTip(
                owner.control_help(
                    "Select this group's elements in the current section.",
                    title=group.name,
                    keys=("Double-click: rename this group.",),
                )
            )
            for button, (text, title, purpose) in zip(
                controls[2:],
                (
                    (
                        "+",
                        "Add selection",
                        "Add the currently selected elements to this group.",
                    ),
                    (
                        "-",
                        "Exclude selection",
                        "Remove the currently selected elements from this group.",
                    ),
                    (
                        "x",
                        "Delete group",
                        "Delete this group, keeping all scene elements.",
                    ),
                ),
                strict=True,
            ):
                button.setText(text)
                button.setToolTip(owner.control_help(purpose, title=title))
        if not groups:
            empty = QLabel(
                t("Create a group, then add selected scene elements with +."), self.content
            )
            empty.setWordWrap(True)
            self.rows.insertWidget(0, empty)
        self.new_button.setEnabled(
            len(owner.all_selection_groups()) < 256
            and not owner.view.active_gesture
            and not owner.worker
        )
        if not self.user_sized:
            self.requested_size = QSize(318, min(292, max(112, 78 + len(groups) * 35)))
        self.fit_size()
        self.update_actions()
        self.reposition()

    def restore_scroll_position(self):
        if self.scroll_position is not None:
            self.scroll.verticalScrollBar().setValue(self.scroll_position)
            self.scroll_position = None

    def update_actions(self):
        selection = self.owner.group_selection_ids()
        blocked = bool(self.owner.worker or self.owner.view.active_gesture)
        groups = {g.id: g for g in self.owner.selection_groups()}
        geometry = self.owner.view.editing_geometry() if self.owner.view.session else None
        for identifier, controls in self.row_controls.items():
            swatch, name, add, remove, delete = controls
            swatch.setEnabled(not blocked)
            name.setEnabled(not blocked)
            name.setChecked(identifier == self.owner.active_selection_group())
            members = self.owner.resolved_group_members(identifier)
            if self.owner.current_tool_set in ("regions", "pixels"):
                from dale.region_groups import matched_cells

                group = groups.get(identifier)
                polygons = self.owner.view.region_polygons
                hits = matched_cells(group, geometry, polygons) if group and geometry else ()
                add.setEnabled(not blocked and group is not None and len(hits) < len(polygons))
                remove.setEnabled(not blocked and bool(hits))
            else:
                add.setEnabled(not blocked and bool(selection - members))
                remove.setEnabled(not blocked and bool(selection & members))
            delete.setEnabled(not blocked)

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

    def showEvent(self, event):
        super().showEvent(event)
        self.reposition()
        self.owner.group_manager_button.setChecked(True)
        self.owner.update_group_rendering()

    def wheelEvent(self, event):
        event.accept()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.owner.group_manager_button.setChecked(False)
        self.owner.update_group_rendering()
