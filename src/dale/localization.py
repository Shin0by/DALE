"""English source strings and Russian desktop translations."""

from PySide6.QtCore import QTranslator
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollBar,
    QToolBar,
    QToolButton,
    QWidget,
)

RUSSIAN = {
    "Import wall JSON": "Импорт JSON стен",
    "JSON or DALE projects (*.json *.dale)": "JSON или проекты DALE (*.json *.dale)",
    "JSON files in DALE project": "Файлы JSON в проекте DALE",
    "Choose wall JSON to use with the current JPG.": "Выберите JSON стен для текущего JPG.",
    "Select the original or an updated JSON stored in this project.": (
        "Выберите исходный или обновлённый JSON, сохранённый в этом проекте."
    ),
    "Original JSON": "Исходный JSON",
    "Updated JSON": "Обновлённый JSON",
    "Import": "Импортировать",
    "Import the selected JSON for the current JPG.": "Применить выбранный JSON к текущему JPG.",
    "Cannot import JSON": "Не удалось импортировать JSON",
    (
        "Load another wall JSON for the current JPG. "
        "Save existing edits before replacing the source pair."
    ): (
        "Загрузить другой JSON стен для текущего JPG. "
        "Перед заменой исходной пары сохраните изменения."
    ),
    "Open a source JPG before loading another JSON.": (
        "Сначала откройте исходный JPG, затем можно загрузить другой JSON."
    ),
    "Unsupported DALE project format or version. Older projects are not supported.": (
        "Неподдерживаемый формат или версия проекта DALE. Старые проекты не поддерживаются."
    ),
    "Move regions": "Перемещение областей",
    "Move all connected lines?": "Перемещать все связанные линии?",
    "Remember choice": "Запомнить выбор",
    (
        "Remember this choice between launches. Right-click the tool to change it."
    ): "Запомнить выбор между запусками. Правый клик по инструменту открывает этот вопрос снова.",
    (
        "Yes includes lines connected within the snapping distance. "
        "No moves only selected boundaries. Right-click this tool to reopen this dialog."
    ): (
        "«Да» включает связанные линии в пределах допуска прилипания. "
        "«Нет» перемещает только выбранные контуры. "
        "Правый клик по кнопке инструмента снова открывает это окно."
    ),
    "Move selected boundaries and related lines.": (
        "Перемещать выбранные контуры и связанные линии."
    ),
    "Move only selected region boundaries.": "Перемещать только контуры выбранных областей.",
    "Preferences could not be written.": "Не удалось сохранить настройки.",
    "PNG: none (selection outside the source map)": (
        "PNG: нет (выделение за пределами исходной карты)"
    ),
    (
        "Drag selected region contours. Ctrl+wheel: scale. Alt+wheel: rotate by 0.1 degrees "
        "around their common center. Raster pixels stay unchanged. "
        "Right-click: configure connected lines. Escape: cancel the current gesture."
    ): (
        "Тяните выбранные контуры для перемещения. Ctrl+колесо: масштабирование. "
        "Alt+колесо: вращение с шагом 0,1° вокруг общего центра. Растр остаётся на месте. "
        "Правый клик: настройка связанных линий. Escape: отменить текущий жест."
    ),
    ("Information"): ("Информация"),
    ("Settings"): ("Настройки"),
    ("Close all contours"): ("Замкнуть всю карту"),
    ("Whole-map close distance (px)"): ("Допуск замыкания всей карты (px)"),
    (
        "Extend eligible lines across the whole map after confirmation. Distanc"
        "e uses screen pixels."
    ): (
        "Продлить подходящие линии по всей карте до пересечений после подтвержд"
        "ения «Отмена / Да». Допуск измеряется в экранных пикселях."
    ),
    ("Map: {width} × {height} px\n{detail}\nClosed: {closed} | Open: {open}"): (
        "Карта: {width} × {height} px\n{detail}\nЗамкнутых: {closed} | Незамкнутых: {open}"
    ),
    ("Map: not loaded\nClosed: 0 | Open: 0"): ("Карта не загружена\nЗамкнутых: 0 | Незамкнутых: 0"),
    ("Selectable cells: {cells}\nEditing operations: {operations}"): (
        "Областей для выбора: {cells}\nИзменений: {operations}"
    ),
    ("Contours"): ("Контуры"),
    ("Regions"): ("Области"),
    ("Raster"): ("Растр"),
    ("Edit lines, vertices, auto-close, and snapping."): (
        "Редактирование линий, точек, автозамыкания и прилипания."
    ),
    ("Select closed regions and export their PNGs."): (
        "Выбор замкнутых областей и экспорт их PNG."
    ),
    ("Erase or restore image pixels."): ("Стирание и восстановление пикселей изображения."),
    ("Select regions"): ("Выбор областей"),
    ("Click closed regions to toggle selection. Click empty space to clear selection."): (
        "Клик выбирает минимальную замкнутую область под курсором или снимает е"
        "ё выделение. Клик по пустому месту очищает выбор."
    ),
    ("Export selected regions"): ("Экспорт выбранных"),
    ("Export only the highlighted regions as separate PNGs."): (
        "Экспортировать только выделенные области отдельными PNG."
    ),
    ("Export padding (px)"): ("Дополнительный отступ PNG (px)"),
    ("Additional transparent pixels around each region box, beyond the mandatory 3 px guard."): (
        "Дополнительные прозрачные пиксели вокруг прямоугольника каждой области"
        " сверх обязательного запаса 3 px. Отступ обрезается границами исходног"
        "о JPG."
    ),
    (
        "Distance to existing vertices or lines. Vertices take priority. Click "
        "the icon to toggle snapping."
    ): (
        "Расстояние прилипания к вершинам и линиям. Вершины в приоритете. Нажат"
        "ие на значок включает или выключает прилипание."
    ),
    (
        "Click a line to insert; drag a fixed-size circle to move; double-click"
        " it to delete. Hold Alt to move along the selected line vector."
    ): (
        "Клик по линии добавляет точку; тяните кружок для перемещения, дважды щ"
        "ёлкните для удаления. Зажмите Alt, чтобы двигать точку только по векто"
        "ру выбранного отрезка. Отпустите Alt для свободного движения. Escape о"
        "тменяет жест."
    ),
    (
        "Hover to trace connected lines and valid continuations. White edges sh"
        "ow affected lines; dashed lines preview extensions. Click to extend ex"
        "isting lines along their directions after confirmation in one undo ste"
        "p."
    ): (
        "Наведите курсор, чтобы проследить связанные линии и допустимые продолж"
        "ения. Белый кант показывает затрагиваемые линии, пунктир — продолжения"
        ". Клик открывает подтверждение «Отмена / Да». Продление выполняется од"
        "ним шагом отмены."
    ),
    ("Confirm auto-close"): ("Подтвердить автозамыкание"),
    (
        "Affected segments: {segments}\nEndpoint extensions: {extensions}\nShared"
        " intersections: {connections}\n\nConnect the highlighted lines?"
    ): (
        "Выбрано отрезков: {segments}\nПродлений концов: {extensions}\nОбщих пере"
        "сечений: {connections}\n\nСоединить выделенные линии?"
    ),
    (
        "No changes are needed or possible at this distance. Touching lines are"
        " already connected; remaining gaps need a larger distance or New line."
    ): (
        "При этом допуске нет необходимых или доступных изменений. Касающиеся л"
        "инии уже соединены; для оставшихся зазоров увеличьте дальность или исп"
        "ользуйте «Новую линию»."
    ),
    ("No lines under the cursor. Point at a line and click again."): (
        "Под курсором нет линий. Наведите его на линию и нажмите снова."
    ),
    ("Cancel without changing geometry. Escape: cancel."): (
        "Отменить без изменения линий. Escape: отмена."
    ),
    ("Apply the shown connections as one undo step."): (
        "Применить показанные соединения одним шагом отмены."
    ),
    ("Select at least one closed region on the map."): (
        "Выберите хотя бы одну замкнутую область на карте."
    ),
    ("Selected: {count}"): ("Выбрано: {count}"),
    ("PNG: {width} × {height} (+{margin} px)"): ("PNG: {width} × {height} (+{margin} px)"),
    ("PNG: {count} · max {width} × {height} (+{margin} px)"): (
        "PNG: {count} · макс. {width} × {height} (+{margin} px)"
    ),
    ("The selected region lies outside the source image."): (
        "Выбранная область находится вне исходного изображения."
    ),
    "Auto-close": "Автозамыкание",
    "Auto-close distance (px)": "Дальность автоприлипания (px)",
    "Ctrl+wheel: change the auto-close distance.": (
        "Ctrl + колесо: изменить дальность автоприлипания."
    ),
    "Independent distance in screen pixels; ordinary snapping is unchanged.": (
        "Собственная дальность в экранных пикселях; обычное прилипание настраивается отдельно."
    ),
    (
        "Hover to trace connected lines and valid continuations. White edges show affected lines; "
        "dashed lines preview extensions. Click to extend existing lines "
        "along their directions in one undo step."
    ): (
        "Наведите курсор, чтобы проследить связанные линии и допустимые продолжения. "
        "Белый кант показывает затрагиваемые линии, пунктир — будущие продолжения. "
        "Клик удлиняет существующие линии по их направлениям до пересечения одним шагом отмены."
    ),
    "No eligible gaps here. Increase the auto-close distance or draw a new line.": (
        "Здесь нет подходящих зазоров. Увеличьте дальность автоприлипания "
        "или нарисуйте новую линию."
    ),
    "Finish or cancel the active gesture first.": "Завершите текущий жест или отмените его.",
    "No enclosed region exists. Use Auto-close for nearby gaps or New line to draw a boundary.": (
        "Нет замкнутых областей. Используйте «Автозамыкание» для близких зазоров "
        "или «Новую линию» для построения контура."
    ),
    (
        "{count} unresolved segments remain. They may be gaps or unused/internal lines.\n"
        "Apply the mask to the closed regions anyway? "
        "Choose No to repair with Auto-close or New line."
    ): (
        "Осталось незамкнутых отрезков: {count}. Это могут быть зазоры или лишние линии.\n"
        "Применить маску к замкнутым областям? Выберите «Нет», чтобы исправить контур "
        "инструментами «Автозамыкание» или «Новая линия»."
    ),
    "Shortcut: {keys}": "Горячие клавиши: {keys}",
    "Escape: cancel the current gesture.": "Escape: отменить текущий жест.",
    "Ctrl+wheel: change this value.": "Ctrl + колесо: изменить это значение.",
    "Ctrl+wheel: change this tool's diameter.": "Ctrl + колесо: диаметр этого инструмента.",
    "Snapping (px)": "Прилипание (px)",
    "Geometry eraser diameter (px)": "Диаметр ластика линий и точек (px)",
    "Line eraser diameter (px)": "Диаметр ластика линий (px)",
    "Vertex eraser diameter (px)": "Диаметр ластика точек (px)",
    "This tool keeps its own diameter in screen pixels.": (
        "Этот инструмент хранит собственный диаметр в экранных пикселях."
    ),
    "Pixel eraser diameter (px)": "Диаметр пиксельного ластика (px)",
    "Restore brush diameter (px)": "Диаметр кисти восстановления (px)",
    "Diameter for line and vertex erasers. Ctrl+wheel changes it, independent of map zoom.": (
        "Диаметр ластика линий и точек. Ctrl + колесо меняет его независимо от масштаба карты."
    ),
    "Diameter in original image pixels. Ctrl+wheel changes it.": (
        "Диаметр в пикселях исходной карты. Ctrl + колесо меняет его."
    ),
    (
        "Distance to existing vertices or lines. Vertices take priority. "
        "Click the magnet to toggle snapping."
    ): (
        "Расстояние прилипания к вершинам и линиям. Вершины в приоритете. "
        "Нажатие на магнит включает или выключает прилипание."
    ),
    "Decrease by 1 px.": "Уменьшить на 1 px.",
    "Increase by 1 px.": "Увеличить на 1 px.",
    "Select the target Foundry generation. The choice is saved between launches.": (
        "Выберите версию Foundry. Выбор запоминается между запусками."
    ),
    "Foundry version changed; preferences could not be written.": (
        "Версия Foundry изменена, но сохранить настройки не удалось."
    ),
    "PNG: none": "PNG: нет",
    "PNG: {width} × {height} (+3 px)": "PNG: {width} × {height} (+3 px)",
    "PNG: {count} · max {width} × {height} (+3 px)": (
        "PNG: {count} · макс. {width} × {height} (+3 px)"
    ),
    "Map: {width} × {height} | {detail} | Closed: {closed} | Open: {open}": (
        "Карта: {width} × {height} | {detail} | Замкнутых: {closed} | Незамкнутых: {open}"
    ),
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
        "Настройте прилипание к существующим вершинам и отрезкам линий."
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
    "Snapping": "Прилипание",
    "New line": "Новая линия",
    "Erase lines": "Ластик линий",
    "Erase vertices": "Ластик точек",
    "Close map": "Закрыть карту",
    "Snap": "Прилипание",
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
    "Cyan: closed regions\nRed: open contours (RGB 255, 0, 0)\nLines: 3 px with black edges": (
        "Голубой: замкнутые области\nКрасный: незамкнутые контуры (RGB 255, 0, 0)\n"
        "Линии: 3 px с чёрными краями"
    ),
    (
        "Right-drag: pan in every tool\nWheel: zoom at cursor\n"
        "Ctrl+wheel: active tool size\n\n"
        "Auto-close: hover to trace, click to extend\nWhite edges: affected lines\n"
        "New line: press, drag, release\nEdit points: click line, drag circle\n"
        "Double-click circle: delete\nGeometry erasers: drag the circle\n"
        "Escape: cancel current gesture\n\n"
        "Snapping (px): distance to existing geometry.\nVertices take priority over lines.\n\n"
        "Ctrl+S: save complete project\nPNG: cropped regions + 3 px guard."
    ): (
        "Правая кнопка: перемещение\nКолесо: масштаб у курсора\n"
        "Ctrl + колесо: размер инструмента\n\n"
        "Автозамыкание: навести, кликнуть для продления\nБелый кант: затрагиваемые линии\n"
        "Новая линия: нажать, тянуть, отпустить\nТочки: клик по линии, тянуть кружок\n"
        "Двойной клик: удалить точку\nЛастик геометрии: тяните круг\n"
        "Escape: отменить текущий жест\n\n"
        "Прилипание (px) — расстояние до разметки.\nПриоритет у вершин, затем у линий.\n\n"
        "Ctrl+S: сохранить проект\nPNG: отдельные области + 3 px запаса"
    ),
    "Geometry eraser diameter in screen pixels. Ctrl+wheel changes the active tool size.": (
        "Диаметр ластика геометрии в экранных пикселях. Ctrl + колесо меняет размер инструмента."
    ),
    "Snap radius in screen pixels at any zoom. Prefer vertices, then line interiors.": (
        "Радиус прилипания в экранных пикселях при любом масштабе. Сначала вершины, затем линии."
    ),
    "Press for the first point, drag, release for the second. Snap now or when moving points.": (
        "Нажатие задаёт первую точку, отпускание — вторую. "
        "Прилипание работает при создании и переносе."
    ),
    "Erase entire line segments touched by the circle. Drag is one undo step.": (
        "Удалить отрезки, задетые кругом. Всё движение мышью отменяется одним шагом."
    ),
    (
        "Erase vertices inside the circle; reconnect ordinary line neighbors. "
        "Branching vertices remove their connected edges."
    ): (
        "Удалить точки в круге; соседи обычной точки линии соединяются. "
        "При удалении точки разветвления удаляются её смежные отрезки."
    ),
    "Close the current map after offering to save its project.": (
        "Закрыть текущую карту с предложением сохранить проект."
    ),
    "Enable snapping for new lines and moved vertices; vertices take priority.": (
        "Включить прилипание новых линий и перемещаемых точек; приоритет у вершин."
    ),
    "Click near a wall within the configured snap distance.": (
        "Щёлкните рядом со стеной в пределах установленного радиуса прилипания."
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
    "Close a boundary first": "Сначала замкните контур",
    "Review open contours": "Проверьте незамкнутые контуры",
    "Review contour offset": "Проверьте отступ контура",
    ("No enclosed area remains. Reduce the inward offset or close a boundary."): (
        "Замкнутая область исчезла. Уменьшите отступ внутрь или замкните контур."
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
        if isinstance(widget, (QMenu, QToolBar, QGroupBox)):
            original = widget.property("dale_original_title")
            if original is None:
                original = (
                    widget.title()
                    if isinstance(widget, (QMenu, QGroupBox))
                    else widget.windowTitle()
                )
                widget.setProperty("dale_original_title", original)
            if isinstance(widget, (QMenu, QGroupBox)):
                widget.setTitle(translate(original, language))
            else:
                widget.setWindowTitle(translate(original, language))
        if isinstance(widget, (QLabel, QAbstractButton, QAction)) and not (
            isinstance(widget, QToolButton) and widget.defaultAction() is not None
        ):
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
        action = widget if isinstance(widget, QAction) else None
        if isinstance(widget, QToolButton):
            action = widget.defaultAction()
            if action is not None:
                parts = parts or action.property("dale_tooltip_parts")
        if parts:
            tooltip = "\n".join(translate(part, language) for part in parts)
        else:
            original = widget.property("dale_original_tooltip")
            if original is None:
                original = widget.toolTip()
                widget.setProperty("dale_original_tooltip", original)
            tooltip = translate(original, language) if original else ""
        if action is not None and not action.shortcut().isEmpty():
            keys = action.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
            tooltip += "\n" + translate("Shortcut: {keys}", language, keys=keys)
        if tooltip:
            widget.setToolTip(tooltip)
