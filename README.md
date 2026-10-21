[English](#english) | [Русский](#russian)

# DALE

<a id="english"></a>

## English

**From Dungeon Alchemist or any ordinary image - straight to your Foundry scene.**

A roof you can place separately. A building without the surrounding terrain. A room cut to its own outline. **DALE (Dungeon Alchemist Levels Export)** is a Windows desktop editor for preparing these assets from Dungeon Alchemist exports or ordinary images for use in Foundry VTT.

<img src="docs/images/readme/hero.png" alt="A working scene from village-port.dale. Contours outline the buildings; the selected building is tinted cyan." width="1000">

*A working scene from village-port.dale. Contours outline the buildings; the selected building is tinted cyan.*

Work on the image and its contours together: repair boundaries, choose the parts you need, refine transparency and export separate PNGs at the source resolution. An optional Scene JSON supplies editable walls; you can also start with an image alone.

**Open a map. Prepare its boundaries. Export the parts.** Keep ground, upper floors, roofs and other variations together as datasets, then place the resulting images in Foundry using your preferred scene setup.

**Start on Windows x64:** open [DALE/DALE.exe](DALE/DALE.exe). Keep the entire DALE folder together; Python installation is not required. Projects and source files stay local.

**For your Foundry workflow:** import the prepared images and configure their placement, levels and gameplay in Foundry. DALE edits supplied wall geometry and preserves other source Scene JSON data; it does not generate lights, portals or a finished scene. Placement JSON is a coordinate reference for manual setup.

[Editing workflow](docs/workflow.md) | [Portable startup notes](docs/portable-start.txt) | [Project format](docs/project-format.md) | [Architecture](docs/architecture.md)

Examples below show actual editor states from village-port.dale.

<details>
<summary><strong>Vertices - make the boundary fit the map</strong></summary>

Work at the level of individual points and edges when an imported outline needs a more precise fit.

- Move or insert vertices, draw lines, rectangles and polygonal circles, and erase line sections up to intersections.
- Close gaps and use point, line, guide and right-angle alignment to keep edits controlled. Angle references can include neighbouring corners.

<details>
<summary>See the example</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/vertices-before.png" alt="Before: the original corner." width="330"><br><em>Before: the original corner.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/vertices-align.png" alt="During editing: the two reference legs are highlighted while right-angle alignment is active." width="330"><br><em>During editing: the two reference legs are highlighted while right-angle alignment is active.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Contours - arrange linework as a whole</strong></summary>

Treat selected edges as a working shape, whether they form a closed outline, an open contour or several separate pieces.

- Move, scale, rotate and mirror a combined selection around its shared logical centre.
- Copy contours between datasets or open projects. The image stays in place while you adjust its linework.

<details>
<summary>See the example</summary>

<img src="docs/images/readme/contours-rotate.png" alt="A small contour rotated as one selection. The centre and cumulative rotation angle remain visible." width="660">

*A small contour rotated as one selection. The centre and cumulative rotation angle remain visible.*

</details>

</details>

<details>
<summary><strong>Regions - turn closed spaces into transparent assets</strong></summary>

Choose the enclosed parts of the map you want to use separately in Foundry: a building, a roof, a room or a custom set of cells.

- Export selected cells individually or merge adjacent selections. Keep unselected inner cells as holes; save a reusable inclusion/exclusion choice in a group.
- Adjust the artwork offset at the edge. Optional grid-sized output adds transparent padding so both corners land on scene-grid boundaries.
- PNG names contain a stable selection number and the actual image dimensions. Optional JSON output includes placement coordinates and, when supplied, the edited source Scene JSON.

<details>
<summary>See the example</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/regions.png" alt="Selected closed cells make up the building." width="330"><br><em>Selected closed cells make up the building.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/export-preview.png" alt="An isolated preview reveals the retained image and transparency before export." width="330"><br><em>An isolated preview reveals the retained image and transparency before export.</em></td>
</tr>
</table>

</details>

<details>
<summary>Example: two regions become one</summary>

Removing a shared internal boundary turns adjacent cells into one region while retaining the outer outline and image.

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/regions-merge-before.png" alt="Before: two selected adjacent regions share an internal boundary." width="330"><br><em>Before: two selected adjacent regions share an internal boundary.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/regions-merge-after.png" alt="After removing the internal contour: one closed region with the same outer outline." width="330"><br><em>After removing the internal contour: one closed region with the same outer outline.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Raster - refine the image itself</strong></summary>

Clean up the pixels around an asset, or reposition selected imagery independently of the scene walls.

- Erase and restore with round or square brushes, an adjustable soft-edge band and overall strength.
- Move, scale and rotate a raster selection with its own boundary. Preview the selected result and inspect visible tiles at native resolution.

<details>
<summary>See the example</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/raster-before.png" alt="Before: original imagery beside the contour." width="330"><br><em>Before: original imagery beside the contour.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/raster-cleanup.png" alt="After a soft eraser stroke: the checkerboard shows the newly transparent area." width="330"><br><em>After a soft eraser stroke: the checkerboard shows the newly transparent area.</em></td>
</tr>
</table>

</details>

<details>
<summary>Example: rotate the image, not just its outline</summary>

The selected imagery rotates with its independent raster boundary. The scene wall contours retain their original positions.

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/raster-rotate-before.png" alt="Before rotation: the selected raster image." width="330"><br><em>Before rotation: the selected raster image.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/raster-rotate-after.png" alt="After a 30-degree rotation: the image and its raster boundary turn together." width="330"><br><em>After a 30-degree rotation: the image and its raster boundary turn together.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Groups - return to the selections that matter</strong></summary>

Give a useful selection a name and colour instead of finding the same building again before every operation.

- Each dataset and editing mode has its own groups. Add or remove selected elements explicitly; an element can belong to several groups.
- Recall a group, reorder its place in the list and use a matching region group name when exporting. The compact manager stays over the workspace while the map moves beneath it.

<details>
<summary>See the example</summary>

<img src="docs/images/readme/groups.png" alt="The group manager beside the selected building. Group colours make saved membership visible." width="720">

*The group manager beside the selected building. Group colours make saved membership visible.*

</details>

</details>

<details>
<summary><strong>Datasets - keep one location together</strong></summary>

Organise related map images and their contours inside one .dale project rather than treating every export as a separate job.

- Switch between ground, upper floors, roofs and underground maps with a saved view for each dataset.
- Use the dataset manager to create and rename sets, transfer images or JSON, and merge contour data when needed. Save source assets, editing history, groups and settings together.

<details>
<summary>See the example</summary>

<img src="docs/images/readme/datasets.png" alt="The example project contains four datasets. The manager exposes their images and Scene JSON separately." width="720">

*The example project contains four datasets. The manager exposes their images and Scene JSON separately.*

</details>

</details>

<details>
<summary><strong>View - measure, align and inspect</strong></summary>

Keep useful visual references on the map while changing editing modes.

- Use rulers, persistent guides, a cursor crosshair and a configurable scene grid. Rulers support pixels and game-world feet, centimetres or millimetres when scene metadata permits.
- Inspect native-resolution tiles, choose a workspace background and retain each dataset's zoom and camera position. Guides and grid overlays are not burned into PNGs.

<details>
<summary>See the example</summary>

<img src="docs/images/readme/view.png" alt="Rulers, a scene grid and map-anchored guides around a working area." width="720">

*Rulers, a scene grid and map-anchored guides around a working area.*

</details>

</details>

<details>
<summary><strong>Tool settings - options where you need them</strong></summary>

A filled lower-right corner marks a tool with extra options. **Right-click the tool** to open its settings beside the map.

- Set tolerances, rotation steps, brush behaviour or export options in a nonmodal panel. Apply commits the changes; Cancel discards them.
- Remember a recurring answer, change it later or return to asking every time. Controls and contextual help are available in English and Russian.

<details>
<summary>See the example</summary>

<table>
<tr>
<td width="18%"><img src="docs/images/readme/settings-trigger.png" alt="Right-click this marked tool." width="48"><br><em>Right-click this marked tool.</em></td>
<td><img src="docs/images/readme/settings.png" alt="Right-clicking Right-angle alignment opens its tolerance and behaviour settings." width="416"><br><em>Right-clicking Right-angle alignment opens its tolerance and behaviour settings.</em></td>
</tr>
</table>

</details>

</details>

<a id="russian"></a>

## Русский

**Из Dungeon Alchemist или любой обычной картинки - прямиком на сцену Foundry.**

Крыша, которую можно разместить отдельно. Здание без окружающей земли. Комната, вырезанная точно по своему контуру. **DALE (Dungeon Alchemist Levels Export)** - настольный редактор для Windows, который помогает подготовить такие элементы из выгрузок Dungeon Alchemist или обычных изображений для Foundry VTT.

<img src="docs/images/readme/hero.png" alt="Рабочая сцена из village-port.dale. Контуры очерчивают здания; выбранное здание выделено голубым." width="1000">

*Рабочая сцена из village-port.dale. Контуры очерчивают здания; выбранное здание выделено голубым.*

Работайте с изображением и контурами вместе: исправляйте границы, выбирайте нужные части карты, уточняйте прозрачность и выгружайте отдельные PNG в исходном разрешении. JSON сцены добавляет редактируемые стены, но начать можно и с одного изображения.

**Откройте карту. Подготовьте границы. Выгрузите нужные части.** Храните поверхность, этажи, крыши и другие варианты в наборах одного проекта, а полученные изображения размещайте в Foundry согласно своему устройству сцены.

**Запуск в Windows x64:** откройте [DALE/DALE.exe](DALE/DALE.exe). Переносите папку DALE целиком; устанавливать Python не требуется. Проекты и исходники остаются на вашем компьютере.

**Для работы в Foundry:** разместите подготовленные изображения и настройте этажи и игровые свойства в самой Foundry. DALE редактирует переданную геометрию стен, сохраняя прочие данные исходного JSON сцены; свет, порталы и готовую сцену программа не генерирует. JSON размещения - справочник координат для ручной настройки.

[Рабочий процесс](docs/workflow.md) | [Запуск portable-версии](docs/portable-start.txt) | [Формат проекта](docs/project-format.md) | [Архитектура и разработка](docs/architecture.md)

Примеры ниже сняты с настоящего интерфейса на проекте village-port.dale.

<details>
<summary><strong>Вершины - подгоните границу под карту</strong></summary>

Работайте с отдельными точками и отрезками, когда исходному контуру нужна более точная форма.

- Перемещайте и добавляйте вершины, рисуйте линии, прямоугольники и многоугольные окружности, стирайте участки линий до пересечений.
- Замыкайте разрывы и используйте привязки к точкам, линиям, направляющим и прямым углам. При выравнивании можно учитывать и соседние углы.

<details>
<summary>Посмотреть пример</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/vertices-before.png" alt="До правки: исходный угол." width="330"><br><em>До правки: исходный угол.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/vertices-align.png" alt="Во время правки: две опорные линии подсвечены при действующей привязке к прямому углу." width="330"><br><em>Во время правки: две опорные линии подсвечены при действующей привязке к прямому углу.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Контуры - работайте с линиями как с целым</strong></summary>

Обращайтесь с выбранными отрезками как с одной рабочей фигурой: замкнутой, открытой или состоящей из нескольких отдельных частей.

- Перемещайте, масштабируйте, вращайте и отражайте общее выделение относительно его логического центра.
- Копируйте контуры между наборами и открытыми проектами. Изображение остаётся на месте, пока вы меняете линии поверх него.

<details>
<summary>Посмотреть пример</summary>

<img src="docs/images/readme/contours-rotate.png" alt="Небольшой контур повёрнут целиком. В центре видны опорная точка и суммарный угол вращения." width="660">

*Небольшой контур повёрнут целиком. В центре видны опорная точка и суммарный угол вращения.*

</details>

</details>

<details>
<summary><strong>Области - превратите замкнутые участки в отдельные изображения</strong></summary>

Выберите здание, крышу, комнату или несколько замкнутых ячеек, чтобы использовать их как самостоятельные элементы Foundry.

- Выгружайте ячейки отдельно или объединяйте смежные. Невыбранные внутренние ячейки останутся отверстиями; состав с исключениями можно сохранить в группе.
- Регулируйте отступ изображения. Размер под сетку добавит прозрачные поля, чтобы углы PNG совпали с границами клеток.
- PNG получают стабильный номер выделения и фактические размеры в имени. Дополнительно выгружаются JSON с координатами размещения и изменённый исходный JSON сцены.

<details>
<summary>Посмотреть пример</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/regions.png" alt="Выбранные замкнутые ячейки составляют здание." width="330"><br><em>Выбранные замкнутые ячейки составляют здание.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/export-preview.png" alt="Изолированный предпросмотр показывает сохраняемую картинку и прозрачность до выгрузки." width="330"><br><em>Изолированный предпросмотр показывает сохраняемую картинку и прозрачность до выгрузки.</em></td>
</tr>
</table>

</details>

<details>
<summary>Пример: две области становятся одной</summary>

Удаление общей внутренней границы превращает соседние ячейки в одну область, сохраняя внешний контур и изображение.

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/regions-merge-before.png" alt="До: две выбранные смежные области разделены внутренней границей." width="330"><br><em>До: две выбранные смежные области разделены внутренней границей.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/regions-merge-after.png" alt="После удаления внутреннего контура: одна замкнутая область с прежней внешней границей." width="330"><br><em>После удаления внутреннего контура: одна замкнутая область с прежней внешней границей.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Растр - доработайте само изображение</strong></summary>

Очищайте изображение и меняйте положение его частей независимо от стен сцены.

- Стирайте и восстанавливайте изображение круглой или квадратной кистью с настраиваемой мягкой кромкой и общим нажимом.
- Перемещайте, масштабируйте и вращайте растровую область с её изображением. Проверяйте предпросмотр и видимые фрагменты в исходном разрешении.

<details>
<summary>Посмотреть пример</summary>

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/raster-before.png" alt="До обработки: исходное изображение рядом с контуром." width="330"><br><em>До обработки: исходное изображение рядом с контуром.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/raster-cleanup.png" alt="После прохода мягким ластиком: шахматный фон показывает появившуюся прозрачность." width="330"><br><em>После прохода мягким ластиком: шахматный фон показывает появившуюся прозрачность.</em></td>
</tr>
</table>

</details>

<details>
<summary>Пример: вращение самой картинки</summary>

Выбранное изображение вращается вместе со своей независимой растровой границей. Контуры стен сцены сохраняют исходное положение.

<table>
<tr>
<td width="50%" valign="top"><img src="docs/images/readme/raster-rotate-before.png" alt="До вращения: выбранное растровое изображение." width="330"><br><em>До вращения: выбранное растровое изображение.</em></td>
<td width="50%" valign="top"><img src="docs/images/readme/raster-rotate-after.png" alt="После поворота на 30 градусов: изображение и его растровая граница повёрнуты вместе." width="330"><br><em>После поворота на 30 градусов: изображение и его растровая граница повёрнуты вместе.</em></td>
</tr>
</table>

</details>

</details>

<details>
<summary><strong>Группы - возвращайтесь к важным выделениям</strong></summary>

Дайте полезному выделению имя и цвет, чтобы не искать одно и то же здание перед каждой операцией.

- У каждого набора и режима свой список групп. Добавляйте и исключайте выбранные элементы явно; один элемент может входить в несколько групп.
- Выбирайте сохранённую группу, меняйте порядок списка и используйте имя совпадающей группы областей при выгрузке. Компактный менеджер остаётся над рабочей областью при перемещении карты.

<details>
<summary>Посмотреть пример</summary>

<img src="docs/images/readme/groups.png" alt="Менеджер групп рядом с выбранным зданием. Цвета помогают видеть состав сохранённых групп." width="720">

*Менеджер групп рядом с выбранным зданием. Цвета помогают видеть состав сохранённых групп.*

</details>

</details>

<details>
<summary><strong>Наборы - держите одну локацию вместе</strong></summary>

Соберите связанные изображения карты и их контуры в одном проекте .dale вместо отдельных рабочих файлов на каждый вариант.

- Переключайтесь между поверхностью, этажами, крышами и подземельем с сохранённым положением камеры для каждого набора.
- В менеджере наборов создавайте и переименовывайте наборы, переносите изображения или JSON и при необходимости объединяйте контуры. Сохраняйте исходники, историю правок, группы и настройки вместе.

<details>
<summary>Посмотреть пример</summary>

<img src="docs/images/readme/datasets.png" alt="В примере четыре набора. Менеджер показывает их изображения и JSON сцены отдельными компонентами." width="720">

*В примере четыре набора. Менеджер показывает их изображения и JSON сцены отдельными компонентами.*

</details>

</details>

<details>
<summary><strong>Вид - измеряйте, выравнивайте и проверяйте</strong></summary>

Держите полезные ориентиры на карте при переключении между режимами редактирования.

- Используйте линейки, сохраняемые направляющие, перекрестие курсора и настраиваемую сетку сцены. Линейки показывают пиксели и, при наличии данных сцены, игровые футы, сантиметры или миллиметры.
- Рассматривайте фрагменты в исходном разрешении, выбирайте фон рабочей области и возвращайтесь к сохранённому масштабу и положению камеры. Направляющие и экранная сетка не попадают в PNG.

<details>
<summary>Посмотреть пример</summary>

<img src="docs/images/readme/view.png" alt="Линейки, сетка сцены и привязанные к карте направляющие вокруг рабочего участка." width="720">

*Линейки, сетка сцены и привязанные к карте направляющие вокруг рабочего участка.*

</details>

</details>

<details>
<summary><strong>Настройки инструментов - нужные параметры рядом</strong></summary>

Заполненный нижний правый угол отмечает инструмент с дополнительными возможностями. **Нажмите на него правой кнопкой мыши**, чтобы открыть настройки рядом с картой.

- Меняйте допуски, шаг вращения, поведение кисти и параметры выгрузки в немодальной панели. Применение сохраняет изменения, отмена их отбрасывает.
- Запоминайте ответ на повторяющийся вопрос, меняйте его позже или возвращайте вариант «Спрашивать каждый раз». Интерфейс и контекстные подсказки доступны на русском и английском.

<details>
<summary>Посмотреть пример</summary>

<table>
<tr>
<td width="18%"><img src="docs/images/readme/settings-trigger.png" alt="Правый клик по этой кнопке с уголком." width="48"><br><em>Правый клик по этой кнопке с уголком.</em></td>
<td><img src="docs/images/readme/settings.png" alt="Правый клик по инструменту «Прямые углы» открывает допуск и настройки поведения привязки." width="416"><br><em>Правый клик по инструменту «Прямые углы» открывает допуск и настройки поведения привязки.</em></td>
</tr>
</table>

</details>

</details>
