"""Russian labels and help for local Dungeon Alchemist integration."""

RUSSIAN = {
    "Only DA contours": "Только Контуры DA",
    "Export PNG files": "Выгружать PNG",
    "Enable PNG or JSON export.": "Включите выгрузку PNG или JSON.",
    "Invalid PNG export preference.": "Некорректная настройка выгрузки PNG.",
    "Invalid export file settings.": "Некорректные настройки файлов экспорта.",
    "Exporting contours…": "Выгрузка контуров…",
    "Create images for exported regions. When off, skip image rendering "
    "and export only the Scene JSON.": (
        "Создавать изображения экспортируемых областей. При отключении не строить "
        "изображения и выгружать только JSON сцены."
    ),
    "Simplifying contour parts: {done}/{total}": "Упрощение частей контуров: {done}/{total}",
    "Number: height slice, 0..10; -1 follows the ground automatically.": (
        "Число: уровень нарезки, 0..10; -1 автоматически соответствует земле."
    ),
    "Reading cached model projections": "Чтение сохранённых проекций моделей",
    "Calculating model projections": "Расчёт проекций моделей",
    "Models ready. Building placed object contours": (
        "Модели готовы. Построение контуров размещённых объектов"
    ),
    "-1 Ground (automatic)": "-1 Земля (автоматически)",
    "Height slice": "Уровень нарезки",
    "Ctrl+wheel: choose the height slice; -1 uses the ground.": (
        "Ctrl+колесо: выбрать уровень нарезки; -1 соответствует земле."
    ),
    "Import the DAM with object geometry to change its slice level.": (
        "Для смены уровня нарезки импортируйте DAM с загрузкой геометрии объектов."
    ),
    "Normalized object height: 0 is its lowest point, 10 its highest. "
    "-1 follows the local ground or floor. Changing the slice replaces "
    "edited shapes with a cached projection.": (
        "Относительная высота объекта: 0 - его нижняя точка, 10 - верхняя. "
        "-1 соответствует местной земле или полу. Смена уровня заменяет "
        "отредактированную форму сохраненной проекцией."
    ),
    "Cancelling import...": "Отмена импорта...",
    "JSON wall settings": "Параметры стен JSON",
    "JSON export only. These settings do not change display filters or contours.": (
        "Только для экспорта JSON. Эти параметры не меняют фильтры отображения и контуры."
    ),
    "Restriction direction": "Направление ограничений",
    "Both": "Оба",
    "Left": "Слева",
    "Right": "Справа",
    "Wall restrictions": "Ограничения стены",
    "Movement": "Перемещение",
    "Light": "Свет",
    "Sight": "Зрение",
    "Sound": "Звук",
    "Limited": "Ограничено",
    "Normal": "Обычно",
    "Proximity": "Близость",
    "Reverse proximity": "Обратная близость",
    "Threshold distance (feet)": "Порог расстояния (футы)",
    "Proximity threshold attenuation": "Ослабление порога видимости вблизи",
    "Door settings": "Настройка двери",
    "Door type": "Тип двери",
    "Door": "Дверь",
    "Secret door": "Секретная дверь",
    "Door state": "Состояние двери",
    "Closed": "Закрыта",
    "Opened": "Открыта",
    "None": "Нет",
    "Locked": "Заперта",
    "Door sound": "Звук двери",
    "Animation type": "Тип анимации",
    "Door animation": "Анимация двери",
    "Texture": "Текстура",
    "Flip texture": "Отразить текстуру",
    "Double door": "Двойная дверь",
    "Open direction": "Направление открытия",
    "Reversed": "Обратное",
    "Duration (ms)": "Длительность (мс)",
    "Strength": "Интенсивность",
    "Ascend": "Подъём",
    "Descend": "Опускание",
    "Slide": "Сдвиг",
    "Swing": "Распахивание",
    "Swivel": "Поворот",
    "Wall height": "Высота стены",
    "Unbounded": "Без ограничения",
    "Choose the value written to exported walls in this category.": (
        "Выбрать значение для экспортируемых стен этой категории."
    ),
    "Numeric export value; does not affect contour selection or filtering.": (
        "Числовое значение для экспорта; не влияет на выделение и фильтрацию контуров."
    ),
    "Attenuate the light and vision source radius through a proximity wall.": (
        "Уменьшать радиус источника света и зрения при прохождении через стену с порогом близости."
    ),
    "Foundry asset path written to JSON. DALE does not open or download it.": (
        "Путь ресурса Foundry для записи в JSON. DALE не открывает и не загружает этот ресурс."
    ),
    "Configure the exported door animation.": "Настроить экспортируемую анимацию двери.",
    "Export this height without a limit. Global height normalization takes priority.": (
        "Выгрузить эту высоту без ограничения. Общая нормализация высоты имеет приоритет."
    ),
    "JSON wall top must be above its base.": (
        "Верхняя высота стены JSON должна быть выше основания."
    ),
    "Invalid JSON wall numeric setting.": "Недопустимое числовое значение стены JSON.",
    "Invalid JSON wall settings.": "Недопустимые параметры стены JSON.",
    "Invalid JSON wall restriction.": "Недопустимое ограничение стены JSON.",
    "Invalid JSON wall thresholds.": "Недопустимые пороги стены JSON.",
    "Invalid JSON wall heights.": "Недопустимые высоты стены JSON.",
    "Invalid JSON door sound.": "Недопустимый звук двери JSON.",
    "Invalid JSON door animation.": "Недопустимая анимация двери JSON.",
    "Invalid category JSON wall settings.": "Недопустимые параметры стен JSON категории.",
    "Cached projection": "Проекция из кэша",
    "Computed projection": "Проекция вычислена",
    "Load object geometry": "Загрузка геометрии объектов",
    (
        "Load object geometry? Cache local models in 10-percent height layers and select "
        "the layer at the ground or floor for each object. The first import may take longer. "
        "No keeps circular contours. Unavailable models also keep circles."
    ): (
        "Загрузить геометрию объектов? Сохранить проекции слоёв по 10% высоты модели и "
        "выбрать слой на уровне земли или этажа для каждого объекта. Первая загрузка может "
        "занять больше времени. При ответе Нет останутся круги. Для недоступных моделей "
        "также сохранятся круговые контуры."
    ),
    "Reading local object geometry": "Загрузка локальной геометрии объектов",
    (
        "Object geometry is unavailable for {count} types. Their circular contours "
        "are kept. For missing Workshop items, open this map in Dungeon Alchemist "
        "and install the items there, then attach the DAM again."
    ): (
        "Геометрия недоступна для типов объектов: {count}. Для них сохранены круговые контуры. "
        "Если отсутствуют предметы Workshop, откройте эту карту в Dungeon Alchemist и "
        "загрузите их там, затем добавьте DAM повторно."
    ),
    "Select visible objects of this same type?": "Выделить видимые объекты такого же типа?",
    "Click: select visible objects of the same type.": (
        "Клик: выделить видимые объекты такого же типа."
    ),
    "Rotate selected DA objects around their own contour centers.": (
        "Вращать выбранные объекты DA вокруг собственных центров контуров."
    ),
    "Resize selected DA objects around their own contour centers.": (
        "Изменить размер выбранных объектов DA относительно собственных центров контуров."
    ),
    "Wheel: rotate each selected DA object around its own contour center.": (
        "Колесо: вращать каждый выбранный объект DA вокруг собственного центра контура."
    ),
    "Each selected DA object scales around its own contour center.": (
        "Каждый выбранный объект DA масштабируется относительно собственного центра контура."
    ),
    "Individual object centers": "Собственные центры объектов",
    "Click: toggle individual object centers.": (
        "Нажатие: включить или выключить собственные центры."
    ),
    (
        "Rotate and scale selected DA objects around their own current contour centers. "
        "Select whole contours to transform whole objects. When off, use the shared "
        "selection center. Moving and mirroring keep their usual behavior."
    ): (
        "Вращать и масштабировать выбранные объекты DA вокруг собственных центров "
        "текущих контуров. "
        "Чтобы преобразовать объекты целиком, выделите их контуры целиком. В выключенном состоянии "
        "используется общий центр выделения. Перемещение и отражение работают как обычно."
    ),
    "Select same object type": "Выделить такой же тип",
    (
        "Select all visible DA objects with the same source object type as the "
        "selection. Selecting part of a palm selects all palms of that exact type. "
        "Several selected types select their combined instances."
    ): (
        "Выделить все видимые объекты DA того же исходного типа, что и выбранные. "
        "Выделение части пальмы позволяет выбрать все пальмы именно этого типа. Если "
        "выбрано несколько типов, выделяются экземпляры каждого из них."
    ),
    ("DA contours is active and a visible object with a known source type is selected."): (
        "Активен режим Контуры DA и выделен видимый объект с известным исходным типом."
    ),
    ("Click: select matching objects in the current height and visibility scope."): (
        "Нажатие: выделить объекты такого же типа с учетом текущего слоя высоты и видимости."
    ),
    ("Scene image: {width} x {height} px\nPNG dimensions are calculated when exporting."): (
        "Изображение сцены: {width} x {height} px\nРазмеры PNG рассчитываются при экспорте."
    ),
    (
        "Export uses the current geometry and visibility settings. Editing does not "
        "prepare PNG dimensions."
    ): (
        "Экспорт использует текущую геометрию и настройки видимости. При "
        "редактировании размеры PNG не рассчитываются."
    ),
    "Opening DALE project": "Открытие проекта DALE",
    "Reading project archive": "Чтение архива проекта",
    "Checking project documents": "Проверка документов проекта",
    "Extracting and checking project files": "Извлечение и проверка файлов проекта",
    "Loading project state": "Загрузка состояния проекта",
    "Loading project datasets": "Загрузка наборов проекта",
    "Preparing project image": "Подготовка изображения проекта",
    "Preparing project contours": "Подготовка контуров проекта",
    "Loading Dungeon Alchemist": "Загрузка Dungeon Alchemist",
    "Updating Dungeon Alchemist contours": "Обновление контуров Dungeon Alchemist",
    "Updating the display": "Обновление отображения",
    "Preparing contour categories": "Подготовка категорий контуров",
    "Preparing height layers": "Подготовка слоев высоты",
    "Calculating visible regions": "Расчет видимых областей",
    "Preparing export regions": "Подготовка областей экспорта",
    "Measuring original object heights": "Определение исходной высоты объектов",
    "Reading the Dungeon Alchemist map": "Чтение карты Dungeon Alchemist",
    "Reading local object descriptions": "Чтение локальных описаний объектов",
    "Building object contours": "Создание контуров объектов",
    "Resizing object contours": "Изменение размера контуров объектов",
    "Minimum height above surface": "Минимальная высота над поверхностью",
    "Feet; 0 includes all heights.": "Футы; 0 включает объекты любой высоты.",
    (
        "Minimum original height from the local ground or floor to the object's top, "
        "in feet. Zero disables this filter. Shape edits and export height normalization "
        "do not change the measurement. Objects without a known height are included "
        "only at zero."
    ): (
        "Минимальная исходная высота от местной земли или пола до верха объекта, "
        "в футах. Ноль отключает фильтр. Правка формы и нормализация высот при экспорте "
        "не меняют измерение. Объекты с неизвестной высотой включаются только при нуле."
    ),
    "Load DAM": "Загрузить DAM",
    "Replace DAM": "Заменить DAM",
    "Delete DAM": "Удалить DAM",
    "Attach Dungeon Alchemist contours to the selected dataset.": (
        "Добавить контуры Dungeon Alchemist в выбранный набор."
    ),
    "Replace the attached Dungeon Alchemist file and its contours.": (
        "Заменить привязанный файл Dungeon Alchemist и его контуры."
    ),
    "Remove the attached Dungeon Alchemist file and its contours. Keep the external file.": (
        "Удалить привязанный файл Dungeon Alchemist и его контуры. Сохранить исходный файл."
    ),
    "Scene JSON heights": "Высоты в JSON сцены",
    "Height normalization": "Нормализация высоты",
    "Base height": "Высота основания",
    "Top height": "Высота верха",
    " ft": " фт",
    "Lower contour height in feet; step: 1 foot.": "Высота основания контура в футах; шаг: 1 фут.",
    "Upper contour height in feet; step: 1 foot.": "Высота верха контура в футах; шаг: 1 фут.",
    "Top height must be greater than base height.": (
        "Высота верха должна быть больше высоты основания."
    ),
    "Top height must be greater than base height; use whole feet.": (
        "Высота верха должна быть больше высоты основания; укажите целое число футов."
    ),
    (
        "Assign the chosen base and top heights to every exported contour. "
        "Hidden DA contours stay excluded. Project heights and PNGs are unchanged."
    ): (
        "Назначить выбранные высоты основания и верха всем экспортируемым контурам. "
        "Скрытые контуры DA остаются исключенными. Высоты проекта и PNG не меняются."
    ),
    "Dungeon Alchemist floor {floor}": "Этаж Dungeon Alchemist {floor}",
    "Dungeon Alchemist": "Dungeon Alchemist",
    "DA contours": "Контуры DA",
    "DA walls": "Стена",
    "DA trees": "Дерево",
    "DA bushes": "Куст",
    "DA rocks": "Камень",
    "Display contours": "Отображение контуров",
    "Dungeon Alchemist executable": "EXE-файл Dungeon Alchemist",
    "Choose Dungeon Alchemist": "Указать Dungeon Alchemist",
    "Dungeon Alchemist executable (*.exe)": "EXE-файл Dungeon Alchemist (*.exe)",
    "Clear Alchemist cache": "Очистить кэш алхимиста",
    "Dungeon Alchemist project": "Проект Dungeon Alchemist",
    "Load Dungeon Alchemist project": "Добавить файл Dungeon Alchemist",
    "Remove Dungeon Alchemist project": "Удалить файл Dungeon Alchemist",
    "No Dungeon Alchemist project": "Файл Dungeon Alchemist не добавлен",
    "Dungeon Alchemist projects (*.dam)": "Проекты Dungeon Alchemist (*.dam)",
    "Missing Dungeon Alchemist objects": "Не найдены объекты Dungeon Alchemist",
    "Minimum original size": "Минимальный исходный размер",
    "Map cells; 0 includes all objects.": "Клетки карты; 0 включает все объекты.",
    "Scene JSON contours": "Контуры в JSON сцены",
    "Export all": "Выгружать все",
    "Export contours": "Выгружать контуры",
    "Export contours and DA contours": "Выгружать контуры и контуры алхимиста",
    (
        "Path to Dungeon Alchemist.exe. Read local object libraries without "
        "administrator rights or downloads."
    ): (
        "Путь к Dungeon Alchemist.exe. Чтение локальных библиотек объектов "
        "без прав администратора и скачивания."
    ),
    ("Choose the installed Dungeon Alchemist.exe to resolve missing object metadata."): (
        "Укажите установленный Dungeon Alchemist.exe для чтения недостающих описаний объектов."
    ),
    (
        "Confirm removal of cached model descriptions. Existing project "
        "contours and Dungeon Alchemist files are kept."
    ): (
        "Подтвердите удаление кэша описаний моделей. Контуры проектов и файлы "
        "Dungeon Alchemist сохраняются."
    ),
    (
        "Dungeon Alchemist contours. Edit additional walls and obstacles from "
        "the attached DAM file."
    ): (
        "Контуры Dungeon Alchemist. Редактирование дополнительных стен и "
        "препятствий из добавленного DAM-файла."
    ),
    ("Show ordinary contours as stationary snapping references with 30% transparency."): (
        "Показать обычные контуры с прозрачностью 30% как неподвижные ориентиры для привязки."
    ),
    ("Show or hide this category in DA contours, Regions, Raster and exported Scene JSON."): (
        "Показать или скрыть категорию в режимах Контуры DA, Области, Растр и "
        "в экспортируемом JSON сцены."
    ),
    (
        "Clear cached Dungeon Alchemist object descriptions? Project contours "
        "and installed game files are kept."
    ): (
        "Очистить кэш описаний объектов Dungeon Alchemist? Контуры проектов и "
        "установленные файлы игры сохраняются."
    ),
    ("Choose Dungeon Alchemist.exe to read locally installed object descriptions."): (
        "Укажите Dungeon Alchemist.exe для чтения локально установленных описаний объектов."
    ),
    (
        "Open this DAM project in Dungeon Alchemist, wait for its resources "
        "to download there, then retry importing. DALE does not download "
        "Workshop items."
    ): (
        "Откройте этот DAM-проект в Dungeon Alchemist, дождитесь загрузки "
        "ресурсов там и повторите импорт. DALE не скачивает объекты Workshop."
    ),
    ("Remove the attached DAM file and its contours? The original file is kept."): (
        "Удалить привязанный DAM-файл и его контуры? Исходный файл сохраняется."
    ),
    (
        "Attach or remove Dungeon Alchemist contours in the selected dataset. "
        "Changes apply with the dataset manager."
    ): (
        "Добавить или удалить контуры Dungeon Alchemist в выбранном наборе. "
        "Изменения применяются вместе с менеджером наборов."
    ),
    (
        "Scale each current contour around its current center. 100% keeps its "
        "size. Apply commits one undo step."
    ): (
        "Масштабировать каждый текущий контур вокруг его текущего центра. "
        "100% сохраняет размер. Применение создает один шаг отмены."
    ),
    (
        "Minimum original obstacle diameter in map cells. Zero includes all. "
        "Later contour edits and scaling do not change this filter. Lowering "
        "it restores filtered contours with their edits."
    ): (
        "Минимальный исходный диаметр препятствия в клетках карты. Ноль "
        "включает все. Правки формы и масштабирование не влияют на фильтр. "
        "Снижение порога возвращает контуры с их правками."
    ),
    (
        "Choose contour sources in Scene JSON. All includes ordinary and "
        "visible DA contours. Hidden and size-filtered DA objects are never "
        "exported. Only DA contours also limits PNG regions to DA contours."
    ): (
        "Выбрать источники контуров в JSON сцены. Все включает обычные и "
        "видимые контуры DA. Скрытые и отфильтрованные по размеру объекты DA "
        "не выгружаются. «Только Контуры DA» также ограничивает области PNG контурами DA."
    ),
    ("Attach a scene image or Scene JSON before importing Dungeon Alchemist contours."): (
        "Перед импортом контуров Dungeon Alchemist добавьте изображение сцены или JSON сцены."
    ),
    ("Choose Dungeon Alchemist.exe from the installed application."): (
        "Выберите Dungeon Alchemist.exe из установленной программы."
    ),
    ("The selected Dungeon Alchemist installation has no readable object database."): (
        "В выбранной установке Dungeon Alchemist не найдена доступная для чтения база объектов."
    ),
    "Transform center": "Центр преобразования",
    "Select visible objects of the same exact type.": "Выделить видимые объекты такого же типа.",
    "Use ordinary connected contour selection.": "Использовать обычный выбор связного контура.",
    "Keep the selection from before the double-click.": "Сохранить выделение до двойного клика.",
    "Rotate selected raster regions around their common center.": (
        "Вращать выбранные растровые области относительно общего центра."
    ),
    "Resize selected raster regions around their common center.": (
        "Масштабировать выбранные растровые области относительно общего центра."
    ),
    (
        "Double-click: offer to select visible objects of the same exact type. "
        "Right-click Select contours to change the remembered answer."
    ): (
        "Двойной клик: предложить выделить видимые объекты такого же типа. "
        "Правый клик по кнопке Выбор контуров: изменить запомненный ответ."
    ),
    "Select all visible objects of this same type?": "Выделить все видимые объекты такого же типа?",
    "Select the same type": "Выделять такой же тип",
    "Select only this contour": "Выделять только этот контур",
    "Remember this answer. Right-click Select contours to change it.": (
        "Запомнить ответ. Изменить его можно правой кнопкой по кнопке Выбор контуров."
    ),
    (
        "Transform each selected object around its own contour center. "
        "When off, use the shared selection center. This setting applies only "
        "to this operation in the current mode and dataset."
    ): (
        "Преобразовывать каждый выбранный объект относительно центра его контура. "
        "Если выключено, использовать общий центр выделения. Настройка действует только "
        "для этой операции в текущем режиме и наборе."
    ),
    "Rotate selected objects around their own contour centers.": (
        "Вращать выбранные объекты относительно собственных центров контуров."
    ),
    "Resize selected objects around their own contour centers.": (
        "Масштабировать выбранные объекты относительно собственных центров контуров."
    ),
    "Wheel: rotate each selected object around its own contour center.": (
        "Колесо: вращать каждый выбранный объект относительно центра его контура."
    ),
    "Each selected object scales around its own contour center.": (
        "Каждый выбранный объект масштабируется относительно центра его контура."
    ),
    "Object slices": "Нарезка объектов",
    "Saving DALE project": "Сохранение проекта DALE",
    "Preparing project state": "Подготовка состояния проекта",
    "Serializing project datasets": "Подготовка данных наборов проекта",
    "Serializing project state": "Подготовка данных проекта",
    "Preparing project assets": "Подготовка ресурсов проекта",
    "Writing project archive": "Запись архива проекта",
    "Verifying project archive": "Проверка архива проекта",
    "Publishing project archive": "Завершение сохранения проекта",
    "Preparing Scene JSON": "Подготовка JSON сцены",
    "Preparing export identity": "Подготовка имени экспорта",
    "Applying export heights": "Применение высот экспорта",
    "Processing objects: {done}/{total}": "Обработка объектов: {done}/{total}",
    "Normalized model height: 0 is the lowest point, 10 the highest; -1 uses local ground.": (
        "Нормированная высота модели: 0 - нижняя точка, 10 - верхняя; -1 учитывает местную землю."
    ),
    "Upper model height for the combined slice range, from 0 to 10.": (
        "Верхняя высота модели для объединения срезов, от 0 до 10."
    ),
    "Size as a percentage of the selected objects at the start of this editing segment.": (
        "Размер в процентах от выбранных объектов в начале этого блока изменений."
    ),
    "Opening DA contours": "Включение контуров ДА",
    "Preparing project image and contours": "Подготовка изображения и контуров проекта",
    "Finishing project image": "Завершение подготовки изображения проекта",
    "Calculating DA contours": "Расчёт контуров ДА",
    "Preparing contour selection": "Подготовка выделения контуров",
    "Contour complexity": "Сложность контура",
    "Maximum vertices per selected closed contour; minimum 4.": (
        "Максимальное число вершин каждого выделенного замкнутого контура; минимум 4."
    ),
    "Remove assets outside map": "Удалить ассеты за пределами карты",
    "Checking map bounds": "Проверка границ карты",
    "Removed outside assets: {count}": "Удалено внешних ассетов: {count}",
    "Remove whole assets of all categories outside the map. Touching and crossing assets stay.": (
        "Удалить целиком ассеты всех типов за пределами карты. Касающиеся границы "
        "и пересекающие её ассеты сохраняются."
    ),
    "Walls": "Стены",
    "Trees": "Деревья",
    "Bushes": "Кусты",
    "Rocks": "Камни",
    "Open the movable slicing window for selected objects.": (
        "Открыть перемещаемое окно нарезки выделенных объектов."
    ),
    "Upper slice boundary": "Верхняя граница нарезки",
    "Slice range": "Диапазон нарезки",
    "Select all objects of this category": "Выбрать все объекты этого типа",
    "Selected objects: {count}": "Выделено объектов: {count}",
    "Select at least one contour to change slicing.": (
        "Выделите хотя бы один контур, чтобы изменить нарезку."
    ),
    "Mixed slice settings": "Разные настройки нарезки",
    "Close the slicing window and restore category visibility.": (
        "Закрыть окно нарезки и восстановить видимость типов объектов."
    ),
    "Size and slices affect selected objects. Changes form one undo step until "
    "the selection changes or this window closes.": (
        "Размер и нарезка меняют выделенные объекты. "
        "Изменения объединяются в один шаг отмены до смены выделения "
        "или закрытия окна."
    ),
    "These filters affect all objects of this category, regardless of selection.": (
        "Эти фильтры действуют на все объекты данного типа независимо от выделения."
    ),
    "Merge adjacent contours": "Объединять смежные контуры",
    "Only during export, combine adjacent selected regions into one PNG per "
    "group and remove their internal JSON lines. Keep the group perimeters "
    "and leave project contours unchanged.": (
        "Только при экспорте объединять смежные выбранные области в один PNG на группу "
        "и удалять их внутренние линии в JSON. Сохранять периметры групп. "
        "Контуры в проекте не изменяются."
    ),
    "Saved object settings": "Сохранённые настройки объектов",
    "Applying dataset changes": "Применение изменений наборов",
    "Click or drag a selection box to select whole DA objects.": (
        "Щелчок или рамка выделяют целые объекты DA."
    ),
    "Wheel: resize each selected object around its own contour center.": (
        "Колесо: менять размер каждого выделенного объекта относительно его центра."
    ),
    "Object slices changes the selected whole objects.": (
        "Нарезка объектов изменяет выделенные объекты целиком."
    ),
    "Choose a whole DA object or all visible objects.": (
        "Выберите целый объект DA или все видимые объекты."
    ),
    "Load object slices again for the attached Dungeon Alchemist file? "
    "Read local models and rebuild the cache. Current project contours and "
    "their edits are kept.": (
        "Загрузить нарезку заново для подключённого файла Dungeon Alchemist? "
        "Локальные модели будут прочитаны повторно для заполнения кэша. "
        "Текущие контуры проекта и их правки сохраняются."
    ),
    "Object slices are unavailable for {count} types. Current project contours are kept.": (
        "Нарезка недоступна для {count} типов объектов. Текущие контуры проекта сохраняются."
    ),
    "Applying saved object settings": "Применение сохранённых настроек объектов",
    "Use saved size, rotation, slices and complexity for {count} object types? "
    "Saved slices use local model geometry. No keeps the original settings "
    "from Dungeon Alchemist.": (
        "Применить сохранённые размер, поворот, срезы и сложность для {count} типов объектов? "
        "Для сохранённых срезов используются локальные модели. "
        "Нет - оставить исходные настройки из Dungeon Alchemist."
    ),
    "Some saved slices require unavailable local models. "
    "Their original contours and other saved parameters are kept.": (
        "Для части сохранённых срезов недоступны локальные модели. "
        "Для этих объектов сохраняются исходные контуры и применяются остальные параметры."
    ),
    "Object settings could not be saved: {error}": (
        "Не удалось сохранить настройки объектов: {error}"
    ),
    "Clear cached Dungeon Alchemist models and saved object settings "
    "(size, rotation, slices and complexity)? Project contours and installed "
    "game files are kept.": (
        "Очистить кэш моделей Dungeon Alchemist и сохранённые настройки объектов "
        "(размер, поворот, срезы и сложность)? Контуры в проектах и файлы игры сохранятся."
    ),
    "The requested contour complexity could not be built. The previous contours were kept.": (
        "Не удалось построить контуры с указанной сложностью. Предыдущие контуры сохранены."
    ),
    "This contour complexity would join separate parts. The previous contours were kept.": (
        "При такой сложности отдельные части соединились бы. Предыдущие контуры сохранены."
    ),
    "Thin objects": "Прореживание",
    "Thinning objects": "Прореживание объектов",
    "No objects to thin.": "Нет объектов для прореживания.",
    "Click: enable or disable thinning.": "Щелчок: включить или выключить прореживание.",
    "Ctrl+wheel: change thinning strength, 0..10.": (
        "Ctrl+колесо: изменить силу прореживания от 0 до 10."
    ),
    "Thin overlapping trees, bushes and rocks in the current dataset, independently of selection. "
    "Hidden objects are excluded from exports; zero restores them. Preserve the user selection.": (
        "Проредить пересекающиеся деревья, кусты и камни текущего набора независимо от выделения. "
        "Скрытые объекты исключаются из экспорта; значение 0 возвращает их. Выделение сохраняется."
    ),
    "Number: thinning strength, 0 restores all, 10 keeps disjoint objects.": (
        "Число: сила прореживания; 0 возвращает всё, 10 оставляет непересекающиеся объекты."
    ),
    "Thinning: hidden {count} of {total} objects.": (
        "Прореживание: скрыто {count} из {total} объектов."
    ),
    "Updated {done} objects. Kept {failed} objects at their previous complexity "
    "because their requested outlines could not be built.": (
        "Обновлено объектов: {done}. Для {failed} сохранена предыдущая сложность, "
        "так как не удалось построить запрошенную форму."
    ),
    "Invalid object thinning settings.": "Некорректные настройки прореживания объектов.",
    "Invalid object thinning level.": "Некорректная сила прореживания объектов.",
}
