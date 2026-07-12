# -*- coding: utf-8 -*-
"""Модуль для записи аудио с микрофона"""

import numpy as np
import sounddevice as sd
from threading import Thread, Event, Lock
from queue import Queue, Empty

from src.crash_logger import get_logger

logger = get_logger()


class AudioRecorder:
    """
    Запись аудио в реальном времени.

    ВАЖНО: раньше analyze-цикл вытаскивал из очереди только ОДИН чанк
    за раз, а callback устройства клал в неё чанки гораздо чаще, чем
    их успевали разбирать. Очередь росла бесконечно, и анализ со
    временем начинал показывать всё более "старый" звук - отсюда
    ощущение прогрессирующих лагов/подвисаний.

    Здесь очередь на каждый вызов get_audio_chunk() вычищается
    полностью и склеивается в один буфер, обрезанный до разумного
    максимума. Это гарантирует, что задержка никогда не накапливается:
    анализ всегда работает с самым свежим доступным звуком.
    """

    def __init__(self, config):
        self.sample_rate = config['audio']['sample_rate']
        self.chunk_size = config['audio']['chunk_size']
        self.channels = config['audio']['channels']
        self.device_index = config['audio']['device_index']

        # Не даём буферу анализа расти дольше ~1.5 секунды звука,
        # даже если обработка временно отстаёт - предотвращает
        # накопление задержки и лишнее потребление памяти.
        self._max_buffer_samples = int(self.sample_rate * 1.5)

        self.is_recording = False
        self.audio_queue = Queue()
        self.stop_event = Event()
        self.record_thread = None

        self._level_lock = Lock()
        self._current_db = -100.0
        self._last_error = None

    def start(self):
        """Начать запись"""
        if self.is_recording:
            return

        self.is_recording = True
        self.stop_event.clear()
        self._last_error = None
        self.record_thread = Thread(
            target=self._record_loop, daemon=True, name="AudioRecorderThread"
        )
        self.record_thread.start()

    def stop(self):
        """Остановить запись"""
        if not self.is_recording:
            return

        self.is_recording = False
        self.stop_event.set()
        if self.record_thread:
            self.record_thread.join(timeout=1.0)
            if self.record_thread.is_alive():
                logger.warning("Поток записи не завершился вовремя")

        # Очищаем очередь, чтобы не тащить старые данные в новую сессию
        self._drain_queue()

    def _record_loop(self):
        """Основной цикл записи"""

        def callback(indata, frames, time_info, status):
            if status:
                logger.debug("Audio callback status: %s", status)
            if self.is_recording:
                audio_data = indata.copy()
                self.audio_queue.put(audio_data)

                # Обновляем текущий уровень громкости для VU-метра
                rms = float(np.sqrt(np.mean(np.square(audio_data))))
                db = 20 * np.log10(rms) if rms > 1e-10 else -100.0
                with self._level_lock:
                    self._current_db = db

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.chunk_size,
                device=self.device_index,
                callback=callback
            ):
                self.stop_event.wait()
        except Exception as e:
            logger.exception("Ошибка записи аудио (устройство недоступно?)")
            self._last_error = str(e)
            self.is_recording = False

    def _drain_queue(self):
        """Полностью опустошить очередь и вернуть список чанков"""
        chunks = []
        while True:
            try:
                chunks.append(self.audio_queue.get_nowait())
            except Empty:
                break
        return chunks

    def get_audio_chunk(self):
        """
        Получить самый свежий доступный кусок аудио.

        Забирает ВСЁ, что накопилось в очереди с прошлого вызова,
        склеивает в один массив и (если нужно) обрезает до последних
        _max_buffer_samples сэмплов, чтобы анализ никогда не отставал
        от реального звука.
        """
        chunks = self._drain_queue()

        if not chunks:
            return None

        try:
            audio = np.concatenate(chunks, axis=0)
        except ValueError:
            logger.warning("Не удалось склеить аудио-чанки, пропускаем кадр")
            return None

        if len(audio) > self._max_buffer_samples:
            audio = audio[-self._max_buffer_samples:]

        # sounddevice отдаёт (frames, channels) - приводим к 1D для моно
        if audio.ndim > 1:
            audio = audio.flatten() if audio.shape[1] == 1 else audio.mean(axis=1)

        return audio

    def get_level_db(self):
        """Текущий уровень громкости входного сигнала в дБ (для VU-метра)"""
        with self._level_lock:
            return self._current_db

    def get_last_error(self):
        """Последняя ошибка потока записи (если была)"""
        return self._last_error

    @staticmethod
    def list_devices():
        """Список доступных аудио устройств"""
        return sd.query_devices()

    @staticmethod
    def get_default_input_device():
        """Получить индекс устройства ввода по умолчанию"""
        return sd.query_devices(kind='input')['index']
