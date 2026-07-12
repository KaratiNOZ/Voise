# -*- coding: utf-8 -*-
"""Обработка аудиосигнала"""

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter

from src.crash_logger import get_logger

logger = get_logger()


class AudioProcessor:
    """Обработчик аудиосигнала для фильтрации и подготовки к анализу"""

    def __init__(self, config):
        self.sample_rate = config['audio']['sample_rate']
        self.noise_gate_db = config['analysis']['noise_gate_db']

        # Параметры фильтра для голоса
        self.voice_lowcut = config['voice_detection']['min_frequency']
        self.voice_highcut = config['voice_detection']['max_frequency']

        # Раньше коэффициенты фильтра Баттерворта пересчитывались
        # (включая нахождение полюсов/нулей) на КАЖДОМ кадре анализа -
        # это заметная доля CPU-нагрузки, которая напрямую вела к лагам.
        # Теперь считаем их один раз при создании процессора.
        #
        # ВАЖНО: фильтр представлен в виде SOS (second-order sections),
        # а не классических b/a коэффициентов передаточной функции.
        # Полосовой Баттерворт 5-го порядка в форме b/a фактически
        # становится фильтром 10-го порядка с коэффициентами очень
        # разного масштаба - это классически неустойчиво в floating
        # point и может давать переполнение/NaN/Inf прямо в аудио-данных
        # (именно это было видно в логах: "overflow encountered in
        # square" и т.п. в самом librosa/numpy). SOS-форма считает
        # фильтр как каскад устойчивых звеньев 2-го порядка и не имеет
        # этой проблемы - стандартная практика для аудио-фильтрации.
        self._filter_order = 5
        self._sos = None
        self._build_filter()

    def _build_filter(self):
        """Построить и закэшировать SOS-коэффициенты полосового фильтра"""
        nyquist = self.sample_rate / 2
        low = max(1e-6, self.voice_lowcut / nyquist)
        high = min(0.999999, self.voice_highcut / nyquist)

        if low >= high:
            logger.warning(
                "Некорректный диапазон частот фильтра (%s-%s Hz), используется запасной диапазон",
                self.voice_lowcut, self.voice_highcut
            )
            low, high = 80 / nyquist, 1000 / nyquist

        self._sos = signal.butter(self._filter_order, [low, high], btype='band', output='sos')
        # Консервативная минимальная длина сигнала для sosfiltfilt
        # (padlen внутри scipy зависит от числа секций)
        self._min_filter_len = 3 * 2 * self._sos.shape[0] + 3

    def apply_noise_gate(self, audio_data):
        """
        Применить noise gate для отсечения тихих шумов

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Обработанные данные
        """
        rms = np.sqrt(np.mean(audio_data ** 2))

        if rms > 0:
            db = 20 * np.log10(rms)
        else:
            db = -np.inf

        if db < self.noise_gate_db:
            return np.zeros_like(audio_data)

        return audio_data

    def bandpass_filter(self, audio_data):
        """
        Полосовой фильтр для выделения диапазона голоса (устойчивая SOS-форма)

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Отфильтрованные данные или None, если сигнал слишком короткий
            или фильтрация дала некорректный результат
        """
        flat = audio_data.flatten()

        if len(flat) <= self._min_filter_len:
            # Сигнал слишком короткий для sosfiltfilt с текущим порядком фильтра
            return None

        try:
            filtered = signal.sosfiltfilt(self._sos, flat)
        except ValueError:
            logger.debug("Не удалось применить полосовой фильтр к короткому кадру")
            return None

        if not np.all(np.isfinite(filtered)):
            # Подстраховка: если всё же где-то проскочил NaN/Inf -
            # не пропускаем такой кадр дальше в анализ
            logger.debug("Полосовой фильтр вернул NaN/Inf, кадр пропущен")
            return None

        return filtered

    def reduce_noise(self, audio_data):
        """
        Уменьшение шума медианным фильтром

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Обработанные данные
        """
        return median_filter(audio_data, size=3)

    def process(self, audio_data):
        """
        Полная обработка аудио: фильтрация + noise gate

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Обработанные данные готовые для анализа, либо None
        """
        if audio_data is None or len(audio_data) == 0:
            return None

        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        gated = self.apply_noise_gate(audio_data)

        if np.allclose(gated, 0):
            return None

        filtered = self.bandpass_filter(gated)
        if filtered is None:
            return None

        clean = self.reduce_noise(filtered)

        if not np.all(np.isfinite(clean)):
            logger.debug("Итоговый аудио-кадр содержит NaN/Inf после обработки, пропущен")
            return None

        return clean

    def update_config(self, config):
        """Обновить параметры фильтра без пересоздания всего процессора"""
        self.sample_rate = config['audio']['sample_rate']
        self.noise_gate_db = config['analysis']['noise_gate_db']
        self.voice_lowcut = config['voice_detection']['min_frequency']
        self.voice_highcut = config['voice_detection']['max_frequency']
        self._build_filter()

    @staticmethod
    def get_rms(audio_data):
        """Получить RMS (громкость) сигнала"""
        return np.sqrt(np.mean(audio_data ** 2))

    @staticmethod
    def get_db(audio_data):
        """Получить уровень в дБ"""
        rms = AudioProcessor.get_rms(audio_data)
        if rms > 0:
            return 20 * np.log10(rms)
        return -np.inf
