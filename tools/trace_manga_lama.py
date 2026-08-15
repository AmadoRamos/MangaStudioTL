"""Genera el modelo de inpainting afinado para manga. Se ejecuta una vez.

Descarga los pesos de dreMaz/AnimeMangaInpainting (204 MB, MIT), los mete
en la arquitectura de ``manga_lama.py`` y guarda un TorchScript en
``MODELS_DIR``. A partir de ahi el programa lo carga solo con
``INPAINT_MODEL=manga``, sin necesitar nada de este directorio: un
TorchScript lleva el grafo dentro.

Por que TorchScript y no cargar los pesos en caliente: simple-lama ya mira
la variable LAMA_MODEL y hace torch.jit.load de esa ruta, asi que por esta
via el programa no se entera de que ha cambiado el modelo. Cero codigo
nuevo de inferencia y cero arquitectura empaquetada.

El peligro esta en el trazado. Las capas de Fourier sacan las formas de
``x.shape``, y trace puede congelarlas: quedaria un modelo que solo
funciona al tamano con el que se trazo. Es el mismo muro contra el que se
estrello el intento de exportar a ONNX. Por eso esto no guarda nada sin
antes comparar contra el modelo normal a varios tamanos distintos.

    python tools/trace_manga_lama.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import MODELS_DIR  # noqa: E402

from manga_lama import load_lama_mpe  # noqa: E402

URL = ("https://huggingface.co/dreMaz/AnimeMangaInpainting/resolve/main/"
       "lama_large_512px.ckpt")
SHA256 = "11d30fbb3000fb2eceae318b75d9ced9229d99ae990a7f8b3ac35c8d31f2c935"
CKPT = MODELS_DIR / "lama_large_512px.ckpt"
TARGET = MODELS_DIR / "lama-manga.pt"

# Multiplos de 8, que es lo que exige el preprocesado, y de proporciones
# distintas a proposito: un globo apaisado, uno cuadrado y uno vertical.
# Si el trazado congelo las formas, cualquiera de los tres revienta.
SIZES = [(192, 512), (256, 256), (384, 200)]
TOL = 1e-4


def download() -> None:
    if CKPT.exists() and sha256(CKPT) == SHA256:
        print(f"pesos ya descargados: {CKPT}")
        return
    import requests

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"descargando 204 MB de {URL}")
    done = 0
    with requests.get(URL, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(CKPT, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                print(f"\r  {done / 1e6:6.1f} MB", end="")
    print()
    got = sha256(CKPT)
    if got != SHA256:
        CKPT.unlink(missing_ok=True)
        sys.exit(f"sha256 no coincide:\n  esperado {SHA256}\n  recibido {got}")
    print("sha256 verificado")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Composited(torch.nn.Module):
    """El generador mas la composicion final, que es lo que espera la app.

    ``LamaFourier`` no es un nn.Module —es una clase pelada con el
    generador dentro— asi que no se puede trazar tal cual. Esto replica
    lo que hace su ``__call__`` en modo ``inpaint_only``, que es tambien
    lo que hace el big-lama.pt de simple-lama: devolver la imagen ya
    compuesta, intacta fuera de la mascara.
    """

    def __init__(self, generator: torch.nn.Module) -> None:
        super().__init__()
        self.generator = generator

    def forward(self, img: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        return self.generator(img, mask) * mask + (1 - mask) * img


def sample(h: int, w: int) -> tuple[torch.Tensor, torch.Tensor]:
    torch.manual_seed(h * 1000 + w)
    img = torch.rand(1, 3, h, w)
    mask = torch.zeros(1, 1, h, w)
    mask[:, :, h // 4: h - h // 4, w // 4: w - w // 4] = 1
    return img, mask


def check(traced: torch.nn.Module, eager: torch.nn.Module) -> bool:
    """El modelo trazado tiene que dar lo mismo a TODOS los tamanos."""
    ok = True
    for h, w in SIZES:
        img, mask = sample(h, w)
        with torch.inference_mode():
            want = eager(img, mask)
            try:
                got = traced(img, mask)
            except Exception as exc:
                print(f"  {h}x{w}: FALLA -> {type(exc).__name__}: {str(exc)[:120]}")
                ok = False
                continue
        diff = (want - got).abs().max().item()
        flag = "ok" if diff <= TOL else "DISTINTO"
        print(f"  {h}x{w}: diferencia maxima {diff:.2e}  {flag}")
        ok = ok and diff <= TOL
    return ok


def main() -> None:
    download()

    print("cargando pesos en la arquitectura...")
    model = load_lama_mpe(str(CKPT), device="cpu", use_mpe=False,
                          large_arch=True)
    eager = Composited(model.generator).eval()

    print(f"trazando a {SIZES[0][0]}x{SIZES[0][1]}...")
    img, mask = sample(*SIZES[0])
    with torch.inference_mode():
        traced = torch.jit.trace(eager, (img, mask), check_trace=False)
    traced = torch.jit.freeze(traced.eval())

    print("comprobando que sirve a cualquier tamano:")
    if not check(traced, eager):
        sys.exit(
            "El trazado congelo las formas: el modelo solo valdria al tamano\n"
            "con el que se trazo, y los recortes de la app son de todos los\n"
            "tamanos. No se guarda nada. Habria que probar torch.jit.script."
        )

    torch.jit.save(traced, str(TARGET))
    print(f"\nguardado {TARGET}  ({TARGET.stat().st_size / 1e6:.1f} MB)")
    print("para usarlo:  set INPAINT_MODEL=manga")


if __name__ == "__main__":
    main()
