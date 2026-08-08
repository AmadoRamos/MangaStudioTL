"""El gestor de perfiles de texto: verlos todos, y poder tocarlos.

Hasta aquí un perfil solo se podía crear —y editar, sin avisar— guardando
una sección con un nombre. Quitarlo era editar el JSON a mano. Esta
ventana es el sitio donde un perfil existe por sí mismo: se renombra, se
duplica, se borra y se ajusta sin pasar por ninguna sección.

No tiene botón de guardar. Cada control publica al instante por el mismo
camino que el riel —a la lista, al lienzo y al disco—, así que la página
que se ve detrás del modal se repinta mientras se edita, y no hay una
copia en escenario que pueda desincronizarse de lo guardado.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import colorchooser
from typing import Callable

from src.config import (
    COLOR_BG,
    COLOR_DIVIDER,
    COLOR_SURFACE,
    COLOR_TEXT,
    ERROR_COLOR,
    NEUTRAL_600,
    TEXT_COLOR_PRESETS,
    TEXT_RENDER_STROKE_COLOR,
    TEXT_RENDER_STROKE_MAX_PX,
    TEXT_RENDER_USER_MAX_PT_MAX,
    TEXT_RENDER_USER_MAX_PT_MIN,
)
from src.utils.text_profiles import TextProfile, validate_name
from src.views import theme
from src.views.translator_canvas import _rgb_to_hex, _stroke_text

#: Más ancho que ``theme.DIALOG_WIDTH``: son dos paneles, no un párrafo.
DIALOG_WIDTH = 640
#: Lo que ocupa la lista de la izquierda. El resto es el editor.
LIST_WIDTH = 230


class ProfileDialog(tk.Toplevel):
    """Modal de administración de perfiles. Bloquea hasta cerrarse.

    No devuelve nada: lo que hace ya está hecho cuando se cierra.
    ``usage_of`` es una función y no un diccionario porque después de
    renombrar un diccionario estaría mintiendo.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        profiles: tuple[TextProfile, ...],
        usage_of: Callable[[str], int],
        font_options: list[str],
        on_change: Callable[[tuple[TextProfile, ...]], None],
        on_rename: Callable[[str, str], None],
    ) -> None:
        super().__init__(master, bg=COLOR_BG)
        self._profiles = profiles
        self._usage_of = usage_of
        self._font_options = font_options
        self._on_change = on_change
        self._on_rename = on_rename
        self._selected: str | None = profiles[0].name if profiles else None
        #: La fila de color del contorno, que solo está cuando hay borde.
        self._stroke_colors: tk.Frame | None = None

        self.title("Gestor de perfiles")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.configure(
            highlightthickness=2,
            highlightbackground=COLOR_TEXT, highlightcolor=COLOR_TEXT,
        )

        self._build_header()
        panes = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        panes.pack(fill=tk.BOTH, expand=True)
        self._list_pane = tk.Frame(panes, bg=COLOR_BG, width=LIST_WIDTH)
        self._list_pane.pack(side=tk.LEFT, fill=tk.Y)
        self._list_pane.pack_propagate(False)
        theme.rule(panes, thickness=1, vertical=True).pack(
            side=tk.LEFT, fill=tk.Y, padx=14,
        )
        self._editor = tk.Frame(panes, bg=COLOR_BG)
        self._editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_actions()

        self._refresh()

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _e: self._close())
        theme.center_on(self, master, DIALOG_WIDTH)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=COLOR_BG, padx=18, pady=16)
        header.pack(fill=tk.X)
        theme.heading(header, "Gestor de perfiles", size=15).pack(fill=tk.X)
        theme.body(
            header,
            "Un perfil es la capa de en medio: gana a los valores del "
            "capítulo y pierde contra lo que la sección haya elegido a mano.",
            size=9, fg=NEUTRAL_600, wrap=DIALOG_WIDTH - 36,
        ).pack(fill=tk.X, pady=(5, 0))
        theme.rule(self, thickness=2, color=COLOR_TEXT).pack(fill=tk.X)

    def _build_actions(self) -> None:
        theme.rule(self, thickness=2, color=COLOR_DIVIDER).pack(fill=tk.X)
        actions = tk.Frame(self, bg=COLOR_BG, padx=18, pady=14)
        actions.pack(fill=tk.X)
        theme.button(
            actions, "Cerrar", self._close, variant="outline",
            padx=16, pady=10,
        ).pack(side=tk.LEFT)
        # No hay «Guardar»: cada cambio ya fue al disco cuando se hizo.
        theme.body(
            actions, "Los cambios se guardan solos.", size=9, fg=NEUTRAL_600,
        ).pack(side=tk.LEFT, padx=(12, 0))

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def _current(self) -> TextProfile | None:
        for profile in self._profiles:
            if profile.name == self._selected:
                return profile
        return None

    def _publish(self, profiles: tuple[TextProfile, ...]) -> None:
        """El único sitio que suelta la lista nueva hacia fuera."""
        self._profiles = profiles
        self._on_change(profiles)

    def _edit_current(self, **changes) -> None:
        """Cambia un campo del perfil seleccionado y repinta el editor."""
        current = self._current()
        if current is None:
            return
        edited = replace(current, **changes)
        self._publish(tuple(
            edited if p.name == current.name else p for p in self._profiles
        ))
        self._build_editor()

    def _refresh(self) -> None:
        self._build_list()
        self._build_editor()

    # ------------------------------------------------------------------
    # Left: the list
    # ------------------------------------------------------------------

    def _build_list(self) -> None:
        for widget in list(self._list_pane.winfo_children()):
            widget.destroy()
        theme.kicker(self._list_pane, "Perfiles").pack(fill=tk.X, pady=(0, 8))

        if not self._profiles:
            theme.body(
                self._list_pane,
                "Todavía no hay ninguno. Se crean desde una sección, con "
                "«Guardar como perfil…».",
                size=9, fg=NEUTRAL_600, wrap=LIST_WIDTH,
            ).pack(fill=tk.X)
            return

        for profile in self._profiles:
            row = tk.Frame(self._list_pane, bg=COLOR_BG)
            row.pack(fill=tk.X, pady=(0, 3))
            selected = profile.name == self._selected
            theme.button(
                row, profile.name,
                lambda n=profile.name: self._select(n),
                variant="ink" if selected else "ghost",
                size=9, padx=8, pady=6, anchor=tk.W,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)
            used = self._usage_of(profile.name)
            theme.tag(
                row,
                f"{used}" if used else "—",
                kind="accent" if used else "neutral",
            ).pack(side=tk.RIGHT, padx=(6, 0))

        buttons = tk.Frame(self._list_pane, bg=COLOR_BG)
        buttons.pack(fill=tk.X, pady=(10, 0))
        theme.button(
            buttons, "Duplicar", self._duplicate,
            variant="outline", size=8, padx=8, pady=5,
            tooltip="Copiar el perfil seleccionado con otro nombre",
        ).pack(side=tk.LEFT)
        theme.button(
            buttons, "Eliminar", self._delete,
            variant="outline", size=8, padx=8, pady=5,
            tooltip="Borrar el perfil seleccionado",
        ).pack(side=tk.LEFT, padx=(4, 0))

    def _select(self, name: str) -> None:
        self._selected = name
        self._refresh()

    def _duplicate(self) -> None:
        current = self._current()
        if current is None:
            return
        name = f"{current.name} - copia"
        n = 2
        while validate_name(name, self._profiles) is not None:
            name = f"{current.name} - copia {n}"
            n += 1
        self._publish((*self._profiles, replace(current, name=name)))
        self._selected = name
        self._refresh()

    def _delete(self) -> None:
        current = self._current()
        if current is None:
            return
        used = self._usage_of(current.name)
        detail = (
            f"{used} sección(es) se quedarán sin perfil y volverán a los "
            "valores del capítulo en los campos que no hayan tocado."
            if used else
            "No lo usa ninguna sección."
        )
        if not theme.confirm(
            self, f"Eliminar «{current.name}»", detail,
            confirm_label=f"Eliminar «{current.name}»",
        ):
            return
        remaining = tuple(
            p for p in self._profiles if p.name != current.name
        )
        self._publish(remaining)
        self._selected = remaining[0].name if remaining else None
        self._refresh()

    # ------------------------------------------------------------------
    # Right: the editor
    # ------------------------------------------------------------------

    def _build_editor(self) -> None:
        for widget in list(self._editor.winfo_children()):
            widget.destroy()
        self._stroke_colors = None
        profile = self._current()
        if profile is None:
            theme.body(
                self._editor,
                "Selecciona un perfil para ver lo que impone.",
                size=9, fg=NEUTRAL_600, wrap=320,
            ).pack(fill=tk.X)
            return

        # Nombre. Se valida al confirmar, no al teclear: avisar de que
        # «Grit» ya existe mientras se escribe «Grito» sería ruido.
        theme.field_label(self._editor, "Nombre").pack(fill=tk.X, pady=(0, 5))
        self._name_var = tk.StringVar(value=profile.name)
        field = theme.entry(self._editor, self._name_var)
        field.pack(fill=tk.X, ipady=4)
        field.bind("<Return>", lambda _e: self._commit_name())
        field.bind("<FocusOut>", lambda _e: self._commit_name())
        # El motivo del rechazo va en su propio hueco, y se empaqueta solo
        # cuando lo hay: una etiqueta vacía siempre presente deja una
        # línea en blanco bajo el campo, y su sitio es este y no el final
        # del panel, que es donde caería si se empaquetara más tarde.
        holder = tk.Frame(self._editor, bg=COLOR_BG)
        holder.pack(fill=tk.X, pady=(3, 10))
        self._name_error = theme.body(
            holder, "", size=8, fg=ERROR_COLOR, wrap=320,
        )

        theme.field_label(self._editor, "Fuente").pack(fill=tk.X, pady=(0, 5))
        self._font_var = tk.StringVar(value=profile.font_family or "")
        theme.option_menu(
            self._editor, self._font_var, self._font_options,
            lambda name: self._edit_current(font_family=name),
        ).pack(fill=tk.X, pady=(0, 10))

        theme.field_label(self._editor, "Estilo").pack(fill=tk.X, pady=(0, 5))
        style_row = tk.Frame(self._editor, bg=COLOR_BG)
        style_row.pack(fill=tk.X, pady=(0, 10))
        for field_name, label in (("bold", "Negrita"), ("italic", "Cursiva")):
            theme.button(
                style_row, label,
                lambda f=field_name: self._toggle_style(f),
                variant="ink" if getattr(profile, field_name) else "outline",
                size=8, padx=10, pady=5,
            ).pack(side=tk.LEFT, padx=(0, 4))

        max_pt = profile.max_pt or TEXT_RENDER_USER_MAX_PT_MAX
        self._size_label = theme.field_label(
            self._editor, f"Tamaño máximo · {max_pt} pt",
        )
        self._size_label.pack(fill=tk.X, pady=(0, 2))
        self._size_var = tk.IntVar(value=max_pt)
        theme.slider(
            self._editor,
            from_=TEXT_RENDER_USER_MAX_PT_MIN,
            to=TEXT_RENDER_USER_MAX_PT_MAX,
            variable=self._size_var,
            command=self._on_size_change,
        ).pack(fill=tk.X, pady=(0, 10))

        theme.field_label(self._editor, "Color").pack(fill=tk.X, pady=(0, 5))
        self._color_row("color", (0, 0, 0)).pack(fill=tk.X, pady=(0, 10))

        # Contorno. Cero es sin borde, así que el deslizador es a la vez
        # el interruptor.
        stroke = profile.stroke_width or 0
        self._stroke_label = theme.field_label(
            self._editor, _stroke_text(stroke),
        )
        self._stroke_label.pack(fill=tk.X, pady=(0, 2))
        self._stroke_var = tk.IntVar(value=stroke)
        theme.slider(
            self._editor,
            from_=0,
            to=TEXT_RENDER_STROKE_MAX_PX,
            variable=self._stroke_var,
            command=self._on_stroke_change,
        ).pack(fill=tk.X)
        # Igual que en el riel: el holder está siempre, la fila entra y
        # sale de él para no acabar al final del panel al reaparecer.
        holder = tk.Frame(self._editor, bg=COLOR_BG)
        holder.pack(fill=tk.X)
        self._stroke_colors = self._color_row(
            "stroke_color", TEXT_RENDER_STROKE_COLOR, parent=holder,
        )
        self._sync_stroke_colors(stroke)

        used = self._usage_of(profile.name)
        theme.body(
            self._editor,
            f"Lo usan {used} sección(es) del capítulo." if used else
            "Ninguna sección lo usa todavía.",
            size=8, fg=NEUTRAL_600, wrap=320, bg=COLOR_SURFACE,
        ).pack(fill=tk.X, pady=(14, 0), ipadx=8, ipady=6)

    def _color_row(
        self,
        field: str,
        fallback: tuple[int, int, int],
        parent: tk.Misc | None = None,
    ) -> tk.Frame:
        """Una fila de muestras y su «Más…». La piden dos: texto y contorno."""
        profile = self._current()
        row = tk.Frame(parent if parent is not None else self._editor, bg=COLOR_BG)
        current = getattr(profile, field, None) or fallback
        for color in TEXT_COLOR_PRESETS:
            theme.swatch(
                row, _rgb_to_hex(color),
                command=lambda c=color: self._edit_current(**{field: tuple(c)}),
                selected=(tuple(color) == tuple(current)),
            ).pack(side=tk.LEFT, padx=(0, 3))
        theme.button(
            row, "Más…", lambda: self._pick_color(field, fallback),
            variant="ghost", size=8, padx=4, pady=2,
        ).pack(side=tk.LEFT, padx=(4, 0))
        return row

    def _sync_stroke_colors(self, width: int) -> None:
        """El color del borde solo se enseña cuando hay borde que colorear."""
        if self._stroke_colors is None:
            return
        if width > 0:
            self._stroke_colors.pack(fill=tk.X, pady=(0, 10))
        else:
            self._stroke_colors.pack_forget()

    def _on_stroke_change(self, value: str) -> None:
        try:
            width = int(float(value))
        except (TypeError, ValueError):
            return
        self._stroke_label.configure(text=_stroke_text(width))
        self._sync_stroke_colors(width)
        profile = self._current()
        if profile is None or (profile.stroke_width or 0) == width:
            return
        # Sin reconstruir el editor, por lo mismo que el tamaño.
        self._publish(tuple(
            replace(p, stroke_width=width) if p.name == profile.name else p
            for p in self._profiles
        ))

    def _commit_name(self) -> None:
        """Renombrar, si el nombre nuevo vale.

        Renombrar sin arrastrar el nombre a las secciones que lo usaban
        sería borrar el perfil, así que quien manda aquí es la vista: el
        diálogo solo avisa de que el nombre cambió.
        """
        profile = self._current()
        if profile is None:
            return
        name = self._name_var.get().strip()
        if name == profile.name:
            return
        reason = validate_name(name, self._profiles, current=profile.name)
        if reason is not None:
            self._name_error.configure(text=reason)
            self._name_error.pack(fill=tk.X)
            self._name_var.set(profile.name)
            return
        old = profile.name
        self._publish(tuple(
            replace(p, name=name) if p.name == old else p
            for p in self._profiles
        ))
        self._on_rename(old, name)
        self._selected = name
        self._refresh()

    def _toggle_style(self, field: str) -> None:
        profile = self._current()
        if profile is None:
            return
        self._edit_current(**{field: not bool(getattr(profile, field))})

    def _on_size_change(self, value: str) -> None:
        try:
            size = int(float(value))
        except (TypeError, ValueError):
            return
        self._size_label.configure(text=f"Tamaño máximo · {size} pt")
        profile = self._current()
        if profile is None or profile.max_pt == size:
            # El deslizador dispara mientras se arrastra, y otra vez al
            # caer en el valor que ya tenía.
            return
        # Sin reconstruir el editor: eso se llevaría el deslizador por
        # delante mientras el ratón sigue encima de él.
        self._publish(tuple(
            replace(p, max_pt=size) if p.name == profile.name else p
            for p in self._profiles
        ))

    def _pick_color(
        self, field: str, fallback: tuple[int, int, int],
    ) -> None:
        profile = self._current()
        if profile is None:
            return
        what = "Color" if field == "color" else "Contorno"
        result = colorchooser.askcolor(
            color=_rgb_to_hex(getattr(profile, field) or fallback),
            title=f"{what} de «{profile.name}»", parent=self,
        )
        if not result or not result[0]:
            return
        self._edit_current(
            **{field: tuple(int(round(c)) for c in result[0])},
        )
