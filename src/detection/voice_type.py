# -*- coding: utf-8 -*-
"""Определение типа голоса (грудной/фальцет)"""

import numpy as np
from scipy import signal
from scipy.linalg import solve_toeplitz, LinAlgError

from src.crash_logger import get_logger

logger = get_logger()


class VoiceTypeDetector:
    """Детектор типа голоса"""

    def __init__(self, config):
        self.sample_rate = config['audio']['sample_rate']
        self.falsetto_threshold = config['voice_detection']['falsetto_threshold']

    def calculate_formants(self, audio_data):
        """
        Вычислить форманты (резонансные частоты голосового тракта).

        Раньше матрица автокорреляции R собиралась двойным Python-циклом
        (~lpc_order^2 итераций на КАЖДЫЙ вызов) - это была одна из
        основных причин нагрузки на CPU. Теперь используется
        scipy.linalg.solve_toeplitz, который решает ту же систему
        Юла-Уокера значительно быстрее и без ручных циклов.

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            list первых 4 формант в Hz
        """
        lpc_order = int(self.sample_rate / 1000) + 2

        if len(audio_data) <= lpc_order:
            return []

        r = np.correlate(audio_data, audio_data, mode='full')
        r = r[len(r) // 2:]
        r = r[:lpc_order + 1]

        if r[0] == 0:
            return []

        try:
            # Симметричная теплицева система Юла-Уокера: R * a = r[1:]
            a = solve_toeplitz(r[:lpc_order], r[1:lpc_order + 1])
        except (LinAlgError, ValueError):
            return []

        roots = np.roots(np.concatenate(([1], -a)))
        roots = roots[np.abs(roots) < 1]

        angles = np.angle(roots)
        freqs = angles * (self.sample_rate / (2 * np.pi))

        freqs = freqs[freqs > 0]
        freqs = np.sort(freqs)

        return freqs[:4] if len(freqs) >= 4 else freqs

    def calculate_spectral_slope(self, audio_data):
        """
        Вычислить наклон спектра.
        Фальцет имеет более крутой спад высоких частот

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Наклон спектра в дБ/Hz
        """
        spectrum = np.abs(np.fft.rfft(audio_data))
        freqs = np.fft.rfftfreq(len(audio_data), 1 / self.sample_rate)

        spectrum_db = 20 * np.log10(spectrum + 1e-10)

        mask = (freqs >= 200) & (freqs <= 2000)
        if np.sum(mask) < 2:
            return 0

        x = freqs[mask]
        y = spectrum_db[mask]

        slope = np.polyfit(x, y, 1)[0]

        return slope

    def calculate_harmonic_ratio(self, audio_data):
        """
        Вычислить соотношение четных и нечетных гармоник.
        Фальцет имеет больше нечетных гармоник

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Отношение четных к нечетным гармоникам
        """
        spectrum = np.abs(np.fft.rfft(audio_data))
        freqs = np.fft.rfftfreq(len(audio_data), 1 / self.sample_rate)

        peaks, properties = signal.find_peaks(spectrum, height=np.max(spectrum) * 0.1)

        if len(peaks) < 2:
            return 1.0

        peak_freqs = freqs[peaks]
        peak_heights = properties['peak_heights']

        f0 = peak_freqs[0]

        if f0 < 50:
            return 1.0

        even_energy = 0
        odd_energy = 0

        for freq, height in zip(peak_freqs, peak_heights):
            harmonic_num = round(freq / f0)
            if harmonic_num < 1:
                continue

            if harmonic_num % 2 == 0:
                even_energy += height
            else:
                odd_energy += height

        if odd_energy > 0:
            return even_energy / odd_energy
        else:
            return 1.0

    def detect_voice_type(self, audio_data, detected_pitch=None):
        """
        Определить тип голоса (грудной/фальцет)

        Args:
            audio_data: numpy array с аудио данными
            detected_pitch: dict с данными о высоте тона (опционально)

        Returns:
            dict с результатом или None
        """
        if audio_data is None or len(audio_data) < 512:
            return None

        try:
            formants = self.calculate_formants(audio_data)
            spectral_slope = self.calculate_spectral_slope(audio_data)
            harmonic_ratio = self.calculate_harmonic_ratio(audio_data)
        except Exception:
            logger.exception("Ошибка при вычислении признаков типа голоса")
            return None

        falsetto_score = 0

        if spectral_slope < -0.01:
            falsetto_score += 0.4
        elif spectral_slope < -0.005:
            falsetto_score += 0.2

        if harmonic_ratio < 0.5:
            falsetto_score += 0.4
        elif harmonic_ratio < 0.7:
            falsetto_score += 0.2

        if detected_pitch and detected_pitch.get('frequency'):
            freq = detected_pitch['frequency']
            if freq > 350:
                falsetto_score += 0.2

        falsetto_score = min(1.0, falsetto_score)

        is_falsetto = falsetto_score >= self.falsetto_threshold
        voice_type = 'falsetto' if is_falsetto else 'chest'
        confidence = falsetto_score if is_falsetto else (1.0 - falsetto_score)

        return {
            'type': voice_type,
            'confidence': float(confidence),
            'features': {
                'formants': [float(f) for f in formants],
                'spectral_slope': float(spectral_slope),
                'harmonic_ratio': float(harmonic_ratio),
                'falsetto_score': float(falsetto_score)
            }
        }

    def get_voice_type_description(self, voice_type_data):
        """
        Получить текстовое описание типа голоса

        Args:
            voice_type_data: dict с данными от detect_voice_type

        Returns:
            str с описанием
        """
        if voice_type_data is None:
            return "Не определено"

        voice_type = voice_type_data['type']
        confidence = voice_type_data['confidence']

        if voice_type == 'falsetto':
            if confidence > 0.8:
                return "Фальцет (уверенно)"
            else:
                return "Фальцет (вероятно)"
        else:
            if confidence > 0.8:
                return "Грудной голос (уверенно)"
            else:
                return "Грудной голос (вероятно)"
