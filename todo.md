# Pendientes

Lo que falta por revisar o cambiar. Un apartado por tema: **qué**, **dónde**
(los ficheros que hay que tocar) y **qué queda por decidir** antes de empezar.

Cuando algo se termine, se mueve a *Hecho* al final con una línea de qué
cambió. Las convenciones de estilo visual están en [DESIGN.md](DESIGN.md); el
funcionamiento del flujo, en [README.md](README.md).

---

## 1 · Paso 4 (Render) · perfiles de texto

**Qué.** Un perfil guarda fuente, tamaño, color y negrita/cursiva bajo un
nombre («Diálogo», «Grito», «Narración», «Pensamiento»). Asignar un perfil a
una sección es un atajo, no una atadura: **el valor específico de la sección
manda sobre el perfil.**

**Precedencia** (de más fuerte a más débil), que es la regla que hay que
implementar y probar:

```
valor puesto a mano en la sección  >  perfil asignado  >  RenderConfig global
```

**Estado actual.** El resolvedor ya está: `resolve_box(mark, entry, config)`
(`src/utils/text_renderer.py`) es el único sitio donde la capa específica gana a
la global, y `RenderConfig` es esa capa global — que hasta ahora eran dos
atributos sueltos en el controlador (`controller.py:53-54`) copiados a mano en
tres módulos. El exportador, el lienzo y el inspector lo llaman a él.

`TranslationEntry` es la capa específica y sus campos son `None` cuando no se
han tocado — que es justo lo que hace falta para distinguir «no puesto» de
«puesto igual que el perfil». Esa distinción es toda la funcionalidad; si un
campo se rellena al asignar el perfil, la regla de precedencia se pierde.

**Lo que queda.**

- Modelo del perfil: `nombre, font_family, max_pt, color, bold, italic`.
- `TranslationEntry` — `profile: str | None`, guardando el **nombre**, no una
  copia de los valores.
- Dónde viven los perfiles: son del usuario, no del capítulo. Un JSON propio en
  la raíz. `json.dump` / `json.load` sobre un dict y poco más: `recent_paths.py`
  es largo por normalizar rutas de Windows y descartar carpetas borradas, nada
  de lo cual aplica aquí.
- `resolve_box` pasa a recibir el perfil como capa intermedia:
  `entrada > perfil > RenderConfig`. Un parámetro más, no una cuarta copia de
  la regla.
- `src/views/render_view.py` — selector de perfil en el inspector, un
  «restablecer» por campo que devuelve el campo a `None` (o sea, al perfil), un
  «Guardar como perfil…» que toma los valores de la sección seleccionada y un
  «Aplicar a toda la página».

**Decidido.**

- **Asignar a varias secciones**: botón «Aplicar a toda la página» en el
  inspector que ya existe, no una superficie nueva. Todo el capítulo de golpe,
  si hace falta, después.
- **Editar un perfil actualiza las secciones que lo usan**: sí, y sale gratis
  porque la entrada guarda el nombre. Solo cambian los campos que la sección no
  había tocado.
- **Perfiles de fábrica**: ninguno. La lista empieza vacía y se llena con
  «Guardar como perfil…» desde una sección real, en vez de con cuatro juegos de
  valores inventados que nadie pidió.

---

## 2 · Paso 4 (Render) · redimensionar el cuadro de la sección

**Qué.** Poder cambiar el tamaño y la posición del cuadro de texto en el
render, para colocarlo bien en el producto final.

**Estado actual.** El cuadro de texto **es** la marca: el render usa
`Mark.x/y/w/h` tal cual. Eso ata dos cosas que no deberían estarlo — la marca
define *qué se borra* (paso 2) y aquí hace falta definir *dónde se escribe*.

**Dónde.**

- `TranslationEntry` — el desplazamiento del cuadro respecto a la marca
  (`box_dx, box_dy, box_dw, box_dh`, todos `0` por defecto) en vez de
  coordenadas absolutas: así, si el usuario mueve la marca en el paso 2, el
  cuadro la sigue.
- `src/views/translator_canvas.py` — tiradores para arrastrar y redimensionar,
  como los del paso 2. El editor en el lienzo (`translator_canvas.py:325`) ya se
  coloca con `place` sobre las coordenadas de la marca; pasa a usar las del
  cuadro.
- `src/views/render_view.py` — campos numéricos en el inspector y un
  «restablecer al tamaño de la marca».
- `src/utils/text_renderer.py` — nada nuevo, ya recibe `TextBox` con su
  geometría.

**A decidir.**

- ¿El cuadro puede salirse del área que se limpió? Se puede, y el texto caería
  sobre dibujo sin borrar. *Propuesta: dejar que se salga* —a veces es lo que
  se quiere, un texto que rebasa el globo— pero avisar en el riel cuando pase.
- Ahora que el margen de borrado es editable por marca, el área limpiada ya
  no coincide con la caja. Conviene que el paso 4 pueda enseñarla de fondo
  mientras se coloca el cuadro de texto.

---

## 3 · Dejar el alert nativo y hacer uno con el estilo de la app

**Qué.** Sustituir `tkinter.messagebox` por un diálogo propio, con la tipografía,
los colores y los botones del resto de la aplicación. El messagebox de Tk usa el
diálogo del sistema: fuente distinta, iconos de Windows, botones «Aceptar /
Cancelar» del sistema operativo. Es lo único que rompe el aspecto de la app.

**Estado actual.** 18 llamadas, de las cuales **15 en código vivo**:

| Tipo | Sitios vivos | Qué necesita |
|---|---|---|
| `showinfo` | `app.py:404`, `home_view.py:233` y `:258`, `marks_view.py:1749` | avisar y ya |
| `showwarning` | `app.py:399`, `home_view.py:265`, `marks_view.py:1800`, `ocr_review_view.py:264` y `:644` | igual, con otro tono |
| `showerror` | `app.py:514`, `render_view.py:593` | igual |
| `askyesno` | `marks_view.py:1648` | devuelve `bool`, bloquea |
| `askokcancel` | `home_view.py:242`, `marks_view.py:1777`, `ocr_review_view.py:655` | devuelve `bool`, bloquea |

Las otras 3 están en `base_marks_view.py` (código muerto, ver el punto 4).

**El patrón ya existe.** `src/views/export_dialog.py` es exactamente esto hecho
a mano: `Toplevel` con `COLOR_BG`, borde de 2 px con `highlightthickness`,
`transient` + `grab_set` + `wait_window` para bloquear, `Escape` cancela,
`Return` confirma, `_center_on(master)`, y el resultado en `self.result`. El
trabajo es generalizarlo, no inventarlo.

**Dónde.**

- `src/views/theme.py` — es donde va, según DESIGN.md: el vocabulario de
  controles vive en `theme`, no en las vistas. Algo como
  `theme.alert(master, titulo, mensaje, level=...)` y
  `theme.confirm(master, titulo, mensaje, confirmar="…", peligro=False) -> bool`.
- `src/app.py:510` — `messagebox_safe` es el embudo de errores (5 llamadas lo
  usan). Cambiarlo ahí cubre la mitad del trabajo de golpe.
- Los 15 sitios de la tabla.

**A decidir.**

- **El respaldo nativo hay que conservarlo.** `messagebox_safe` se llama desde
  manejadores de excepción, y algunos pueden dispararse antes de que exista la
  raíz o antes de `theme.init(root)`. Un diálogo propio no se puede pintar ahí.
  *Propuesta:* `messagebox_safe` intenta el diálogo del tema y cae al
  `messagebox.showerror` de siempre si algo falla — nunca debe ser el error
  quien se coma el aviso del error.
- Los niveles: DESIGN.md §8 ya tiene `info` / `working` / `success` / `warning`
  / `error` para la barra de estado. El diálogo debería usar los mismos, sin
  iconos: una banda o un rótulo de color, como el resto de la app.
- ¿Los avisos de «ya está» (`showinfo`) merecen un diálogo modal, o van mejor a
  la barra de estado que ya existe? Un modal para decir «exportado» interrumpe
  sin necesidad. *Propuesta:* revisar los cuatro `showinfo` uno por uno; varios
  probablemente sobran.
- Los botones: el que confirma es `primary`; si la acción borra o descarta,
  DESIGN.md pide que el rótulo diga qué hace («Descartar cambios»), no «Sí».

---

## 4 · Revisar el uso del tema

Del repaso de DESIGN.md contra el código. Nada de esto rompe la aplicación;
son incoherencias con el sistema visual ya documentado.

**Ficheros muertos — ruido, no defectos.** `floating_bar.py`, `marks_panel.py`
y `base_marks_view.py` concentran casi todas las infracciones (`tk.Button`
crudo, tuplas de fuente literales, `#666666`, `#9a9a9a`), pero el README ya los
marca como *legacy, sin uso*: ningún módulo activo los importa. **A decidir: se
borran o se dejan.** Borrarlos quita 3 de los 4 hallazgos de golpe, y también
los 3 `messagebox` del punto 3.

**Código vivo.**

- **`variant="secondary"` en botones que van solos** — la trampa de Windows de
  DESIGN.md §7: Tk no pinta el `highlightthickness` de un `tk.Button` en
  Windows, así que un `secondary` suelto se ve *sin borde*. Sitios a revisar:
  `export_dialog.py:130` (Cancelar, junto al primario), `marks_view.py:714`
  (Eliminar marca, sobre el riel), `render_view.py:278` y `:283` (Anterior /
  Siguiente), `sidebar.py:403` y `:619`, y los `set_footer(variant="secondary")`
  de `marks_view.py:854` y `render_view.py:682`. Si están sobre el fondo del
  riel sin contenedor con borde, la regla dice `outline`.
- **`toolbar.py:31-32`** — `TOOLTIP_BG "#201e1d"` y `TOOLTIP_FG "#f3f2f2"` son
  los valores de `COLOR_TEXT` / `COLOR_BG` copiados a mano. Deben referenciar
  los tokens.
- **`toolbar.py:33, 176-178, 351, 362`** y **`translator_canvas.py:328`** —
  tuplas de fuente literales en vez de `theme.body_font` / `theme.heading_font`.
- **`toolbar.py:209`, `floating_bar.py:66`** — `disabledforeground="#666666"`
  sin token. Falta un token de texto deshabilitado en `config.py`.
- **`sidebar.py:80-81`** — `"#ffffff"` y `"#ffd8d0"` en la fila del paso activo.
  El segundo no está en la rampa; o se añade como token o se sustituye por
  `ACCENT_100`.
- **`SPACE_1 … SPACE_8`** (`src/config.py`) están declarados y **no se usan en
  ningún sitio**. O se adoptan o se borran; declarados sin usar solo confunden.

**Excepción deliberada, no defecto.** `translator_canvas.py:325-331`: el editor
de texto sobre el lienzo es blanco con texto negro a propósito — imita la
página final, no la interfaz. Conviene anotarlo en DESIGN.md para que no se
«corrija» más adelante.

---

## 5 · Paso 2 (Marcar) · la rueda no desplaza mientras se marca

**Qué.** Con el modo de edición encendido —o sea, justo mientras se están
añadiendo marcas— la rueda del ratón no mueve la imagen. Hay que apagar la
edición, desplazarse y volver a encenderla.

**Estado actual.** Son dos huecos distintos, uno por cada modo de la vista:

- **«Todas» (la tira).** `marks_view.py:1176` engancha la rueda con `bind_all`,
  y el manejador `_strip_mousewheel` (`marks_view.py:1490`) se sale en la
  primera línea si `self._edit_state` está activo. La condición es literalmente
  «mientras marcas, no desplaces».
- **«Una» (página suelta).** La rueda la atiende `ZoomedCanvas._on_wheel`
  (`zoomed_canvas.py:493`), que sí funciona con la edición encendida, pero
  devuelve `None` sin hacer nada cuando `can_pan_y()` es falso —es decir,
  cuando la página cabe entera en el lienzo. Y el respaldo de `bind_all`
  tampoco actúa, porque también se sale si el modo no es `MODE_ALL`. Resultado:
  la rueda no hace absolutamente nada.

**Dónde.**

- `src/views/marks_view.py:1490` — la condición del manejador.
- `src/views/marks_view.py:1176` — el `bind_all`.
- `src/views/zoomed_canvas.py:493` — el caso de «no hay nada que desplazar».

**A decidir.**

- ¿Por qué bloquea la edición? Lo razonable sería no mover la tira **en medio
  de un arrastre**, que es cuando el desplazamiento estropearía el rectángulo
  que se está dibujando. *Propuesta: condicionarlo al arrastre en curso*, no al
  modo de edición entero.
- En «Una», cuando la página cabe y no hay nada que desplazar, ¿la rueda pasa a
  la página anterior o siguiente? Es lo que la rueda significa en un lector de
  cómic. *Propuesta: sí.*
- `bind_all` es una atadura global: se dispara para cualquier widget de la
  aplicación. `sidebar.py:348` ya guarda y restaura el enganche anterior para
  convivir con este, señal de que hay dos manejadores globales disputándose la
  rueda. Conviene decidir si la tira se engancha a su propio lienzo y se acaba
  la disputa.

---

## 6 · Paso 3 (Traducir) · el texto largo se corta en vez de seguir abajo

**Qué.** Cuando una traducción no cabe en el ancho de la columna, el final
desaparece. Debería continuar en otra línea.

**Estado actual.** Hay dos cortes, uno encima del otro:

- `_truncate` (`translation_table.py:386`) recorta a `PREVIEW_LEN = 120`
  caracteres y añade «…». Ese es explícito y se quita cuando se quiera.
- Debajo hay otro que no se quita: **`ttk.Treeview` no sabe partir líneas.**
  Cada celda es un renglón, el alto de fila lo fija el estilo
  (`theme.py:117`, `rowheight=30`) y un `\n` dentro del valor no se dibuja.
  Ensanchar la columna solo mueve el problema.
- Relacionado: el editor en línea es un `tk.Entry` de un solo renglón
  (`translation_table.py:282`), así que al corregir un texto largo tampoco se
  ve entero.

**Dónde.**

- `src/views/translation_table.py` — casi todo el trabajo.
- `src/views/theme.py:117` — `rowheight`, si el alto pasa a ser variable.

**A decidir.**

- La decisión de fondo, porque el Treeview no da más de sí:
  - **(a)** Sustituir la tabla por una lista hecha con marcos y un `tk.Text`
    por fila. Da salto de línea y edición de varios renglones, pero es rehacer
    el widget entero con sus filtros, sus etiquetas de color y su edición en
    línea.
  - **(b)** Dejar el Treeview y enseñar el texto completo en otro sitio: un
    panel de detalle bajo la tabla con la sección seleccionada.
    *Propuesta: empezar por (b)* —es barato y cubre el leer— y dejar (a) para
    si lo que de verdad hace falta es editar textos largos ahí mismo.
- Si el texto pasa a partirse, ¿desaparece `PREVIEW_LEN` o se queda un tope de
  dos o tres renglones con «…» al final? Sin tope, una sección larga empuja al
  resto del capítulo fuera de la pantalla.
- El editor debería ser de varios renglones en cualquiera de los dos caminos.
  Antes de eso hay que mirar qué pasa con un `\n` escrito a mano: el OCR se
  normaliza a un renglón (`to_single_line`) porque Argos parte por ahí, y el
  render vuelve a repartir el texto por su cuenta.

---

## Hecho

- **Paso 1 · carpeta reciente**, **`*.clean.*` como versión limpia**,
  **centrado y zoom de la tira**, **marcas como sublista de páginas** — ver el
  README.
- **El riel enseña un solo paso** — los otros tres se construyen y se dejan sin
  empaquetar; libera 189 px.
- **El OCR va siempre en un solo renglón** — `to_single_line` en
  `marks_store.py`, aplicado en las dos únicas puertas (`from_dict` al leer,
  `set_ocr_result` al escribir), porque Argos parte por `\n` y traduce cada
  trozo sin contexto.
- **DESIGN.md** — el sistema visual escrito.
- **Paso 2 · margen de borrado por marca** — cada marca dibuja el
  recuadro punteado de lo que se va a borrar —solo en la marca
  seleccionada— y el deslizador **Margen** (0–100 px) del inspector lo
  ajusta una por una. El margen vive en `Mark.padding`
  (`None` = el del capítulo), se resuelve en un único sitio
  (`Mark.erase_padding`) y solo entra en `clean_signature` cuando alguien
  lo puso, para no re-limpiar capítulos que nadie tocó.
- **Paso 4 · negrita y cursiva por sección** — dos conmutadores
  independientes en el inspector (`Negrita`, `Cursiva`); «normal» es
  tenerlos los dos apagados y la combinación de ambos es legítima.
  `text_renderer` pasó a tener las variantes separadas por estilo
  (`familia → {regular, bold, italic, bold_italic}`), lo que de paso mata
  el error latente de que `arialbd.ttf` viviera dentro de la lista de la
  familia normal. Como PIL no sintetiza nada, `resolve_style` decide en
  un único sitio qué se va a dibujar de verdad, y con eso el riel avisa
  cuando la familia no tiene la variante en vez de que el conmutador
  parezca roto. `bold`/`italic` son `None` mientras nadie los toque, que
  es justo la distinción que necesitan los perfiles del punto 1.
- **Un solo resolvedor de estilo** — `resolve_box(mark, entry, config)` en
  `text_renderer.py` es el único sitio donde «lo que puso la sección» gana a
  «lo que dice el capítulo», y `RenderConfig` es esa capa global. Antes la regla
  estaba copiada en el exportador, en el lienzo y cuatro veces sueltas en el
  inspector, y ya no coincidían: la exportación dibujaba en negro puro y la
  vista previa en `#201E1D`, porque `export_translations` tenía su propio
  `text_color=(0,0,0)` por defecto que nadie le pasaba. El `TextBox` que
  devuelve lleva el estilo **que se va a dibujar**, no el que se pidió, así que
  la vista previa, el PNG y el sidecar no pueden discrepar.
- **Paso 1 · el botón abre solo la carpeta** — se quitó el
  `askopenfilenames` que iba delante (`app.py:423`), el rótulo pasó a «Abrir
  carpeta» y el diálogo usa `mustexist=True`. Arrastrar imágenes sueltas
  sigue funcionando: eso es un gesto deliberado, no un diálogo cancelado.
