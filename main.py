"""Punto de entrada: arranca el registro y abre la ventana."""

from src.app import App
from src.utils.logger import get_logger, log_file_path


def main() -> None:
    log = get_logger("main")
    log.info("=" * 60)
    log.info("Taller de Rotulación - Iniciando")
    log.info("Log en: %s", log_file_path())
    log.info("=" * 60)
    try:
        app = App()
        app.run()
    except Exception as exc:
        log.exception("Error fatal: %s", exc)
        raise


if __name__ == "__main__":
    main()
