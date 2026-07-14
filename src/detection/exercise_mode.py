"""
exercise_mode.py
SLS строится не на одной ноте, а на упражнениях: сирена вверх-вниз,
глиссандо через "переход" (passaggio), гласные на разной высоте.

Этот модуль задаёт траекторию ожидаемого pitch во времени и в реальном
времени сравнивает, насколько плавно и без срывов пользователь по ней идёт.
"""

from dataclasses import dataclass, field
from typing import List, Callable
import time
import numpy as np


@dataclass
class ExerciseResult:
    smoothness: float        # 0..1, насколько плавно (мало прыжков/срывов) пройдена траектория
    pitch_accuracy: float     # 0..1, среднее отклонение от целевой траектории
    breaks: int                # сколько раз strain_detector поймал break_detected
    duration_sec: float
    feedback: str


class SirenExercise:
    """
    Пример упражнения: сирена от low_note до high_note и обратно,
    классика SLS для сглаживания passaggio.
    """

    def __init__(self, low_hz: float, high_hz: float, duration_sec: float = 6.0):
        self.low_hz = low_hz
        self.high_hz = high_hz
        self.duration_sec = duration_sec
        self.start_time = None
        self._pitch_log: List[float] = []
        self._target_log: List[float] = []
        self._break_count = 0

    def target_pitch_at(self, t: float) -> float:
        """Синусоидальная траектория: вверх и обратно вниз за duration_sec."""
        phase = (t % self.duration_sec) / self.duration_sec  # 0..1
        # треугольная волна 0->1->0 для симметричного вверх-вниз
        triangle = 1 - abs(2 * phase - 1)
        return self.low_hz + (self.high_hz - self.low_hz) * triangle

    def start(self):
        self.start_time = time.time()
        self._pitch_log.clear()
        self._target_log.clear()
        self._break_count = 0

    def feed_frame(self, current_pitch_hz: float, break_detected: bool):
        """Вызывать на каждый кадр анализа (10 раз/сек), пока упражнение активно."""
        if self.start_time is None:
            self.start()
        t = time.time() - self.start_time
        target = self.target_pitch_at(t)
        self._pitch_log.append(current_pitch_hz)
        self._target_log.append(target)
        if break_detected:
            self._break_count += 1
        return t < self.duration_sec  # False когда упражнение закончилось

    def finish(self) -> ExerciseResult:
        pitches = np.array(self._pitch_log)
        targets = np.array(self._target_log)

        if len(pitches) == 0:
            return ExerciseResult(0, 0, 0, 0, "Нет данных — упражнение не было спето")

        # Точность: нормализованная ошибка в центах
        cents_error = 1200 * np.log2(np.clip(pitches, 1, None) / np.clip(targets, 1, None))
        mean_abs_cents = float(np.mean(np.abs(cents_error)))
        pitch_accuracy = float(np.clip(1 - mean_abs_cents / 200.0, 0.0, 1.0))  # 200 центов = совсем мимо

        # Плавность: маленькие резкие скачки pitch между кадрами = хорошо (кроме самой траектории)
        residual = pitches - targets
        jump_penalty = float(np.mean(np.abs(np.diff(residual))))
        smoothness = float(np.clip(1 - jump_penalty / 50.0, 0.0, 1.0))

        duration = len(pitches) / 10.0  # 10 Гц

        if self._break_count == 0 and smoothness > 0.8:
            fb = "Отличная плавная сирена, переход почти не заметен — то, что нужно в SLS"
        elif self._break_count > 0:
            fb = f"Срывов на переходе: {self._break_count}. Попробуй медленнее и тише в момент перехода"
        elif pitch_accuracy < 0.5:
            fb = "Траектория смазана — постарайся точнее следовать за целевой высотой"
        else:
            fb = "Неплохо, есть небольшая резкость — сглаживай движение голоса"

        return ExerciseResult(
            smoothness=smoothness,
            pitch_accuracy=pitch_accuracy,
            breaks=self._break_count,
            duration_sec=duration,
            feedback=fb,
        )
