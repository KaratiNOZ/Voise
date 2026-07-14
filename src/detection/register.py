# -*- coding: utf-8 -*-
"""
Регистр (грудной/микст/фальцет) как непрерывная величина + детекция
зажатости и срывов на переходах — то, вокруг чего построена методика
SLS (Speech Level Singing).

Сознательно НЕ пересчитывает признаки заново, а опирается на то, что
уже надёжно посчитано в voice_type.py (smoothed_score там уже сглажен
скользящим средним и стабилизирован гистерезисом - см. комментарии в
detect_voice_type). Дублировать эту логику здесь смысла нет, только
интерпретируем тот же score как непрерывную шкалу регистра, а не
бинарное chest/falsetto.
"""

from collections import deque

import numpy as np

from src.crash_logger import get_logger

logger = get_logger()


class RegisterAnalyzer:
    """Превращает falsetto_score в понятную 5-ступенчатую шкалу регистра"""

    LABELS = [
        (0.20, "грудной"),
        (0.40, "нижний микст"),
        (0.60, "микст"),
        (0.80, "верхний микст"),
        (1.01, "фальцет"),
    ]

    def estimate(self, voice_type_data, quality_data):
        """
        Args:
            voice_type_data: результат VoiceTypeDetector.detect_voice_type()
            quality_data: результат QualityAnalyzer.analyze_quality()

        Returns:
            dict {
                'register_mix': 0..1 (0=грудной, 1=фальцет),
                'label': str,
                'confidence': 0..1
            }
        """
        if voice_type_data is None:
            return {'register_mix': 0.0, 'label': 'Не определено', 'confidence': 0.0}

        register_mix = float(voice_type_data.get('features', {}).get(
            'smoothed_score', voice_type_data.get('confidence', 0.0)
        ))
        register_mix = float(np.clip(register_mix, 0.0, 1.0))

        label = "фальцет"
        for threshold, name in self.LABELS:
            if register_mix < threshold:
                label = name
                break

        # Уверенность зависит от чистоты сигнала (HNR) - на шумном/грязном
        # звуке форманты и наклон спектра считаются ненадёжно
        hnr = quality_data.get('hnr', 0.0) if quality_data else 0.0
        confidence = float(np.clip(hnr / 25.0, 0.0, 1.0))

        return {
            'register_mix': register_mix,
            'label': label,
            'confidence': confidence,
        }


class StrainDetector:
    """
    Эвристическая детекция напряжения гортани и срывов ("трещин") на
    переходах регистра по короткой истории последних кадров.

    Работает на тех же данных, что уже считаются в analyze_chunk на
    каждом кадре (10 раз/сек по умолчанию), доп. вычислений почти нет.
    """

    def __init__(self, window_size=15):
        # 15 кадров ~= 1.5 сек истории при стандартном update_interval
        self.pitch_history = deque(maxlen=window_size)
        self.hnr_history = deque(maxlen=window_size)
        self.register_history = deque(maxlen=window_size)

    def reset(self):
        self.pitch_history.clear()
        self.hnr_history.clear()
        self.register_history.clear()

    def update(self, frequency, hnr, register_mix):
        """
        Args:
            frequency: текущая частота Hz (pitch_data['frequency'])
            hnr: текущий HNR (quality_data['hnr'])
            register_mix: текущий register_mix из RegisterAnalyzer

        Returns:
            dict {
                'strain_score': 0..1,
                'break_detected': bool,
                'note': str
            }
        """
        try:
            self.pitch_history.append(float(frequency))
            self.hnr_history.append(float(hnr))
            self.register_history.append(float(register_mix))

            if len(self.pitch_history) < 5:
                return {'strain_score': 0.0, 'break_detected': False, 'note': 'Накопление данных'}

            pitches = np.array(self.pitch_history)
            hnrs = np.array(self.hnr_history)
            registers = np.array(self.register_history)

            # 1. Дрожание высоты тона (jitter-подобная метрика) -
            #    признак напряжения гортани
            pitch_deltas = np.abs(np.diff(pitches))
            jitter = float(np.mean(pitch_deltas) / (np.mean(pitches) + 1e-6))

            # 2. Резкий провал HNR внутри окна - признак срыва/трещины
            hnr_drop = float(np.max(hnrs) - hnrs[-1])

            # 3. Резкий скачок регистра за короткое окно - признак
            #    "переключения" вместо плавного перехода, ровно то, что
            #    SLS-техника должна убирать
            register_jump = float(np.max(np.abs(np.diff(registers))))

            strain_score = float(np.clip(
                0.5 * min(jitter * 20, 1.0) +
                0.3 * min(hnr_drop / 10.0, 1.0) +
                0.2 * min(register_jump * 5, 1.0),
                0.0, 1.0
            ))

            break_detected = hnr_drop > 6.0 and register_jump > 0.25

            if break_detected:
                note = "Похоже на срыв/трещину на переходе регистра"
            elif strain_score > 0.6:
                note = "Голос дрожит/напряжён"
            elif strain_score > 0.3:
                note = "Лёгкое напряжение"
            else:
                note = "Звучит свободно"

            return {
                'strain_score': strain_score,
                'break_detected': break_detected,
                'note': note,
            }
        except Exception:
            logger.exception("Ошибка в StrainDetector.update")
            return {'strain_score': 0.0, 'break_detected': False, 'note': 'Ошибка анализа'}
