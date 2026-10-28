"""Compact persistent map overlay for editing dataset selection groups."""

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
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

from dale.map_panel import MapPanel
from dale.toolbar import tool_icon


class GroupDragHandle(QToolButton):
    """A color swatch in ordinary mode, a drag-only grip while sorting."""

    def __init__(self, manager, identifier, parent):
        super().__init__(parent)
        self.manager, self.identifier = manager, identifier
        self.setFixedSize(24, 26)

    def choose_color(self):
        if not self.manager.sorting:
            self.manager.owner.change_group_color(self.identifier)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.manager.sorting:
            painter = QPainter(self)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.palette().color(QPalette.ColorRole.ButtonText))
            for x in (self.width() // 2 - 4, self.width() // 2 + 2):
                for y in (self.height() // 2 - 6, self.height() // 2 - 1, self.height() // 2 + 4):
                    painter.drawEllipse(x, y, 2, 2)

    def mousePressEvent(self, event):
        if self.manager.sorting and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.manager.begin_group_drag(self.identifier, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.manager.sorting:
            self.manager.update_group_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.manager.sorting and event.button() == Qt.MouseButton.LeftButton:
            self.manager.finish_group_drag(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def event(self, event):
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and event.key() == Qt.Key.Key_Escape
            and self.manager.drag_group is not None
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.manager.drag_group is not None:
            self.manager.cancel_group_drag()
            event.accept()
        else:
            super().keyPressEvent(event)


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


class GroupManager(MapPanel):
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
        self.sorting = False
        self.sort_context = None
        self.drag_group = None
        self.drag_origin = self.drag_position = None
        self.drop_index = None
        self.dragging = False
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
        self.drop_indicator = QWidget(self.scroll.viewport())
        self.drop_indicator.setObjectName("groupDropIndicator")
        self.drop_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drop_indicator.setStyleSheet("background: #e4e8ed;")
        self.drop_indicator.hide()
        self.drag_scroll = QTimer(self)
        self.drag_scroll.setInterval(30)
        self.drag_scroll.timeout.connect(self.scroll_group_drag)
        self.row_controls = {}
        self.scroll_position = None
        self.scroll_restore = QTimer(self)
        self.scroll_restore.setSingleShot(True)
        self.scroll_restore.timeout.connect(self.restore_scroll_position)
        layout.addWidget(self.scroll)
        self.new_button = QPushButton(self)
        self.new_button.setFixedHeight(26)
        self.new_button.clicked.connect(owner.create_selection_group)
        self.sort_button = QToolButton(self)
        self.sort_button.setFixedSize(26, 26)
        self.sort_button.setIcon(tool_icon("Sorting"))
        self.sort_button.setIconSize(QSize(20, 20))
        self.sort_button.setCheckable(True)
        self.sort_button.toggled.connect(self.set_sorting)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(3)
        bottom.addWidget(self.sort_button)
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
        if self.sort_context != self.group_context():
            self.set_sorting(False)
        section = owner.tool_set_actions[owner.current_tool_set].text()
        self.title.setText(t("Groups: {section}", section=section))
        self.close_button.setToolTip(
            owner.control_help(
                "Close group mode and restore ordinary selection colors.", title="Close"
            )
        )
        self.new_button.setText("+")
        self.sort_button.setText(t("Sorting"))
        self.sort_button.setAccessibleName(t("Sorting"))
        self.sort_button.setToolTip(
            owner.control_help(
                "Reorder groups by dragging their handles. "
                "Group actions are disabled while sorting.",
                title="Sorting",
            )
        )
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
        if not groups and self.sorting:
            self.set_sorting(False)
        identifiers = {group.id for group in groups}
        if tuple(self.row_controls) != tuple(group.id for group in groups):
            self.cancel_group_drag()
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
                swatch = GroupDragHandle(self, group.id, row)
                swatch.clicked.connect(swatch.choose_color)
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
            self.update_handle(swatch, group)
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
        self.sort_button.setEnabled(bool(groups) and not blocked)
        if blocked:
            self.cancel_group_drag()
        geometry = self.owner.view.editing_geometry() if self.owner.view.session else None
        for identifier, controls in self.row_controls.items():
            swatch, name, add, remove, delete = controls
            if identifier not in groups:
                for control in controls:
                    control.setEnabled(False)
                continue
            swatch.setEnabled(not blocked)
            name.setEnabled(not blocked and not self.sorting)
            name.setChecked(identifier == self.owner.active_selection_group())
            if self.sorting or blocked:
                for button in (add, remove, delete):
                    button.setEnabled(False)
                continue
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

    def group_context(self):
        catalog = self.owner.catalog
        return id(catalog), catalog.current.id if catalog else None, self.owner.current_tool_set

    def set_sorting(self, enabled):
        self.cancel_group_drag()
        self.sorting = enabled
        self.sort_context = self.group_context()
        blocked = self.sort_button.blockSignals(True)
        self.sort_button.setChecked(enabled)
        self.sort_button.blockSignals(blocked)
        self.update_actions()
        for group in self.owner.selection_groups():
            if group.id in self.row_controls:
                self.update_handle(self.row_controls[group.id][0], group)

    def update_handle(self, handle, group):
        owner = self.owner
        if self.sorting:
            handle.setStyleSheet("")
            handle.setAccessibleName(owner.t("Move group"))
            handle.setToolTip(
                owner.control_help(
                    "Drag up or down. The light line marks the new group position.",
                    title="Move group",
                    keys=("Escape: cancel this drag.",),
                )
            )
            handle.setCursor(
                Qt.CursorShape.ClosedHandCursor
                if self.drag_group == group.id
                else Qt.CursorShape.OpenHandCursor
            )
        else:
            handle.setStyleSheet(
                f"QToolButton {{ background: {group.color}; border: 1px solid #aaaaaa; }}"
            )
            handle.setAccessibleName(owner.t("Group color"))
            handle.setToolTip(
                owner.control_help("Choose the color of this group.", title="Group color")
            )
            handle.unsetCursor()
        handle.update()

    def begin_group_drag(self, identifier, position):
        if not self.sorting or self.owner.worker or self.owner.view.active_gesture:
            return
        self.cancel_group_drag()
        self.drag_group, self.drag_origin, self.drag_position = identifier, position, position
        self.row_controls[identifier][0].setCursor(Qt.CursorShape.ClosedHandCursor)

    def update_group_drag(self, position):
        if self.drag_group is None:
            return
        if (
            self.sort_context != self.group_context()
            or self.owner.worker
            or self.owner.view.active_gesture
        ):
            self.cancel_group_drag()
            return
        self.drag_position = position
        if not self.dragging:
            self.dragging = (
                position - self.drag_origin
            ).manhattanLength() >= QApplication.startDragDistance()
        if not self.dragging:
            return
        viewport = self.scroll.viewport()
        point = viewport.mapFromGlobal(position)
        if not viewport.rect().contains(point):
            self.drop_index = None
            self.drop_indicator.hide()
            self.drag_scroll.stop()
            return
        rows = [
            controls[0].parentWidget()
            for i, controls in self.row_controls.items()
            if i != self.drag_group
        ]
        y = self.content.mapFromGlobal(position).y()
        self.drop_index = next(
            (i for i, row in enumerate(rows) if y < row.geometry().center().y()), len(rows)
        )
        line_y = (
            rows[self.drop_index].y() - 2
            if self.drop_index < len(rows)
            else rows[-1].geometry().bottom() + 2
            if rows
            else 0
        )
        line_y = self.content.mapTo(viewport, QPoint(0, line_y)).y()
        self.drop_indicator.setGeometry(
            0, max(0, min(line_y, viewport.height() - 2)), viewport.width(), 2
        )
        self.drop_indicator.show()
        self.drop_indicator.raise_()
        if point.y() < 18 or point.y() > viewport.height() - 18:
            self.drag_scroll.start()
        else:
            self.drag_scroll.stop()

    def scroll_group_drag(self):
        if self.drag_position is None:
            return
        viewport = self.scroll.viewport()
        y = viewport.mapFromGlobal(self.drag_position).y()
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.value() + (-8 if y < 18 else 8))
        self.update_group_drag(self.drag_position)

    def cancel_group_drag(self):
        self.drag_scroll.stop()
        self.drop_indicator.hide()
        if self.drag_group in self.row_controls:
            self.row_controls[self.drag_group][0].setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_group = self.drag_origin = self.drag_position = self.drop_index = None
        self.dragging = False

    def finish_group_drag(self, position):
        self.update_group_drag(position)
        identifier, index = self.drag_group, self.drop_index
        self.cancel_group_drag()
        if identifier is not None and index is not None:
            self.owner.reorder_selection_group(identifier, index)

    def showEvent(self, event):
        super().showEvent(event)
        self.reposition()
        self.owner.group_manager_button.setChecked(True)
        self.owner.update_group_rendering()

    def wheelEvent(self, event):
        event.accept()

    def hideEvent(self, event):
        self.set_sorting(False)
        super().hideEvent(event)
        self.owner.group_manager_button.setChecked(False)
        self.owner.update_group_rendering()
