# -*- coding: utf-8 -*-
"""Простой синтезатор звука для MIDI-клавиатуры"""

import numpy as np
import sounddevice as sd
from threading import Lock

from src.crash_logger import get_logger

logger = get_logger()

# Длина плавного нарастания/затухания громкости (в сэмплах), чтобы
# избежать щелчков при смене ноты - без блокирующего time.sleep()
_FADE_SAMPLES = 400


class SimpleSynthesizer:
    """
    Простой синтезатор для воспроизведения нот.

    ВАЖНО: раньше каждый клик по клавише открывал НОВЫЙ sd.OutputStream
    (и синхронно закрывал предыдущий) прямо в обработчике клика мыши.
    Открытие аудио-устройства - относительно медленная операция
    (десятки-сотни мс), из-за которой клавиатура ощутимо "лагала":
    интерфейс не мог перерисоваться, пока не откроется поток.

    Теперь поток открывается ОДИН РАЗ и живёт всё время работы
    приложения. Смена ноты - это просто изменение целевой частоты под
    локом (микросекунды), без пересоздания устройства.
    """

    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.is_playing = False
        self.current_frequency = None
        self.lock = Lock()
        self.stream = None
        self.phase = 0.0
        # Множитель громкости для плавного fade in/out без sleep()
        self._gain = 0.0
        self._target_gain = 0.0

        self._ensure_stream()

    def midi_to_frequency(self, midi_note):
        """Конвертировать MIDI номер в частоту"""
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    def _ensure_stream(self):
        """Открыть постоянный выходной поток, если он ещё не открыт"""
        if self.stream is not None:
            return
        try:
            self.stream = sd.OutputStream(
                channels=1,
                samplerate=self.sample_rate,
                blocksize=1024,
                callback=self.audio_callback
            )
            self.stream.start()
        except Exception:
            logger.exception("Не удалось открыть аудио-поток синтезатора")
            self.stream = None

    def generate_wave(self, frequency, num_samples, phase=0.0):
        """
        Генерировать волну с заданной частотой

        Args:
            frequency: Частота в Hz
            num_samples: Количество сэмплов
            phase: Начальная фаза

        Returns:
            numpy array с аудио сигналом, новая фаза
        """
        t = np.arange(num_samples) / self.sample_rate

        wave = np.sin(2 * np.pi * frequency * t + phase)
        wave += 0.3 * np.sin(2 * np.pi * frequency * 2 * t + phase)
        wave += 0.15 * np.sin(2 * np.pi * frequency * 3 * t + phase)

        wave = wave / np.max(np.abs(wave) + 1e-10) * 0.2

        new_phase = (2 * np.pi * frequency * num_samples / self.sample_rate + phase) % (2 * np.pi)

        return wave.astype(np.float32), new_phase

    def audio_callback(self, outdata, frames, time_info, status):
        """Callback для потокового воспроизведения (без блокировок и пересоздания устройства)"""
        if status:
            logger.debug("Synth audio status: %s", status)

        with self.lock:
            playing = self.is_playing
            freq = self.current_frequency

            if playing and freq:
                wave, self.phase = self.generate_wave(freq, frames, self.phase)
            else:
                wave = np.zeros(frames, dtype=np.float32)

            # Плавный fade in/out по сэмплам, чтобы не было щелчков
            # при старте/остановке ноты (замена старому time.sleep(0.05))
            self._target_gain = 1.0 if playing else 0.0
            gains = np.linspace(self._gain, self._target_gain, frames, dtype=np.float32)
            self._gain = float(gains[-1]) if frames > 0 else self._gain

            outdata[:] = (wave * gains).reshape(-1, 1)

    def start_note(self, midi_note):
        """
        Начать воспроизведение ноты (непрерывно, без пересоздания потока)

        Args:
            midi_note: MIDI номер ноты (0-127)
        """
        try:
            self._ensure_stream()
            frequency = self.midi_to_frequency(midi_note)

            with self.lock:
                self.current_frequency = frequency
                self.is_playing = True

        except Exception:
            logger.exception("Ошибка start_note")
            with self.lock:
                self.is_playing = False

    def stop_note(self):
        """Остановить воспроизведение ноты (мгновенно, без sleep - затухание идёт в callback'е)"""
        try:
            with self.lock:
                self.is_playing = False
                self.current_frequency = None
        except Exception:
            logger.exception("Ошибка stop_note")

    def cleanup(self):
        """Полностью остановить и закрыть аудио-поток (вызывать при закрытии приложения)"""
        try:
            with self.lock:
                self.is_playing = False
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    logger.exception("Ошибка при закрытии потока синтезатора")
                self.stream = None
        except Exception:
            logger.exception("Ошибка cleanup синтезатора")
