"""
strain_detector.py
Эвристическая детекция напряжения ("зажатости") гортани и срывов
на переходах регистра (registration break) — то, над чем в первую
очередь работает SLS.

Использует скользящее окно последних N кадров pitch/HNR/register_mix,
которые ваш analyzer.py уже считает 10 раз в секунду.
"""

from collections import deque
from dataclasses import dataclass
import numpy as np


@dataclass
class StrainReading:
    strain_score: float     # 0..1, чем выше — тем больше признаков зажатости
    break_detected: bool    # True если похоже на "трещину"/срыв в этом кадре
    note: str                # человекочитаемая причина


class StrainDetector:
    def __init__(self, window_size: int = 15):
        # 15 кадров при 10Гц обновлении = 1.5 сек истории
        self.pitch_history = deque(maxlen=window_size)
        self.hnr_history = deque(maxlen=window_size)
        self.register_history = deque(maxlen=window_size)

    def update(self, pitch_hz: float, hnr: float, register_mix: float) -> StrainReading:
        self.pitch_history.append(pitch_hz)
        self.hnr_history.append(hnr)
        self.register_history.append(register_mix)

        if len(self.pitch_history) < 5:
            return StrainReading(0.0, False, "недостаточно данных")

        pitches = np.array(self.pitch_history)
        hnrs = np.array(self.hnr_history)
        registers = np.array(self.register_history)

        # 1. Дрожание pitch (jitter-подобная метрика) — признак напряжения
        pitch_deltas = np.abs(np.diff(pitches))
        jitter = float(np.mean(pitch_deltas) / (np.mean(pitches) + 1e-6))

        # 2. Резкий провал HNR внутри окна — признак срыва/трещины
        hnr_drop = float(np.max(hnrs) - hnrs[-1]) if len(hnrs) > 1 else 0.0

        # 3. Резкий скачок register_mix за короткое окно — типичный признак
        #    "переключения" вместо плавного перехода (то, что SLS должен убрать)
        register_jump = float(np.max(np.abs(np.diff(registers)))) if len(registers) > 1 else 0.0

        # Комбинируем в один score, веса — отправная точка, калибруй под себя
        strain_score = float(np.clip(
            0.5 * min(jitter * 20, 1.0) +
            0.3 * min(hnr_drop / 10.0, 1.0) +
            0.2 * min(register_jump * 5, 1.0),
            0.0, 1.0
        ))

        break_detected = hnr_drop > 6.0 and register_jump > 0.25

        if break_detected:
            note = "похоже на срыв/трещину на переходе регистра"
        elif strain_score > 0.6:
            note = "признаки зажатости: голос дрожит или напряжён"
        elif strain_score > 0.3:
            note = "лёгкое напряжение, стоит расслабить гортань"
        else:
            note = "звучит свободно"

        return StrainReading(strain_score, break_detected, note)
