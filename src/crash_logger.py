# -*- coding: utf-8 -*-
"""
Система логирования крашей и ошибок.

Задачи:
- Ловит все необработанные исключения (в главном потоке и в QThread'ах)
- Ловит низкоуровневые креши (сегфолты и т.п.) через faulthandler
- Пишет понятный текстовый crash-report с датой, версией Python/ОС,
  установленными пакетами и полным traceback
- Ведёт общий лог-файл приложения (voise.log) со всеми событиями
"""

import sys
import os
import threading
import traceback
import logging
import platform
import datetime
import faulthandler
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOGGER_NAME = "voise"

_faulthandler_file = None


def _timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _file_timestamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _system_info_block():
    lines = [
        f"Время: {_timestamp()}",
        f"ОС: {platform.platform()}",
        f"Python: {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"Процессор: {platform.processor() or 'н/д'}",
    ]
    try:
        import PyQt5.QtCore as qc
        lines.append(f"PyQt5: {qc.PYQT_VERSION_STR} / Qt {qc.QT_VERSION_STR}")
    except Exception:
        pass
    try:
        import numpy
        lines.append(f"numpy: {numpy.__version__}")
    except Exception:
        pass
    try:
        import sounddevice
        lines.append(f"sounddevice: {sounddevice.__version__}")
    except Exception:
        pass
    return "\n".join(lines)


def _write_crash_report(kind, exc_type, exc_value, exc_tb, extra_context=""):
    """Записать отдельный человекочитаемый crash-report файл."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"crash_{_file_timestamp()}.txt"
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

    with open(path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"VOISE - ОТЧЁТ О КРАШЕ ({kind})\n")
        f.write("=" * 60 + "\n\n")
        f.write(_system_info_block())
        f.write("\n\n")
        if extra_context:
            f.write(f"Контекст: {extra_context}\n\n")
        f.write(f"Тип ошибки: {exc_type.__name__ if exc_type else 'н/д'}\n")
        f.write(f"Сообщение: {exc_value}\n\n")
        f.write("Полный traceback:\n")
        f.write("-" * 60 + "\n")
        f.write(tb_text)
        f.write("-" * 60 + "\n")

    return path


def _excepthook(exc_type, exc_value, exc_tb):
    """Хук для необработанных исключений в главном потоке."""
    logger = logging.getLogger(LOGGER_NAME)
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ (главный поток):\n%s", tb_text)

    try:
        report_path = _write_crash_report("главный поток", exc_type, exc_value, exc_tb)
        logger.critical("Crash-report сохранён: %s", report_path)
    except Exception:
        logger.critical("Не удалось сохранить crash-report", exc_info=True)

    # Также выводим в консоль, как обычно
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_excepthook(args):
    """Хук для необработанных исключений в дополнительных потоках (Python 3.8+)."""
    logger = logging.getLogger(LOGGER_NAME)
    exc_type, exc_value, exc_tb, thread = (
        args.exc_type, args.exc_value, args.exc_traceback, args.thread
    )
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    thread_name = thread.name if thread else "неизвестный поток"
    logger.critical("НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ (поток '%s'):\n%s", thread_name, tb_text)

    try:
        report_path = _write_crash_report(
            f"поток '{thread_name}'", exc_type, exc_value, exc_tb
        )
        logger.critical("Crash-report сохранён: %s", report_path)
    except Exception:
        logger.critical("Не удалось сохранить crash-report", exc_info=True)


def setup_crash_logging():
    """
    Инициализировать систему логирования и перехвата крашей.
    Вызывать один раз в самом начале main().

    Returns:
        Path к основному лог-файлу приложения
    """
    global _faulthandler_file

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "voise.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(threadName)s: %(message)s"
    ))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    # Низкоуровневые креши (segfault, stack overflow, etc.)
    faulthandler_path = LOG_DIR / "faulthandler.log"
    _faulthandler_file = open(faulthandler_path, "a", encoding="utf-8")
    _faulthandler_file.write(
        f"\n--- Запуск приложения {_timestamp()} ---\n"
    )
    _faulthandler_file.flush()
    faulthandler.enable(file=_faulthandler_file, all_threads=True)

    # Необработанные исключения
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    logger.info("=" * 50)
    logger.info("Запуск Voise")
    logger.info(_system_info_block().replace("\n", " | "))
    logger.info("=" * 50)

    return log_file


def get_logger():
    """Получить логгер приложения (использовать во всех модулях)."""
    return logging.getLogger(LOGGER_NAME)


def open_logs_folder():
    """Открыть папку с логами в проводнике (кроссплатформенно)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(LOG_DIR))  # noqa
        elif sys.platform == "darwin":
            os.system(f'open "{LOG_DIR}"')
        else:
            os.system(f'xdg-open "{LOG_DIR}"')
    except Exception:
        get_logger().exception("Не удалось открыть папку с логами")
