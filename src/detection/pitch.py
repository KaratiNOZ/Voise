# -*- coding: utf-8 -*-
"""Определение высоты тона (pitch detection)"""

import numpy as np
import librosa

from src.crash_logger import get_logger

logger = get_logger()


class PitchDetector:
    """Детектор высоты тона"""

    # MIDI ноты и их частоты (A4 = 440 Hz)
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

    # Верхняя граница поиска pitch расширена до C7, чтобы покрывать
    # действительно высокие ноты (сопрано и т.п.), а не только C6.
    FMIN_NOTE = 'E2'
    FMAX_NOTE = 'C7'

    def __init__(self, config):
        self.sample_rate = config['audio']['sample_rate']
        self.threshold = config['analysis']['pitch_threshold']

        self.fmin = librosa.note_to_hz(self.FMIN_NOTE)
        self.fmax = librosa.note_to_hz(self.FMAX_NOTE)

        # Кэш для сглаживания дрожания между кадрами
        self._last_frequency = None
        self._stable_count = 0

        # Не используем аудио старше ~0.5с - для real-time анализа
        # этого достаточно и держит расход CPU предсказуемым.
        self._max_pitch_samples = int(self.sample_rate * 0.5)

    @staticmethod
    def hz_to_midi(frequency):
        """
        Конвертировать частоту в MIDI номер ноты

        Args:
            frequency: Частота в Hz

        Returns:
            MIDI номер ноты (float)
        """
        if frequency <= 0:
            return None
        return 69 + 12 * np.log2(frequency / 440.0)

    @staticmethod
    def midi_to_hz(midi_note):
        """
        Конвертировать MIDI номер в частоту

        Args:
            midi_note: MIDI номер ноты

        Returns:
            Частота в Hz
        """
        return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))

    @staticmethod
    def midi_to_note_name(midi_note):
        """
        Конвертировать MIDI номер в название ноты

        Args:
            midi_note: MIDI номер ноты

        Returns:
            Название ноты (например, "C4", "A#5")
        """
        if midi_note is None:
            return None

        midi_int = int(round(midi_note))
        octave = (midi_int // 12) - 1
        note_idx = midi_int % 12
        note_name = PitchDetector.NOTE_NAMES[note_idx]

        return f"{note_name}{octave}"

    def _autocorrelation_confidence(self, audio_data, frequency):
        """
        Реальная оценка уверенности через нормированную автокорреляцию
        на найденном периоде ("clarity" / чистота периодичности сигнала).

        Раньше уверенность вычислялась как 1/(1+std/frequency) -
        формула, которая почти всегда близка к 1 даже для НЕВЕРНОГО
        детектирования (она измеряет только стабильность оценки между
        кадрами, а не то, насколько сигнал вообще периодичен). Из-за
        этого мусорные детекции проходили с высокой "уверенностью".

        Автокорреляция на лаге, соответствующем периоду обнаруженной
        частоты, - стандартная и физически осмысленная мера: 1.0 для
        идеально периодичного тона, около 0 для шума/тишины.
        """
        if frequency is None or frequency <= 0:
            return 0.0

        period_samples = int(round(self.sample_rate / frequency))
        if period_samples <= 0 or period_samples >= len(audio_data):
            return 0.5

        x = audio_data.astype(np.float64) - np.mean(audio_data)
        usable_len = len(x) - period_samples
        if usable_len <= 0:
            return 0.5

        r0 = np.sum(x[:usable_len] ** 2)
        r1 = np.sum(x[:usable_len] * x[period_samples:period_samples + usable_len])

        if r0 <= 1e-12:
            return 0.0

        clarity = r1 / r0
        return float(np.clip(clarity, 0.0, 1.0))

    def _correct_octave_error(self, audio_data, frequency):
        """
        Эвристическая проверка на "октавную ошибку" YIN.

        Классический баг pitch-детекторов: когда основной тон (f0)
        относительно слаб по сравнению со 2-й гармоникой (типично для
        головного регистра/фальцета или при агрессивной фильтрации),
        алгоритм иногда сообщает субгармонику - частоту РОВНО в 2 раза
        ниже настоящей. Из-за этого пользователь, поющий высокую ноту,
        может получить "идеальное попадание" в совершенно другую,
        низкую целевую ноту.

        Сравниваем энергию спектра рядом с обнаруженной частотой и
        рядом с удвоенной частотой. Если "гармоника x2" заметно сильнее
        самой f0 - это признак того, что настоящая высота тона выше,
        и мы её корректируем.
        """
        try:
            if frequency * 2 > self.fmax * 1.05:
                return frequency

            spectrum = np.abs(np.fft.rfft(audio_data))
            freqs = np.fft.rfftfreq(len(audio_data), 1.0 / self.sample_rate)

            def amp_near(target_freq, tol_hz=20):
                mask = np.abs(freqs - target_freq) <= tol_hz
                if not np.any(mask):
                    return 0.0
                return float(np.max(spectrum[mask]))

            base_amp = amp_near(frequency)
            octave_amp = amp_near(frequency * 2)

            if base_amp > 0 and octave_amp > base_amp * 1.3:
                return frequency * 2.0
        except Exception:
            logger.debug("Не удалось выполнить проверку октавной ошибки", exc_info=True)

        return frequency

    def detect_pitch(self, audio_data):
        """
        Определить высоту тона в аудио данных

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            dict с данными: {
                'frequency': частота в Hz,
                'midi_note': MIDI номер,
                'note_name': название ноты,
                'confidence': уверенность (0-1)
            }
        """
        if audio_data is None or len(audio_data) < 512:
            return None

        if not np.all(np.isfinite(audio_data)):
            logger.debug("detect_pitch: получен кадр с NaN/Inf, пропущен")
            return None

        if len(audio_data) > self._max_pitch_samples:
            audio_data = audio_data[-self._max_pitch_samples:]

        frame_length = min(2048, len(audio_data))
        if frame_length < 512:
            return None

        try:
            f0 = librosa.yin(
                audio_data,
                fmin=self.fmin,
                fmax=self.fmax,
                sr=self.sample_rate,
                frame_length=frame_length
            )

            valid_f0 = f0[f0 > 0]

            if len(valid_f0) == 0:
                return None

            frequency = float(np.median(valid_f0))

            if frequency <= 0 or np.isnan(frequency):
                return None

            # Лёгкое сглаживание дрожания между кадрами для УЖЕ близких
            # значений (не подменяет частоту при реальной смене ноты,
            # т.к. диапазон в 5 Hz разрывается при любом заметном скачке)
            if self._last_frequency is not None:
                diff = abs(frequency - self._last_frequency)
                if diff < 5:
                    self._stable_count += 1
                    if self._stable_count > 2:
                        frequency = self._last_frequency
                else:
                    self._stable_count = 0
            self._last_frequency = frequency

            # Проверка и коррекция октавной ошибки по спектру исходного кадра
            frequency = self._correct_octave_error(audio_data, frequency)

            # Реальная оценка уверенности через автокорреляцию (clarity).
            # ВАЖНО: раньше здесь было жёсткое отсечение по порогу
            # (confidence < threshold -> None), но настоящая тишина/шум
            # уже отсекается раньше, на уровне noise gate в
            # AudioProcessor - там весь кадр обнуляется, и process()
            # возвращает None ДО того, как мы вообще сюда попадаем.
            # Дополнительное отсечение здесь только резало реальное
            # пение всякий раз, когда честная (а не как раньше -
            # фиктивная) уверенность оказывалась не идеальной из-за
            # шума с микрофона. confidence остаётся в результате для
            # информации/отладки, но больше не приводит к "Голос не
            # обнаружен".
            confidence = self._autocorrelation_confidence(audio_data, frequency)

            midi_note = self.hz_to_midi(frequency)
            note_name = self.midi_to_note_name(midi_note)

            return {
                'frequency': float(frequency),
                'midi_note': float(midi_note),
                'note_name': note_name,
                'confidence': float(confidence)
            }

        except Exception:
            # В случае ошибки просто возвращаем None вместо краша
            logger.exception("Ошибка определения pitch")
            return None

    @staticmethod
    def calculate_cents_difference(freq1, freq2):
        """
        Вычислить разницу между двумя частотами в центах

        Args:
            freq1: Первая частота (Hz)
            freq2: Вторая частота (Hz)

        Returns:
            Разница в центах (100 центов = 1 полутон)
        """
        if freq1 <= 0 or freq2 <= 0:
            return None

        return 1200 * np.log2(freq1 / freq2)

    def check_pitch_match(self, detected_freq, target_freq, tolerance_cents=50):
        """
        Проверить попадание в ноту

        Args:
            detected_freq: Обнаруженная частота
            target_freq: Целевая частота
            tolerance_cents: Допустимое отклонение в центах

        Returns:
            dict с результатом: {
                'match': попал ли в ноту (bool),
                'cents_off': отклонение в центах,
                'percentage': процент точности (0-100)
            }
        """
        if detected_freq is None or target_freq is None:
            return None

        cents_off = self.calculate_cents_difference(detected_freq, target_freq)

        if cents_off is None:
            return None

        match = abs(cents_off) <= tolerance_cents

        if abs(cents_off) <= tolerance_cents:
            percentage = 100 * (1 - abs(cents_off) / tolerance_cents)
        else:
            percentage = 0

        return {
            'match': match,
            'cents_off': float(cents_off),
            'percentage': float(percentage)
        }
