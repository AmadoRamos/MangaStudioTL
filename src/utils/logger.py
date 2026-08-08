"""Centralized logging configuration.

Logs are written to ``logs/app.log`` next to the project root and also
echoed to stderr. The log directory is created on demand. Calling
``setup_logging`` more than once is safe; handlers are not duplicated.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config import PROJECT_ROOT

_LOGGER_NAME = "visor"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_LOG_DIR: Path = PROJECT_ROOT / "logs"
_LOG_FILE: Path = _LOG_DIR / "app.log"
_MAX_BYTES: int = 2 * 1024 * 1024
_BACKUP_COUNT: int = 3
_initialized: bool = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the application logger and return it."""
    global _initialized
    logger = logging.getLogger(_LOGGER_NAME)
    if _initialized:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(stream=sys.stderr)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    _initialized = True
    logger.info("===== Logging iniciado =====")
    logger.info("Archivo de log: %s", _LOG_FILE)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger. Configures the root logger on first call."""
    setup_logging()
    if name is None or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def log_file_path() -> Path:
    """Return the path of the active log file."""
    return _LOG_FILE
