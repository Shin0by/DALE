"""English source strings and Russian desktop translations."""

from textwrap import wrap

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
    "View": "Вид",
    "Top panels": "Верхние панели",
    "Regions is active, a region is selected and no gesture or export is in progress.": (
        "Включён режим «Области», выбрана область, нет незавершённого действия или экспорта."
    ),
    "Scroll the top panels horizontally with the mouse wheel.": (
        "Прокручивать верхние панели по горизонтали колесом мыши."
    ),
    "Navigate, select, copy, delete and configure the current editing mode.": (
        "Перемещать сцену, выбирать, копировать и удалять элементы текущего режима; "
        "открывать настройки."
    ),
    "Fit the scene and configure contours, guides, background and image resolution.": (
        "Вместить сцену и настроить показ контуров, направляющие, фон и разрешение изображения."
    ),
    "Snap the highlighted vertex or common center to an existing point.": (
        "Притянуть подсвеченную вершину или общий центр к существующей вершине."
    ),
    "The nearest vertex or common center is highlighted; "
    "dragging keeps this point as the anchor.": (
        "Ближайшая вершина или общий центр подсвечены; "
        "при перетаскивании эта точка остаётся опорной."
    ),
    "The nearest vertex or common center is highlighted and stays the grab point while dragging.": (
        "Ближайшая вершина или общий центр подсвечены и остаются опорной точкой при перетаскивании."
    ),
    "Angled contour guides": "Наклонные направляющие контура",
    "Guide targets": "Цели привязки",
    "Connected by contours": "Связаны контуром",
    "Snap the highlighted vertex or common center to a stationary line's "
    "virtual extension at any angle. No lines are added.": (
        "Притянуть подсвеченную вершину или общий центр к виртуальному продолжению "
        "неподвижного отрезка под любым углом. Новые линии не создаются."
    ),
    "Use only lines touching the moved selection through a chain of contours "
    "before the gesture. Independent contours are excluded.": (
        "Использовать только линии, связанные с выделением цепочкой касающихся "
        "контуров до начала действия. Независимые контуры исключаются."
    ),
    "Number: perpendicular distance to a virtual line, in screen pixels.": (
        "Значение: расстояние до виртуальной линии по перпендикуляру в экранных пикселях."
    ),
    "Vertices alignment": "Привязки вершин",
    "Contours alignment": "Привязки контуров",
    "Regions alignment": "Привязки областей",
    "Configure alignment while editing contour vertices and lines.": (
        "Настроить привязки при редактировании вершин и линий контура."
    ),
    "Configure alignment while moving or pasting contours.": (
        "Настроить привязки при перемещении и вставке контуров."
    ),
    "Configure alignment while moving or pasting regions.": (
        "Настроить привязки при перемещении и вставке областей."
    ),
    "Do you want to deselect all regions?": "Желаете отменить выделение всех областей?",
    "Click to toggle a region; drag over 10 screen pixels to invert regions in a box. "
    "Empty click asks before clearing selection. Undo/redo includes selection changes.": (
        "Клик меняет выбор области; перетаскивание дальше 10 экранных пикселей "
        "инвертирует выбор в рамке. Клик по пустому месту запрашивает снятие выделения. "
        "Изменения выбора можно отменять и возвращать."
    ),
    "Click a region: select/deselect. Empty click: ask before clearing selection.": (
        "Клик по области: выбрать или снять выбор. Клик по пустому месту: "
        "запросить снятие выделения."
    ),
    "Not enough temporary disk space for native image preview.": (
        "Недостаточно места на диске для кэша исходного изображения в папке программы."
    ),
    "Native preview requires an uncompressed BMP image.": (
        "Для просмотра BMP в исходном разрешении нужен файл без сжатия."
    ),
    "px": "пкс",
    "ft": "фут",
    "cm": "см",
    "mm": "мм",
    "Raster crosshair": "Перекрестие курсора",
    "Show dashed one-pixel cursor axes across the scene editing area.": (
        "Показать пунктирные оси толщиной в один пиксель через курсор во всех разделах."
    ),
    "Raster rulers": "Линейки и направляющие",
    "Move guides": "Перемещение направляющих",
    "Modes": "Режимы",
    "Canvas background": "Фон рабочей области",
    "Checkerboard": "Шахматный фон",
    "Solid color": "Сплошной цвет",
    "Background color": "Цвет фона",
    "Choose a checkerboard or solid canvas background for this dataset.": (
        "Выбрать шахматный или одноцветный фон рабочей области для текущего набора."
    ),
    "Choose the canvas background for this dataset. Exported pixels stay unchanged.": (
        "Выбрать фон рабочей области для этого набора. Пиксели экспорта не меняются."
    ),
    "Choose a solid preview background color.": "Выбрать цвет фона предпросмотра.",
    "Move raster regions": "Перемещение областей с растром",
    "Rotate raster regions": "Вращение областей с растром",
    "Scale raster regions": "Масштабирование областей с растром",
    "Scale contours": "Масштабирование контуров",
    "Scaling step (%)": "Шаг масштабирования (%)",
    "Resize selected contour lines around their common center.": (
        "Изменить размер выбранных линий контуров относительно их общего центра."
    ),
    "Wheel: scale selected contours by the configured step.": (
        "Колесо: масштабировать выбранные контуры с заданным шагом."
    ),
    "Number: contour scaling step, in percent. Shared with Move contours.": (
        "Число: шаг масштабирования контуров в процентах. "
        "Также применяется в «Перемещении контуров»."
    ),
    "Raster artwork offset": "Отступ изображения областей",
    "Show selected raster regions": "Показать растр выбранных областей",
    "Preview selected regions": "Предпросмотр выбранных областей",
    "Region output": "Экспорт областей",
    "Raster output": "Предпросмотр растра",
    "Move selected boundaries together with their current image pixels.": (
        "Перемещать выбранные границы вместе с текущими пикселями изображения."
    ),
    "Rotate selected boundaries and their image pixels around their common center.": (
        "Вращать выбранные границы и их изображение вокруг общего центра."
    ),
    "Resize selected boundaries together with their image pixels.": (
        "Менять размер выбранных границ вместе с их изображением."
    ),
    "Preview only selected region imagery; show the whole image when selection is empty.": (
        "Показать только изображение выбранных областей. Без выбора показать всё."
    ),
    "Wheel: resize selected raster regions.": "Колесо: масштабировать выбранные области с растром.",
    "Select and reposition ruler guides without editing the scene.": (
        "Выбирать и перемещать направляющие линеек, не изменяя сцену."
    ),
    "Rulers are visible and guide editing is enabled.": (
        "Линейки показаны, режим перемещения направляющих включён."
    ),
    "Drag a guide: move it.": "Перетаскивание направляющей: переместить.",
    "Double-click a guide: delete it.": "Двойной клик по направляющей: удалить.",
    "Native raster resolution": "Исходное разрешение",
    "Square raster eraser": "Квадратный ластик растра",
    "Square raster restore": "Квадратное восстановление растра",
    "Erase image pixels with an axis-aligned square brush.": (
        "Удалить пиксели изображения квадратной кистью."
    ),
    "Restore image pixels with an axis-aligned square brush.": (
        "Восстановить пиксели изображения квадратной кистью."
    ),
    "Show dashed one-pixel cursor axes across the Raster editing area.": (
        "Показать пунктирные оси толщиной в один пиксель через курсор в рабочей области."
    ),
    "Measure the scene and drag horizontal or vertical guides from the rulers.": (
        "Измерять сцену и вытягивать из линеек горизонтальные и вертикальные направляющие."
    ),
    "Show visible image tiles at source resolution with current raster edits.": (
        "Показать видимую часть изображения в исходном разрешении с текущими правками растра."
    ),
    "Raster is active and a scene image is open.": ("Открыты раздел «Растр» и изображение сцены."),
    "Drag from this ruler to create a scene-anchored guide.": (
        "Вытянуть из линейки направляющую, закреплённую в координатах сцены."
    ),
    "Drag from a ruler: create a guide.": "Перетаскивание из линейки: создать направляющую.",
    "Ctrl+drag a guide: move it; return it to a ruler to delete.": (
        "Ctrl+перетаскивание направляющей: переместить; вернуть на линейку для удаления."
    ),
    "Escape: cancel the guide drag.": "Escape: отменить перемещение направляющей.",
    "Ctrl+wheel: change brush diameter.": "Ctrl+колесо: изменить диаметр кисти.",
    "Alt+wheel: change feather width.": "Alt+колесо: изменить ширину мягкой кромки.",
    "Escape: cancel the stroke.": "Escape: отменить мазок.",
    "Ruler units": "Единицы линейки",
    "Source pixels": "Исходные пиксели",
    "Feet": "Футы",
    "Centimeters": "Сантиметры",
    "Millimeters": "Миллиметры",
    "World distances use the scene JSON grid. Ruler zero is the image origin.": (
        "Игровые расстояния рассчитываются по сетке JSON сцены. Ноль - начало изображения."
    ),
    "One game foot: {x} × {y} source px.": "Один игровой фут: {x} × {y} исходных пикселей.",
    "World rulers require scene JSON grid size, distance and units.": (
        "Для игровых единиц нужны размер клетки, расстояние и единицы сетки из JSON сцены."
    ),
    "Scene grid units cannot be converted to feet or centimeters.": (
        "Единицы сетки сцены невозможно перевести в футы или сантиметры."
    ),
    "Snap guides to whole ruler values": "Привязка направляющих к целым значениям",
    "Round a dragged guide to a whole value in the selected ruler unit.": (
        "Округлять положение направляющей до целого значения выбранной единицы."
    ),
    "Automatic grid": "Автоматическая сетка",
    "Show automatic grid": "Показать автоматическую сетку",
    "Grid spacing in the selected units": "Шаг сетки в выбранных единицах",
    "Grid spacing": "Шаг сетки",
    "Set the spacing of scene-anchored grid lines in the selected units.": (
        "Задать расстояние между линиями сетки в выбранных единицах."
    ),
    "Show a solid translucent grid over the scene image.": (
        "Показать поверх изображения сетку из сплошных полупрозрачных линий."
    ),
    "Dense grid lines are thinned only on screen at low zoom.": (
        "При отдалении частые линии прореживаются только на экране."
    ),
    "Brush shape": "Форма кисти",
    "Circle": "Круг",
    "Square": "Квадрат",
    "Choose the round or square tool for this raster operation.": (
        "Выбрать круглую или квадратную кисть для этой операции с растром."
    ),
    "Feather width (%)": "Ширина мягкой кромки (%)",
    "Brush pressure (%)": "Нажим кисти (%)",
    "Keep a solid center and soften only the outer band.": (
        "Сохранить плотную середину и размыть только внешнюю кромку."
    ),
    "Set the strength of each erase or restore stroke.": (
        "Задать силу удаления или восстановления за один мазок."
    ),
    "Not enough memory for native raster resolution.": (
        "Недостаточно памяти для отображения растра в исходном разрешении."
    ),
    "Too many guides. Remove a guide before creating another.": (
        "Слишком много направляющих. Удалите одну перед созданием новой."
    ),
    "The raster guide limit has been reached.": "Достигнут предел числа направляющих растра.",
    "Circle detail": "Детализация круга",
    "Maximum: 4096 segments.": "Максимум: 4096 отрезков.",
    "More segments make the contour smoother without changing its radius.": (
        "Больше отрезков делают контур плавнее, не меняя его радиус."
    ),
    "Multiplier: ×{factor}": "Множитель: ×{factor}",
    "Increase the automatic segment count. Multiplier 1.0 keeps current detail.": (
        "Увеличить автоматически рассчитанное число отрезков. "
        "Множитель 1,0 сохраняет текущую детализацию."
    ),
    "Left/Right: change the multiplier by 0.2.": ("Влево/Вправо: изменить множитель на 0,2."),
    "Home/End: minimum/maximum detail.": ("Home/End: минимальная/максимальная детализация."),
    "Right-click the circle button: adjust detail.": (
        "Правый клик по кнопке круга: настроить детализацию."
    ),
    "Current dataset data exceeds the project limit even without undo history.": (
        "Текущие данные наборов превышают лимит проекта даже без истории отмены."
    ),
    "Invalid project undo checkpoint.": "Некорректная граница истории отмены в проекте.",
    "Groups": "Группы",
    "Resize group manager": "Изменить размер менеджера групп",
    "Change the width and height of the group manager.": (
        "Изменить ширину и высоту менеджера групп."
    ),
    "Manage dataset selection groups and choose a group to select.": (
        "Управлять группами текущего набора и выбирать их элементы."
    ),
    "Group manager": "Менеджер групп",
    "Sorting": "Сортировка",
    "Move group": "Переместить группу",
    "Reorder groups by dragging their handles. Group actions are disabled while sorting.": (
        "Менять порядок групп перетаскиванием за ручки. Действия групп на это время отключены."
    ),
    "Drag up or down. The light line marks the new group position.": (
        "Перетащите вверх или вниз. Светлая линия показывает новое место группы."
    ),
    "Escape: cancel this drag.": "Escape: отменить перетаскивание.",
    "Groups: {section}": "Группы: {section}",
    "Group {number}": "Группа {number}",
    "+ New group": "+ Новая группа",
    "Rename group": "Переименовать группу",
    "Group name": "Название группы",
    "Group color": "Цвет группы",
    "Delete group": "Удалить группу",
    "Add selection": "Добавить выбранное",
    "Exclude selection": "Исключить выбранное",
    "All group colors": "Все цвета групп",
    "Cannot update group": "Не удалось изменить группу",
    "Show or hide the floating group manager and group colors.": (
        "Показать или скрыть менеджер групп и окраску групп на карте."
    ),
    "Select a group's elements. Each section of this dataset has its own groups.": (
        "Выбрать элементы группы. У каждого раздела этого набора свои группы."
    ),
    "Close group mode and restore ordinary selection colors.": (
        "Закрыть менеджер и вернуть обычные цвета выделения."
    ),
    "Create an empty group in this section of the current dataset.": (
        "Создать пустую группу в текущем разделе этого набора."
    ),
    "Create a group, then add selected scene elements with +.": (
        "Создайте группу, выберите элементы сцены и добавьте их кнопкой +."
    ),
    "Choose the color of this group.": "Изменить цвет этой группы.",
    "Select this group's elements in the current section.": (
        "Выбрать элементы этой группы в текущем разделе."
    ),
    "Double-click: rename this group.": "Двойной клик: переименовать группу.",
    "Add the currently selected elements to this group.": (
        "Добавить выбранные элементы в эту группу."
    ),
    "Remove the currently selected elements from this group.": (
        "Исключить выбранные элементы из этой группы."
    ),
    "Delete this group, keeping all scene elements.": (
        "Удалить только группу. Элементы сцены останутся."
    ),
    'Delete group "{name}"? Scene elements will remain.': (
        'Удалить группу "{name}"? Элементы сцены останутся.'
    ),
    "Export adjacent regions as one?": "Выгрузить смежные области как одну?",
    (
        "Yes: one PNG per connected group of selected regions. No: one PNG per region. "
        "Unselected regions are not included."
    ): (
        "Да: один PNG для каждой связной группы выбранных областей. Нет: отдельный PNG "
        "для каждой области. Невыбранные области не включаются."
    ),
    "Remember the answer between launches. Right-click Export selected regions to change it.": (
        "Запомнить ответ между запусками. Правый клик по кнопке экспорта выбранных областей "
        "меняет настройку."
    ),
    "Save each adjacent selected group in one PNG.": "Сохранить каждую смежную группу одним PNG.",
    "Save each selected region in its own PNG.": (
        "Сохранить каждую выбранную область отдельным PNG."
    ),
    "Cancel without exporting or changing the question settings.": (
        "Отменить экспорт, сохранив настройку вопроса."
    ),
    "Right-click this button: configure adjacent-region export.": (
        "Правый клик по кнопке: настроить объединение смежных областей при экспорте."
    ),
    "Save selected regions as transparent PNGs, optionally joining adjacent selections.": (
        "Сохранить выбранные области прозрачными PNG с возможностью объединить смежные."
    ),
    "Do not ask again": "Не спрашивать снова",
    "Choose the answer for export. Clear the checkbox to ask on every export.": (
        "Выберите ответ для экспорта. Снимите галочку, чтобы спрашивать при каждом экспорте."
    ),
    "Connect new cut endpoints to intersecting contours with shared vertices?": (
        "Связать новые концы обрезанных линий с пересекающими контурами общими точками?"
    ),
    "Connect this point to the other contour with a shared vertex?": (
        "Связать эту точку с другим контуром, сделав её общей?"
    ),
    "Choose the answer for this tool. Clear the checkbox to ask on each contact.": (
        "Выберите ответ для этого инструмента. Снимите галочку, "
        "чтобы спрашивать при каждом касании."
    ),
    "Remember this answer for this tool. Right-click its button to change it.": (
        "Запомнить ответ для этого инструмента. Правый клик по его кнопке меняет настройку."
    ),
    "Connect the contours with shared vertices.": "Связать контуры общими точками.",
    "Keep the contours separate.": "Оставить контуры независимыми, даже если точки совпадают.",
    "Leave contours and question settings unchanged.": (
        "Отменить правку и оставить настройку вопроса."
    ),
    "Right-click the tool button: configure the connection question.": (
        "Правый клик по кнопке инструмента: настроить вопрос о связи контуров."
    ),
    "Select all contour lines": "Выбрать все отрезки контуров",
    "Select all regions": "Выбрать все области",
    "Select all elements of the current section in the visible height scope.": (
        "Выбрать все элементы текущего раздела в выбранном слое высоты."
    ),
    "The current section contains selectable elements.": (
        "В текущем разделе есть доступные элементы."
    ),
    "Select contour lines for moving, scaling, rotating or copying.": (
        "Выбрать линии контуров для перемещения, масштабирования, вращения или копирования."
    ),
    "Transform selected open or closed contour lines as one group.": (
        "Перемещать, масштабировать и вращать выбранные линии открытых и замкнутых контуров вместе."
    ),
    "Select open or closed contour lines to move, scale, rotate or copy together.": (
        "Выбирать линии открытых и замкнутых контуров для совместного перемещения, "
        "масштабирования, вращения и копирования."
    ),
    "Contours are available.": "На сцене есть линии контуров.",
    "Click: toggle the line under the cursor.": (
        "Клик: выбрать или снять выбор отрезка под курсором."
    ),
    "Double-click: select or deselect all lines connected by shared vertices.": (
        "Двойной клик: выбрать или снять выбор всех линий, связанных общими вершинами."
    ),
    "Drag over 10 screen pixels: invert lines intersecting the box.": (
        "Перетаскивание дальше 10 экранных пикселей: инвертировать выбор отрезков в рамке."
    ),
    "Empty click clears selection.": "Клик по пустому месту снимает выделение.",
    "No selected contours": "Контуры не выбраны",
    "All contours": "Все контуры",
    "Contour {number}": "Контур {number}",
    "Selected lines: {count}": "Выбрано отрезков: {count}",
    "Contour groups: {groups}\nSelected lines: {lines}": (
        "Связанных контуров: {groups}\nВыбрано отрезков: {lines}"
    ),
    "Contours copied. Ctrl+V: place a copy.": "Контуры скопированы. Ctrl+V: вставить копию.",
    "Vertices": "Вершины",
    "Delete contours": "Удалить контуры",
    "Cannot delete contours": "Не удалось удалить контуры",
    "Delete only selected contour lines; keep unselected lines and image pixels.": (
        "Удалить только выбранные линии контуров, сохранив остальные линии и пиксели изображения."
    ),
    "Contours is active, a line is selected and no gesture or export is in progress.": (
        "Открыт раздел «Контуры», выбрана линия, нет незавершённого действия или экспорта."
    ),
    "Select contours": "Выбор контуров",
    "Move contours": "Перемещение контуров",
    "Rotate contours": "Вращение контуров",
    "Contour point alignment": "К точкам контура",
    "Contour guide alignment": "По направляющим контура",
    "Mirror contours about vertical axis": "Отразить контуры по вертикальной оси",
    "Mirror contours about horizontal axis": "Отразить контуры по горизонтальной оси",
    (
        "Swap left and right about the vertical axis through the common contour center. "
        "Keep image pixels and unselected lines in place."
    ): (
        "Поменять левую и правую стороны относительно вертикальной оси через общий центр контуров. "
        "Изображение и невыбранные линии остаются на месте."
    ),
    (
        "Swap top and bottom about the horizontal axis through the common contour center. "
        "Keep image pixels and unselected lines in place."
    ): (
        "Поменять верхнюю и нижнюю стороны относительно горизонтальной оси "
        "через общий центр контуров. "
        "Изображение и невыбранные линии остаются на месте."
    ),
    "Cannot transform contours": "Не удалось преобразовать контуры",
    "Choose a vertical or horizontal mirror axis.": "Выберите вертикальную или горизонтальную ось.",
    "Rotation step (degrees)": "Шаг вращения (градусы)",
    "Wheel": "Колесо",
    "Alt+wheel": "Alt+колесо",
    "Degrees per wheel notch. Apply to remember this rotation step.": (
        "Градусы за деление колеса. Нажмите «Применить», чтобы сохранить шаг."
    ),
    "Invalid project rotation step.": "Некорректный шаг вращения в проекте.",
    "Rotate selected region contours around their common center.": (
        "Вращать контуры выбранных областей вокруг их общего центра."
    ),
    "Wheel: rotate by the configured step.": "Колесо: вращать с настроенным шагом.",
    "Alt+wheel: rotate by the configured Alt step.": "Alt+колесо: вращать с настроенным шагом Alt.",
    (
        "Wheel: rotate selected contour lines by the configured step around their common center."
    ): "Колесо: вращение выбранных линий вокруг общего центра с настроенным шагом.",
    (
        "Wheel: rotate selected regions by the configured step around their common center."
    ): "Колесо: вращение выбранных областей вокруг общего центра с настроенным шагом.",
    (
        "The center label shows the total angle since this rotation started; "
        "negative is counterclockwise."
    ): (
        "Число в центре - суммарный угол от начала вращения; "
        "отрицательный угол означает вращение против часовой стрелки."
    ),
    "Figure point alignment": "К точкам",
    "Figure guide alignment": "По направляющим",
    "Copy contours": "Копировать контуры",
    "Paste contours": "Вставить контуры",
    "Copy selected contour lines. Image pixels stay in place.": (
        "Копировать выбранные линии контуров. Пиксели изображения остаются на месте."
    ),
    "Place copied contour lines. Image pixels stay in place.": (
        "Разместить скопированные линии контуров. Пиксели изображения остаются на месте."
    ),
    "Contour lines have been copied to the application clipboard.": (
        "Линии контуров скопированы в буфер программы."
    ),
    "Choose a connected contour or all contour lines to select.": (
        "Выбрать связанный контур или все линии контуров."
    ),
    "Select and position whole closed contour figures independently.": (
        "Выбирать и размещать цельные замкнутые фигуры независимо от посторонних контуров."
    ),
    "Move selected contour lines together. Image pixels stay in place.": (
        "Перемещать выбранные линии контуров вместе. Пиксели изображения остаются на месте."
    ),
    "Rotate selected contour lines around their common center.": (
        "Вращать выбранные линии контуров вокруг общего центра."
    ),
    "Snap the highlighted contour vertex to an existing point.": (
        "Совместить подсвеченную вершину контура с существующей точкой."
    ),
    "Align the highlighted contour vertex with vertex X/Y guides.": (
        "Выровнять подсвеченную вершину контура по горизонтали или вертикали других вершин."
    ),
    "This button is enabled and contours are being moved or pasted.": (
        "Кнопка включена; выполняется перемещение или вставка контуров."
    ),
    "Contours enclose a closed figure.": "Контуры образуют замкнутую фигуру.",
    "At least one contour line is selected.": "Выбрана хотя бы одна линия контура.",
    "Alt+wheel: rotate by 45 degrees per notch.": "Alt+колесо: вращать с шагом 45°.",
    "Wheel: rotate selected contours by 0.1 degrees.": (
        "Колесо: вращать выбранные контуры с шагом 0,1 градуса."
    ),
    "Click a figure: select/deselect its whole closed contour. Empty click clears selection.": (
        "Клик по фигуре: выбрать или снять выбор её замкнутого контура целиком. "
        "Пустой клик снимает выделение."
    ),
    "Drag over 10 screen pixels: invert figures intersecting the box.": (
        "Перетаскивание дальше 10 экранных пикселей: инвертировать выбор фигур в рамке."
    ),
    "Drag selected contour lines: move. Ctrl+wheel: scale.": (
        "Перетаскивание выбранных линий контуров: перемещение. Ctrl+колесо: масштабирование."
    ),
    "Wheel: rotate selected contour lines by 0.1 degrees around their common center.": (
        "Колесо: вращение выбранных линий контуров с шагом 0,1 градуса вокруг общего центра."
    ),
    "The nearest contour vertex is highlighted and stays the grab point while dragging.": (
        "Ближайшая вершина контура подсвечена и остаётся опорной при перетаскивании."
    ),
    "Alt: use the enabled contour point/guide alignment buttons.": (
        "Alt: применить включённые кнопки привязки контуров к точкам и направляющим."
    ),
    "Ctrl+C: copy selected contours. Ctrl+V: preview a copy; click to place. Escape cancels.": (
        "Ctrl+C: копировать выбранные контуры. Ctrl+V: предпросмотр копии; клик вставляет её. "
        "Escape отменяет вставку."
    ),
    (
        "Select whole closed figures. Unrelated crossings and nested contours "
        "do not cut their shape."
    ): (
        "Выбрать замкнутые фигуры целиком. Посторонние пересечения и вложенные контуры "
        "не разрезают их форму."
    ),
    "Closed figures stay whole across unrelated crossings and nested contours.": (
        "Замкнутые фигуры остаются целыми при посторонних пересечениях и вложенных контурах."
    ),
    "Selectable closed figures: {cells}\nEditing operations: {operations}": (
        "Замкнутых фигур для выбора: {cells}\nИзменений: {operations}"
    ),
    "Select raster regions": "Выбор областей растра",
    "Erase raster outside selected regions": "Удалить растр снаружи областей",
    "Erase raster inside selected regions": "Удалить растр внутри областей",
    (
        "Click to toggle a region; drag over 10 screen pixels to invert regions in a box. "
        "Empty click clears selection."
    ): (
        "Клик переключает выделение области; перетаскивание дальше 10 экранных пикселей "
        "инвертирует выделение в рамке. Клик по пустому месту снимает выделение."
    ),
    "Drag over 10 screen pixels: invert regions intersecting the box.": (
        "Перетаскивание дальше 10 экранных пикселей: инвертировать выделение областей в рамке."
    ),
    "Escape: restore the selection from before dragging.": (
        "Escape: восстановить выделение, которое было до перетаскивания."
    ),
    "Raster inside/outside commands use selected regions only.": (
        "Удаление растра внутри и снаружи действует только относительно выделенных областей."
    ),
    "A scene image and selected regions are available.": (
        "Открыто изображение сцены и выделены области."
    ),
    "Erase pixels outside selected regions using the same edge filtering as PNG export.": (
        "Удалить пиксели снаружи выделенных областей, со сглаживанием краёв как при экспорте PNG."
    ),
    "Erase pixels inside selected regions using the same edge filtering as PNG export.": (
        "Удалить пиксели внутри выделенных областей, со сглаживанием краёв как при экспорте PNG."
    ),
    "Decrease value": "Уменьшить значение",
    "Increase value": "Увеличить значение",
    "More tools": "Другие инструменты",
    "Collapse the project/settings panel to give the scene more space.": (
        "Свернуть панель проекта и настроек, освободив место для сцены."
    ),
    "Show the project and settings panel.": "Показать панель проекта и настроек.",
    "Delete region": "Удалить область",
    "Cannot delete region": "Не удалось удалить область",
    (
        "Delete selected region boundaries, including hole outlines. "
        "Keep lines inside and image pixels."
    ): (
        "Удалить границы выбранных областей, включая границы отверстий. "
        "Линии внутри и изображение сохраняются."
    ),
    "Regions is active, a region is selected and no gesture is in progress.": (
        "Открыт раздел «Области», есть выделение, текущий жест завершён."
    ),
    "Region point alignment": "К точкам",
    "Region guide alignment": "По направляющим",
    "Snap the highlighted region vertex to an existing point; move the whole figure.": (
        "Совместить подсвеченную вершину области с существующей точкой, сдвигая всю фигуру."
    ),
    "Align the highlighted region vertex with horizontal/vertical vertex guides.": (
        "Выровнять подсвеченную вершину области по горизонтали или вертикали других вершин."
    ),
    "This button is enabled and a region is being moved or pasted.": (
        "Кнопка включена; выполняется перемещение или вставка области."
    ),
    "The nearest region vertex is highlighted; dragging keeps this vertex as the anchor.": (
        "Ближайшая вершина области подсвечена; при перетаскивании она остаётся опорной."
    ),
    "Alt: use the enabled region point/guide alignment buttons.": (
        "Alt: применять включённые кнопки привязки области к точкам и направляющим."
    ),
    "Import to project…": "Импорт в проект…",
    (
        "Import images or scene JSON into the open project; replace the"
        " current set or add a new one."
    ): (
        "Импортировать изображение или JSON в открытый проект: заменить"
        " текущий набор или добавить новый."
    ),
    (
        "Replace files in the current set or add a new set? Replaced "
        "files are removed when no other set or history uses them."
    ): (
        "Заменить файлы в текущем наборе или добавить новый набор? "
        "Заменённые файлы удаляются, если не используются другими "
        "наборами или историей."
    ),
    "Replace in current set": "Заменить в текущем наборе",
    "Add new set": "Добавить новый набор",
    ("Scene assets (*.json *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.dale)"): (
        "Файлы сцены (*.json *.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.dale)"
    ),
    "Choose one DALE project, or at most one image and one JSON.": (
        "Выберите один проект DALE либо не более одного изображения и одного JSON."
    ),
    "The project image catalog is full.": "Каталог изображений проекта заполнен.",
    "Copy region contours": "Копировать контуры областей",
    "Paste region contours": "Вставить контуры областей",
    "Cannot paste regions": "Не удалось вставить области",
    "Copy selected region boundaries. Raster pixels stay in place.": (
        "Копировать границы выбранных областей. Растр остаётся на месте."
    ),
    (
        "Preview copied contours at the cursor; click to place. Alt with "
        "Contour alignment: snap to a vertex first, then horizontal/vertical guides. "
        "Escape: cancel."
    ): (
        "Предпросмотр контуров у курсора; щелчок - вставить. Alt с "
        "притягиванием контуров - сначала к вершине, затем к горизонтали или вертикали. Escape - "
        "отменить."
    ),
    "Pasting with Alt: vertices take priority over horizontal/vertical guides.": (
        "При вставке с Alt вершины имеют приоритет перед горизонталями и вертикалями."
    ),
    "Regions copied. Ctrl+V: place a copy of their contours.": (
        "Области скопированы. Ctrl+V - разместить копию их контуров."
    ),
    ("Alt with Contour alignment enabled: align horizontally/vertically with distant vertices."): (
        "Alt с включённым притягиванием контуров: выравнивание по "
        "горизонтали и вертикали с удалёнными вершинами."
    ),
    (
        "Ctrl+C: copy selected region contours. Ctrl+V: preview a copy; "
        "click to place. Escape: cancel. Raster stays in place."
    ): (
        "Ctrl+C - копировать контуры выбранных областей. Ctrl+V - "
        "предпросмотр копии; щелчок - вставить. Escape - отменить. Растр "
        "остаётся на месте."
    ),
    "The project JSON catalog is full. Export to a different project.": (
        "Каталог JSON проекта заполнен. Выгрузите набор в другой проект."
    ),
    "Dataset": "Набор",
    "Image": "Изображение",
    "No JSON": "Без JSON",
    "No image": "Без изображения",
    "Rename…": "Переименовать…",
    "Rename current set": "Переименовать текущий набор",
    "Set name": "Название набора",
    "Cannot rename set": "Не удалось переименовать набор",
    "Export to project…": "Экспорт в проект…",
    ("Choose project assets independently. Each pair retains its editing history."): (
        "Выбирайте JSON и изображение независимо. У каждой пары сохраняется своя история правок."
    ),
    "Rename the current JSON/image set without changing source files.": (
        "Переименовать текущий набор JSON и изображения, сохранив исходные файлы."
    ),
    (
        "Append current contours and the exact source image to an existing"
        " DALE project without opening it."
    ): (
        "Добавить текущие контуры и исходное изображение в существующий "
        "проект DALE, не открывая его."
    ),
    "Set appended. The current editor remains open.": (
        "Набор добавлен. Текущая сцена осталась открытой."
    ),
    "An identical set is already in this project.": "Точно такой же набор уже есть в этом проекте.",
    "Current contours (DALE)": "Исправленные контуры (DALE)",
    "New rectangle": "Прямоугольник",
    "New rectangular contour": "Создать прямоугольный контур",
    (
        "Press for the first corner, drag, release for the opposite "
        "corner. One closed contour, one undo step."
    ): (
        "Нажмите для первого угла, растяните и отпустите для "
        "противоположного. Замкнутый контур создаётся за один шаг отмены."
    ),
    "A set name must contain 1 to 251 characters.": (
        "Название набора должно содержать от 1 до 251 символа."
    ),
    (
        "Affected segments: {segments}\nEndpoint extensions: {extensions}\n"
        "Endpoint shortenings: {retractions}\nShared intersections: {connections}\n\n"
        "Connect the highlighted lines?"
    ): (
        "Затронуто отрезков: {segments}\nПродлений концов: {extensions}\n"
        "Укорочений концов: {retractions}\nОбщих пересечений: {connections}\n\n"
        "Соединить подсвеченные линии?"
    ),
    "No compatible endpoint moves at this distance.": (
        "Нет согласованных перемещений концов при этом допуске."
    ),
    (
        "Hover to trace connected lines and valid continuations. White edges show affected lines; "
        "dashed lines preview extensions and shortened tails. Click to adjust free ends "
        "along their vectors after confirmation in one undo step."
    ): (
        "Наведите курсор для поиска связанных линий. Белые края показывают затронутые линии; "
        "пунктир - продления и укорачиваемые хвосты. После подтверждения концы перемещаются "
        "вдоль своих векторов одним шагом отмены."
    ),
    (
        "Extend or shorten eligible free ends along their vectors after "
        "confirmation. Distance uses screen pixels."
    ): (
        "Продлить или укоротить свободные концы вдоль их векторов после подтверждения. "
        "Допуск измеряется в экранных пикселях."
    ),
    "Height layers": "Слои высоты",
    "All height layers": "Все слои",
    "Ambiguous heights": "Неоднозначные высоты",
    "{range} (exact range)": "{range} (только этот диапазон)",
    (
        "Show and edit one height band including shared contours, or an exact source range. "
        "Shared contours keep one identity in every covered band. New contours use this range."
    ): (
        "Показать и редактировать слой вместе с общими контурами или только точный диапазон. "
        "Общий контур остаётся одним во всех своих слоях. Новые контуры получают этот диапазон."
    ),
    (
        "Repair contours by height layers, move endpoints and draw ordinary new contours. "
        "Original properties are preserved. Disable for PNG editing."
    ): (
        "Склеивание по слоям высоты, перемещение точек и рисование новых обычных контуров. "
        "Исходные свойства сохраняются. Выключите для подготовки PNG."
    ),
    (
        "Original contours: {count}\nNew contours: {added}\nVisible contours: {visible}\n"
        "Height bands: {layers}\nAmbiguous heights: {ambiguous}"
    ): (
        "Исходных контуров: {count}\nНовых контуров: {added}\nВидимых контуров: {visible}\n"
        "Слоёв высоты: {layers}\nНеоднозначных высот: {ambiguous}"
    ),
    "Choose a height range before drawing a new contour.": (
        "Выберите диапазон высоты справа перед рисованием нового контура."
    ),
    "Moving this point would collapse a contour. The move was not applied.": (
        "Такое перемещение схлопнет контур в точку. Перемещение не применено."
    ),
    (
        "Drag a circle: move existing contour endpoints. Alt-drag: use enabled "
        "angle/contour alignment buttons; "
        "guides show anchors."
    ): (
        "Перетаскивайте кружок для перемещения концов контура. Alt применяет включённые "
        "кнопки углов и привязки по контуру; опоры показаны направляющими."
    ),
    "Shared endpoints follow the contour in every covered height band.": (
        "Общие точки перемещаются вместе с контуром во всех его слоях высоты."
    ),
    "Use New line to close a gap manually. Escape: cancel the current gesture.": (
        "Для ручного замыкания используйте новую линию контура. Escape: отмена действия."
    ),
    "Choose a height range. Press, drag, release: create an ordinary contour there.": (
        "Выберите диапазон высоты. Нажмите, протяните, отпустите: создать обычный контур."
    ),
    "Original contours are not split or replaced. Escape: cancel the current gesture.": (
        "Исходные контуры не разбиваются и не заменяются. Escape: отмена действия."
    ),
    "Editing operations: {operations}": "Изменений: {operations}",
    "No compatible endpoint extensions at this distance.": (
        "Нет согласованных продлений концов при этом допуске."
    ),
    "Preserve JSON when joining contours": "Сохранять JSON при склеивании контуров",
    (
        "Join existing contours by height layers without duplicating contours. "
        "Other geometry tools are disabled in this mode. Disable for PNG editing."
    ): (
        "Склеивать исходные контуры по слоям высоты без дублирования. "
        "Остальные инструменты геометрии отключены. Выключите этот режим для подготовки PNG."
    ),
    "Export JSON…": "Экспорт JSON…",
    "Export the current set's applied contours as JSON, including unsaved edits.": (
        "Экспортировать текущие контуры выбранного набора в JSON, включая несохранённые правки."
    ),
    "Height bands: {layers}. Conflict groups left unchanged: {conflicts}.": (
        "Слоёв высоты: {layers}. Конфликтных групп без изменений: {conflicts}."
    ),
    "Review original contours: {numbers}.": "Проверьте исходные контуры: {numbers}.",
    "Source contours: {count}\nHeight bands: {layers}\nAmbiguous heights: {ambiguous}": (
        "Исходных контуров: {count}\nСлоёв высоты: {layers}\nНеоднозначных высот: {ambiguous}"
    ),
    "JSON exported": "JSON экспортирован",
    "Current set contours exported.\n{path}": "Текущие контуры набора экспортированы.\n{path}",
    "Cannot export scene JSON": "Не удалось экспортировать JSON сцены",
    "Cannot enable JSON repair": "Не удалось включить исправление JSON",
    "Undo other geometry edits or reopen the JSON for safe repair.": (
        "Для безопасного исправления отмените другие правки геометрии или откройте JSON заново."
    ),
    "Disable JSON repair and open a scene image for PNG export.": (
        "Для экспорта PNG отключите исправление JSON и откройте изображение сцены."
    ),
    "PNG export": "Экспорт PNG",
    "JSON repair requires original wall identities. Undo geometry edits or reopen the JSON.": (
        "Для исправления JSON нужны исходные контуры. Отмените правки геометрии "
        "или откройте JSON заново."
    ),
    "JSON export supports safe contour repair only. Undo other geometry edits or reopen.": (
        "В JSON можно выгрузить только безопасное склеивание контуров. "
        "Отмените другие правки геометрии или откройте исходник заново."
    ),
    "JSON export cannot replace an imported source file.": "Нельзя перезаписывать исходный файл.",
    "Source JSON changed outside DALE. Reopen it before exporting.": (
        "Исходный JSON изменён вне DALE. Откройте его заново перед экспортом."
    ),
    "The original scene snapshot is no longer intact.": "Исходные данные сцены изменены.",
    "Open a scene JSON before exporting repaired JSON.": (
        "Откройте JSON сцены перед экспортом исправленного JSON."
    ),
    "The repair preview is no longer current. Analyze connections again.": (
        "Предпросмотр исправлений устарел. Повторите анализ соединений."
    ),
    "Scene images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)": (
        "Изображения сцены (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"
    ),
    "This project contains no scene JSON.": "В этом проекте нет JSON сцены.",
    "Sections": "Разделы",
    "Main": "Основное",
    "Common navigation, selection, visibility, and settings controls.": (
        "Общие действия: перемещение, выделение, видимость контуров и настройки."
    ),
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
    "Create, open, save, export regions, close, and exit.": (
        "Создание, открытие, сохранение, экспорт областей, закрытие и выход."
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
        "отпустите для создания круглого контура. До 0,5 клетки - 4 "
        "вершины, до 1 - 6, до 2 - 8; дальше число вершин растёт. "
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
    (
        "Double-click a circle: delete the point. Alt-drag: use enabled angle/contour "
        "alignment buttons; "
        "guides show anchors."
    ): (
        "Двойной клик по кружку: удалить точку. Alt применяет включённые кнопки углов "
        "и привязки по контуру; опоры показаны направляющими."
    ),
    "Press, drag, release: draw a contour line.": "Нажать, тянуть, отпустить: новая линия контура.",
    "Hover: preview contour connections. Click: review and apply.": (
        "Наведение: предпросмотр замыкания контуров. Клик: подтверждение и применение."
    ),
    "Drag the circle: erase highlighted pieces up to intersections or endpoints.": (
        "Тяните круг: стереть подсвеченные части до пересечений или концов."
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
    "Deselect elements in the current section; cancel the current gesture.": (
        "Снять выделение элементов текущего раздела и отменить текущий жест."
    ),
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
    "Edit contour vertices": "Вершины контура",
    "New contour line": "Новая линия контура",
    "Erase contour lines": "Ластик линий контура",
    "Erase contour vertices": "Ластик вершин контура",
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
    "Right-angle alignment": "Прямые углы",
    "Contour alignment": "Привязка по контуру",
    (
        "With Alt held, snap to 90 degrees between adjacent lines, including rotated "
        "contours. Own screen-pixel tolerance; highlighted lines and a square mark show the joint."
    ): (
        "При зажатом Alt выправлять 90° между смежными линиями, включая повёрнутые контуры. "
        "Свой допуск в экранных пикселях; подсветка линий и знак прямого угла показывают стык."
    ),
    (
        "With Alt held, snap x/y to other vertices in this connected contour or region. "
        "Own screen-pixel tolerance; thin dashed guides show the anchors."
    ): (
        "При зажатом Alt привязывать X/Y к другим вершинам этого связанного контура или области. "
        "Свой допуск в экранных пикселях; тонкий пунктир показывает опорные точки."
    ),
    "Right-angle tolerance (px)": "Допуск прямого угла (px)",
    "Contour alignment tolerance (px)": "Допуск привязки по контуру (px)",
    "Independent screen-pixel distance to a 90-degree joint. Requires this button and Alt.": (
        "Свой допуск до стыка 90° в экранных пикселях. Нужны включённая кнопка и зажатый Alt."
    ),
    (
        "Independent screen-pixel distance to a contour vertex's horizontal/vertical guide. "
        "Requires this button and Alt."
    ): (
        "Свой допуск до горизонтали/вертикали вершины контура в экранных пикселях. "
        "Нужны включённая кнопка и зажатый Alt."
    ),
    "Current contours (DALE).json": "Исправленные контуры (DALE).json",
    "Save JSON…": "Сохранить JSON…",
    "Save the selected JSON to a separate file without importing it.": (
        "Сохранить выбранный JSON отдельным файлом без импорта."
    ),
    (
        "Current contours (DALE) contains applied line edits only, in image pixels. "
        "Use it in DALE; it is not a full Foundry Scene."
    ): (
        "«Исправленные контуры (DALE)» содержит текущие линии в пикселях изображения. "
        "Этот JSON предназначен для DALE, а не для импорта полной сцены в Foundry."
    ),
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
        "центра. Вверх - по часовой стрелке, вниз - обратно. Растр "
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
        "double-click it to delete. Hold Alt to use enabled angle/contour alignment buttons "
        "with their independent tolerances."
    ): (
        "Клик по линии добавляет точку; тяните кружок для перемещения, "
        "дважды щёлкните для удаления. Alt применяет включённые кнопки углов и "
        "привязки по контуру с независимыми допусками. Отпустите Alt для "
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
        "- продолжения. Клик открывает подтверждение «Отмена / Да». "
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
        "Замкнутые - связанные замкнутые области текущей геометрии. "
        "Незамкнутые - связанные группы незамкнутых линий. PNG включает "
        "каждый пиксель с альфа-каналом больше нуля после "
        "bicubic-сглаживания в пределах исходного изображения сцены."
    ),
    "Region {number}": "Область {number}",
    "Choose all closed regions or one region to highlight and export.": (
        "Выберите все замкнутые области или одну для подсветки и экспорта."
    ),
    ("Press for the first point, drag, release for the second. Snap now or when moving points."): (
        "Нажатие задаёт первую точку, отпускание - вторую. Прилипание "
        "работает при создании и переносе."
    ),
    ("Erase touched pieces between intersections or endpoints. Drag is one undo step."): (
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
    "Language": "Язык",
    "Open a scene image to begin; scene JSON is optional.": (
        "Откройте изображение сцены. JSON сцены необязателен."
    ),
    "Ready. All editing is local.": "Готово. Файлы обрабатываются на этом компьютере.",
    "Load a scene image and optional scene JSON.": (
        "Загрузить изображение сцены и необязательный JSON сцены."
    ),
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
    (
        "Connect free contour ends within this distance in original image "
        "pixels. 0 disables joining."
    ): (
        "Соединять свободные концы контуров в пределах указанного "
        "расстояния в исходных пикселях. 0 - выключено."
    ),
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
    "Export separate PNGs": "Экспорт отдельных PNG",
    "Export": "Экспортировать",
    "Export folder": "Папка экспорта",
    "Export folder:": "Папка экспорта:",
    "File already exists": "Файл уже существует",
    'Overwrite file "{name}"?': "Перезаписать файл «{name}»?",
    "Folder: {folder}": "Папка: {folder}",
    "Overwrite": "Перезаписать",
    "Create copy": "Создать копию",
    "Replace only this exported file.": "Заменить только этот экспортируемый файл.",
    "Keep the existing file and save a copy with a free name.": (
        "Сохранить прежний файл и создать копию со свободным именем."
    ),
    "Cancel this export and keep existing files unchanged.": (
        "Отменить этот экспорт, сохранив прежние файлы."
    ),
    "File export cancelled.": "Экспорт отменён.",
    "Only a regular export file can be overwritten.": "Можно перезаписать только обычный файл.",
    "Export destination changed. Try exporting again.": (
        "Файл назначения изменился. Повторите экспорт."
    ),
    "Export cannot replace an imported source file.": (
        "Экспорт не может заменить импортированный исходный файл."
    ),
    "&Look in:": "Папка:",
    "Files of &type:": "Тип файлов:",
    "All Files (*)": "Все файлы (*)",
    "Back": "Назад",
    "Forward": "Вперёд",
    "Parent Directory": "На папку выше",
    "Create New Folder": "Создать папку",
    "List View": "Список",
    "Detail View": "Таблица",
    "Name": "Имя",
    "Size": "Размер",
    "Type": "Тип",
    "Date Modified": "Дата изменения",
    "Computer": "Компьютер",
    "My Computer": "Мой компьютер",
    "Choose an existing folder or a new folder inside it.": (
        "Выберите существующую папку или укажите новую папку внутри неё."
    ),
    (
        "Choose an existing folder or enter a new folder name. "
        "PNG files are saved directly inside it."
    ): ("Выберите существующую папку или введите имя новой. PNG сохраняются прямо в неё."),
    "The export destination must be a folder.": "Путь экспорта должен указывать на папку.",
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


RUSSIAN.update(
    {
        "Rename the dataset. Export filenames follow this name.": (
            "Переименовать набор. Имена экспортируемых файлов берутся из этого названия."
        ),
        "Rename this file label without changing its contents.": (
            "Переименовать файл в наборе, сохранив его содержимое."
        ),
        "Scene JSON": "JSON сцены",
        "Scene image": "Изображение сцены",
        "Load JSON": "Загрузить JSON",
        "Replace JSON": "Заменить JSON",
        "Merge contours": "Объединить контуры",
        "Load image": "Загрузить изображение",
        "Replace image": "Заменить изображение",
        "To another dataset": "В другой набор",
        "Delete JSON": "Удалить JSON",
        "Delete image": "Удалить изображение",
        "Import datasets from project": "Импорт наборов из проекта",
        "Export dataset to project": "Экспорт набора в проект",
        "Import datasets": "Импорт наборов",
        "Export dataset": "Экспорт набора",
        "Save JSON": "Сохранить JSON",
        "Cancel this operation without changing the datasets.": (
            "Отменить эту операцию, сохранив наборы без изменений."
        ),
        "Move this file and its current edits to the chosen dataset, removing it here.": (
            "Перенести файл с текущими правками в выбранный набор, убрав его из этого набора."
        ),
        (
            "Copy this file and its current edits to the chosen dataset, "
            "keeping both copies independent."
        ): ("Скопировать файл с текущими правками в выбранный набор. Обе копии будут независимы."),
        "Create an independent empty dataset, then load its JSON or image.": (
            "Создать независимый пустой набор, затем загрузить в него JSON или изображение."
        ),
        (
            "Delete the selected dataset, including its JSON, contours, image and edits.\n"
            "External files are kept. Deleting the last dataset leaves one empty dataset."
        ): (
            "Удалить выбранный набор вместе с JSON, контурами, изображением и правками.\n"
            "Внешние файлы сохраняются. После удаления последнего набора остаётся один пустой."
        ),
        (
            "Choose a Scene JSON and load its contours into this dataset.\n"
            "You can also choose a JSON stored in a DALE project. The image and "
            "raster edits are kept."
        ): (
            "Выбрать JSON сцены и загрузить его контуры в этот набор.\n"
            "Можно выбрать JSON из проекта DALE. Изображение и правки растра сохраняются."
        ),
        (
            "Choose another JSON to replace the current JSON and all its "
            "contours, including edits.\n"
            "The image and raster edits are kept. Use Merge contours to keep the current contours."
        ): (
            "Выбрать другой JSON вместо текущего JSON и всех его контуров, включая правки.\n"
            "Изображение и правки растра сохраняются. Для дополнения используйте "
            "«Объединить контуры»."
        ),
        (
            "Choose another JSON and add its contours to the current ones, "
            "keeping existing edits.\n"
            "Exact copies of coordinates and properties are skipped. Export "
            "produces one combined JSON."
        ): (
            "Выбрать ещё один JSON и добавить его контуры к текущим, сохранив "
            "существующие правки.\n"
            "Точные копии координат и свойств пропускаются. Экспортируется один общий JSON."
        ),
        (
            "Choose an image for this dataset. Existing contours keep their coordinates.\n"
            "For a completely empty dataset, a same-name JSON beside the image is loaded too."
        ): (
            "Выбрать изображение для этого набора. Существующие контуры сохраняют координаты.\n"
            "В полностью пустой набор также загрузится JSON с тем же именем рядом с изображением."
        ),
        (
            "Choose another image to replace the current image and its raster edits.\n"
            "Contours keep their coordinates."
        ): (
            "Выбрать другое изображение вместо текущего изображения и его правок растра.\n"
            "Контуры сохраняют координаты."
        ),
        (
            "Choose another dataset, then move or copy this file with its current edits.\n"
            "Move removes it from this dataset; copy keeps both versions independent.\n"
            "An occupied destination requires explicit replacement."
        ): (
            "Выбрать другой набор, затем перенести или скопировать в него этот "
            "файл с текущими правками.\n"
            "При переносе файл убирается из этого набора; при копировании обе версии независимы.\n"
            "Занятое место требует явного подтверждения замены."
        ),
        (
            "Remove this dataset's JSON and all its contours, including edits.\n"
            "The image and raster edits are kept. External files are kept."
        ): (
            "Убрать из набора JSON и все его контуры, включая правки.\n"
            "Изображение, правки растра и внешние файлы сохраняются."
        ),
        (
            "Remove this dataset's image and all its raster edits.\n"
            "Contours and external files are kept."
        ): (
            "Убрать из набора изображение и все его правки растра.\n"
            "Контуры и внешние файлы сохраняются."
        ),
        (
            "Choose an existing DALE project and select complete datasets to add here.\n"
            "Their files and edits are copied; the current datasets are kept."
        ): (
            "Выбрать существующий проект DALE и отметить наборы для добавления сюда целиком.\n"
            "Их файлы и правки копируются; текущие наборы сохраняются."
        ),
        (
            "Add the selected dataset with its current files and edits to an "
            "existing DALE project.\n"
            "The destination stays closed and its other datasets are kept. "
            "Duplicate names get a suffix."
        ): (
            "Добавить выбранный набор с текущими файлами и правками в существующий проект DALE.\n"
            "Проект назначения остаётся закрытым, его наборы сохраняются. "
            "Совпавшие имена получают суффикс."
        ),
        (
            "Close the manager and discard unapplied changes.\n"
            "Changes already applied to the editor remain."
        ): (
            "Закрыть менеджер и отменить неприменённые изменения.\n"
            "Уже применённые в редакторе изменения остаются."
        ),
        (
            "Apply all dataset changes to the editor and keep this manager open.\n"
            "Use Save project to write the project to disk."
        ): (
            "Применить все изменения наборов в редакторе, оставив менеджер открытым.\n"
            "Для записи проекта на диск используйте «Сохранить проект»."
        ),
        (
            "Apply all dataset changes, open the selected dataset in the editor "
            "and close the manager.\n"
            "Use Save project to write the project to disk."
        ): (
            "Применить изменения всех наборов, открыть выбранный набор в "
            "редакторе и закрыть менеджер.\n"
            "Для записи проекта на диск используйте «Сохранить проект»."
        ),
        "Dataset manager": "Менеджер наборов",
        "Dataset manager…": "Менеджер наборов…",
        "New project": "Новый проект",
        "Select contour by double-click": "Выделять контур двойным кликом",
        "An independent dragged end can align perpendicular to a nearby "
        "stationary line without joining it.": (
            "Независимый перемещаемый конец можно выровнять перпендикулярно "
            "ближайшей неподвижной линии без соединения с ней."
        ),
        "A free end of an isolated line can follow its original vector "
        "within the guide tolerance.": (
            "Свободный конец отдельной линии можно перемещать вдоль её исходного "
            "вектора в пределах допуска направляющих."
        ),
        "Contour selection": "Выделение контуров",
        "Double-click a line to select only its connected contour. "
        "Double-click empty space to clear selection. "
        "Single clicks keep the current selection for moving.": (
            "Двойной клик по линии выделяет только её связанный контур. "
            "Двойной клик по пустому месту снимает выделение. "
            "Одиночные клики сохраняют текущий выбор для перемещения."
        ),
        "Double-click: select only this contour; empty space clears selection, when enabled.": (
            "Двойной клик: выделить только этот контур; по пустому месту - снять выделение, "
            "если это включено в настройках."
        ),
        "Contours are available; select lines to move.": (
            "В наборе есть контуры; выберите линии для перемещения."
        ),
        "Create an empty project with one dataset. Unsaved changes can be saved first.": (
            "Создать пустой проект с одним набором. Несохранённые изменения можно сохранить."
        ),
        "No gesture or export is in progress.": "Нет активного жеста или экспорта.",
        "Discard": "Не сохранять",
        "Dismiss": "Закрыть",
        "&Dismiss": "&Закрыть",
        "Hide right panel": "Скрыть правую панель",
        "Show right panel": "Показать правую панель",
        "Choose a dataset with its current image and contours.": (
            "Выбрать набор с его текущим изображением и контурами."
        ),
        "Open the dataset manager. Ctrl+I": "Открыть менеджер наборов. Ctrl+I",
        "No dataset": "Нет набора",
        "Close project": "Закрыть проект",
        "Cannot update datasets": "Не удалось изменить наборы",
        "Use a nonempty file-safe name of at most 240 characters.": (
            "Введите непустое имя до 240 символов, допустимое для файла."
        ),
        "A dataset with this name already exists.": "Набор с таким именем уже существует.",
        "+ New dataset": "+ Новый набор",
        "Delete dataset": "Удалить набор",
        "+ Add JSON…": "+ Добавить JSON…",
        "Replace…": "Заменить…",
        "Transfer…": "Передать…",
        "Delete": "Удалить",
        "Add…": "Добавить…",
        "Export filenames": "Имена при экспорте",
        "Export filename prefix": "Начало имени при экспорте",
        (
            "Exports add the selected-region number and PNG dimensions. "
            "Names and paths inside JSON are preserved."
        ): (
            "При экспорте добавляются номер выбранных областей и размеры PNG. "
            "Имена и пути внутри JSON сохраняются."
        ),
        "Names and paths inside JSON are preserved.": "Имена и пути внутри JSON сохраняются.",
        "Import datasets from project…": "Импорт наборов из проекта…",
        "Export dataset to project…": "Экспорт набора в проект…",
        "Drag JSON or an image onto another dataset. Changes apply together.": (
            "Перетащите JSON или изображение на другой набор. Изменения применяются вместе."
        ),
        "Apply": "Применить",
        "Open dataset": "Открыть набор",
        "Drag to another dataset, then choose Move or Copy.": (
            "Перетащите на другой набор и выберите «Перенести» или «Копировать»."
        ),
        "Empty dataset": "Пустой набор",
        "Delete this dataset and its edits? External source files are kept.": (
            "Удалить этот набор и его правки? Внешние исходные файлы сохраняются."
        ),
        "Delete JSON and all current contours? The image is kept.": (
            "Удалить JSON и все текущие контуры? Изображение останется."
        ),
        "Delete the image and its raster edits? Contours are kept.": (
            "Удалить изображение и его правки растра? Контуры останутся."
        ),
        "JSON added; existing contours are kept.": "JSON добавлен; существующие контуры сохранены.",
        "Dataset updated. Press Apply to keep changes.": (
            "Набор изменён. Нажмите «Применить», чтобы сохранить изменения."
        ),
        "Transfer JSON": "Передать JSON",
        "Transfer image": "Передать изображение",
        "Move": "Перенести",
        "Copy": "Копировать",
        "The destination already contains this component. Replace it or cancel.": (
            "В выбранном наборе такой файл уже есть. Замените его или отмените действие."
        ),
        "Move or copy the current edits to this dataset?": (
            "Перенести или скопировать текущие правки в этот набор?"
        ),
        "Replace and move": "Заменить и перенести",
        "Replace and copy": "Заменить и копировать",
        "PNG naming": "Именование PNG",
        "Which name should a region matching a group use?": (
            "Как назвать область, совпадающую с группой?"
        ),
        "Dataset name": "Имя набора",
        "Group name": "Имя группы",
        (
            "Dataset: {dataset}\nGroups: {groups}\nUnique numbers and PNG dimensions are kept."
        ): "Набор: {dataset}\nГруппы: {groups}\nУникальные номера и размеры PNG сохраняются.",
        ("Remember this naming choice. Right-click Export selected regions to change it."): (
            "Запомнить способ именования. Изменить его можно правым кликом по кнопке "
            "«Экспорт выбранных областей»."
        ),
        (
            "Choose the filename prefix for an exact group boundary match. "
            "Other regions keep the dataset name."
        ): (
            "Выбрать начало имени файла при точном совпадении границы с группой. "
            "Остальные области используют имя набора."
        ),
        "Use the dataset name for every exported PNG.": (
            "Использовать имя набора для всех выгружаемых PNG."
        ),
        "Use matching group names; other PNGs keep the dataset name.": (
            "Использовать имена совпавших групп. Остальные PNG используют имя набора."
        ),
        "The destination already contains JSON. Replace it, merge contours or cancel.": (
            "В выбранном наборе уже есть JSON. Замените его, объедините контуры "
            "или отмените действие."
        ),
        (
            "Add the current source contours to the destination without replacing its "
            "contours or image. Keep the source dataset unchanged."
        ): (
            "Добавить текущие контуры к контурам выбранного набора. Его изображение "
            "и исходный набор сохраняются."
        ),
        "The destination already has JSON or drawn contours.": (
            "В выбранном наборе уже есть JSON или нарисованные контуры."
        ),
        "Dataset changes applied. Save the project to write them to disk.": (
            "Изменения наборов применены. Сохраните проект для записи на диск."
        ),
        "Dataset exported": "Набор экспортирован",
        "Cannot export dataset": "Не удалось экспортировать набор",
        "Unknown dataset.": "Неизвестный набор.",
        "Unknown dataset component.": "Неизвестный файл набора.",
    }
)


RUSSIAN.update(
    {
        "Purpose: {description}": ("Назначение: {description}"),
        "Condition: {description}": ("Условие: {description}"),
        "Keys:": ("Клавиши:"),
        "Keys: no dedicated shortcut.": ("Клавиши: отдельного сочетания нет."),
        "No additional conditions.": ("Дополнительных условий нет."),
        "Run this command.": ("Выполнить действие."),
        "Dataset manager: create, rename, combine or transfer datasets.": (
            "Менеджер наборов: создать, переименовать, объединить или перенести наборы."
        ),
        "Open a .dale project with its files, edits and undo history.": (
            "Открыть проект .dale с файлами, правками и историей отмены."
        ),
        "Save every dataset and its editing history in the current .dale project.": (
            "Сохранить все наборы и историю правок в текущем проекте .dale."
        ),
        "Save all datasets and editing history to a new .dale project file.": (
            "Сохранить все наборы и историю правок в новый файл проекта .dale."
        ),
        ("Save closed regions as separate transparent PNGs with a coordinate manifest."): (
            "Сохранить замкнутые области отдельными PNG с прозрачностью и файлом координат."
        ),
        "Save the current dataset's contours, including unsaved edits, as JSON.": (
            "Сохранить текущие контуры набора в JSON, включая несохранённые правки."
        ),
        "Close all datasets. Unsaved changes can be saved first.": (
            "Закрыть все наборы. Перед закрытием можно сохранить изменения."
        ),
        "Exit DALE. Unsaved changes can be saved first.": (
            "Выйти из DALE. Перед выходом можно сохранить изменения."
        ),
        "Show the installed version and application information.": (
            "Показать версию и сведения о программе."
        ),
        "Drag with either mouse button to pan the scene. Wheel: zoom.": (
            "Перетаскивайте сцену любой кнопкой мыши. Колесо меняет масштаб."
        ),
        "Hover over a contour to preview connections. Click to confirm them.": (
            "Наведите на контур, чтобы увидеть возможные соединения. Клик открывает подтверждение."
        ),
        "Preview joins across all contours by extending or shortening free ends.": (
            "Найти соединения на всей сцене, продлевая или укорачивая свободные "
            "концы. Результат нужно подтвердить."
        ),
        ("Press at the first point, drag to the second and release to create a line."): (
            "Нажмите в первой точке, протяните до второй и отпустите, чтобы создать линию."
        ),
        "Press at one corner, drag to the opposite corner and release.": (
            "Нажмите в одном углу, растяните до противоположного и отпустите."
        ),
        "Press at the center, drag the radius and release to create a contour.": (
            "Нажмите в центре, растяните радиус и отпустите, чтобы создать круглый контур."
        ),
        "Delete touched line pieces up to their intersections or endpoints.": (
            "Удалить задетые части линий до ближайших пересечений или концов."
        ),
        "Drag to delete points. Two neighbours reconnect; branches are removed.": (
            "Проведите кистью, чтобы удалить точки. Две соседние линии "
            "соединятся; у развилки удалятся её ветви."
        ),
        "Toggle snapping to existing points and lines. Points take priority.": (
            "Включить или выключить прилипание к точкам и линиям. Точки имеют приоритет."
        ),
        "Make a right angle while moving a vertex or drawing a line from a contour.": (
            "Выставить прямой угол при перемещении вершины или рисовании линии от контура."
        ),
        "This button is enabled and a point is being moved or a line is being drawn.": (
            "Кнопка включена; перемещается вершина или рисуется новая линия."
        ),
        "Align a point or shape with other vertices horizontally or vertically.": (
            "Выровнять точку или фигуру по горизонтали или вертикали с другими вершинами."
        ),
        "Edit contour vertices and lines, draw shapes and close gaps.": (
            "Редактировать вершины и линии контуров, рисовать и замыкать разрывы."
        ),
        "Select closed regions, adjust their contours and export PNGs.": (
            "Перейти к выбору областей, перемещению их контуров и экспорту PNG."
        ),
        "Erase image pixels or restore them from the original image.": (
            "Перейти к стиранию изображения и восстановлению исходных пикселей."
        ),
        ("Click a closed region to select or deselect it. Empty click: clear selection."): (
            "Клик по замкнутой области выбирает её или снимает выбор. Клик по "
            "пустому месту очищает выбор."
        ),
        "Drag selected contours to move them. Image pixels stay in place.": (
            "Перетащить выбранные контуры. Изображение сцены остаётся на месте."
        ),
        (
            "Wheel: rotate selected contours by 0.1 degrees per notch; up is "
            "clockwise. Image pixels stay in place."
        ): (
            "Колесо поворачивает выбранные контуры на 0,1° за шаг; вверх - по "
            "часовой стрелке. Изображение остаётся на месте."
        ),
        "Save only selected regions as separate transparent PNGs.": (
            "Сохранить только выбранные области отдельными PNG с прозрачностью."
        ),
        "Include scene image pixels beyond the contour or cut inward.": (
            "Добавить пиксели изображения сцены за контуром или обрезать их внутрь."
        ),
        ("Click a line: add a point. Drag a point: move it. Double-click: delete it."): (
            "Клик по линии добавляет точку. Перетаскивание точки перемещает её, "
            "двойной клик удаляет."
        ),
        "Drag to make image pixels transparent.": (
            "Проведите кистью, чтобы сделать пиксели изображения прозрачными."
        ),
        "Drag to restore image pixels from the original scene image.": (
            "Проведите кистью, чтобы восстановить пиксели исходного изображения сцены."
        ),
        "Make pixels outside closed contours transparent.": (
            "Сделать пиксели снаружи замкнутых контуров прозрачными."
        ),
        "Make pixels inside closed contours transparent.": (
            "Сделать пиксели внутри замкнутых контуров прозрачными."
        ),
        "Undo the last edit in the current dataset.": (
            "Отменить последнюю правку текущего набора."
        ),
        "Reapply the last undone edit in the current dataset.": (
            "Вернуть последнюю отменённую правку текущего набора."
        ),
        "Fit the whole scene image in the editing area.": (
            "Показать изображение сцены целиком в рабочей области."
        ),
        ("Toggle contour visibility. Selected regions and highlighted lines stay visible."): (
            "Показать или скрыть контуры. Выбранные области и подсвеченные линии остаются видимыми."
        ),
        "Deselect regions and highlighted contours; cancel the current gesture.": (
            "Снять выбор областей и подсветку контуров; отменить текущий жест."
        ),
        "Open or close language and tool settings in the right panel.": (
            "Открыть или закрыть настройки языка и инструментов справа."
        ),
        "Copy selected outlines to the clipboard for use in any dataset.": (
            "Скопировать контуры выбранных областей для вставки в любой набор."
        ),
        "Click to place copied outlines. Image pixels stay in place.": (
            "Поставить копию контуров кликом на сцене. Изображение остаётся на месте."
        ),
        "An image or contour JSON is open.": ("Открыто изображение или JSON с контурами."),
        "This button is enabled and Alt is held while moving a point.": (
            "Кнопка включена; при перемещении точки зажат Alt."
        ),
        "This button is enabled and Alt is held while moving or drawing.": (
            "Кнопка включена; при перемещении или рисовании зажат Alt."
        ),
        "Contours enclose a closed region.": ("Есть замкнутая область."),
        "At least one region is selected.": ("Выбрана хотя бы одна область."),
        "Region contours have been copied to the application clipboard.": (
            "Контуры областей скопированы в буфер программы."
        ),
        "A scene image is open and at least one region is selected.": (
            "Открыто изображение сцены и выбрана хотя бы одна область."
        ),
        ("A scene image and closed contours are available; JSON preservation is off."): (
            "Есть изображение и замкнутые контуры; сохранение исходных данных JSON выключено."
        ),
        "The current dataset has contours or a scene JSON.": (
            "В текущем наборе есть контуры или JSON сцены."
        ),
        "A scene image is open; JSON preservation is off.": (
            "Открыто изображение; сохранение исходных данных JSON выключено."
        ),
        "A scene image and closed contours are available.": (
            "Есть изображение сцены и замкнутые контуры."
        ),
        "The current dataset has an edit to undo.": ("В текущем наборе есть правка для отмены."),
        "The current dataset has an undone edit to reapply.": (
            "В текущем наборе есть отменённая правка."
        ),
        "Alt: use the enabled alignment buttons.": (
            "Alt: применить включённые кнопки выравнивания."
        ),
        "Alt: align corners when Contour alignment is enabled.": (
            "Alt: выровнять углы при включённой привязке по контуру."
        ),
        "Alt: apply this alignment while dragging.": (
            "Alt: применить это выравнивание при перетаскивании."
        ),
        "Ctrl+wheel: scale selected contours.": (
            "Ctrl+колесо: изменить размер выбранных контуров."
        ),
        "Right-click this button: choose whether connected lines follow.": (
            "Правый клик по кнопке задаёт, перемещать ли связанные линии."
        ),
        "Number: angular deviation from 90 degrees, in degrees.": (
            "Значение: отклонение от 90° в градусах."
        ),
        "Number: snap distance to horizontal/vertical guides, in screen pixels.": (
            "Значение: допуск до горизонтали или вертикали вершины в экранных пикселях."
        ),
        "Number: brush diameter in screen pixels.": (
            "Значение: диаметр кисти в экранных пикселях."
        ),
        "Number: maximum endpoint movement, in screen pixels.": (
            "Значение: максимальное перемещение конца линии в экранных пикселях."
        ),
        "Number: brush diameter in original image pixels.": (
            "Значение: диаметр кисти в пикселях исходного изображения."
        ),
        "Number: snap distance in screen pixels; 0 disables snapping.": (
            "Значение: допуск прилипания в экранных пикселях; 0 выключает прилипание."
        ),
        "Number: original image pixels; positive expands, negative cuts inward.": (
            "Значение: отступ в пикселях исходного изображения; плюс расширяет, "
            "минус обрезает внутрь."
        ),
        "Ctrl+wheel: change this value.": ("Ctrl+колесо: изменить значение."),
        "Drag an endpoint to move it in every shared height layer.": (
            "Перетащить конец линии. Общая точка переместится во всех её слоях высоты."
        ),
        "Choose a height range, then drag to draw a new line in that range.": (
            "Выберите диапазон высоты, затем растяните новую линию на сцене."
        ),
        (
            "Use these tool values for every project. Enabling copies current "
            "values; disabling restores this project's values."
        ): (
            "Применять эти значения инструментов во всех проектах. Включение "
            "копирует текущие значения, выключение возвращает значения этого "
            "проекта."
        ),
        (
            "Keep other scene JSON data unchanged while editing contours. Turn "
            "off to prepare and export PNG regions."
        ): (
            "Сохранять остальные данные JSON сцены при правке контуров. Для "
            "подготовки и экспорта PNG выключите."
        ),
        "Create an empty dataset for its own image and contours.": (
            "Создать пустой набор для отдельного изображения и контуров."
        ),
        "Delete this dataset and its edits. External source files are kept.": (
            "Удалить набор со всеми правками. Исходные файлы на диске сохраняются."
        ),
        "Load contours from a JSON file or DALE project. Keep the current image.": (
            "Загрузить контуры из JSON или проекта DALE. Текущее изображение сохранится."
        ),
        "Replace the current JSON and contour edits. Keep the image.": (
            "Заменить текущий JSON и правки контуров. Изображение сохранится."
        ),
        (
            "Add contours from another JSON without replacing existing ones. "
            "Export one combined JSON; exact copies are skipped."
        ): (
            "Добавить контуры из другого JSON к текущим. Экспортируется один "
            "общий JSON; точные копии пропускаются."
        ),
        (
            "Load an image without moving existing contours. An empty dataset "
            "also loads a same-name JSON beside the image."
        ): (
            "Загрузить изображение, не сдвигая контуры. Для пустого набора также "
            "загрузится одноимённый JSON рядом с изображением."
        ),
        "Replace the image and its raster edits. Keep contour coordinates.": (
            "Заменить изображение и его правки растра. Координаты контуров сохранятся."
        ),
        ("Move or copy this file and its edits to another dataset. A copy is independent."): (
            "Перенести или скопировать файл с правками в другой набор. Копия будет независимой."
        ),
        "Remove the JSON and all contour edits. Keep the image and external files.": (
            "Удалить JSON и все правки контуров. Изображение и исходные файлы на диске сохранятся."
        ),
        "Remove the image and raster edits. Keep contours and external files.": (
            "Удалить изображение и правки растра. Контуры и исходные файлы на диске сохранятся."
        ),
        "Copy complete datasets from another .dale project into this project.": (
            "Скопировать целые наборы из другого проекта .dale в текущий."
        ),
        ("Add this dataset and its edits to an existing .dale project without opening it."): (
            "Добавить набор с правками в существующий проект .dale, не открывая его."
        ),
        ("Close without applying pending changes. Previously applied changes remain."): (
            "Закрыть без применения новых правок. Ранее применённые изменения останутся."
        ),
        (
            "Apply changes to the editor and keep this window open. Save project "
            "writes them to disk."
        ): (
            "Применить изменения в редакторе и оставить окно открытым. На диск "
            "их записывает команда сохранения проекта."
        ),
        (
            "Apply changes, open the selected dataset and close this window. "
            "Save project writes changes to disk."
        ): (
            "Применить изменения, открыть выбранный набор и закрыть окно. На "
            "диск изменения записывает команда сохранения проекта."
        ),
        "A dataset is selected; deleting the last one leaves an empty dataset.": (
            "Выбран набор; удаление последнего оставит один пустой набор."
        ),
        "The selected dataset has JSON or contours.": ("В выбранном наборе есть JSON или контуры."),
        "The selected dataset already has JSON or drawn contours.": (
            "В выбранном наборе уже есть JSON или нарисованные контуры."
        ),
        "The selected dataset has an image.": ("В выбранном наборе есть изображение."),
        "This file exists and there is another dataset to receive it.": (
            "Файл есть в наборе; существует другой набор для передачи."
        ),
        "Choose an existing source .dale project.": (
            "Выберите существующий проект .dale для импорта."
        ),
        "Choose an existing destination .dale project.": (
            "Выберите существующий проект .dale для добавления набора."
        ),
        "Select the dataset to edit.": ("Выбран набор для редактирования."),
        "Escape: close without applying pending changes.": (
            "Escape: закрыть без применения новых правок."
        ),
        "Enter: apply changes and open the selected dataset.": (
            "Enter: применить изменения и открыть выбранный набор."
        ),
        "Close this window.": ("Закрыть это окно."),
        "Escape: close this window.": ("Escape: закрыть окно."),
        "Leave contours unchanged.": ("Оставить контуры без изменений."),
        "Escape: cancel.": ("Escape: отменить действие."),
        "This button is enabled and a contour point is being moved.": (
            "Кнопка включена; перемещается точка контура."
        ),
        "This button is enabled and a point or shape is being moved or drawn.": (
            "Кнопка включена; перемещается или рисуется точка либо фигура."
        ),
    }
)


RUSSIAN.update(
    {
        (
            "Turn off Preserve JSON when joining contours in the right panel. "
            "Show the panel with the edge arrow."
        ): (
            "Выключите «Сохранять JSON при склеивании контуров» справа. "
            "Панель раскрывается стрелкой у края."
        ),
    }
)


RUSSIAN.update(
    {
        "Edit contours by height layers": "Редактировать контуры по слоям высоты",
        "Filter contour editing by height range. JSON export preserves all other scene data.": (
            "Выбрать диапазон высоты для редактирования контуров. "
            "При экспорте JSON остальные данные сцены сохраняются."
        ),
        "A scene image is open.": "Открыто изображение сцены.",
    }
)


RUSSIAN.update(
    {
        "Right-click: open tool settings.": "Правый клик: открыть настройки инструмента.",
        "Ask every time": "Спрашивать каждый раз",
        "Default action": "Действие по умолчанию",
        "Connect contours": "Связывать контуры",
        "Keep contours independent": "Оставлять контуры независимыми",
        "One PNG per adjacent group": "Один PNG для каждой смежной группы",
        "One PNG per region": "Отдельный PNG для каждой области",
        "Size to grid": "Размер под сетку",
        "Scene grid": "Сетка",
        "Grid color": "Цвет сетки",
        "Grid transparency": "Прозрачность сетки",
        "Grid line thickness (screen pixels)": "Толщина линий сетки (экранные пиксели)",
        "0% shows opaque grid lines; 100% hides them. PNG pixels stay unchanged.": (
            "0%: непрозрачные линии; 100%: невидимые. Пиксели PNG не изменяются."
        ),
        "Keep grid line thickness constant on screen when zooming the map.": (
            "Сохранять толщину линий сетки на экране при изменении масштаба карты."
        ),
        "Choose the grid line color for this dataset. PNG pixels stay unchanged.": (
            "Выбрать цвет линий сетки для текущего набора. Цвет пикселей PNG не изменяется."
        ),
        "Show the square grid used by PNG export and preview.": (
            "Показать квадратную сетку, используемую экспортом PNG и предпросмотром."
        ),
        "Grid cell size (scene pixels)": "Размер клетки (пиксели сцены)",
        (
            "Use one cell size for both axes. The grid starts at the scene origin "
            "and controls PNG padding when Size to grid is enabled."
        ): (
            "Один размер клетки для обеих осей. Сетка начинается от начала сцены "
            "и определяет прозрачные поля PNG при включённом «Размер под сетку»."
        ),
        "PNG dimensions": "Размер PNG",
        (
            "PNG bounds retain every nonzero alpha pixel after artwork offset, "
            "then expand to grid lines with transparent padding."
        ): (
            "Размер PNG учитывает все непрозрачные пиксели после отступа области, "
            "затем расширяется до линий сетки прозрачными полями."
        ),
        "Use this action automatically, or show the question on every operation.": (
            "Выполнять выбранное действие автоматически или задавать вопрос при каждой операции."
        ),
        (
            "Add transparent padding after artwork offset "
            "so both PNG corners lie on scene grid lines."
        ): (
            "Добавить прозрачные поля после учёта отступа области, "
            "чтобы оба угла PNG совпали с узлами сетки сцены."
        ),
        "Apply these tool settings.": "Применить настройки этого инструмента.",
        "Leave tool settings unchanged.": "Закрыть без изменения настроек инструмента.",
        "Close without applying settings.": "Закрыть без применения настроек.",
        "Artwork offset (source pixels)": "Отступ области (пиксели изображения)",
        "Brush diameter (source pixels)": "Диаметр кисти (пиксели изображения)",
        "Brush diameter (screen pixels)": "Диаметр кисти (экранные пиксели)",
        "Snap distance (screen pixels)": "Допуск прилипания (экранные пиксели)",
        "Angular tolerance (degrees)": "Угловой допуск (градусы)",
        "Export files": "Файлы экспорта",
        "Different regions generated the same export filename.": (
            "Разные области получили одинаковое имя файла экспорта."
        ),
        "Export JSON files": "Выгружать JSON",
        ("Include the current scene JSON and PNG placement JSON. When off, export only PNGs."): (
            "Добавить текущий JSON сцены и JSON размещения PNG. Без галочки выгружаются только PNG."
        ),
        "Export assets (*.json *.png)": "Ассеты экспорта (*.json *.png)",
        "Export assets (*.json *.png);;Scene JSON (*.json);;All files (*)": (
            "Ассеты экспорта (*.json *.png);;JSON сцены (*.json);;Все файлы (*)"
        ),
        (
            "Hover a stationary vertex during placement to keep its X/Y guides "
            "until the gesture ends."
        ): (
            "Наведите курсор на неподвижную вершину при размещении: её направляющие "
            "X/Y сохранятся до конца жеста."
        ),
        (
            "With guide alignment enabled, hover stationary vertices while dragging "
            "or placing. Their X/Y guides stay available until the gesture ends; "
            "hold Alt to align."
        ): (
            "При включённой привязке по направляющим наводите курсор на неподвижные "
            "вершины во время перемещения или размещения. Их направляющие X/Y "
            "запоминаются до конца жеста; для выравнивания зажмите Alt."
        ),
        "Alt: use guide alignment while drawing.": (
            "Alt: применить привязку по направляющим при рисовании."
        ),
        "At adjacent vertices": "По соседним вершинам",
        "Own right-angle priority": "Приоритет собственного прямого угла",
        (
            "Prefer the dragged vertex's right angle. When off, adjacent angles "
            "and horizontal/vertical guides take priority."
        ): (
            "Сначала сохранять прямой угол перемещаемой вершины. Без галочки приоритет "
            "получают соседние углы и горизонтальные/вертикальные направляющие."
        ),
        (
            "Also square angles at neighbouring vertices. When off, only angles "
            "at the dragged vertex are considered."
        ): (
            "Учитывать углы в соседних вершинах. Без галочки учитываются только "
            "углы в перемещаемой вершине."
        ),
        "Maximum endpoint movement (screen pixels)": (
            "Максимальное смещение вершины (экранные пиксели)"
        ),
        "Grid: {width} × {height} source px. Origin: {x}, {y}.": (
            "Клетка: {width} × {height} пикселей изображения. Начало сетки: {x}, {y}."
        ),
        "Size to grid requires a scene JSON with a valid grid size.": (
            "Для размера под сетку нужен JSON сцены с корректным размером клетки."
        ),
        "Size to grid requires a square scene grid.": (
            "Для размера под сетку нужна квадратная сетка сцены."
        ),
        "Size to grid does not support nonzero legacy scene shifts.": (
            "Размер под сетку не поддерживает ненулевые shiftX/shiftY старого формата сцены."
        ),
        "Grid boundaries fall between source pixels; exact grid padding is unavailable.": (
            "Границы сетки проходят между пикселями изображения. Точные поля под сетку недоступны."
        ),
        "Grid cell size is outside the supported source-pixel range.": (
            "Размер клетки выходит за допустимый диапазон пикселей изображения."
        ),
    }
)


def translate(text: str, language: str, **values) -> str:
    result = RUSSIAN.get(text, text) if language == "ru" else text
    return result.format(**values) if values else result


def format_tooltip(
    parts, language, shortcut=None, *, condition=None, keys=(), shortcut_label=None, title=None
):
    """Render the tool name, purpose, preconditions and actual controls from stable sources."""
    purpose = " ".join(translate(part, language) for part in dict.fromkeys(parts) if part)
    if not purpose:
        return ""
    caption = title or shortcut_label
    lines = [translate(caption, language).replace("&", "")] if caption else []
    lines.append(translate("Purpose: {description}", language, description=purpose))
    if condition:
        lines.append(
            translate(
                "Condition: {description}",
                language,
                description=translate(condition, language),
            )
        )
    key_lines = [translate(key, language) for key in dict.fromkeys(keys) if key]
    if shortcut is not None and not shortcut.isEmpty():
        sequence = shortcut.toString(QKeySequence.SequenceFormat.PortableText)
        key_lines.insert(
            0, f"{sequence}: {shortcut_label or translate('Run this command.', language)}"
        )
    if key_lines:
        lines.append(translate("Keys:", language))
        lines.extend(f"- {line}" for line in key_lines)
    return "\n".join(
        chunk
        for line in lines
        for chunk in wrap(
            line,
            width=68,
            subsequent_indent="  " if line.startswith("- ") else "",
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


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
            control.setProperty("dale_tooltip_title", "More tools")
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
            source_parts = parts
        else:
            original = widget.property("dale_original_tooltip")
            if original is None:
                original = widget.toolTip()
                widget.setProperty("dale_original_tooltip", original)
            source_parts = [original] if original else []
        tooltip = format_tooltip(
            source_parts,
            language,
            action.shortcut() if action is not None else None,
            condition=widget.property("dale_tooltip_condition")
            or (action.property("dale_tooltip_condition") if action is not None else None),
            keys=widget.property("dale_tooltip_keys")
            or (action.property("dale_tooltip_keys") if action is not None else [])
            or [],
            shortcut_label=action.text() if action is not None else None,
            title=widget.property("dale_tooltip_title")
            or (action.text() if action is not None else None)
            or (
                (widget.text() or widget.accessibleName())
                if isinstance(widget, QAbstractButton)
                else None
            ),
        )
        if tooltip:
            widget.setToolTip(tooltip)
