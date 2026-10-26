# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de «Taller de Rotulación» con PyInstaller.

Compilar con:  build_exe.bat   (o: python -m PyInstaller translator.spec --clean)

onedir y no onefile a propósito: torch pesa medio giga, y un onefile se
descomprimiría entero en cada arranque.
"""

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

# Sin tilde: da nombre al .exe y a la carpeta de dist, y esos dos los
# manosean un .bat y un .iss. El nombre con tilde es el que se ve —barra
# de titulo, accesos directos, instalador—, y ese sí la lleva.
APP_NAME = "Taller de Rotulacion"

with open("VERSION", "r", encoding="utf-8") as fh:
    version = fh.read().strip()

# Lo que Windows ensena en las propiedades del archivo. Sin esto el .exe
# sale sin version mientras el instalador si la lleva, y entonces no hay
# forma de saber que version esta instalada mirando el programa.
# PyInstaller acepta la estructura ya construida, asi que no hace falta
# el archivo de texto arcano que pide `version=` normalmente.
_nums = (tuple(int(p) for p in version.split(".")) + (0, 0, 0, 0))[:4]
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums),
    kids=[
        # 040a04b0: espanol de Espana en Unicode, como el instalador.
        StringFileInfo([StringTable("040a04b0", [
            StringStruct("CompanyName", "AmadoRamos"),
            # El nombre sin tilde tambien aqui: es el mismo string que da
            # nombre al .exe, y uno solo no se desincroniza del otro.
            StringStruct("FileDescription", APP_NAME),
            StringStruct("FileVersion", version),
            StringStruct("ProductName", APP_NAME),
            StringStruct("ProductVersion", version),
            StringStruct("LegalCopyright", "Copyright 2026"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x040A, 1200])]),
    ],
)

datas = []
binaries = []
hiddenimports = []

# Estos tres traen datos que el análisis estático no ve, y sus submódulos
# cambian entre versiones: enumerarlos a mano es una lista que se rompe
# sola en cada actualización.
#
# torch y tkinterdnd2 NO están aquí, y es deliberado: PyInstaller ya trae
# hooks para ambos que hacen un trabajo mejor que collect_all. El de torch
# excluye las cabeceras C++ (medio giga de .h/.hpp/.lib que no sirven en
# ejecución) y recoge las DLLs de MKL; el de tkinterdnd2 copia solo el
# subdirectorio tkdnd de esta plataforma en vez de los seis. Añadirlos
# aquí pisaría ese criterio y engordaría el bundle para nada.
# Igual con PIL, numpy, cv2, spacy, thinc y onnxruntime: ya tienen hook.
for pkg in (
    "argostranslate",
    "ctranslate2",
    "simple_lama_inpainting",
    # Sus modelos ONNX y los .yaml de configuración son datos del paquete:
    # sin esto el ejecutable arranca y el OCR cae siempre al respaldo.
    "rapidocr_onnxruntime",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

datas += [
    # theme.ICON_DIR los lee de aquí; la ruta dentro del bundle tiene que
    # coincidir con la del repo porque PROJECT_ROOT resuelve igual en ambos.
    ("src/assets/images", "src/assets/images"),
    # El icono va dos veces y no es un descuido: aquí como dato, porque
    # App.__init__ lo abre en caliente con iconbitmap para la barra de
    # título; y abajo en `icon=`, que es lo que Windows incrusta en el .exe
    # y enseña en el explorador. Son dos consumidores distintos.
    ("src/assets/logo.ico", "src/assets"),
    ("VERSION", "."),
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "_pytest",
        "pylint",
        "astroid",
        "tests",
        "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX sobre las DLLs de torch tarda muchísimo y rompe algunas.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="src/assets/logo.ico",
    version=version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
