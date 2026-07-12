# -*- coding: utf-8 -*-
"""
Фоновый поток анализа.

Раньше analyze_chunk() вызывался таймером ПРЯМО в главном (GUI) потоке.
Вся тяжёлая математика (YIN pitch-detection, полосовая фильтрация,
LPC для формант) выполнялась синхронно и периодически "подвешивала"
интерфейс - отсюда рывки и лаги при взаимодействии с окном.

Здесь анализ вынесен в отдельный QThread. Пользователь разрешил
приложению использовать ресурсы системы более свободно, поэтому поток
работает в тесном цикле (без искусственных задержек сверх заданного
интервала) - это даёт максимально отзывчивый, "живой" анализ, а GUI
при этом остаётся полностью отзывчивым, потому что вся нагрузка ушла
в отдельный поток.
"""

import time

from PyQt5.QtCore import QThread, pyqtSignal

from src.crash_logger import get_logger

logger = get_logger()


class AnalysisWorker(QThread):
    """Фоновый поток, циклически вызывающий VoiceAnalyzer.analyze_chunk()"""

    result_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, analyzer, interval_ms=50, parent=None):
        super().__init__(parent)
        self.analyzer = analyzer
        self.interval = max(0.005, interval_ms / 1000.0)
        self._running = False

    def set_interval(self, interval_ms):
        self.interval = max(0.005, interval_ms / 1000.0)

    def run(self):
        self._running = True
        logger.info("Поток анализа запущен (интервал=%.0f мс)", self.interval * 1000)

        while self._running:
            start = time.perf_counter()

            try:
                result = self.analyzer.analyze_chunk()
                if result is not None:
                    self.result_ready.emit(result)
            except Exception as e:
                logger.exception("Ошибка в потоке анализа")
                self.error_occurred.emit(str(e))
                # небольшая пауза, чтобы не заспамить лог при повторяющейся ошибке
                time.sleep(0.2)

            elapsed = time.perf_counter() - start
            remaining = self.interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

        logger.info("Поток анализа остановлен")

    def stop(self):
        """Корректно остановить поток и дождаться его завершения"""
        self._running = False
        if not self.wait(1500):
            logger.warning("Поток анализа не остановился вовремя, принудительное завершение")
            self.terminate()
            self.wait()
