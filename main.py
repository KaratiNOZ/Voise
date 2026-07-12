#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voise - Анализатор вокала
Главный файл приложения
"""

import sys
import json
from pathlib import Path

from src.crash_logger import setup_crash_logging, get_logger

# Настраиваем логирование крашей САМЫМ первым делом,
# чтобы поймать даже ошибки при импорте PyQt5/numpy/librosa
LOG_FILE = setup_crash_logging()
logger = get_logger()

try:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from PyQt5.QtCore import Qt
    from src.gui.main_window import MainWindow
    from src.gui.theme import APP_STYLESHEET
except Exception:
    logger.exception("Критическая ошибка при импорте зависимостей")
    raise


DEFAULT_CONFIG = {
    "audio": {
        "sample_rate": 44100,
        "chunk_size": 2048,
        "channels": 1,
        "device_index": None
    },
    "analysis": {
        "pitch_threshold": 0.2,
        "noise_gate_db": -45,
        "quality_threshold": 0.65,
        "cent_tolerance": 50,
        "update_interval_ms": 50
    },
    "voice_detection": {
        "min_frequency": 80,
        "max_frequency": 1000,
        "falsetto_threshold": 0.6
    },
    "gui": {
        "window_width": 1050,
        "window_height": 780,
        "theme": "light"
    }
}


def _deep_merge(base, override):
    """Рекурсивно дополнить base значениями из override, не теряя отсутствующие ключи."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config():
    """Загрузка конфигурации с защитой от повреждённого/неполного файла"""
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
        config = _deep_merge(DEFAULT_CONFIG, user_config)
        logger.info("Конфигурация загружена из %s", config_path)
        return config
    except FileNotFoundError:
        logger.warning("config.json не найден, используются настройки по умолчанию")
        return dict(DEFAULT_CONFIG)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Ошибка чтения config.json (%s), используются настройки по умолчанию", e)
        return dict(DEFAULT_CONFIG)


def main():
    """Точка входа"""
    config = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName("Voise")
    app.setOrganizationName("VoiseApp")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET.get(config.get("gui", {}).get("theme", "light"), ""))

    try:
        window = MainWindow(config)
        window.show()
    except Exception:
        logger.exception("Критическая ошибка при запуске главного окна")
        QMessageBox.critical(
            None,
            "Voise — критическая ошибка",
            "Приложение не смогло запуститься.\n\n"
            f"Подробности сохранены в:\n{LOG_FILE}\n\n"
            "Проверьте, что микрофон подключен и драйверы установлены."
        )
        sys.exit(1)

    exit_code = app.exec_()
    logger.info("Приложение завершено с кодом %s", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Подстраховка на случай ошибки до/после app.exec_()
        logger.exception("Неперехваченная ошибка в main()")
        raise
