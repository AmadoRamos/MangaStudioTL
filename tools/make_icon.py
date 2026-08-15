"""Genera src/assets/logo.ico a partir del icono de marcar zona.

El .ico se commitea: compilar no debe depender de ejecutar esto. El
script existe para poder rehacerlo si cambia la paleta, y para dejar
escrito de dónde salió el dibujo.

    python tools/make_icon.py

Provisional a propósito. Sustituir el .ico por un diseño de verdad no
toca ni el .spec ni el .iss.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position  # el sys.path de arriba lo exige
from src.config import COLOR_ACCENT, NEUTRAL_900, PROJECT_ROOT  # noqa: E402

#: El polígono es el gesto central de la app —marcar la zona a limpiar—,
#: así que es el dibujo que mejor la nombra sin inventar un logo.
SOURCE = PROJECT_ROOT / "src" / "assets" / "images" / "draw-polygon-solid.png"
TARGET = PROJECT_ROOT / "src" / "assets" / "logo.ico"

#: Windows escoge el tamaño según dónde lo pinte: 16 en la barra de
#: título, 256 en la vista de iconos grandes. Un .ico con uno solo se ve
#: borroso en los demás.
SIZES = [(n, n) for n in (16, 32, 48, 64, 128, 256)]

#: Margen alrededor del dibujo, en tanto por uno del lado. Sin él el
#: polígono toca los bordes y a 16 px se lee como un cuadrado.
PADDING = 0.18


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def build() -> Image.Image:
    """La baldosa de tinta con el polígono en rojo acento, a 256 px."""
    side = 256
    tile = Image.new("RGBA", (side, side), _hex_to_rgb(NEUTRAL_900) + (255,))

    inner = int(side * (1 - 2 * PADDING))
    glyph = Image.open(SOURCE).convert("RGBA")
    glyph = glyph.resize((inner, inner), Image.Resampling.LANCZOS)

    # El PNG es negro sobre transparente: se conserva su alfa como recorte
    # y se rellena con el acento, igual que hace theme.icon() en la app.
    tinted = Image.new("RGBA", glyph.size, _hex_to_rgb(COLOR_ACCENT) + (255,))
    tinted.putalpha(glyph.getchannel("A"))

    offset = (side - inner) // 2
    tile.alpha_composite(tinted, (offset, offset))
    return tile


def main() -> None:
    """Escribe el .ico multi-tamaño en :data:`TARGET`."""
    if not SOURCE.is_file():
        raise SystemExit(f"No existe el dibujo de origen: {SOURCE}")
    icon = build()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    icon.save(TARGET, format="ICO", sizes=SIZES)
    print(f"Escrito {TARGET} ({TARGET.stat().st_size} bytes, {len(SIZES)} tamaños)")


if __name__ == "__main__":
    main()
