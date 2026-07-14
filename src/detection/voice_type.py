# -*- coding: utf-8 -*-
"""Определение типа голоса (грудной/фальцет)"""

from collections import deque

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

        # --- Стабилизация решения ---
        # Раньше тип голоса определялся заново на КАЖДОМ кадре без
        # какой-либо памяти о предыдущих кадрах. Даже на идеально
        # стабильно спетой ноте признаки (наклон спектра, отношение
        # гармоник) чуть колеблются от кадра к кадру из-за шума
        # микрофона и естественной микро-нестабильности голоса. Если
        # falsetto_score оказывался рядом с порогом, результат
        # дёргался между "falsetto" и "chest" каждый кадр.
        #
        # Решение - две меры:
        # 1) Сглаживание score скользящим средним по последним кадрам.
        # 2) Гистерезис: разные пороги для входа в фальцет и выхода
        #    из него, так что решение не может "дребезжать" на границе.
        smoothing_frames = config['voice_detection'].get('smoothing_frames', 6)
        self._score_history = deque(maxlen=smoothing_frames)
        self._hysteresis_margin = config['voice_detection'].get('hysteresis_margin', 0.08)
        self._current_type = None  # None, 'falsetto' или 'chest'

    def calculate_formants(self, audio_data):
        """
        Вычислить форманты (резонансные частоты голосового тракта).

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
        Вычислить наклон спектра. Фальцет имеет более крутой спад
        высоких частот.

        Кадр окуривается окном Ханна перед FFT - без окна края кадра
        обрезаются резко, что даёт спектральную утечку и шумный,
        дёргающийся от кадра к кадру наклон, особенно на границе
        порога falsetto_threshold.

        Args:
            audio_data: numpy array с аудио данными

        Returns:
            Наклон спектра в дБ/Hz
        """
        window = np.hanning(len(audio_data))
        windowed = audio_data * window

        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), 1 / self.sample_rate)

        spectrum_db = 20 * np.log10(spectrum + 1e-10)

        mask = (freqs >= 200) & (freqs <= 2000)
        if np.sum(mask) < 2:
            return 0

        x = freqs[mask]
        y = spectrum_db[mask]

        slope = np.polyfit(x, y, 1)[0]

        return slope

    def calculate_harmonic_ratio(self, audio_data, f0_hint=None):
        """
        Вычислить соотношение четных и нечетных гармоник.
        Фальцет имеет больше нечетных гармоник.

        Раньше f0 бралась как "первый найденный пик спектра" -
        ненадёжная оценка, которая скачет от кадра к кадру (шум,
        побочные пики рядом с порогом height=max*0.1 то появляются,
        то исчезают). Теперь если снаружи уже известна частота
        (сглаженная в PitchDetector), используем её - она гораздо
        стабильнее.

        Args:
            audio_data: numpy array с аудио данными
            f0_hint: известная (сглаженная) частота основного тона, Hz

        Returns:
            Отношение четных к нечетным гармоникам
        """
        window = np.hanning(len(audio_data))
        windowed = audio_data * window

        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), 1 / self.sample_rate)

        peaks, properties = signal.find_peaks(spectrum, height=np.max(spectrum) * 0.1)

        if len(peaks) < 2:
            return 1.0

        peak_freqs = freqs[peaks]
        peak_heights = properties['peak_heights']

        if f0_hint and f0_hint > 0:
            f0 = f0_hint
        else:
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

        f0_hint = None
        if detected_pitch and detected_pitch.get('frequency'):
            f0_hint = detected_pitch['frequency']

        try:
            formants = self.calculate_formants(audio_data)
            spectral_slope = self.calculate_spectral_slope(audio_data)
            harmonic_ratio = self.calculate_harmonic_ratio(audio_data, f0_hint=f0_hint)
        except Exception:
            logger.exception("Ошибка при вычислении признаков типа голоса")
            return None

        # --- Голосование вместо суммы весов ---
        # Раньше falsetto_score был простой суммой весов, из-за чего
        # ДВА слабых, по отдельности ничего не доказывающих сигнала
        # (например, чуть завышенный spectral_slope + просто высокая
        # нота) складывались и пробивали даже строгий порог 0.6 -
        # реальный грудной голос получал "Фальцет (вероятно)".
        #
        # Теперь каждый признак голосует независимо: 1.0 - сильный
        # сигнал, 0.5 - слабый/неоднозначный, 0.0 - против фальцета.
        # Итоговый score штрафуется вдвое, если среди голосов нет ни
        # одного СИЛЬНОГО - тогда одни слабые сигналы не могут поднять
        # score выше половины порога сами по себе.
        votes = []

        if spectral_slope < -0.01:
            votes.append(1.0)
        elif spectral_slope < -0.005:
            votes.append(0.5)
        else:
            votes.append(0.0)

        if harmonic_ratio < 0.5:
            votes.append(1.0)
        elif harmonic_ratio < 0.7:
            votes.append(0.5)
        else:
            votes.append(0.0)

        if f0_hint and f0_hint > 350:
            votes.append(0.5)  # частота сама по себе - только вспомогательный сигнал
        else:
            votes.append(0.0)

        strong_votes = sum(1 for v in votes if v >= 1.0)
        raw_score = sum(votes) / len(votes)

        if strong_votes == 0:
            raw_score *= 0.5

        falsetto_score = min(1.0, raw_score)

        # --- Сглаживание по нескольким последним кадрам ---
        self._score_history.append(falsetto_score)
        smoothed_score = float(np.mean(self._score_history))

        # --- Гистерезис вокруг порога ---
        # Если сейчас "falsetto" - выйти из него можно только заметно
        # ниже порога. Если сейчас "chest" - войти во "falsetto" можно
        # только заметно выше порога. Это и убирает дребезг на границе.
        if self._current_type == 'falsetto':
            is_falsetto = smoothed_score >= (self.falsetto_threshold - self._hysteresis_margin)
        elif self._current_type == 'chest':
            is_falsetto = smoothed_score >= (self.falsetto_threshold + self._hysteresis_margin)
        else:
            is_falsetto = smoothed_score >= self.falsetto_threshold

        voice_type = 'falsetto' if is_falsetto else 'chest'
        self._current_type = voice_type

        confidence = smoothed_score if is_falsetto else (1.0 - smoothed_score)

        return {
            'type': voice_type,
            'confidence': float(confidence),
            'features': {
                'formants': [float(f) for f in formants],
                'spectral_slope': float(spectral_slope),
                'harmonic_ratio': float(harmonic_ratio),
                'falsetto_score': float(falsetto_score),
                'smoothed_score': smoothed_score
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