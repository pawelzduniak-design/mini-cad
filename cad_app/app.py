"""Application entry point and logging bootstrap."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter

from cad_app.env import ensure_runtime_dependencies
from cad_app.main_window import create_main_window
from cad_app.scene import Scene
from cad_app.viewer import Viewer

LOGGER = logging.getLogger(__name__)


def configure_logging() -> Path:
    """Configure console and file logging for runtime diagnostics."""
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "cad_app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    if any(handler.name == "cad_app_file" for handler in root_logger.handlers):
        return log_path

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)s [%(name)s] %(message)s",
        "%H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.name = "cad_app_console"
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.name = "cad_app_file"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    _redirect_occt_messages()

    return log_path


def _redirect_occt_messages() -> None:
    try:
        from OCP.Message import (
            Message_Gravity,
            Message_Messenger,
            Message_Printer,
        )
        from OCP.TCollection import TCollection_AsciiString

        occt_logger = logging.getLogger("OCP")

        class PyMessagePrinter(Message_Printer):
            def send(self, text, gravity, put_endline):
                msg = str(TCollection_AsciiString(text).ToCString())
                msg = msg.rstrip("\n")
                level = {
                    Message_Gravity.Message_INFO: logging.DEBUG,
                    Message_Gravity.Message_WARNING: logging.WARNING,
                    Message_Gravity.Message_ALARM: logging.ERROR,
                    Message_Gravity.Message_FAIL: logging.ERROR,
                }.get(gravity, logging.DEBUG)
                occt_logger.log(level, msg)

        printer = PyMessagePrinter()
        messenger = Message_Messenger.DefaultMessenger()
        messenger.AddPrinter(printer)
    except Exception:
        pass


def create_initial_scene() -> Scene:
    """Create an empty startup scene with no default body."""
    return Scene()


@contextmanager
def logged_stage(name: str):
    """Log elapsed time for a startup stage."""
    start = perf_counter()
    LOGGER.info("%s started", name)
    try:
        yield
    finally:
        elapsed_ms = (perf_counter() - start) * 1000.0
        LOGGER.info("%s finished in %.1f ms", name, elapsed_ms)


def run() -> None:
    """Run the application."""
    log_path = configure_logging()
    LOGGER.info("Logging to %s", log_path)
    logging.getLogger("build123d").setLevel(logging.WARNING)

    with logged_stage("Runtime dependency check"):
        ensure_runtime_dependencies()

    with logged_stage("PySide6 import"):
        from PySide6.QtWidgets import QApplication

    with logged_stage("QApplication create"):
        app = QApplication([])

    with logged_stage("Initial scene create"):
        scene = create_initial_scene()

    with logged_stage("Main window create"):
        viewer = Viewer()
        main_window = create_main_window(viewer, scene)

    with logged_stage("Main window show"):
        main_window.window.show()

    exit_code = app.exec()
    viewer.close()
    LOGGER.info("Application exited with code %s", exit_code)
    os._exit(exit_code)
