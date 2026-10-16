"""English source strings and Russian desktop translations."""

from PySide6.QtCore import QTranslator
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollBar,
    QToolBar,
    QToolButton,
    QWidget,
)

RUSSIAN = {
    "Tool size": "Размер",
    "Screen px": "Экранные px",
    "Source px": "Исходные px",
    "Image + JSON": "JPG + JSON",
    "Open": "Открыть",
    "Save as…": "Сохранить как…",
    "Close": "Закрыть",
    "Export": "Экспорт",
    "Hand": "Рука",
    "Walls": "Стены",
    "Open, save, close, export, and navigate projects.": (
        "Открытие, сохранение, закрытие, экспорт и навигация по карте."
    ),
    "Choose which tools appear to the left of the map.": (
        "Выберите набор инструментов, который будет показан слева от карты."
    ),
    "Size of the geometry eraser or pixel brush. Ctrl+wheel adjusts sizes.": (
        "Размер ластика геометрии или пиксельной кисти. Ctrl + колесо меняет размер."
    ),
    "Configure snapping to existing vertices and line interiors.": (
        "Настройте привязку к существующим вершинам и отрезкам линий."
    ),
    "Geometry size uses screen pixels; pixel brush size uses original image pixels.": (
        "Размер геометрического ластика — в экранных пикселях, кисти — в исходных пикселях карты."
    ),
    "Right-drag pans, wheel zooms, Ctrl+wheel changes tool size. Escape cancels a gesture.": (
        "Правая кнопка перемещает карту, колесо меняет масштаб, "
        "Ctrl + колесо — размер инструмента. "
        "Escape отменяет текущий жест."
    ),
    "Pan the map horizontally.": "Переместить карту по горизонтали.",
    "Pan the map vertically.": "Переместить карту по вертикали.",
    "Scroll map settings and editing help.": "Прокрутить настройки карты и подсказки редактора.",
    "Scroll the available choices.": "Прокрутить доступные варианты.",
    "Show tools that do not fit in this panel.": (
        "Показать инструменты, не поместившиеся на панели."
    ),
    "Project file menu.": "Меню файлов проекта.",
    "General": "Общие действия",
    "Tool sets": "Набор инструментов",
    "Show the single-column line and vertex tools beside the map.": (
        "Показать слева от карты инструменты линий и точек одним столбцом."
    ),
    "Show the single-column pixel editing tools beside the map.": (
        "Показать слева от карты пиксельные инструменты одним столбцом."
    ),
    "Lines and vertices": "Линии и точки",
    "Pixels": "Пиксели",
    "Snapping": "Привязка",
    "New line": "Новая линия",
    "Erase lines": "Ластик линий",
    "Erase vertices": "Ластик точек",
    "Close map": "Закрыть карту",
    "Snap": "Привязка",
    "Eraser (screen px)": "Диаметр (экранные px)",
    "Brush (source px)": "Кисть (исходные px)",
    "Distance (screen px)": "Радиус (экранные px)",
    "All regions": "Все области",
    (
        "Closed: connected closed regions in current geometry. "
        "Open: connected groups of unresolved lines. Export bounds include 3 px on every side."
    ): (
        "Замкнутые — связанные замкнутые области текущей геометрии. "
        "Незамкнутые — связанные группы незамкнутых линий. "
        "Габариты экспорта включают запас 3 px с каждой стороны."
    ),
    "Region {number}": "Область {number}",
    "Choose all closed regions or one region to highlight and export.": (
        "Выберите все замкнутые области или одну для подсветки и экспорта."
    ),
    "Map: not loaded | Closed: 0 | Open: 0": "Карта не загружена | Замкнутых: 0 | Незамкнутых: 0",
    "Export: no closed region": "Экспорт: нет замкнутых областей",
    "Export (+3 px): {width} × {height} px | X: {x}, Y: {y}": (
        "Экспорт (+3 px): {width} × {height} px | X: {x}, Y: {y}"
    ),
    "Export: {count} PNGs | Largest crop (+3 px): {width} × {height} px": (
        "Экспорт: {count} PNG | Наибольший PNG (+3 px): {width} × {height} px"
    ),
    "Map: {width} × {height} px | Closed: {closed} | Open: {open}\n{detail}": (
        "Карта: {width} × {height} px | Замкнутых: {closed} | Незамкнутых: {open}\n{detail}"
    ),
    "Cyan: closed regions\nRed: open contours\nAll geometry lines: 2 screen pixels": (
        "Голубой: замкнутые области\nКрасный: незамкнутые контуры\n"
        "Толщина линий: 2 экранных пикселя"
    ),
    (
        "Right-drag: pan in every tool\nWheel: zoom at cursor\n"
        "Ctrl+wheel: active tool size\nAlt-click: free closure corner\n\n"
        "New line: press, drag, release\nEdit points: click line, drag circle\n"
        "Double-click circle: delete\nGeometry erasers: drag the circle\n"
        "Escape: cancel current gesture\n\n"
        "Snap distance uses screen pixels.\nVertices take priority over lines.\n\n"
        "Ctrl+S: save complete project\nPNG: cropped regions + 3 px guard."
    ): (
        "Правая кнопка: перемещение\nКолесо: масштаб у курсора\n"
        "Ctrl + колесо: размер инструмента\nAlt + клик: угол замыкания\n\n"
        "Новая линия: нажать, тянуть, отпустить\nТочки: клик по линии, тянуть кружок\n"
        "Двойной клик: удалить точку\nЛастик геометрии: тяните круг\n"
        "Escape: отменить текущий жест\n\n"
        "Радиус привязки — в экранных пикселях.\nПриоритет у вершин, затем у линий.\n\n"
        "Ctrl+S: сохранить проект\nPNG: отдельные области + 3 px запаса"
    ),
    "Geometry eraser diameter in screen pixels. Ctrl+wheel changes the active tool size.": (
        "Диаметр ластика геометрии в экранных пикселях. Ctrl + колесо меняет размер инструмента."
    ),
    "Snap radius in screen pixels at any zoom. Prefer vertices, then line interiors.": (
        "Радиус привязки в экранных пикселях при любом масштабе. Сначала вершины, затем линии."
    ),
    "Snap the first/last click to a wall; Alt-click adds free corners.": (
        "Первый и последний клик привязываются к стене; Alt + клик добавляет свободный угол."
    ),
    "Press for the first point, drag, release for the second. Snap now or when moving points.": (
        "Нажатие задаёт первую точку, отпускание — вторую. "
        "Привязка работает при создании и переносе."
    ),
    "Erase entire line segments touched by the circle. Drag is one undo step.": (
        "Удалить отрезки, задетые кругом. Всё движение мышью отменяется одним шагом."
    ),
    "Erase vertices inside the circle using the selected junction deletion policy.": (
        "Удалить точки внутри круга с учётом выбранного правила удаления Т-узлов."
    ),
    "Close the current map after offering to save its project.": (
        "Закрыть текущую карту с предложением сохранить проект."
    ),
    "Enable snapping for new lines and moved vertices; vertices take priority.": (
        "Включить привязку новых линий и перемещаемых точек; приоритет у вершин."
    ),
    "Click near a wall within the configured snap distance.": (
        "Щёлкните рядом со стеной в пределах установленного радиуса привязки."
    ),
    (
        "{count} unresolved segments remain. They may be gaps or unused/internal lines.\n"
        "Apply the mask to the closed regions anyway? Choose No to repair with Closure."
    ): (
        "Осталось незамкнутых отрезков: {count}. Это могут быть зазоры или лишние линии.\n"
        "Применить маску к замкнутым областям? Выберите «Нет», чтобы исправить контур."
    ),
    (
        "No enclosed region exists. Use Closure to connect original walls: "
        "click to snap, Alt-click for corners, click to snap the end."
    ): (
        "Нет замкнутых областей. Соедините стены: клик привязывает начало, "
        "Alt + клик добавляет углы, последний клик привязывает конец."
    ),
    "Floor overlay editor": "Редактор этажей",
    "Editing": "Редактирование",
    "History and view": "История и вид",
    ("Switch the interface language. The choice is saved locally."): (
        "Переключить язык интерфейса. Выбор сохраняется на этом компьютере."
    ),
    ("Select the target Foundry generation for placement guidance and metadata."): (
        "Выбрать версию Foundry для подсказок размещения и метаданных."
    ),
    ("Source scene origin in scene pixels. Apply alignment to start a fresh session."): (
        "Начало исходной сцены в её пикселях. Применение смещения начинает новое редактирование."
    ),
    ("Circular brush diameter in original image pixels, independent of zoom."): (
        "Диаметр круглой кисти в исходных пикселях, независимо от масштаба."
    ),
    ("Language changed; preferences could not be written."): (
        "Язык изменён; сохранить настройки на диск не удалось."
    ),
    (
        "Foundry 13: place the PNG as a tile at {height} ft. Floor visibil"
        "ity depends on the scene's module configuration."
    ): (
        "Foundry 13: разместите PNG как тайл на высоте {height} футов. Вид"
        "имость этажей зависит от модулей сцены."
    ),
    (
        "Foundry 14: assign the PNG to the intended Scene Level at {height"
        "} ft and configure its elevation range/visibility."
    ): (
        "Foundry 14: назначьте PNG нужному уровню сцены на высоте {height}"
        " футов и настройте диапазон высот и видимость."
    ),
    (
        "{count} unresolved segments remain (orange). They may be gaps or "
        "unused/internal lines.\nApply the mask to the closed regions anywa"
        "y? Choose No to repair with Closure."
    ): (
        "Осталось незамкнутых отрезков: {count} (оранжевые). Это могут быт"
        "ь зазоры или лишние внутренние линии.\nПрименить маску к замкнутым"
        " областям? Выберите «Нет», чтобы сначала замкнуть контур."
    ),
    ("Click within 14 screen pixels of an original cyan wall."): (
        "Щёлкните рядом с исходной голубой стеной: в пределах 14 экранных пикселей."
    ),
    ("Cancelling after the current decode/stripe…"): (
        "Отмена после текущего декодирования или полосы изображения…"
    ),
    ("Cancelling export. Close the window after export stops."): (
        "Экспорт отменяется. Закройте окно после его остановки."
    ),
    "PNG export cancelled; destination unchanged.": "Экспорт PNG отменён; результат не изменён.",
    "Export ended without a result.": "Экспорт завершился без результата.",
    "Open pair": "Открыть JPG + JSON",
    "Open project": "Открыть проект",
    "Save project": "Сохранить проект",
    "Save project as…": "Сохранить проект как…",
    "Export PNGs": "Экспорт PNG",
    "File": "Файл",
    "Pan": "Перемещение",
    "Closure": "Замкнуть контур",
    "Edit points": "Точки",
    "Erase": "Ластик",
    "Restore": "Восстановление",
    "Remove outside": "Удалить снаружи",
    "Remove inside": "Удалить внутри",
    "Undo": "Отменить",
    "Redo": "Повторить",
    "Fit": "Вся карта",
    "Show walls": "Показать стены",
    "Apply alignment": "Применить смещение",
    "Target": "Версия Foundry",
    "Elevation (ft)": "Высота (футы)",
    "Scene origin X": "Начало сцены X",
    "Scene origin Y": "Начало сцены Y",
    "Join gaps up to (px)": "Соединять зазоры до (px)",
    "Contour offset (px)": "Отступ контура (px)",
    "Junction deletion": "Удаление Т-узла",
    "Keep main wall": "Сохранить основную стену",
    "Remove incident edges": "Удалить смежные отрезки",
    "Language": "Язык",
    "  Brush diameter (px): ": "  Диаметр кисти (px): ",
    ("Open an upper-floor JPG and its Foundry JSON to begin."): (
        "Откройте JPG этажа и соответствующий JSON Foundry."
    ),
    "Ready. All editing is local.": "Готово. Файлы обрабатываются на этом компьютере.",
    (
        "Cyan: source walls\nOrange: unresolved lines\nYellow: local closure"
        "s\nPurple: gap joins\nGreen: offset boundary"
    ): (
        "Голубой: импортированные стены\nОранжевый: незамкнутые линии\nЖёлты"
        "й: добавленные линии\nФиолетовый: соединения зазоров\nЗелёный: гран"
        "ица с отступом"
    ),
    (
        "Right-drag: pan in every tool\nWheel: zoom at cursor\n\nClosure:\nCli"
        "ck: snap start/end\nCtrl/Alt-click: free corner\nEscape: cancel\n\nEd"
        "it points:\nClick line: insert point\nDrag circle: move\nDouble-clic"
        "k circle: delete\nCircles keep their screen size.\n\nErase/Restore: "
        "drag to paint\nBrush size: original pixels\n\nCtrl+S: save complete "
        "project\nPNG: cropped regions + 3 px guard."
    ): (
        "Правая кнопка + движение: перемещение\nКолесо: масштаб у курсора\n\n"
        "Замыкание:\nКлик: привязать начало/конец\nCtrl/Alt + клик: добавить"
        " угол\nEscape: отменить ввод\n\nТочки:\nКлик по линии: добавить точку"
        "\nТянуть кружок: переместить\nДвойной клик: удалить точку\nРазмер кр"
        "ужков не зависит от масштаба.\n\nЛастик/восстановление: рисуйте мыш"
        "ью\nРазмер кисти — в исходных пикселях\n\nCtrl+S: сохранить весь про"
        "ект\nPNG: отдельные контуры + 3 px запаса"
    ),
    ("Load a source JPG and matching wall JSON."): (
        "Загрузить исходную карту JPG и JSON с разметкой стен."
    ),
    ("Open a portable .dale archive including sources and undo history."): (
        "Открыть архив .dale с исходниками и историей изменений."
    ),
    ("Save sources, masks, geometry, preferences, and undo/redo in one .dale file."): (
        "Сохранить исходники, маски, линии, настройки и Undo/Redo в один файл .dale."
    ),
    ("Export separate cropped PNGs with a 3 px guard and a placement manifest."): (
        "Экспортировать отдельные PNG по контурам с запасом 3 px и файлом координат."
    ),
    ("Drag to move the map. Right-drag works in every tool."): (
        "Перемещайте карту мышью. Правая кнопка работает во всех инструментах."
    ),
    ("Snap the first/last click to a wall; Ctrl/Alt-click adds free corners."): (
        "Первый и последний клик привязываются к стене; Ctrl/Alt + клик добавляет свободный угол."
    ),
    "Click a line to insert; drag a fixed-size circle to move; double-click it to delete.": (
        "Клик по линии добавляет точку; тяните кружок для перемещения, два"
        "жды щёлкните для удаления."
    ),
    "Paint transparency over unwanted objects.": "Закрасить ненужные объекты прозрачностью.",
    "Restore opacity from the original JPG.": "Восстановить непрозрачность исходного JPG.",
    ("Keep enclosed regions and make their exterior transparent."): (
        "Оставить замкнутые области, сделать остальное прозрачным."
    ),
    ("Erase enclosed regions and keep their exterior."): (
        "Удалить замкнутые области, оставить остальное."
    ),
    ("Undo the last complete stroke, mask, or geometry edit."): (
        "Отменить последний мазок, маску или изменение линий."
    ),
    "Redo the last undone edit.": "Повторить отменённое изменение.",
    "Show the complete source map.": "Показать всю исходную карту.",
    "Show or hide wall and contour overlays.": "Показать или скрыть разметку стен и контуров.",
    ("Apply source-scene origin offsets. Existing edits require save/discard."): (
        "Применить смещение начала сцены. Текущую работу можно предварительно сохранить."
    ),
    ("Presets every 5 ft; type any whole number of feet, including negatives."): (
        "Готовые высоты через 5 футов. Можно ввести целое число, включая отрицательное."
    ),
    ("Connect free wall ends within this distance in original image pixels. 0 disables joining."): (
        "Соединять свободные концы стен в пределах указанного расстояния в"
        " исходных пикселях. 0 — выключено."
    ),
    ("Original image pixels: positive expands the contour, negative shrinks it."): (
        "В исходных пикселях: положительное значение расширяет контур, отрицательное сужает."
    ),
    (
        "Deleting a junction can preserve the straightest wall continuatio"
        "n, or remove all incident wall edges. Undo is available."
    ): (
        "При удалении Т-узла можно сохранить наиболее прямое продолжение с"
        "тены или убрать все смежные отрезки. Доступна отмена."
    ),
    "Enter a whole-number elevation in feet.": "Введите высоту в футах целым числом.",
    "Elevation must be a whole number of feet.": "Высота должна быть целым числом футов.",
    ("Placement in Foundry is configured separately. PNG edge guard: 3 px."): (
        "Высота размещения настраивается в Foundry. Запас у края PNG: 3 px."
    ),
    ("Contour preview updated. Apply Remove outside/inside to use these settings."): (
        "Предпросмотр контура обновлён. Примените «Удалить снаружи/внутри», чтобы изменить маску."
    ),
    (
        "Closed faces: {faces}\nUnresolved segments: {unresolved}\nGap joins"
        ": {joins}\nEditing operations: {operations}"
    ): (
        "Замкнутых областей: {faces}\nНезамкнутых отрезков: {unresolved}\nСо"
        "единений зазоров: {joins}\nИзменений: {operations}"
    ),
    "Save changes?": "Сохранить изменения?",
    ("Save the project and editing history before continuing?"): (
        "Сохранить проект и историю изменений перед продолжением?"
    ),
    "Save DALE project": "Сохранить проект DALE",
    "Open DALE project": "Открыть проект DALE",
    "DALE projects (*.dale)": "Проекты DALE (*.dale)",
    "Open source JPG": "Открыть исходный JPG",
    "Open matching Foundry JSON": "Открыть соответствующий JSON Foundry",
    "JPEG images (*.jpg *.jpeg)": "Изображения JPEG (*.jpg *.jpeg)",
    "JSON files (*.json)": "Файлы JSON (*.json)",
    "Cannot open source pair": "Не удалось открыть исходники",
    "Cannot save project": "Не удалось сохранить проект",
    "Cannot open project": "Не удалось открыть проект",
    "Saved complete project: {path}": "Проект сохранён: {path}",
    "Finish editing": "Завершите редактирование",
    "Finish the active drag before saving.": "Завершите перетаскивание перед сохранением.",
    "Finish closure": "Завершите контур",
    ("Finish the closure or cancel it with Escape."): (
        "Завершите линию или отмените её клавишей Escape."
    ),
    "Close a boundary first": "Сначала замкните контур",
    (
        "No enclosed region exists. Use Closure to connect original walls:"
        " click to snap, Ctrl/Alt-click for corners, click to snap the end"
        "."
    ): (
        "Нет замкнутых областей. Соедините стены инструментом замыкания: к"
        "лик привязывает начало, Ctrl/Alt + клик добавляет углы, последний"
        " клик привязывает конец."
    ),
    "Review open contours": "Проверьте незамкнутые контуры",
    "Review contour offset": "Проверьте отступ контура",
    ("No enclosed area remains. Reduce the inward offset or close a boundary."): (
        "Замкнутая область исчезла. Уменьшите отступ внутрь или замкните контур."
    ),
    ("Finish or cancel the active stroke/closure first."): (
        "Сначала завершите или отмените текущую линию или мазок."
    ),
    "Invalid elevation": "Некорректная высота",
    "Export separate PNGs with 3 px edge guard": "Экспорт отдельных PNG с запасом 3 px",
    "Exporting separate PNGs with 3 px edge guard…": "Экспорт отдельных PNG с запасом 3 px…",
    "Export failed": "Ошибка экспорта",
    "Exported {path}": "Экспортировано: {path}",
    "Cancel": "Отмена",
    "Save": "Сохранить",
    "Discard": "Не сохранять",
    "Yes": "Да",
    "No": "Нет",
    "&Save": "&Сохранить",
    "&Cancel": "&Отмена",
    "&Discard": "&Не сохранять",
    "&Yes": "&Да",
    "&No": "&Нет",
}


def translate(text: str, language: str, **values) -> str:
    result = RUSSIAN.get(text, text) if language == "ru" else text
    return result.format(**values) if values else result


class DesktopTranslator(QTranslator):
    language = "ru"

    def isEmpty(self):
        return False

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        return RUSSIAN.get(sourceText, "") if self.language == "ru" else ""


def prepare_control_tooltips(root):
    """Give embedded editors, scrollbars, and toolbar overflow buttons localized source help."""
    for control in root.findChildren(QWidget):
        if (
            not isinstance(
                control, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QScrollBar)
            )
            or control.toolTip()
        ):
            continue
        if isinstance(control, QScrollBar):
            control.setToolTip("Scroll the available choices.")
            continue
        if isinstance(control, QToolButton) and control.defaultAction() is None:
            control.setToolTip("Show tools that do not fit in this panel.")
            continue
        parent = control.parentWidget()
        while parent is not None:
            original = parent.property("dale_original_tooltip") or parent.toolTip()
            if original:
                control.setToolTip(original)
                break
            parent = parent.parentWidget()


def translate_static(root: QWidget, language: str, excluded=()):
    for widget in [root, *root.findChildren(QWidget), *root.findChildren(QAction)]:
        if widget in excluded:
            continue
        if isinstance(widget, QAction) and widget.menu() is not None:
            continue
        if isinstance(widget, (QMenu, QToolBar)):
            original = widget.property("dale_original_title")
            if original is None:
                original = widget.title() if isinstance(widget, QMenu) else widget.windowTitle()
                widget.setProperty("dale_original_title", original)
            if isinstance(widget, QMenu):
                widget.setTitle(translate(original, language))
            else:
                widget.setWindowTitle(translate(original, language))
        if isinstance(widget, (QLabel, QAbstractButton, QAction)):
            original = widget.property("dale_original_text")
            if original is None:
                original = widget.text()
                widget.setProperty("dale_original_text", original)
            widget.setText(translate(original, language))
        if isinstance(widget, QComboBox) and not widget.isEditable():
            original = widget.property("dale_original_items")
            if original is None:
                original = [widget.itemText(i) for i in range(widget.count())]
                widget.setProperty("dale_original_items", original)
            for i, text in enumerate(original):
                widget.setItemText(i, translate(text, language))
        parts = widget.property("dale_tooltip_parts")
        if isinstance(widget, QToolButton) and widget.defaultAction() is not None:
            parts = parts or widget.defaultAction().property("dale_tooltip_parts")
        if parts:
            widget.setToolTip("\n".join(translate(part, language) for part in parts))
            continue
        original = widget.property("dale_original_tooltip")
        if original is None:
            original = widget.toolTip()
            widget.setProperty("dale_original_tooltip", original)
        if original:
            widget.setToolTip(translate(original, language))
