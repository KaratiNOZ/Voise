# -*- coding: utf-8 -*-
"""
Секвенсор - режим "как в FL Studio": расставленные на пиано-ролле ноты
проигрываются одна за другой (Play/Space), синтезатор озвучивает
мелодию, а одновременно с этим продолжает работать обычный анализ
микрофона (AnalysisWorker) - на каждом шаге секвенсор просто говорит
VoiceAnalyzer'у, какая нота сейчас "целевая", поэтому вся уже
существующая логика проверки попадания в ноту (pitch_match) работает
без изменений.

Сам секвенсор не делает никакого тяжёлого аудио-анализа - только
таймер шагов в GUI-потоке (дешёвая операция: старт/стоп ноты
синтезатора + смена целевой ноты анализатора), поэтому отдельный поток
для него не нужен.
"""

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from src.crash_logger import get_logger

logger = get_logger()


class Sequencer(QObject):
    """Проигрывает ноты, расставленные на пиано-ролле, по шагам"""

    step_changed = pyqtSignal(int)              # текущий шаг (для плейхеда)
    note_started = pyqtSignal(int, int, int)     # step, midi_note, length_steps
    note_ended = pyqtSignal(int, int)            # step, midi_note - пора оценить попадание
    playback_finished = pyqtSignal()

    def __init__(self, synthesizer, analyzer, parent=None):
        super().__init__(parent)
        self.synthesizer = synthesizer
        self.analyzer = analyzer

        self.notes = []          # [{'step': int, 'note': int, 'length': int}, ...]
        self.num_steps = 32
        self.bpm = 100
        self.steps_per_beat = 4
        self.loop = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        self._current_step = -1
        self._active_note = None  # {'note', 'start_step', 'end_step'}
        self._is_playing = False

    def _step_interval_ms(self):
        beat_ms = 60000.0 / max(1, self.bpm)
        return beat_ms / self.steps_per_beat

    def load(self, notes, num_steps, bpm, steps_per_beat=4, loop=False):
        """Загрузить мелодию перед стартом"""
        self.notes = sorted(notes, key=lambda n: n['step'])
        self.num_steps = num_steps
        self.bpm = bpm
        self.steps_per_beat = steps_per_beat
        self.loop = loop

    def is_playing(self):
        return self._is_playing

    def start(self):
        """Начать (или перезапустить) воспроизведение"""
        if self._is_playing:
            return
        if not self.notes:
            logger.info("Секвенсор: нечего играть - ни одной ноты не расставлено")
            return

        self._is_playing = True
        self._current_step = -1
        self._active_note = None
        self._timer.start(int(self._step_interval_ms()))
        logger.info("Секвенсор запущен: %s BPM, %s шагов, %s нот",
                    self.bpm, self.num_steps, len(self.notes))

    def stop(self):
        """Остановить воспроизведение"""
        self._timer.stop()
        if self._active_note is not None:
            self._end_active_note()
        self._is_playing = False
        self._current_step = -1
        try:
            self.analyzer.clear_target_note()
        except Exception:
            logger.exception("Ошибка очистки целевой ноты при остановке секвенсора")
        try:
            self.synthesizer.stop_note()
        except Exception:
            logger.exception("Ошибка остановки синтезатора при остановке секвенсора")
        logger.info("Секвенсор остановлен")

    def set_bpm(self, bpm):
        """Изменить темп на лету"""
        self.bpm = bpm
        if self._is_playing:
            self._timer.setInterval(int(self._step_interval_ms()))

    # ------------------------------------------------------------------ #
    #  Внутреннее
    # ------------------------------------------------------------------ #

    def _end_active_note(self):
        note = self._active_note
        try:
            self.synthesizer.stop_note()
        except Exception:
            logger.exception("Ошибка остановки ноты синтезатора")
        self.note_ended.emit(note['start_step'], note['note'])
        self._active_note = None

    def _on_tick(self):
        self._current_step += 1

        if self._current_step >= self.num_steps:
            if self._active_note is not None:
                self._end_active_note()
            if self.loop:
                self._current_step = 0
            else:
                self._timer.stop()
                self._is_playing = False
                try:
                    self.analyzer.clear_target_note()
                except Exception:
                    logger.exception("Ошибка очистки целевой ноты по окончании секвенса")
                self.playback_finished.emit()
                return

        step = self._current_step

        # Завершаем текущую ноту, если её время вышло
        if self._active_note is not None and step >= self._active_note['end_step']:
            self._end_active_note()

        # Начинаем новую ноту, если она стартует на этом шаге
        starting = [n for n in self.notes if n['step'] == step]
        if starting and self._active_note is None:
            n = starting[0]
            try:
                self.synthesizer.start_note(n['note'])
                self.analyzer.set_target_note(n['note'])
            except Exception:
                logger.exception("Ошибка запуска ноты секвенсора")
            self._active_note = {
                'note': n['note'],
                'start_step': n['step'],
                'end_step': n['step'] + n['length']
            }
            self.note_started.emit(n['step'], n['note'], n['length'])
        elif self._active_note is None:
            # Пауза между нотами - убираем целевую ноту, чтобы тишина
            # между нотами случайно не засчиталась как попадание
            try:
                self.analyzer.clear_target_note()
            except Exception:
                pass

        self.step_changed.emit(step)
