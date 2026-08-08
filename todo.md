# Pendientes

Lo que falta por revisar o cambiar. Un apartado por tema: **qué**, **dónde**
(los ficheros que hay que tocar) y **qué queda por decidir** antes de empezar.

Cuando algo se termine, se mueve a *Hecho* al final con una línea de qué
cambió. Las convenciones de estilo visual están en [DESIGN.md](DESIGN.md); el
funcionamiento del flujo, en [README.md](README.md).

**Ahora mismo no hay ninguno.** Lo último cerrado está el primero de la lista
de abajo.

---

## Hecho

- **Paso 3 · el texto largo** — la celda se cortaba y no había dónde ver el
  resto. El corte de abajo no se quita: un `ttk.Treeview` no parte líneas
  —cada celda es un renglón, el alto lo fija el estilo y un `\n` dentro del
  valor ni se dibuja—, así que ensanchar la columna solo movía el problema.
  La fila se queda entonces en vista previa a propósito, con su recorte a
  `PREVIEW_LEN`, y el texto entero pasa a un **panel bajo la tabla** con la
  sección seleccionada. Se edita además de leerse, porque un texto que no
  cabía en la celda tampoco cabe en el `Entry` de un renglón que abre el
  doble clic; son dos áreas de varios renglones que guardan con `Ctrl+Enter`
  —`Enter` mete un salto— o al salir del área. Guardar escribe contra la fila
  que el panel tenía **cargada** y no contra la seleccionada, que al cambiar
  de fila no son la misma; y `_detail_loaded` se actualiza *antes* de avisar
  a la vista, porque el aviso repinta la tabla y la repintada vuelve a pasar
  por el guardado. En la traducción un `\n` escrito a mano se respeta y llega
  al render (`_wrap` parte por él antes de repartir); en el OCR no, que se
  sigue normalizando a un renglón por lo de Argos. No hizo falta tocar
  `rowheight` ni cambiar el widget de la tabla.

- **Un solo dueño de la rueda** — `bind_all` escribe en la etiqueta `all` de
  Tk, que **solo guarda un script por secuencia**, así que dos dueños no la
  comparten: el segundo sustituye al primero. El riel lo sorteaba
  guardándose el script anterior al entrar el puntero y devolviéndolo al
  salir, y ahí estaba el fallo: si la vista se destruía entre el `<Enter>` y
  el `<Leave>` —entrar al riel, pulsar un paso, salir—, el riel reinstalaba
  el script de una vista muerta, cuyo comando Tk ya había borrado. Ahora el
  dueño es uno y de por vida: el riel, que se construye una vez y sobrevive a
  las cuatro vistas. Reparte por posición del puntero —encima del riel,
  desplaza el riel; fuera, se la pasa a la vista activa, que se apunta con
  `set_wheel_client`—. Se reparte **por dónde está el puntero y no por quién
  tiene el foco** porque en Tk 8.6 sobre Windows la rueda llega al widget con
  el foco de teclado, que aquí es el marco de la vista y nunca un lienzo. El
  borrado del apuntado compara con `==` y no con `is`, porque cada acceso a
  un método ligado devuelve un objeto nuevo, y solo borra si el manejador
  sigue siendo el suyo: una vista que muere tarde no debe dejar sin rueda a
  la que ya ocupó su sitio. De regalo, el riel se desplaza ahora en los
  cuatro pasos y no solo en el 2.

- **Paso 2 · la rueda mientras se marca** — lo que la bloqueaba era el modo de
  edición entero; ahora la bloquea `self._drag`, o sea el arrastre en curso,
  que es el único momento en que desplazar estropea algo: el rectángulo que se
  está dibujando. El atributo ya existía, así que el arreglo del síntoma
  reportado era una condición. Debajo había dos cosas más. Una, que en «Una» la
  rueda no hacía nada aunque hubiera de sobra que desplazar: el `bind_all`
  vivía **dentro del constructor de la tira**, que solo se ejecuta al entrar en
  «Todas», así que la vista arrancaba —en «Una», que es el modo inicial— sin
  ningún enganche de rueda. Subió a `_bind_keys`, junto a las demás teclas
  globales. Dos, que la explicación que traía el apartado —«la atiende
  `ZoomedCanvas._on_wheel`»— es dudosa: en Tk 8.6 sobre Windows la rueda va al
  widget con el foco de teclado, y el foco lo tiene el marco de la vista, no el
  lienzo. El despachador desplaza él mismo en vez de delegar, con lo que
  funciona bajo las dos lecturas: si el lienzo llegó a atenderla, devolvió
  «break» y esto no se ejecuta. Y cuando la página cabe entera, la rueda pasa
  de página —lo que significa en un lector de cómic—, apoyándose en `_on_prev`
  / `_on_next`, que ya se guardaban de salirse del rango.

- **Fuera la variante `secondary`** — el apartado pedía revisar nueve botones
  «por si acaso» estaban sobre el riel sin contenedor con borde. Estaban los
  nueve: no quedaba en toda la aplicación un solo botón dentro de un
  contenedor con borde, que es el único sitio donde DESIGN.md §7 permitía
  `secondary`. Una variante cuya regla se incumple en el 100 % de sus usos no
  es una regla, así que en vez de corregir los nueve sitios se borró la
  variante: `outline` pasa a ser el defecto de `theme.button` y el respaldo
  ante un nombre desconocido, con lo que la trampa de Windows —Tk no pinta el
  `highlightthickness` de un `Button`— deja de ser algo que recordar y pasa a
  ser inalcanzable. Se ven cuatro bordes nuevos: los pies de riel de los pasos
  2 y 4 y el «Cancelar» del diálogo de exportación. De paso, `TOOLTIP_BG` /
  `TOOLTIP_FG` dejaron de ser `COLOR_TEXT` / `COLOR_BG` copiados a mano, las
  cuatro tuplas `("Segoe UI", n)` pasaron a `theme.body_font` —`TOOLTIP_FONT`
  no podía sobrevivir como constante porque la familia no se resuelve hasta
  `theme.init()`—, y la fila del paso activo usa `BTN_FG` y `ACCENT_200` en
  vez de `#ffffff` y un `#ffd8d0` que no estaba en la rampa. Tres de los
  hallazgos del apartado ya no existían: `SPACE_1…SPACE_8` no está en
  `config.py`, `disabledforeground="#666666"` es `NEUTRAL_500` en los dos
  sitios vivos y `floating_bar.py` no existe — así que el token de «texto
  deshabilitado» que el punto pedía añadir sobraba.

- **Fuera el alert nativo** — `theme.alert()` y `theme.confirm()` son un
  único `Toplevel` con el borde de 2 px, la tipografía y los botones de la
  app; un aviso es esa misma clase sin el botón de cancelar, porque se
  diferencian en un botón y no en una disposición. Al hacer el inventario
  resultó que **la mitad de los quince sitios no debía ser un diálogo**: el
  corte no está entre `showinfo` y `showwarning` sino entre las cuatro
  llamadas que devuelven `bool` —que bloquean porque el código siguiente
  depende de la respuesta— y los once avisos, que en cuanto la vista tenga
  `StatusBar` van a la barra. Cinco se mudaron ahí, incluidos dos que ya
  estaban dichos dos veces: la exportación fallida abría un modal y acto
  seguido escribía el mismo error en la barra, y «Sin marcas» era un modal a
  catorce líneas de un aviso idéntico resuelto con `_status.set`. Los cuatro
  que preguntan estrenan rótulo que dice qué hacen —«Borrar las marcas»,
  «Volver a leerlas»— en vez de «Sí». No hizo falta variante `danger`:
  `primary` ya es el rojo acento. `messagebox_safe` intenta el diálogo propio
  y **conserva el `messagebox` nativo debajo**, porque se llama desde
  manejadores de excepción que pueden dispararse antes de que haya ventana
  donde pintar: nunca debe ser el aviso del error quien se caiga avisando.

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
  es justo la distinción sobre la que se construyeron después los
  perfiles de texto.
- **Paso 4 · mover y redimensionar el cuadro de texto** — la marca dice
  *qué se borra* y el cuadro *dónde se escribe*, que hasta ahora eran la
  misma caja. Ocho tiradores sobre la sección seleccionada, los mismos
  del paso 2: `move_rect` / `resize_rect` / `handle_centers` pasaron a
  `zoomed_canvas.py`, que es el ancestro común, en vez de copiar el
  volteo y los recortes en un segundo sitio donde se irían separando.
  `TranslationEntry.box_offset` guarda `(dx, dy, dw, dh)` **contra la
  marca**, así que mover la marca en el paso 2 se lleva el texto con
  ella, y arrastrar el cuadro justo encima de la marca borra el
  desplazamiento en vez de guardar cuatro ceros. Mientras esté
  desplazado, la marca se dibuja punteada detrás y el riel avisa si el
  cuadro se sale de lo que se limpió —se permite, pero ahí el texto cae
  sobre dibujo—. `box_rect` es la mitad geométrica de `resolve_box`,
  separada porque las pruebas de ratón la piden en cada movimiento y
  resolver una fuente contra el disco para saber *dónde* está una caja
  sería absurdo.
- **Paso 4 · perfiles de texto** — un perfil («Diálogo», «Grito»…) guarda
  fuente, tamaño, color y estilo bajo un nombre, y se mete como capa
  intermedia de la precedencia: `sección > perfil > capítulo`. Asignarlo
  escribe el **nombre** en el sidecar y nunca una copia de los valores, que
  es lo que hace que editar un perfil alcance a las secciones que lo usan
  —solo en los campos que ellas no tocaron— y que un nombre borrado se lea
  como «ninguno» en vez de reventar. Los perfiles son de quien rotula, no
  del capítulo, así que viven en `text_profiles.json` en la raíz. La lista
  empieza vacía: **Guardar como perfil…** lo crea con lo que se ve en la
  sección seleccionada (y guardar con un nombre existente lo edita), **A
  toda la página** lo reparte, y el **↺** de cada campo lo devuelve al
  perfil —solo aparece cuando hay algo que deshacer—.
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
