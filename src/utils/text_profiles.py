"""Los perfiles de texto del usuario: un nombre y lo que ese nombre impone.

Un perfil es un atajo, no una atadura. Sus campos entran en
``resolve_box`` como capa intermedia —lo que la sección puso a mano gana
al perfil, y el perfil gana a los valores del capítulo—, así que asignar
«Grito» a una sección no pisa el color que esa sección ya tenía elegido.
Sus campos son ``None`` mientras el perfil no diga nada de ellos, con la
misma regla que en el sidecar: ausente es «sin tocar», no «puesto al
valor por defecto».

Los perfiles son de quien rotula, no del capítulo, así que viven en un
único JSON del usuario (:data:`~src.config.USER_DATA_DIR`) y no dentro de
cada sidecar. El sidecar solo guarda el nombre.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Iterable

from src.config import USER_DATA_DIR, TEXT_PROFILES_FILE
from src.utils.logger import get_logger
from src.utils.marks_store import opt_bool, opt_color, opt_int

log = get_logger("text_profiles")

_PATH: Path = USER_DATA_DIR / TEXT_PROFILES_FILE

#: La fila de «sin perfil» del selector. No es el nombre de un perfil: una
#: sección sin perfil cae directamente a los valores del capítulo. Vive
#: aquí y no en la vista porque es la regla que dice qué nombre no puede
#: llevar un perfil, y esa regla se comprueba en dos sitios.
NO_PROFILE = "(ninguno)"


@dataclass(frozen=True)
class TextProfile:
    """Un juego de valores con nombre («Diálogo», «Grito», «Narración»)."""

    name: str
    font_family: str | None = None
    max_pt: int | None = None
    color: tuple[int, int, int] | None = None
    bold: bool | None = None
    italic: bool | None = None
    #: Cero es «este perfil dibuja sin contorno», no «sin tocar».
    stroke_width: int | None = None
    stroke_color: tuple[int, int, int] | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("color", "stroke_color"):
            if data[key] is not None:
                data[key] = list(data[key])
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict) -> "TextProfile | None":
        """``None`` si la entrada no tiene nombre: sin nombre no es nada."""
        name = str(data.get("name", "")).strip()
        if not name:
            return None
        return cls(
            name=name,
            font_family=(
                str(data["font_family"]) if data.get("font_family") else None
            ),
            max_pt=opt_int(data.get("max_pt")),
            color=opt_color(data.get("color")),
            bold=opt_bool(data.get("bold")),
            italic=opt_bool(data.get("italic")),
            stroke_width=opt_int(data.get("stroke_width")),
            stroke_color=opt_color(data.get("stroke_color")),
        )


#: Lo que un perfil dicta y una sección puede pisar. Sale del propio
#: dataclass para que añadir un campo no obligue a acordarse también de
#: esta lista; la sección lleva los mismos nombres, y eso lo comprueba
#: ``test_profile_layer``.
STYLE_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(TextProfile) if f.name != "name"
)


def validate_name(
    name: str,
    profiles: Iterable[TextProfile],
    *,
    current: str | None = None,
) -> str | None:
    """El motivo por el que *name* no vale como nombre de perfil, o ``None``.

    Un solo sitio para las tres reglas, porque las piden dos: el campo
    del riel al crear y el del gestor al renombrar. ``current`` es el
    nombre que ya lleva el perfil que se está editando, para que cambiar
    «Grito» por «GRITO» no se lea como un duplicado de sí mismo.
    """
    name = name.strip()
    if not name:
        return "El perfil necesita un nombre."
    if name.casefold() == NO_PROFILE.casefold():
        return f"«{NO_PROFILE}» es la fila de quitar el perfil, no un nombre."
    mine = current.casefold() if current else None
    for existing in profiles:
        key = existing.name.casefold()
        if key == name.casefold() and key != mine:
            return f"Ya hay un perfil «{existing.name}»."
    return None


def load() -> tuple[TextProfile, ...]:
    """Los perfiles guardados, en el orden en que se escribieron.

    Un archivo ilegible o corrupto se trata como «todavía no hay
    perfiles»: la lista vacía es un estado normal de la aplicación, y
    perder los perfiles no debe impedir exportar un capítulo.
    """
    if not _PATH.exists():
        return ()
    try:
        raw = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("No se pudo leer %s: %s", _PATH, exc)
        return ()
    if not isinstance(raw, list):
        log.warning("%s no contiene una lista de perfiles", _PATH)
        return ()
    out: list[TextProfile] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        profile = TextProfile.from_dict(item)
        # El nombre es la clave con la que lo busca el sidecar, así que
        # un duplicado haría que la sección dependiese del orden. Se
        # compara sin distinguir mayúsculas: «Grito» y «grito» en un JSON
        # editado a mano son dos filas que el selector no sabe separar.
        if profile is None or profile.name.casefold() in seen:
            continue
        seen.add(profile.name.casefold())
        out.append(profile)
    return tuple(out)


def save(profiles: Iterable[TextProfile]) -> bool:
    """Escribe la lista entera. ``False`` si el disco no dejó."""
    payload = [p.to_dict() for p in profiles]
    try:
        _PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("No se pudo escribir %s: %s", _PATH, exc)
        return False
    return True
