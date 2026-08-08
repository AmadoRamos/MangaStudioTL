"""Los perfiles de texto del usuario: un nombre y lo que ese nombre impone.

Un perfil es un atajo, no una atadura. Sus campos entran en
``resolve_box`` como capa intermedia —lo que la sección puso a mano gana
al perfil, y el perfil gana a los valores del capítulo—, así que asignar
«Grito» a una sección no pisa el color que esa sección ya tenía elegido.
Sus campos son ``None`` mientras el perfil no diga nada de ellos, con la
misma regla que en el sidecar: ausente es «sin tocar», no «puesto al
valor por defecto».

Los perfiles son de quien rotula, no del capítulo, así que viven en un
único JSON en la raíz del proyecto y no dentro de cada sidecar. El
sidecar solo guarda el nombre.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from src.config import PROJECT_ROOT, TEXT_PROFILES_FILE
from src.utils.logger import get_logger
from src.utils.marks_store import opt_bool, opt_color, opt_int

log = get_logger("text_profiles")

_PATH: Path = PROJECT_ROOT / TEXT_PROFILES_FILE


@dataclass(frozen=True)
class TextProfile:
    """Un juego de valores con nombre («Diálogo», «Grito», «Narración»)."""

    name: str
    font_family: str | None = None
    max_pt: int | None = None
    color: tuple[int, int, int] | None = None
    bold: bool | None = None
    italic: bool | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.color is not None:
            data["color"] = list(self.color)
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
        )


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
        # un duplicado haría que la sección dependiese del orden.
        if profile is None or profile.name in seen:
            continue
        seen.add(profile.name)
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
