"""Local translation engine based on Argos Translate.

Argos Translate runs entirely offline once the language pair models are
downloaded from the public package index. This module is a thin,
lazy-loading wrapper that:

* Detects availability (module import + index access).
* Lists installed language pairs.
* Downloads / installs a missing pair on demand (background-friendly:
  the download itself happens in the caller, the worker only
  translates).
* Exposes a single :meth:`translate` for short text snippets.

Pair installation is a one-time cost (~300 MB per pair). Models live in
the user data directory chosen by ``argospm`` / ``argostranslate``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from src.utils.logger import get_logger

log = get_logger("translator")

try:
    import argostranslate.package as argos_package
    import argostranslate.translate as argos_translate

    _ARGOS_AVAILABLE: bool = True
    _IMPORT_ERROR: str | None = None
except Exception as exc:
    argos_package = None  # type: ignore[assignment]
    argos_translate = None  # type: ignore[assignment]
    _ARGOS_AVAILABLE = False
    _IMPORT_ERROR = str(exc)
    log.warning("argostranslate no disponible: %s", exc)


def _translation_codes(translation) -> tuple[str | None, str | None]:
    """Read the (from, to) codes off an argos ``ITranslation``.

    Installed translations expose ``from_lang`` / ``to_lang`` (Language
    objects that carry ``.code``); only *packages* have flat
    ``from_code`` / ``to_code``. Reading the package spelling off a
    translation raises, which used to leave the installed-pair list
    permanently empty — the UI then reported an installed model as
    missing. Try both spellings so either API shape answers.
    """
    src = getattr(getattr(translation, "from_lang", None), "code", None)
    tgt = getattr(getattr(translation, "to_lang", None), "code", None)
    if src is None:
        src = getattr(translation, "from_code", None)
    if tgt is None:
        tgt = getattr(translation, "to_code", None)
    return src, tgt


@dataclass(frozen=True)
class LanguagePair:
    """An installed (from_code, to_code) pair."""

    from_code: str
    to_code: str

    @property
    def label(self) -> str:
        return f"{self.from_code} -> {self.to_code}"


class Translator:
    """Lazy wrapper around argostranslate.

    Thread safety: Argos Translate's ``get_translation_from_codes`` is
    cached internally and re-entrant. We guard package install with a
    lock so two workers do not double-install the same pair.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._available: bool | None = None
        self._load_error: str | None = None

    @staticmethod
    def is_module_available() -> bool:
        return _ARGOS_AVAILABLE

    @staticmethod
    def module_import_error() -> str | None:
        return _IMPORT_ERROR

    def is_available(self) -> bool:
        """Return True if argostranslate is importable and pairs are usable."""
        if not _ARGOS_AVAILABLE:
            self._available = False
            return False
        if self._available is not None:
            return self._available
        try:
            languages = argos_translate.get_installed_languages()
            self._available = len(languages) > 0
        except Exception as exc:
            self._load_error = str(exc)
            self._available = False
            log.warning("No se pudo inicializar Argos: %s", exc)
        return self._available

    def load_error(self) -> str | None:
        return self._load_error

    def installed_pairs(self) -> list[LanguagePair]:
        """Return the list of installed (from, to) pairs.

        Identity translations (``en -> en``) are dropped: argos
        synthesises one per installed language, and they are not models
        anybody downloaded.
        """
        if not _ARGOS_AVAILABLE or argos_translate is None:
            return []
        try:
            languages = argos_translate.get_installed_languages()
        except Exception as exc:
            log.warning("No se pudo listar idiomas Argos: %s", exc)
            return []
        pairs: list[LanguagePair] = []
        for lang in languages:
            try:
                for t in lang.translations_from:
                    src, tgt = _translation_codes(t)
                    if src and tgt and src != tgt:
                        pairs.append(LanguagePair(src, tgt))
            except Exception as exc:
                log.warning("No se pudo leer los pares de %s: %s", lang, exc)
                continue
        return pairs

    def is_pair_available(self, src: str, tgt: str) -> bool:
        """True only when the pair's model is actually installed.

        ``get_translation_from_codes`` also answers for pairs it could
        only reach by pivoting, so the UI would claim a model was ready
        when nothing had been downloaded. Ask the installed list.
        """
        if not _ARGOS_AVAILABLE or argos_translate is None:
            return False
        if src == tgt:
            return True
        return any(
            pair.from_code == src and pair.to_code == tgt
            for pair in self.installed_pairs()
        )

    def ensure_pair(self, src: str, tgt: str) -> bool:
        """Download and install a language pair if it is not present.

        Returns True on success (or if already installed). False on
        network or installation failure.
        """
        if not _ARGOS_AVAILABLE or argos_package is None:
            return False
        if self.is_pair_available(src, tgt):
            return True
        with self._lock:
            if self.is_pair_available(src, tgt):
                return True
            try:
                log.info("Descargando par de traduccion %s -> %s ...", src, tgt)
                argos_package.update_package_index()
                available = argos_package.get_available_packages()
                matches = [
                    p for p in available
                    if p.from_code == src and p.to_code == tgt
                ]
                if not matches:
                    log.warning("No hay paquete Argos para %s -> %s", src, tgt)
                    return False
                argos_package.install_from_path(matches[0].download())
                log.info("Par %s -> %s instalado", src, tgt)
                self._available = None  # re-evaluate
                return True
            except Exception as exc:
                log.exception("No se pudo instalar el par %s -> %s: %s", src, tgt, exc)
                return False

    def translate(self, text: str, src: str, tgt: str) -> str:
        """Translate ``text`` from ``src`` to ``tgt``.

        Returns the original text if translation is not possible.
        """
        if not text or not text.strip():
            return text
        if not _ARGOS_AVAILABLE or argos_translate is None:
            return text
        if not self.is_pair_available(src, tgt):
            log.warning("Par Argos %s -> %s no disponible", src, tgt)
            return text
        try:
            tr = argos_translate.get_translation_from_codes(src, tgt)
            if tr is None:
                return text
            return tr.translate(text) or text
        except Exception as exc:
            log.exception("Error traduciendo %s -> %s: %s", src, tgt, exc)
            return text


def install_instructions() -> str:
    return (
        "Instala Argos Translate con:\n"
        "  pip install argostranslate argospm\n"
        "La primera vez, descarga un par de idiomas (~300 MB) desde el menu."
    )
