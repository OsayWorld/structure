# main.py
import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as tkb
from app_core import OsayStudioApp


def _setup_logging():
    log_path = os.path.join(os.path.dirname(__file__), "app.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(stream_handler)

    def _handle_uncaught(exc_type, exc, tb):
        logging.getLogger(__name__).exception("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _handle_uncaught

    def _thread_excepthook(args):
        logging.getLogger(__name__).exception(
            "Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    try:
        threading.excepthook = _thread_excepthook
    except Exception:
        pass

    logging.getLogger(__name__).info("Logging initialized. log_file=%s", log_path)


if __name__ == "__main__":
    try:
        # Use tkb.Window for theming
        _setup_logging()
        app = OsayStudioApp()
        app.mainloop()
    except Exception as e:
        print(f"Application error: {e}")
        # Only show messagebox if Tkinter root is available, otherwise just print

        if tk._default_root:
            messagebox.showerror("Application Error", f"An unexpected error occurred: {e}")
        # Consider adding a more robust error logging mechanism for production
        input("Press Enter to exit...")