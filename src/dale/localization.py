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
    "Sections": "Разделы",
    "Scene": "Сцена",
    "Main": "Основное",
    "Levels": "Уровни",
    "Open scene-level sections.": "Открыть разделы работы со сценой.",
    "Common navigation, selection, visibility, and settings controls.": (
        "Общие действия: перемещение, выделение, видимость контуров и настройки."
    ),
    "Open the scene levels panel.": "Открыть панель уровней сцены.",
    "Show or hide the application settings panel.": (
        "Показать или скрыть панель настроек приложения."
    ),
    "Recent projects": "Последние проекты",
    "No recent projects": "Нет последних проектов",
    "Clear recent projects": "Очистить список проектов",
    "Open a recently opened or saved DALE project.": "Открыть недавний проект DALE.",
    "Open this recent DALE project.": "Открыть этот недавний проект DALE.",
    "Project file is unavailable.": "Файл проекта недоступен.",
    "Clear the list without deleting project files.": (
        "Очистить список без удаления файлов проектов."
    ),
    "PNG: calculating exact bounds…": "PNG: расчёт точных границ…",
    "PNG: bounds unavailable": "PNG: границы недоступны",
    ("Scene padding is nonzero. Verify contour alignment before editing."): (
        "У сцены есть отступ. Проверьте совмещение контуров перед редактированием."
    ),
    ("No contour segments found in the scene JSON. Draw contours or edit raster pixels."): (
        "В JSON сцены нет линий контуров. Нарисуйте контуры или редактируйте растр."
    ),
    ("Scene dimensions absent: using scene image dimensions; verify alignment."): (
        "В JSON нет размеров сцены: используются размеры изображения сцены. Проверьте совмещение."
    ),
    ("Scene levels detected. Only the scene-level contour collection is imported."): (
        "В сцене есть уровни. Импортируется только набор контуров самой сцены."
    ),
    ("Above 8,192 pixels: check the texture limit of every Foundry client."): (
        "Изображение больше 8192 px: проверьте предел размера текстур на каждом клиенте Foundry."
    ),
    "File information": "Данные файла",
    "Export regions as PNGs": "Экспорт областей в PNG",
    "Open, save, export regions, close, and exit.": (
        "Открытие, сохранение, экспорт областей, закрытие и выход."
    ),
    "Undo, redo, and clear selection.": "Отмена, повтор и снятие выделения.",
    "Application name, version, and purpose.": "Название, версия и назначение программы.",
    "Application menus.": "Меню приложения.",
    "Edit": "Правка",
    "About": "О программе",
    "About DALE": "О программе DALE",
    "About DALE…": "О программе DALE…",
    "Exit": "Выход",
    "Close this dialog. Escape: close.": "Закрыть это окно. Escape: закрыть.",
    "Close the application after offering to save the current project.": (
        "Выйти из программы с предложением сохранить текущий проект."
    ),
    "Show the application name, version, and purpose.": (
        "Показать название, версию и назначение программы."
    ),
    (
        "Prepare transparent floor maps from Dungeon Alchemist scene images and Foundry scene JSON."
    ): (
        "Подготовка прозрачных карт этажей из изображения сцены Dungeon "
        "Alchemist и JSON сцены Foundry."
    ),
    "New circle": "Новый круглый контур",
    "New circular contour": "Новый круглый контур",
    ("Press: set center. Drag: change radius. Release: create circular contour."): (
        "Нажатие: центр. Перетаскивание: радиус. Отпускание: создать круглый контур."
    ),
    "Ctrl+wheel while drawing: adjust the radius.": "Ctrl+колесо при рисовании: изменить радиус.",
    (
        "Press to set the center, drag to change the radius, release to "
        "create a circular contour. Diameters up to 0.5 cells use 4 "
        "vertices, up to 1 use 6, up to 2 use 8; larger circles use more. "
        "Ctrl+wheel while drawing: adjust the radius."
    ): (
        "Нажмите для задания центра, тяните для изменения радиуса, "
        "отпустите для создания круглого контура. До 0,5 клетки — 4 "
        "вершины, до 1 — 6, до 2 — 8; дальше число вершин растёт. "
        "Ctrl+колесо при рисовании: изменить радиус."
    ),
    ("Circle center and radius must be finite and within coordinate limits."): (
        "Центр и радиус круга должны быть конечными числами в допустимом диапазоне координат."
    ),
    "Window shortcuts": "Общие горячие клавиши",
    "Scroll the available shortcuts for the current tool and window.": (
        "Прокрутить доступные горячие клавиши текущего инструмента и окна."
    ),
    "Project": "Проект",
    "Left-drag: pan the scene image.": "Левая кнопка с перетаскиванием: перемещение сцены.",
    "Right-drag: pan the scene image.": "Правая кнопка с перетаскиванием: перемещение сцены.",
    "Wheel: zoom at cursor.": "Колесо: масштаб сцены у курсора.",
    "Click a line: insert a contour point. Drag a circle: move it.": (
        "Клик по линии: добавить точку контура. Тяните кружок для перемещения."
    ),
    ("Double-click a circle: delete the point. Alt-drag: follow the line vector."): (
        "Двойной клик по кружку: удалить точку. Alt при перетаскивании: вдоль линии."
    ),
    "Press, drag, release: draw a contour line.": "Нажать, тянуть, отпустить: новая линия контура.",
    "Hover: preview contour connections. Click: review and apply.": (
        "Наведение: предпросмотр замыкания контуров. Клик: подтверждение и применение."
    ),
    "Drag the circle: erase highlighted contour lines.": (
        "Тяните круг: стереть подсвеченные линии контура."
    ),
    "Drag the circle: erase highlighted contour points.": (
        "Тяните круг: стереть подсвеченные точки контура."
    ),
    "Click a region: select/deselect. Empty click: clear selection.": (
        "Клик по области: выбрать/снять выбор. Клик по пустому месту: снять выделение."
    ),
    "Drag selected regions: move. Ctrl+wheel: scale.": (
        "Тяните выбранные области для перемещения. Ctrl+колесо: масштабирование."
    ),
    "Right-click the tool button: configure connected lines.": (
        "Правый клик по кнопке инструмента: настройка связанных линий."
    ),
    (
        "Wheel: rotate selected regions by 0.1 degrees around their common center."
    ): "Колесо: вращение выбранных областей на 0,1° вокруг общего центра.",
    "Drag: erase raster pixels.": "Тяните мышь: стирание пикселей растра.",
    "Drag: restore raster pixels.": "Тяните мышь: восстановление пикселей растра.",
    "Store settings globally": "Хранить настройки глобально",
    "Otherwise, tool values are stored in the project file.": (
        "Иначе значения инструментов хранятся в файле проекта."
    ),
    (
        "Store all numeric tool values globally. Enabling copies current "
        "values; opening a project keeps global values. Disable to "
        "restore this project's values. Otherwise values are stored in "
        "the project file."
    ): (
        "Хранить все числовые значения инструментов в общем конфиге. "
        "Включение копирует текущие значения; открытие проекта их не "
        "заменяет. Снимите галочку, чтобы восстановить значения этого "
        "проекта. Иначе настройки хранятся в файле проекта."
    ),
    "Clear selection": "Снять выделение",
    (
        "Clear selected regions and contour highlights. Cancel the "
        "current gesture without changing saved geometry or raster."
    ): (
        "Снять выделение областей и подсветку контуров. Отменить текущий "
        "жест без изменения сохранённой геометрии и растра."
    ),
    "Tool values changed; preferences could not be written.": (
        "Значения инструментов изменены, но сохранить настройки не удалось."
    ),
    "Export regions": "Экспорт областей",
    "Auto-close contours": "Автозамыкание контуров",
    "Edit contour points": "Точки контура",
    "New contour line": "Новая линия контура",
    "Erase contour lines": "Ластик линий контура",
    "Erase contour points": "Ластик точек контура",
    "Contour snapping (px)": "Прилипание контура (px)",
    "Region artwork offset (px)": "Отступ изображения областей (px)",
    "Erase raster pixels": "Ластик растра",
    "Restore raster pixels": "Восстановление растра",
    "Erase raster outside contours": "Стереть растр вне контуров",
    "Erase raster inside contours": "Стереть растр внутри контуров",
    "Contour line eraser diameter (px)": "Диаметр ластика линий контура (px)",
    "Contour point eraser diameter (px)": "Диаметр ластика точек контура (px)",
    "Contour auto-close distance (px)": "Допуск автозамыкания контуров (px)",
    "Scene JSON or DALE projects (*.json *.dale)": "JSON сцены или проекты DALE (*.json *.dale)",
    "Scene JSON documents in DALE project": "Документы JSON сцены в проекте DALE",
    "Choose a scene JSON for the current scene image.": (
        "Выберите JSON сцены для текущего изображения сцены."
    ),
    (
        "Select an original or updated scene JSON stored in this DALE project."
    ): "Выберите исходный или обновлённый JSON сцены из проекта DALE.",
    "Original scene JSON": "Исходный JSON сцены",
    "Updated scene JSON": "Обновлённый JSON сцены",
    "Import": "Импортировать",
    "Load the selected scene JSON for the current scene image.": (
        "Загрузить выбранный JSON сцены для текущего изображения сцены."
    ),
    "Cannot load scene JSON": "Не удалось загрузить JSON сцены",
    "Load a scene JSON. Current edits can be saved before importing.": (
        "Загрузить JSON сцены. Перед импортом можно сохранить текущие изменения."
    ),
    "Open a scene image before loading a scene JSON.": (
        "Сначала откройте изображение сцены, затем загрузите JSON сцены."
    ),
    ("Unsupported DALE project format or version. Older projects are not supported."): (
        "Неподдерживаемый формат или версия проекта DALE. Старые проекты не поддерживаются."
    ),
    "Move regions": "Перемещение областей",
    "Rotate regions": "Вращение областей",
    "Rotate all connected lines?": "Вращать все связанные линии?",
    (
        "Show all contours or hide inactive geometry. Selected regions "
        "and highlighted lines remain visible."
    ): (
        "Показать все контуры или скрыть неактивную разметку. Выбранные "
        "области и подсвеченные линии остаются видимыми."
    ),
    "Move all connected lines?": "Перемещать все связанные линии?",
    "Remember choice": "Запомнить выбор",
    ("Remember this choice between launches. Right-click the tool to change it."): (
        "Запомнить выбор между запусками. Правый клик по инструменту открывает этот вопрос снова."
    ),
    (
        "Yes includes lines connected within the snapping distance. No "
        "affects only selected boundaries. Right-click this tool to "
        "reopen this dialog."
    ): (
        "«Да» включает связанные линии в пределах допуска прилипания. "
        "«Нет» меняет только выбранные контуры. Правый клик по кнопке "
        "инструмента снова открывает это окно."
    ),
    "Transform selected boundaries and related lines.": (
        "Изменять выбранные контуры и связанные линии."
    ),
    "Transform only selected region boundaries.": "Изменять только контуры выбранных областей.",
    "Preferences could not be written.": "Не удалось сохранить настройки.",
    "PNG: none (selection outside the scene image)": (
        "PNG: нет (выделение за пределами исходной сцены)"
    ),
    (
        "Drag selected region contours. Ctrl+wheel: scale. Raster pixels "
        "stay unchanged. Right-click: configure connected lines. Escape: "
        "cancel the current gesture."
    ): (
        "Тяните выбранные контуры для перемещения. Ctrl+колесо: "
        "масштабирование. Растр остаётся на месте. Правый клик: настройка "
        "связанных линий. Escape: отменить текущий жест."
    ),
    (
        "Wheel: rotate selected contours by 0.1 degrees per notch around "
        "their common center. Wheel up rotates clockwise; wheel down "
        "reverses. Raster pixels stay unchanged. Right-click: configure "
        "connected lines. Each notch is one undo step."
    ): (
        "Колесо: вращение выбранных контуров с шагом 0,1° вокруг общего "
        "центра. Вверх — по часовой стрелке, вниз — обратно. Растр "
        "остаётся на месте. Правый клик: настройка связанных линий. "
        "Каждый шаг колеса можно отменить."
    ),
    "Information": "Информация",
    "Settings": "Настройки",
    "Close all contours": "Замкнуть все контуры",
    "Whole-scene close distance (px)": "Допуск замыкания всей сцены (px)",
    (
        "Extend eligible lines across the whole scene after confirmation. "
        "Distance uses screen pixels."
    ): (
        "Продлить подходящие линии по всей сцене до пересечений после "
        "подтверждения «Отмена / Да». Допуск измеряется в экранных "
        "пикселях."
    ),
    ("Scene image: {width} × {height} px\n{detail}\nClosed: {closed} | Open: {open}"): (
        "Изображение сцены: {width} × {height} px\n{detail}\nЗамкнутых: "
        "{closed} | Незамкнутых: {open}"
    ),
    "Scene image: not loaded\nClosed: 0 | Open: 0": (
        "Изображение сцены не загружено\nЗамкнутых: 0 | Незамкнутых: 0"
    ),
    "Selectable cells: {cells}\nEditing operations: {operations}": (
        "Областей для выбора: {cells}\nИзменений: {operations}"
    ),
    "Contours": "Контуры",
    "Regions": "Области",
    "Raster": "Растр",
    "Edit lines, vertices, auto-close, and snapping.": (
        "Редактирование линий, точек, автозамыкания и прилипания."
    ),
    "Select closed regions and export their PNGs.": "Выбор замкнутых областей и экспорт их PNG.",
    "Erase or restore image pixels.": "Стирание и восстановление пикселей изображения.",
    "Select regions": "Выбор областей",
    ("Click closed regions to toggle selection. Click empty space to clear selection."): (
        "Клик выбирает минимальную замкнутую область под курсором или "
        "снимает её выделение. Клик по пустому месту очищает выбор."
    ),
    "Export selected regions": "Экспорт выбранных областей",
    "Export only the highlighted regions as separate PNGs.": (
        "Экспортировать только выделенные области отдельными PNG."
    ),
    "Artwork offset (px)": "Отступ изображения (px)",
    (
        "Keep scene image pixels beyond the lines. Positive expands the "
        "artwork; negative cuts inward."
    ): (
        "Сохранить пиксели изображения сцены снаружи линий. Положительное "
        "значение расширяет изображение, отрицательное срезает внутрь."
    ),
    (
        "Keep scene image pixels beyond the lines. Positive expands the "
        "artwork; negative cuts inward. Ctrl+wheel: change this value."
    ): (
        "Сохранить пиксели изображения сцены снаружи линий. Положительное "
        "значение расширяет изображение, отрицательное срезает внутрь. "
        "Ctrl+колесо: изменить значение."
    ),
    (
        "Distance to existing vertices or lines. Vertices take priority. "
        "Click the icon to toggle snapping."
    ): (
        "Расстояние прилипания к вершинам и линиям. Вершины в приоритете. "
        "Нажатие на значок включает или выключает прилипание."
    ),
    (
        "Click a line to insert; drag a fixed-size circle to move; "
        "double-click it to delete. Hold Alt to move along the selected "
        "line vector."
    ): (
        "Клик по линии добавляет точку; тяните кружок для перемещения, "
        "дважды щёлкните для удаления. Зажмите Alt, чтобы двигать точку "
        "только по вектору выбранного отрезка. Отпустите Alt для "
        "свободного движения. Escape отменяет жест."
    ),
    (
        "Hover to trace connected lines and valid continuations. White "
        "edges show affected lines; dashed lines preview extensions. "
        "Click to extend existing lines along their directions after "
        "confirmation in one undo step."
    ): (
        "Наведите курсор, чтобы проследить связанные линии и допустимые "
        "продолжения. Белый кант показывает затрагиваемые линии, пунктир "
        "— продолжения. Клик открывает подтверждение «Отмена / Да». "
        "Продление выполняется одним шагом отмены."
    ),
    "Confirm auto-close": "Подтвердить автозамыкание",
    (
        "Affected segments: {segments}\nEndpoint extensions: "
        "{extensions}\nShared intersections: {connections}\n\nConnect the "
        "highlighted lines?"
    ): (
        "Выбрано отрезков: {segments}\nПродлений концов: "
        "{extensions}\nОбщих пересечений: {connections}\n\nСоединить "
        "выделенные линии?"
    ),
    (
        "No changes are needed or possible at this distance. Touching "
        "lines are already connected; remaining gaps need a larger "
        "distance or New line."
    ): (
        "При этом допуске нет необходимых или доступных изменений. "
        "Касающиеся линии уже соединены; для оставшихся зазоров увеличьте "
        "дальность или используйте «Новую линию»."
    ),
    "No lines under the cursor. Point at a line and click again.": (
        "Под курсором нет линий. Наведите его на линию и нажмите снова."
    ),
    "Cancel without changing geometry. Escape: cancel.": (
        "Отменить без изменения линий. Escape: отмена."
    ),
    "Apply the shown connections as one undo step.": (
        "Применить показанные соединения одним шагом отмены."
    ),
    "Select at least one closed region on the scene image.": (
        "Выберите хотя бы одну замкнутую область на сцене."
    ),
    "Selected: {count}": "Выбрано: {count}",
    "PNG: {width} × {height}": "PNG: {width} × {height}",
    "PNG: {count} · max {width} × {height}": "PNG: {count} · макс. {width} × {height}",
    "The selected region lies outside the source image.": (
        "Выбранная область находится вне исходного изображения."
    ),
    "Auto-close": "Автозамыкание контуров",
    "Ctrl+wheel: change the auto-close distance.": (
        "Ctrl + колесо: изменить дальность автоприлипания."
    ),
    ("Independent distance in screen pixels; ordinary snapping is unchanged."): (
        "Собственная дальность в экранных пикселях; обычное прилипание настраивается отдельно."
    ),
    "Finish or cancel the active gesture first.": "Завершите текущий жест или отмените его.",
    ("No enclosed region exists. Use Auto-close for nearby gaps or New line to draw a boundary."): (
        "Нет замкнутых областей. Используйте «Автозамыкание» для близких "
        "зазоров или «Новую линию» для построения контура."
    ),
    (
        "{count} unresolved segments remain. They may be gaps or "
        "unused/internal lines.\nApply the mask to the closed regions "
        "anyway? Choose No to repair with Auto-close or New line."
    ): (
        "Осталось незамкнутых отрезков: {count}. Это могут быть зазоры "
        "или лишние линии.\nПрименить маску к замкнутым областям? Выберите "
        "«Нет», чтобы исправить контур инструментами «Автозамыкание» или "
        "«Новая линия»."
    ),
    "Shortcut: {keys}": "Горячие клавиши: {keys}",
    "Escape: cancel the current gesture.": "Escape: отменить текущий жест.",
    "Ctrl+wheel: change this value.": "Ctrl + колесо: изменить это значение.",
    "Ctrl+wheel: change this tool's diameter.": "Ctrl + колесо: диаметр этого инструмента.",
    "Snapping (px)": "Прилипание (px)",
    "This tool keeps its own diameter in screen pixels.": (
        "Этот инструмент хранит собственный диаметр в экранных пикселях."
    ),
    "Pixel eraser diameter (px)": "Диаметр пиксельного ластика (px)",
    "Restore brush diameter (px)": "Диаметр кисти восстановления (px)",
    "Diameter in original image pixels. Ctrl+wheel changes it.": (
        "Диаметр в пикселях исходной сцены. Ctrl + колесо меняет его."
    ),
    "Decrease by 1 px.": "Уменьшить на 1 px.",
    "Increase by 1 px.": "Увеличить на 1 px.",
    (
        "Select the target Foundry generation. The choice is saved between launches."
    ): "Выберите версию Foundry. Выбор запоминается между запусками.",
    "Foundry version changed; preferences could not be written.": (
        "Версия Foundry изменена, но сохранить настройки не удалось."
    ),
    "PNG: none": "PNG: нет",
    "Tool size": "Размер",
    "Image + JSON": "Изображение сцены + JSON",
    "Open": "Открыть",
    "Save as…": "Сохранить как…",
    "Close": "Закрыть",
    "Hand": "Рука",
    "Open, save, close, export, and navigate projects.": (
        "Открытие, сохранение, закрытие, экспорт и навигация по сцене."
    ),
    "Choose which tools appear to the left of the scene image.": (
        "Выберите набор инструментов, который будет показан слева от сцены."
    ),
    ("Size of the geometry eraser or pixel brush. Ctrl+wheel adjusts sizes."): (
        "Размер ластика геометрии или пиксельной кисти. Ctrl + колесо меняет размер."
    ),
    "Configure snapping to existing vertices and line interiors.": (
        "Настройте прилипание к существующим вершинам и отрезкам линий."
    ),
    "Pan the scene image horizontally.": "Переместить изображение сцены по горизонтали.",
    "Pan the scene image vertically.": "Переместить изображение сцены по вертикали.",
    "Scroll scene settings and editing help.": "Прокрутить настройки сцены и подсказки редактора.",
    "Scroll the available choices.": "Прокрутить доступные варианты.",
    "Show tools that do not fit in this panel.": (
        "Показать инструменты, не поместившиеся на панели."
    ),
    "General": "Общие действия",
    "Snapping": "Прилипание",
    "New line": "Новая линия контура",
    "Erase lines": "Ластик линий контура",
    "Erase vertices": "Ластик точек контура",
    "Close scene": "Закрыть сцену",
    "Snap": "Прилипание",
    "All regions": "Все области",
    (
        "Closed: connected closed regions in current geometry. Open: "
        "connected groups of unresolved lines. PNG bounds include every "
        "nonzero bicubic alpha pixel, clipped to the scene image."
    ): (
        "Замкнутые — связанные замкнутые области текущей геометрии. "
        "Незамкнутые — связанные группы незамкнутых линий. PNG включает "
        "каждый пиксель с альфа-каналом больше нуля после "
        "bicubic-сглаживания в пределах исходного изображения сцены."
    ),
    "Region {number}": "Область {number}",
    "Choose all closed regions or one region to highlight and export.": (
        "Выберите все замкнутые области или одну для подсветки и экспорта."
    ),
    ("Press for the first point, drag, release for the second. Snap now or when moving points."): (
        "Нажатие задаёт первую точку, отпускание — вторую. Прилипание "
        "работает при создании и переносе."
    ),
    ("Erase entire line segments touched by the circle. Drag is one undo step."): (
        "Удалить отрезки, задетые кругом. Всё движение мышью отменяется одним шагом."
    ),
    (
        "Erase vertices inside the circle; reconnect ordinary line "
        "neighbors. Branching vertices remove their connected edges."
    ): (
        "Удалить точки в круге; соседи обычной точки линии соединяются. "
        "При удалении точки разветвления удаляются её смежные отрезки."
    ),
    "Close the current scene after offering to save its DALE project.": (
        "Закрыть текущую изображение сцены с предложением сохранить проект."
    ),
    ("Enable snapping for new lines and moved vertices; vertices take priority."): (
        "Включить прилипание новых линий и перемещаемых точек; приоритет у вершин."
    ),
    "Switch the interface language. The choice is saved locally.": (
        "Переключить язык интерфейса. Выбор сохраняется на этом компьютере."
    ),
    ("Source scene origin in scene pixels. Apply alignment to start a fresh session."): (
        "Начало исходной сцены в её пикселях. Применение смещения начинает новое редактирование."
    ),
    "Language changed; preferences could not be written.": (
        "Язык изменён; сохранить настройки на диск не удалось."
    ),
    (
        "Foundry 13: place the PNG as a tile at {height} ft. Floor "
        "visibility depends on the scene's module configuration."
    ): (
        "Foundry 13: разместите PNG как тайл на высоте {height} футов. "
        "Видимость этажей зависит от модулей сцены."
    ),
    (
        "Foundry 14: assign the PNG to the intended Scene Level at "
        "{height} ft and configure its elevation range/visibility."
    ): (
        "Foundry 14: назначьте PNG нужному уровню сцены на высоте "
        "{height} футов и настройте диапазон высот и видимость."
    ),
    "Cancelling after the current decode/stripe…": (
        "Отмена после текущего декодирования или полосы изображения…"
    ),
    "Cancelling export. Close the window after export stops.": (
        "Экспорт отменяется. Закройте окно после его остановки."
    ),
    "PNG export cancelled; destination unchanged.": "Экспорт PNG отменён; результат не изменён.",
    "Export ended without a result.": "Экспорт завершился без результата.",
    "Open scene": "Открыть сцену",
    "Open project": "Открыть проект",
    "Save project": "Сохранить проект",
    "Save project as…": "Сохранить проект как…",
    "Export PNGs": "Экспорт PNG",
    "File": "Файл",
    "Pan": "Перемещение",
    "Edit points": "Точки контура",
    "Erase": "Ластик растра",
    "Restore": "Восстановление растра",
    "Remove outside": "Стереть растр вне контуров",
    "Remove inside": "Стереть растр внутри контуров",
    "Undo": "Отменить",
    "Redo": "Повторить",
    "Fit": "Вся сцена",
    "Show contours": "Показывать контуры",
    "Apply alignment": "Применить смещение",
    "Target": "Версия Foundry",
    "Language": "Язык",
    "Open a scene image and its scene JSON to begin.": (
        "Откройте изображение сцены и соответствующий JSON сцены."
    ),
    "Ready. All editing is local.": "Готово. Файлы обрабатываются на этом компьютере.",
    "Load a scene image and its scene JSON.": "Загрузить изображение сцены и JSON сцены.",
    "Open a portable .dale archive including sources and undo history.": (
        "Открыть архив .dale с исходниками и историей изменений."
    ),
    ("Save sources, masks, geometry, preferences, and undo/redo in one .dale file."): (
        "Сохранить исходники, маски, линии, настройки и Undo/Redo в один файл .dale."
    ),
    ("Export separate cropped PNGs with the configured margin and a placement manifest."): (
        "Экспортировать отдельные PNG по контурам с заданным отступом и файлом координат."
    ),
    "Drag to move the scene image. Right-drag works in every tool.": (
        "Перемещайте изображение сцены мышью. Правая кнопка работает во всех инструментах."
    ),
    "Paint transparency over unwanted objects.": "Закрасить ненужные объекты прозрачностью.",
    "Restore opacity from the original scene image.": (
        "Восстановить непрозрачность исходного изображения сцены."
    ),
    "Keep enclosed regions and make their exterior transparent.": (
        "Оставить замкнутые области, сделать остальное прозрачным."
    ),
    "Erase enclosed regions and keep their exterior.": (
        "Удалить замкнутые области, оставить остальное."
    ),
    "Undo the last complete stroke, mask, or geometry edit.": (
        "Отменить последний мазок, маску или изменение линий."
    ),
    "Redo the last undone edit.": "Повторить отменённое изменение.",
    "Fit the scene image to the viewport.": "Показать изображение сцены целиком.",
    ("Apply source-scene origin offsets. Existing edits require save/discard."): (
        "Применить смещение начала сцены. Текущую работу можно предварительно сохранить."
    ),
    ("Presets every 5 ft; type any whole number of feet, including negatives."): (
        "Готовые высоты через 5 футов. Можно ввести целое число, включая отрицательное."
    ),
    (
        "Connect free contour ends within this distance in original image "
        "pixels. 0 disables joining."
    ): (
        "Соединять свободные концы контуров в пределах указанного "
        "расстояния в исходных пикселях. 0 — выключено."
    ),
    "Enter a whole-number elevation in feet.": "Введите высоту в футах целым числом.",
    "Elevation must be a whole number of feet.": "Высота должна быть целым числом футов.",
    (
        "Placement in Foundry is configured separately. PNG margin is configurable."
    ): "Размещение настраивается в Foundry. Отступ PNG задаётся отдельно.",
    ("Contour preview updated. Apply Remove outside/inside to use these settings."): (
        "Предпросмотр контура обновлён. Примените «Удалить снаружи/внутри», чтобы изменить маску."
    ),
    "Save changes?": "Сохранить изменения?",
    "Save the project and editing history before continuing?": (
        "Сохранить проект и историю изменений перед продолжением?"
    ),
    "Save DALE project": "Сохранить проект DALE",
    "Open DALE project": "Открыть проект DALE",
    "DALE projects (*.dale)": "Проекты DALE (*.dale)",
    "Open scene image": "Открыть изображение сцены",
    "Load scene JSON": "Загрузить JSON сцены",
    "Scene images (*.jpg *.jpeg)": "Изображения сцены (*.jpg *.jpeg)",
    "Scene JSON (*.json)": "JSON сцены (*.json)",
    "Cannot open scene": "Не удалось открыть сцену",
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
    "Export separate PNGs": "Экспорт отдельных PNG",
    "Exporting separate PNGs…": "Экспорт отдельных PNG…",
    "Export failed": "Ошибка экспорта",
    "Exported {path}": "Экспортировано: {path}",
    "Cancel": "Отмена",
    "Save": "Сохранить",
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
        return RUSSIAN.get(sourceText, sourceText) if self.language == "ru" else sourceText


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
