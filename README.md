# Visor de Manga y Webcomic

Aplicación de escritorio (Tkinter) para traducir imágenes de manga / webcomic:

1. **Cargar** imágenes o carpetas
2. **Marcar** las secciones de texto con rectángulos
3. **OCR** automático (Tesseract) sobre cada sección
4. **Limpieza** de las áreas marcadas (LaMa inpainting), en segundo plano
5. **Traducción** local y offline (Argos Translate)
6. **Render** del texto traducido sobre la imagen limpia con fuente, tamaño y color por sección
7. **Export** de las imágenes traducidas a una carpeta nueva

El flujo es lineal: el usuario avanza por 4 pasos con un indicador de progreso
visible en la barra lateral, y puede volver atrás sin perder el trabajo.

> Para tocar la interfaz, el sistema visual está en **[DESIGN.md](DESIGN.md)**:
> los tokens, el vocabulario de `theme.py`, qué variante de botón usar en cada
> sitio y las trampas de Tk en Windows.

---

## Requisitos

- **Python 3.10+** (probado con 3.13)
- **Windows / macOS / Linux** (Tkinter viene con Python)
- Para OCR: **Tesseract** (se instala aparte, ver abajo)
- Conexión a internet solo la **primera vez** para descargar los modelos de Argos
  (~300 MB por par de idiomas). Después todo funciona offline.

---

## Instalación rápida (Windows)

Doble clic sobre `run.bat`. El script:

1. Crea un `.venv` si no existe
2. Activa el entorno virtual
3. Instala las dependencias desde `requirements.txt`
4. Crea la carpeta `logs/`
5. Avisa si Tesseract no está instalado
6. Lanza la aplicación

## Instalación manual

```bash
# Crear y activar entorno virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Lanzar
python main.py
```

### Dependencias de sistema

| Dependencia | Cómo instalar | ¿Necesaria para...? |
|-------------|---------------|---------------------|
| **Tesseract** | Windows: `winget install UB-Mannheim.TesseractOCR` o descarga desde [github.com/UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/releases). Linux: `sudo apt install tesseract-ocr tesseract-ocr-spa`. macOS: `brew install tesseract tesseract-lang` | Paso 2 → 3 (OCR). Sin Tesseract no se puede continuar desde el paso 2: se avisa y se queda ahí. |
| **Argos Translate** | Se instala vía `pip install argostranslate`. Modelos: descarga automática al pulsar **"⬇ Descargar par"** en la vista del paso 3. | Paso 3 (traducción). Sin modelos descargados la traducción devuelve el texto original. |
| **LaMa** | Se instala vía `pip install simple-lama-inpainting`. El modelo (~200 MB) se baja la primera vez que se ejecuta. | Limpieza en segundo plano, desde el paso 2 en adelante. Sin LaMa no se encola nada y la exportación usa la imagen original con texto. |

---

## Uso

### Vista general del flujo

La interfaz sigue el sistema **Modernist** de los mockups (`Traductor de
Manga - Mockups`, dirección 3a): superficies planas, esquinas rectas,
reglas de 2 px, un solo acento rojo y la página siempre sobre lienzo
oscuro.

```
┌────────────┬─────────────────────────────────────────────────┐
│ PASO 3 DE 4│  Barra de controles acoplada (42 px)            │
│ ┌────────┐ ├─────────────────────────────────────────────────┤
│ │3 Tradu-│ │                                                 │
│ │  cir   │ │  Lienzo oscuro con la página                    │
│ └────────┘ │                                                 │
│            │                                                 │
│ [secciones │                                                 │
│  del paso] │                                                 │
│            ├─────────────────────────────────────────────────┤
│ ─────────  │  Barra de estado + atajos                       │
│ [ACCIÓN →] └─────────────────────────────────────────────────┘
│  consecuencia
└────────────┘
```

Tres reglas que valen para los cuatro pasos:

- **Nada flota sobre el lienzo.** Los controles viven en la barra
  acoplada de arriba, en controles segmentados con borde de tinta.
- **La acción principal está anclada al pie del riel**, con una línea
  debajo que dice qué va a pasar al pulsarla.
- **El riel enseña un solo paso: el actual.** La cabecera dice
  **PASO n DE 4** y debajo va únicamente la fila del paso en curso,
  sobre banda de acento. Los otros tres quedan ocultos —eran 189 px de
  riel que no decían nada que no dijera ya ese «de 4»—, y ese espacio se
  lo quedan las secciones del paso: la lista de marcas, la tabla de
  traducciones o el inspector.

### Paso 1 — Inicio

- Zona de arrastre con borde discontinuo: suelta una carpeta —o imágenes
  sueltas— o usa **"Abrir carpeta"**
- El botón abre **solo** el selector de carpeta. Antes encadenaba dos
  diálogos (primero archivos, y al cancelar aparecía el de carpeta):
  cancelar es la forma de decir «ahora no», y responder con otro diálogo
  se leía como que la aplicación no lo aceptaba. Las imágenes sueltas
  siguen entrando arrastrándolas, que es un gesto deliberado
- Si hay un trabajo a medias aparece dentro de la zona un aviso con
  borde de acento y el botón **"Continuar →"**
- El riel muestra el **historial de capítulos abiertos** (hasta cinco
  fichas, la última arriba, con el número de imágenes de cada carpeta y
  la ruta completa al pasar el ratón) y el bloque **Motores** con el
  estado de Tesseract, LaMa y el par de Argos (con **⬇ Bajar** si falta)
- Pulsar una ficha reabre esa carpeta. Si ya no existe, se avisa y sale
  del historial en vez de fallar en silencio. Se recuerdan diez
  carpetas en `.last_folder`, una por línea

### Paso 2 — Marcar secciones

- Barra acoplada: **Todas / Una**, contador de página, navegación
  `◀ n/N ▶`, zoom `−` `42%` `+`, encuadre **Ventana / Ancho / Alto** y
  **Limpia / Original**. Todos los botones con texto miden lo mismo, y
  los dos marcadores —`1 / 12` y `148%`— van a un ancho fijo, así que la
  barra no se mueve al cambiar de página ni al pasar de `98%` a `100%`
- **Limpia / Original mantiene el sitio**: el zoom y la posición se
  conservan al cambiar de versión, en los dos modos, que es lo que
  permite comparar la página limpia con la original de un vistazo
- **Zoom** con `Ctrl + rueda` sobre el cursor, hasta el **800 %** de los
  píxeles reales de la imagen. El porcentaje de la barra es la escala
  frente al original, no un factor sobre el encuadre
- **Los dos modos tienen zoom y encuadre.** En modo **Todas** la tira se
  escala igual que una página suelta y **las páginas van centradas**
  sobre el mismo eje, aunque el capítulo mezcle anchos distintos
- **Desplazamiento** con la rueda (vertical), `Shift + rueda`
  (horizontal), el botón central o `Shift + clic y arrastrar`
- El encuadre inicial se elige solo: las páginas normales entran
  completas y las tiras de webtoon —760 × 15 000 px, que a ventana
  completa quedarían al 5 %— se abren ajustadas al ancho y por arriba
- El riel lista **las páginas del capítulo con sus marcas anidadas**: el
  triángulo abre y cierra cada página, el resto de la fila la activa, y
  al pulsar una marca el lienzo se desplaza hasta ella (solo si no está
  ya a la vista)
- **Las herramientas están a la derecha**, en una columna pegada a la
  página: **Editar / Ocultar / Deshacer / Limpiar todo** y, bajo su
  propio título, **Extraer texto / Re-extraer**. Cada una lleva su atajo
  impreso al lado. Estaban en el riel, que llevaba a la vez la lista de
  pasos, el árbol de marcas, el inspector de sección y seis botones; son
  las que la mano usa mientras dibuja, así que su sitio es junto al
  lienzo. La columna desaparece mientras corre el OCR — no hay nada ahí
  que se pueda pulsar durante la pasada
- **Sección seleccionada**: al elegir una marca —desde la lista o
  haciendo clic sobre ella en la página— el riel muestra su geometría
  editable (`X`, `Y`, `Ancho`, `Alto`), el **Margen** de borrado y
  **Eliminar marca**, en
  los dos modos de vista. Sobre la página, en modo **Una**, la selección
  lleva ocho tiradores: arrastra dentro para moverla y los tiradores para
  redimensionarla. Los valores fuera de la imagen se recortan y el campo
  devuelve lo que se aceptó
- **La marca seleccionada lleva un recuadro punteado alrededor: es lo
  que se va a borrar.** El rotulado casi nunca termina justo en la caja
  que se dibuja, así que la limpieza se come un margen extra; hasta ahora
  ese margen era un único número para todo el capítulo (12 px) y no se
  veía por ninguna parte. Ahora se ve, y el **Margen** del inspector lo
  ajusta **marca por marca** con un deslizador de **0 a 100 px**: un
  globo con contorno grueso puede pedir 60 mientras el resto de la
  página sigue con 12. Deslizador y no un campo de número porque la
  respuesta útil se encuentra mirando la página —arrastra hasta que el
  punteado deje libre el rótulo—, no sabiendo la cifra. El
  punteado es exactamente el rectángulo que LaMa reconstruye, no una
  aproximación. Solo aparece en la marca elegida —en los dos modos de
  vista—: una página con dieciséis globos sería un muro de halos, y el
  margen solo se mira cuando es el que se está tocando
- Una marca que nadie ha tocado **no guarda margen propio**: usa el del
  capítulo y su entrada en el sidecar queda igual que antes. Eso importa
  porque el margen entra en la firma que decide si una página hay que
  volver a limpiarla — escribir el valor que ya se estaba usando habría
  mandado el capítulo entero de vuelta a LaMa para nada
- Eliminar una marca borra también su OCR y su traducción, y **reindexa
  las que van detrás** para que no queden pegadas a la caja del vecino
- Cada marca del riel lleva un **✓** cuando ya tiene texto y un **·**
  cuando no; el tooltip enseña lo que se leyó, así que «no se extrajo
  nada» se ve aquí y no dos pasos más adelante
- **Extraer texto** lee con Tesseract solo las marcas que aún están
  vacías y **se queda en el paso 2**, para poder revisar el resultado
  antes de continuar. **Re-extraer** vuelve a leerlas todas; como eso
  reemplaza también las correcciones hechas a mano, pide confirmación
  diciendo cuántas se van a pisar
- **El texto extraído va siempre en un solo renglón.** Tesseract
  devuelve el recorte tal y como está rotulado el globo, renglón a
  renglón, pero eso no es como se lee la frase — y Argos parte por
  `\n` y traduce cada trozo por separado. `IM FINALLY \nGOLD` se une
  antes de guardarse; un guión al final de renglón (`SOME-\nTHING`) se
  va con el salto
- **Continuar proceso →** extrae el texto pendiente y pasa al paso 3.
  Mientras corre, el riel se convierte en el informe de progreso: la
  barra del OCR, la marca en curso y un registro corto con el texto
  según va saliendo; la acción pasa a ser **Cancelar proceso**
- **La limpieza no se espera.** Al salir del paso 2, las páginas cuya
  versión limpia falta o quedó desfasada se entregan a una cola que
  sigue trabajando en segundo plano mientras se traduce (ver
  [La limpieza en segundo plano](#la-limpieza-en-segundo-plano))

### Paso 3 — Revisión OCR / Traducción

- Una sola tabla con **todas las secciones del capítulo**, identificadas
  como `página·marca`, y cuatro columnas: Sección, OCR, Traducción y
  Confianza (con su banda: alta / media / baja)
- Filtros segmentados **Todas / Pendientes / Confianza baja** con el
  recuento de cada uno. Los tres miden lo mismo —lo que mida el más
  largo— y el ancho no se encoge cuando los recuentos cambian, así que
  la tira no salta bajo el cursor mientras se traduce
- Las acciones de la barra (**⌕ Extraer texto**, **↻ Re-traducir todo**,
  **⬇ Descargar par**) llevan el mismo borde de tinta que la tira de
  filtros que tienen al lado, para que se lean como botones
- **Edición en la celda**: doble clic, `Enter` guarda, `Tab` pasa a la
  siguiente celda, `Esc` cancela, `Supr` borra la traducción
- Al entrar, si hay OCR pendiente de traducir, **auto-traduce** lo que
  falte
- **⌕ Extraer texto** en la barra superior vuelve al paso 2 y lanza allí
  la extracción de lo que falte: Tesseract, las barras de progreso y la
  lista de marcas ya viven en ese paso
- El riel lleva el par **Origen → Destino**, si el modelo está instalado
  y el **progreso** de traducción
- Si no hay OCR en todo el capítulo, el problema se explica **dentro de
  la pantalla** (ruta buscada, «Elegir ruta…», «Extraer texto») con la
  salida de escribir el texto a mano
- **Continuar proceso →** avisa si aún queda limpieza en curso, sin
  bloquear: se puede pasar al render y las páginas se van sustituyendo
  por su versión limpia según terminan

### Paso 4 — Renderizado y exportación

- La página ocupa el lienzo completo; la barra acoplada lleva la
  navegación `◀ n/N ▶`, el zoom y **Traducida / Original**
- Una página que llegue aquí antes de que LaMa la termine se dibuja
  sobre el original y **cambia sola a la limpia** en cuanto está, sin
  mover el zoom ni el encuadre
- El riel es el **inspector de la sección** seleccionada: identificador y
  posición (`3 / 6`), tamaño de la caja y auto-fit, **Texto**,
  **Fuente**, **Estilo**, **Tamaño máximo** (10 – 96 pt) y **Color**
  (7 presets del sistema + "Más…")
- **Estilo** son dos conmutadores independientes, **Negrita** y
  **Cursiva**: se pueden combinar, y «normal» es tenerlos los dos
  apagados. Se guardan por sección, no por capítulo
- **Perfil** es un atajo con nombre («Diálogo», «Grito»…) para fuente,
  tamaño, color y estilo. La regla, de más fuerte a más débil, es
  `lo que la sección puso a mano > su perfil > los valores del capítulo`,
  así que asignar un perfil **no pisa** lo que esa sección ya había
  elegido, y editar un perfil alcanza a las secciones que lo usan solo en
  los campos que ellas no tocaron
- La lista de perfiles empieza vacía: **Guardar como perfil…** crea uno
  con lo que se ve en la sección seleccionada, y guardar con un nombre que
  ya existe lo edita. **A toda la página** asigna el perfil de la sección
  actual a las demás de esa página, sin tocar sus valores propios
- El **↺** que aparece junto a *Fuente*, *Estilo*, *Tamaño máximo* o
  *Color* devuelve ese campo al perfil. Solo aparece cuando la sección se
  aparta de él: si no hay nada que deshacer, no hay botón
- Negrita y cursiva **son ficheros de fuente, no un efecto**: PIL dibuja
  lo que hay en el fichero y no sintetiza nada. Si la familia elegida no
  tiene esa variante instalada, el riel lo dice — «*Tahoma* no tiene
  cursiva instalada…» — en vez de dejar que el conmutador parezca roto.
  La vista previa del lienzo aplica la misma regla, así que enseña lo
  que va a salir en el PNG y no la cursiva falsa que Tk sabe fabricar
- Todo lo que se toca en el inspector — texto, fuente, estilo, tamaño,
  color — **se ve en la página al momento**. El texto se repinta al
  dejar de escribir, sin esperar a que el campo pierda el foco
- Clic en una sección de la imagen para seleccionarla; doble clic (o
  botón derecho) la edita sobre la propia imagen
- **El cuadro de texto se puede mover y redimensionar**, con los mismos
  ocho tiradores del paso 2: arrastra dentro para moverlo, un tirador
  para cambiar su tamaño. La marca dice *qué se borra*; el cuadro, *dónde
  se escribe*, y son dos cosas distintas
- Lo que se guarda es la **diferencia respecto a la marca**, no
  coordenadas absolutas: si luego vuelves al paso 2 y mueves la marca, el
  cuadro va con ella. Devolverlo justo encima de la marca lo deja como
  estaba, sin desplazamiento
- Mientras el cuadro esté desplazado, la marca se dibuja detrás **con
  línea punteada** para tener contra qué colocarlo, y el riel enseña
  **Cuadro de texto** con su ↺. Si el cuadro se sale de lo que se limpió,
  lo dice — se permite (un grito que rebasa el globo es algo que se
  quiere) pero ahí el texto cae sobre dibujo sin borrar
- **◀ Anterior / Siguiente ▶** del inspector recorre las secciones de la
  página y **desplaza la vista hasta la que selecciona**; lo mismo al
  cambiar de página con `◀ n/N ▶`
- **Traducida / Original** conserva el zoom y la posición, igual que
  «Limpia / Original» del paso 2
- **Finalizar y exportar** abre un diálogo que dice el destino, qué se va
  a escribir y qué se omite antes de confirmar
- Al terminar, la pantalla se convierte en el **informe de exportación**:
  ruta, «Abrir carpeta», el recuento de escritas / secciones / omitidas y
  la lista de secciones que salieron sin traducir

---

## Estructura del proyecto

```
.
├── main.py                  Entrada de la app
├── run.bat                  Lanzador para Windows
├── test_smoke.py            Comprobación rápida (python test_smoke.py)
├── requirements.txt
├── logs/                    Se crea al primer arranque
└── src/
    ├── app.py               Controlador principal + ciclo de vida
    ├── config.py            Constantes (colores, fuentes, extensiones…)
    ├── workflow/
    │   └── controller.py    Estado del workflow lineal + transiciones
    ├── utils/
    │   ├── background_worker.py   Base para workers con polling Tk
    │   ├── clean_queue.py         Cola de limpieza en segundo plano,
    │   │                           propiedad del App (no de una vista)
    │   ├── crop_manager.py
    │   ├── dnd_handler.py
    │   ├── exporter.py            PNGs + sidecar JSON (con overrides per-sección)
    │   ├── image_loader.py
    │   ├── inpainter.py           LaMa wrapper + huella y caducidad de
    │   │                           la versión limpia
    │   ├── logger.py
    │   ├── marks_store.py         Sidecars JSON (schema v5) con marcas,
    │   │                           OCR, traducciones, color/family/max_pt
    │   │                           y clean_signature
    │   ├── ocr_engine.py          Wrapper de Tesseract
    │   ├── pipeline_runner.py     OCR del capítulo: recorta, lee y escribe
    │   │                           en el store, todo en su propio hilo
    │   ├── recent_paths.py
    │   ├── text_profiles.py       Perfiles de texto del usuario, en su
    │   │                           propio JSON (no en los sidecars)
    │   ├── text_renderer.py       Auto-fit de fuente (búsqueda binaria)
    │   │                           y resolve_box: el único sitio donde
    │   │                           sección > perfil > capítulo se decide
    │   ├── translation_runner.py  Worker para Argos
    │   └── translator.py          Wrapper de Argos Translate
    └── views/
        ├── theme.py               Sistema Modernist: tokens, botones,
        │                           controles segmentados, medidores,
        │                           avisos y confirmaciones modales
        ├── sidebar.py             Riel persistente: el paso actual (solo
        │                           ese), secciones y acción anclada
        ├── home_view.py           Paso 1
        ├── marks_view.py          Paso 2 + dock de herramientas a la
        │                           derecha (unifica Manga + Webcomic)
        ├── marks_canvas.py        Canvas de marcas (hereda de ZoomedCanvas)
        ├── ocr_review_view.py     Paso 3
        ├── translation_table.py   Tabla del capítulo con edición en celda
        ├── render_view.py         Paso 4 + informe de exportación
        ├── translator_canvas.py   Canvas con texto editable (paso 4)
        ├── export_dialog.py       Diálogo de «Finalizar y exportar»
        ├── zoomed_canvas.py       Base de zoom/pan con render por viewport
        └── toolbar.py             Tooltip + StatusBar
```

Tres workers, no cinco. `OcrRunner` e `InpaintRunner` existían como
workers propios y nadie los llamaba: el OCR lo hace `PipelineRunner` en
su hilo y la limpieza la hace `CleanQueue`. Los módulos legacy que
quedaron sin uso al acoplar los controles (`base_marks_view.py`,
`marks_panel.py`, `popover.py`, `floating_bar.py`, `lru_cache.py`)
están borrados.

### Comprobación rápida

```bash
python test_smoke.py
```

Cubre las piezas que no se ven al usar la app: el reparto de eventos de
`BackgroundWorker` (incluido que `detach()` descarte lo que quede en
cola), el troceo de rutas del drag & drop, la regla de precedencia de
`resolve_box` —incluido que editar un perfil no pise lo que la sección
eligió—, la ida y vuelta de `text_profiles.json` con sus casos feos (un
perfil sin nombre, un nombre duplicado, un archivo que no es JSON) y la
geometría que comparten los dos lienzos: mover y redimensionar con su
recorte, el volteo al cruzar un lado y el tamaño mínimo. También que el
diálogo modal solo diga «sí» por el botón que confirma —cerrar la
ventana o pulsar Escape es «no», y en una confirmación de borrado eso no
puede depender de la suerte—.
Imprime `OK` o revienta con un `assert`. No hay framework de pruebas y
no hace falta uno para esto.

---

## Persistencia

Cada imagen genera un sidecar `<imagen>.marks.json` con:

```json
{
  "version": 5,
  "image": "0001_989fa3f1.jpg",
  "marks": [
    { "x": 100, "y": 50, "w": 200, "h": 80, "color": "#ffcc00",
      "padding": 45 }
  ],
  "ocr_results": {
    "0": {
      "text": "Hello world",
      "confidence": 93,
      "language": "eng",
      "engine": "tesseract",
      "ran_at": "2026-08-06T14:00:00"
    }
  },
  "translations": {
    "0": {
      "text": "Hola mundo",
      "source_lang": "en",
      "target_lang": "es",
      "engine": "argos",
      "edited": false,
      "ran_at": "2026-08-06T14:01:00",
      "color": [255, 0, 0],
      "font_family": "Arial",
      "max_pt": 24,
      "bold": true,
      "profile": "Grito",
      "box_offset": [0, -30, 0, 20]
    }
  }
}
```

`color`, `font_family`, `max_pt`, `bold` e `italic` son opcionales y
sobrescriben los valores por defecto del render. Se editan en el panel del
paso 4.

La clave **solo aparece cuando alguien la puso**, igual que `padding`. Eso
distingue «sin tocar» de «puesto a este valor a propósito»: `"bold": false`
significa que esa sección va en redonda pase lo que pase, y la ausencia de
la clave significa que nadie ha opinado. La diferencia es la que permite
que el perfil de texto rellene lo que nadie tocó sin pisar lo que sí.

`profile` guarda el **nombre** de un perfil, nunca una copia de sus
valores: por eso editar un perfil alcanza a las secciones que lo usan. Un
nombre que ya no exista se lee como «ninguno», no como error. Los perfiles
en sí viven aparte, en `text_profiles.json` en la raíz del proyecto, porque
son de quien rotula y no de un capítulo.

`box_offset` es `[dx, dy, dw, dh]` **contra la marca**, no coordenadas
absolutas. La marca define qué se borra y el cuadro dónde se escribe;
guardar la diferencia es lo que hace que mover la marca en el paso 2 se
lleve el texto con ella. Ausente significa «el cuadro es la marca».

`padding` es el margen de borrado de esa marca, en píxeles de la imagen, y
también es opcional: **la clave solo aparece si el usuario la tocó**. Sin
ella la marca usa `INPAINT_PADDING_PX`, así que un capítulo que nadie haya
ajustado guarda exactamente el mismo sidecar que antes.

El `text` de `ocr_results` es **siempre un solo renglón**. La regla la aplica
el propio store en sus dos únicas puertas —`OcrEntry.from_dict` al leer y
`MarksStore.set_ocr_result` al escribir—, así que un capítulo extraído antes
de esta versión se recoge al abrirlo y no hay que volver a pasarle Tesseract.
El fichero en disco conserva sus saltos hasta que algo lo vuelva a guardar.

La versión limpia se guarda como `<imagen>.clean.png` al lado del original.

Los archivos `<nombre>.clean.<ext>` son **la versión sin texto de la página
`<nombre>`, no una página más**: no aparecen en la lista del capítulo ni se
cuentan como imágenes. La limpieza siempre escribe PNG, pero al leer se
acepta cualquier extensión soportada, así que puedes dejar en la carpeta una
página que hayas limpiado por tu cuenta. Si una `.clean` se queda huérfana
—su página original ya no está—, se abre como una imagen normal en vez de
desaparecer.

---

## La limpieza en segundo plano

**La limpieza no es un paso.** Arranca cuando el paso 2 entrega el capítulo
y sigue mientras se traduce, porque nada la necesita hasta el render: el
paso 3 trabaja solo con texto y el paso 4 dibuja sobre la página original
cuando no hay versión limpia. Un paso dedicado habría sido una pantalla en
la que el usuario no hace nada más que mirar una barra.

Cómo se comporta:

- Al salir del paso 2, **cada página marcada cuya `.clean` falte o esté
  desfasada** entra en la cola. Las que ya están al día no se rehacen, así
  que volver a «Marcar», tocar una caja y continuar cuesta esa página y
  ninguna más
- El riel muestra **Limpieza · LaMa** con su barra y la página en curso,
  en cualquier paso, y la banda desaparece sola al terminar. Es el único
  sitio que lo reporta: un capítulo que sale sin limpiar y nada que lo
  haya dicho se lee como un fallo
- Al entrar al **paso 4** con limpieza pendiente se avisa, sin bloquear.
  El render usa la original mientras tanto y **cambia a la limpia en
  cuanto cada página aterriza**, sin mover el encuadre
- Si la limpieza acaba con el **paso 2** abierto, la página recoge su
  versión limpia igual, conservando zoom y posición

**Dos cosas distintas se llaman «padding».** El **margen** de cada marca
(`INPAINT_PADDING_PX`, 12 px por defecto) es lo que se borra de más
alrededor de la caja: es el recuadro punteado del paso 2, y es el que se
edita por marca. El **contexto** (`INPAINT_DEFAULT_PADDING`, 64 px) no
borra nada; es cuánta imagen de alrededor recibe LaMa para saber con qué
rellenar. Si el margen de una marca se acerca al contexto, el recorte crece
solo para que la máscara siga entrando con sitio de sobra: una máscara
cortada en el borde del recorte deja a LaMa sin píxeles limpios con los que
fundir.

**Cómo se sabe que una limpia quedó desfasada.** El sidecar guarda
`clean_signature`, una huella de las cajas con las que se generó el archivo
(`x,y,ancho,alto`, el margen de la marca cuando lo tenga, más el padding de
contexto y el `cluster_gap` — el color no entra, porque no llega a la
máscara). El margen solo entra en la huella si alguien lo puso: plegar el
valor por defecto habría cambiado todas las huellas ya escritas y mandado
capítulos enteros de vuelta a LaMa sin que se moviera nada. Si la huella
actual no coincide, la página vuelve a la cola. En un capítulo limpiado antes de que existiera la firma,
o limpiado a mano en otra herramienta, no hay con qué comparar: entonces se
respeta el archivo salvo que las marcas se hayan guardado **después** de
escribirlo, que es la única evidencia disponible ahí.

El PNG se escribe a través de un temporal y se mueve de golpe. La limpieza
corre en segundo plano, así que cerrar la app a mitad de un guardado es
posible, y un PNG truncado se leería después como la versión limpia de la
página.

---

## Atajos de teclado

| Tecla | Acción (paso 2) |
|-------|-----------------|
| `E` | Activar / desactivar modo edición |
| `H` | Mostrar / ocultar marcas |
| `Z` | Deshacer última marca |
| `V` | Alternar Limpia / Original |
| `Supr` | Eliminar la marca seleccionada |
| `←` `→` `↑` `↓` | Mover la marca seleccionada un píxel |
| `Mayús` + flechas | Cambiar su tamaño un píxel |

Los cuatro primeros aparecen impresos junto a su botón en la columna de
**Herramientas**; todos están en la barra de estado. Ninguno se dispara
mientras escribes en un campo del inspector.

| Tecla | Acción (paso 3, en la tabla) |
|-------|------------------------------|
| Doble clic | Editar la celda de OCR o de Traducción |
| `Enter` | Guardar la celda |
| `Tab` | Guardar y pasar a la siguiente celda |
| `Esc` | Cancelar la edición |
| `Supr` | Borrar la traducción de la fila |

Zoom:

| Acción | Efecto |
|--------|--------|
| `Ctrl + rueda` | Zoom centrado en el cursor (5 % – 800 %) |
| `rueda` | Desplazar en vertical |
| `Shift + rueda` | Desplazar en horizontal |
| Botón central, o `Shift + clic y arrastrar` | Mover la vista |
| Botón `−` / `+` | Alejar / acercar sobre el centro |
| Botón `42%` | El zoom actual; púlsalo para ajustar a la ventana |
| `Ventana` / `Ancho` / `Alto` | Encuadrar la página completa, a lo ancho o a lo alto |

Todo esto funciona igual en modo **Una** y en modo **Todas**; en la tira,
`Ventana`, `Ancho` y `Alto` toman como referencia la página más ancha y la
más alta del capítulo, para que el encuadre valga para todas.

---

## Solución de problemas

### La app no arranca

- Comprueba la versión de Python: `python --version` (debe ser ≥ 3.10)
- Revisa `logs/app.log`
- Reinstala dependencias: `.venv\Scripts\python.exe -m pip install -r requirements.txt`

### OCR no disponible

- Instala Tesseract (ver tabla de dependencias de sistema)
- En Windows, la app detecta automáticamente `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Si está en otra ruta, cópiala a una de las ubicaciones estándar o añádela al PATH

### Traducción devuelve el texto original

- Abre la vista del paso 3 y pulsa **"⬇ Descargar par"** para bajar el modelo
  de Argos correspondiente al par origen → destino
- La primera descarga es grande (~300 MB) y requiere conexión a internet

### La limpieza no funciona

- LaMa necesita descargar un modelo la primera vez (~200 MB)
- Si ya lo descargaste, debería funcionar offline
- La limpieza corre **en segundo plano**: mira la banda **Limpieza ·
  LaMa** del riel para saber si sigue trabajando. Si no aparece nada al
  salir del paso 2, o LaMa no está disponible o todas las páginas ya
  estaban al día
- Para rehacer una página a mano, borra su `.clean.png` y vuelve a pasar
  por el paso 2: al continuar se detecta que falta y se encola

### La imagen exportada no tiene texto traducido

- Asegúrate de que cada sección tiene texto en la columna **Traducción** del paso 3
- Si editaste el OCR, pulsa `↻ Re-traducir` para forzar la traducción
- La exportación usa la **imagen limpia** si existe (`.clean.png`); si no, usa
  la original con un aviso

### Caracteres rotos en la consola (Windows)

- Es solo cosmético: la app funciona bien, pero `cp1252` no soporta algunos
  emojis. Los logs en `logs/app.log` están en UTF-8

---

## Notas técnicas

- **Background workers**: `PipelineRunner`, `TranslationRunner` y
  `CleanQueue` heredan de `BackgroundWorker`, que usa una cola
  thread-safe y `widget.after()` para entregar eventos al hilo de Tk.
  El hilo encola `self._emit("_on_done", …)` —el nombre del callback,
  no un objeto de evento— y el `_poll` del widget lo resuelve **en el
  momento de despachar**, así que un callback registrado más tarde por
  un `attach()` posterior sigue ganando. Antes cada worker declaraba sus
  propias dataclasses de evento y una cadena de `isinstance` para
  repartirlas: unas 250 líneas que solo movían argumentos de un hilo a
  otro
- **La cola solo se vacía si alguien hizo `attach()`**, así que **un
  worker no puede anidar a otro**: los eventos del de dentro se pierden.
  Por eso `PipelineRunner` hace el OCR él mismo —recorta, llama a
  Tesseract y escribe el resultado en el sidecar en cuanto sale, todo en
  su hilo— en vez de delegarlo a un segundo worker y esperarlo.
  `MarksStore.save()` está protegido por un lock, así que escribir desde
  ese hilo es seguro
- **`CleanQueue` la posee el `App`, no una vista.** Es el mismo problema
  visto por el otro lado: los eventos de un worker solo los vacía el
  widget que hizo `attach()`, y una vista además hace `detach()` y
  `cancel()` al destruirse. La cola de limpieza tiene que sobrevivir a
  los cambios de paso —su razón de ser es seguir mientras se traduce—,
  así que se engancha a la ventana raíz y el `App` reenvía el progreso a
  la vista en pantalla, si es que le interesa (`on_clean_page_done`,
  `on_clean_finished`)
- **Argos parte por `\n`**: `ITranslation.split_into_paragraphs` es
  literalmente `input_text.split("\n")`, y cada trozo se traduce por su
  cuenta y se vuelve a unir con `\n`. Por eso el OCR se guarda en un
  renglón: con los saltos que trae Tesseract, `| DON'T\nKNOW WHY...`
  sale como `.\nSabes por qué...` —el sentido invertido—, y unido sale
  `No sé por qué...`. Sobre las 7 secciones con salto de la página de
  ejemplo, las 7 traducciones cambian
- **Botones**: `theme.button` tiene cuatro variantes, y `outline` es la
  de por defecto. Dibuja su borde con `relief="solid"` en vez de
  `highlightthickness`, porque **Windows nunca pinta el aro de resalte de
  un `tk.Button`**; hubo una quinta variante que sí lo usaba y se veía
  sin borde en esta plataforma, así que se borró en vez de documentarla
  otra vez
  `theme.SEGMENT_CHARS` es el ancho estándar, en caracteres, de los
  segmentos con texto de una `SegmentedBar`; la etiqueta más larga de la
  tira puede subirlo, nunca bajarlo
- **Zoom + pan**: la clase `ZoomedCanvas` centraliza la transformación
  (`_base_scale * _zoom`, `_offset_x/y`) y expone `set_zoom`, `zoom_at`,
  `fit_width`, `fit_height`, `pan_by`, `image_to_canvas`,
  `canvas_to_image` y el par `viewport()` / `set_viewport()`, que dice el
  encuadre en **coordenadas de la imagen** para que sobreviva a un cambio
  de bitmap. Los límites se expresan en **escala efectiva**
  (0,05 – 8,0 sobre los píxeles reales), no como factor sobre el
  encuadre, que dependía del tamaño de la ventana
- **Render por viewport**: `_draw_viewport` recorta la imagen a la
  porción visible *antes* de escalarla, así que el bitmap nunca crece
  más que el lienzo. Escalar la página entera costaría 245 M px al
  800 %; recortando, un paso de pan cuesta ~10 ms sea cual sea el
  tamaño del escaneo. Mientras la vista se mueve se usa un filtro
  rápido y se reafina 140 ms después de que se detenga
- **El texto del paso 4 se maqueta una vez**: ajustar una caja es una
  búsqueda binaria sobre el tamaño de fuente, y cada paso abre el
  archivo de la fuente — unos 12 ms por caja. Como el overlay se
  redibuja en cada fotograma de pan, `TranslatorCanvas` guarda el
  resultado en caché contra el `TextBox` que lo produjo (que es
  `frozen`, así que sirve de clave tal cual). Desplazarse por una página
  de 9 secciones pasó de ~110 ms a ~12 ms por fotograma; se vuelve a
  maquetar cuando cambia el texto, la fuente, el tamaño o la caja, y
  sólo esa caja. Las fuentes de Tk se cachean aparte y **no se expulsan
  durante el dibujado**: un `tkfont.Font` recolectado se lleva por
  delante su fuente nombrada de Tcl y con ella los items que la usan
- **La tira vertical rasteriza igual**: `MarksView._layout_strip` coloca
  las páginas en coordenadas de tira a `_strip_scale` (centradas sobre
  la más ancha) y `_draw_strip` sólo dibuja la banda visible, una
  `PhotoImage` por página en pantalla. Un capítulo de webtoons son
  cientos de megapíxeles: escalarlo entero serían gigabytes de bitmap
  para las dos franjas que se ven. El redibujado se dispara desde
  `yscrollcommand`, así que sirve igual para la rueda, la barra, el
  arrastre y los saltos programáticos
- **Auto-fit de fuente**: `text_renderer.fit_text` hace búsqueda binaria
  entre `min_pt` y `max_pt` para encontrar el tamaño más grande que cabe
  en el rectángulo con wrap por palabras. La negrita es más ancha que la
  redonda, así que el estilo entra en la medida y forma parte de la
  clave de la caché
- **Negrita y cursiva se resuelven contra el disco**: cada familia tiene
  hasta cuatro ficheros (`segoeui.ttf`, `segoeuib.ttf`, `segoeuii.ttf`,
  `segoeuiz.ttf`) y `text_renderer` los tiene separados por estilo. El
  mapa antiguo metía `arialbd.ttf` dentro de la lista de la familia
  normal y se quedaba con el primero que existiera, que es cómo una
  página podía salir en negrita sin que nadie la pidiera. Cuando falta
  la variante, la escalera se queda **dentro de la familia** —perder la
  familia se nota más que perder la inclinación— y `resolve_style` es el
  único sitio que decide qué se va a dibujar de verdad, así que la vista
  previa, el PNG exportado y el aviso del riel no pueden contradecirse
- **Un solo resolvedor de estilo**: `text_renderer.resolve_box` es el
  único sitio que decide qué caja se dibuja, aplicando
  `sección > perfil > capítulo`. Lo llaman el exportador, la vista previa
  del lienzo y el inspector, así que no pueden discrepar — que es lo que
  pasaba cuando cada uno resolvía la regla por su cuenta y
  `export_translations` dibujaba en negro puro lo que la vista previa
  enseñaba en `#201E1D`. El `TextBox` que devuelve lleva el estilo **que
  se va a dibujar**, ya pasado por `resolve_style`, y es lo que se anota
  en el sidecar
- **Cola de modelos Argos**: el paquete `argospm` (mencionado en algunas
  guías antiguas) ya no se distribuye; las versiones modernas de
  `argostranslate` (≥ 1.7) incluyen su propio gestor como
  `argostranslate.package`

---

## Licencia

Uso personal.
