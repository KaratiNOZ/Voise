# -*- coding: utf-8 -*-
"""
Пиано-ролл для режима "Секвенсор" - сетка "нота x время", как в FL Studio.

- Каждая строка - MIDI-нота (сверху высокие, снизу низкие).
- Каждый столбец - шаг по времени (16-я нота при steps_per_beat=4).

Взаимодействие мышью (как в FL Studio):
- ЛКМ на пустой ячейке + протяжка: рисует новую ноту (вправо - длина,
  вверх/вниз - высота). Пока тянете - слышно, какая нота получится.
- ЛКМ по ТЕЛУ существующей ноты + протяжка: перемещает ноту целиком
  (и по времени, и по высоте). Тоже слышно новую высоту при смене ряда.
- ЛКМ по КРАЮ (левому или правому) существующей ноты + протяжка:
  растягивает/сжимает её длину за этот край.
- ПКМ по ноте: удаляет её. Это единственный способ удаления.

Виджет ничего не знает про звук/анализ напрямую - вместо прямого вызова
синтезатора он эмитит сигналы note_preview(midi_note)/preview_stopped(),
на которые подписывается MainWindow и дёргает SimpleSynthesizer. Также
умеет подсвечивать шаг под "плейхедом" во время воспроизведения и
красить ноты по результату (попал/не попал/не было голоса).
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


class PianoRollWidget(QWidget):
    """Сетка расстановки нот для секвенсора"""

    # Эмитится при любом добавлении/удалении/перемещении/изменении ноты
    notes_changed = pyqtSignal()

    # Сигналы для предпрослушивания звука во время редактирования
    note_preview = pyqtSignal(int)   # MIDI-нота, которую сейчас нужно проиграть
    preview_stopped = pyqtSignal()   # редактирование закончено - звук выключить

    ROW_HEIGHT = 16
    COL_WIDTH = 22
    KEY_LABEL_WIDTH = 40
    EDGE_PX = 6  # ширина зоны у края ноты, за которую можно тянуть для ресайза

    def __init__(self, min_note=48, max_note=84, num_steps=32, parent=None):
        super().__init__(parent)

        self.min_note = min_note  # нижняя граница диапазона (например, C3)
        self.max_note = max_note  # верхняя граница диапазона (например, C6)
        self.num_steps = num_steps
        self.steps_per_beat = 4

        # Расставленные ноты: список dict {'step': int, 'note': int, 'length': int}
        self.notes = []

        # Состояние текущего перетаскивания: None | 'create' | 'move' | 'resize_left' | 'resize_right'
        self._drag_mode = None
        # Для 'create'
        self._drag_start_step = None
        self._drag_note = None
        self._drag_current_len = 1
        # Для 'move' / 'resize_*'
        self._drag_note_ref = None   # ссылка на реальный dict из self.notes, который редактируем
        self._drag_orig = None       # снимок исходных step/note/length на момент нажатия
        self._drag_grab_step = None
        self._drag_grab_note = None
        self._last_preview_note = None

        # Состояние воспроизведения (для отрисовки)
        self.playhead_step = -1
        # (step, note) -> 'hit' | 'miss' | 'none'
        self.step_results = {}

        self.setMouseTracking(True)
        self._update_min_size()

    # ------------------------------------------------------------------ #
    #  Геометрия
    # ------------------------------------------------------------------ #

    def _update_min_size(self):
        rows = self.max_note - self.min_note + 1
        self.setMinimumSize(
            self.KEY_LABEL_WIDTH + self.num_steps * self.COL_WIDTH,
            rows * self.ROW_HEIGHT
        )

    def _row_for_note(self, midi_note):
        return self.max_note - midi_note

    def _note_for_row(self, row):
        return self.max_note - row

    def _note_rect(self, step, note, length=1):
        row = self._row_for_note(note)
        x = self.KEY_LABEL_WIDTH + step * self.COL_WIDTH
        y = row * self.ROW_HEIGHT
        return QRect(x, y, length * self.COL_WIDTH, self.ROW_HEIGHT)

    def _pos_to_step_note(self, pos):
        """Строгая версия: возвращает (None, None), если позиция вне сетки"""
        x = pos.x() - self.KEY_LABEL_WIDTH
        if x < 0:
            return None, None
        step = int(x // self.COL_WIDTH)
        row = int(pos.y() // self.ROW_HEIGHT)
        note = self._note_for_row(row)
        if step < 0 or step >= self.num_steps:
            return None, None
        if note < self.min_note or note > self.max_note:
            return None, None
        return step, note

    def _pos_to_step_note_clamped(self, pos):
        """Версия для протяжки мышью: всегда возвращает валидные step/note,
        зажимая координаты в границы сетки (курсор может выйти за виджет)"""
        x = pos.x() - self.KEY_LABEL_WIDTH
        step = int(x // self.COL_WIDTH) if x > 0 else 0
        step = max(0, min(step, self.num_steps - 1))
        row = int(pos.y() // self.ROW_HEIGHT)
        note = self._note_for_row(row)
        note = max(self.min_note, min(note, self.max_note))
        return step, note

    def _note_at(self, step, note):
        for n in self.notes:
            if n['note'] == note and n['step'] <= step < n['step'] + n['length']:
                return n
        return None

    def _hit_test(self, pos):
        """Определить, что находится под курсором: ('create'|'move'|
        'resize_left'|'resize_right'|None, note_dict|None)"""
        step, note = self._pos_to_step_note(pos)
        if step is None:
            return None, None

        existing = self._note_at(step, note)
        if existing is None:
            return 'create', None

        rect = self._note_rect(existing['step'], existing['note'], existing['length'])
        x = pos.x()
        if x <= rect.left() + self.EDGE_PX:
            return 'resize_left', existing
        elif x >= rect.right() - self.EDGE_PX:
            return 'resize_right', existing
        else:
            return 'move', existing

    def _remove_overlapping_others(self, note, keep=None):
        """Убрать все ноты на той же высоте, что пересекаются по времени с
        note, кроме самой keep (используется при завершении move/resize/create,
        чтобы на одной высоте не оставалось наложенных друг на друга нот)"""
        self.notes = [
            n for n in self.notes
            if n is keep or not (
                n['note'] == note['note'] and
                n['step'] < note['step'] + note['length'] and
                n['step'] + n['length'] > note['step']
            )
        ]

    # ------------------------------------------------------------------ #
    #  Публичное API
    # ------------------------------------------------------------------ #

    def get_notes(self):
        """Получить список нот, отсортированный по времени"""
        return sorted((dict(n) for n in self.notes), key=lambda n: n['step'])

    def clear_notes(self):
        """Полностью очистить пиано-ролл"""
        self.notes = []
        self.step_results = {}
        self.notes_changed.emit()
        self.update()

    def set_playhead(self, step):
        """Установить позицию плейхеда (текущий шаг воспроизведения)"""
        self.playhead_step = step
        self.update()

    def set_note_result(self, step, note, result):
        """Покрасить ноту по результату проверки: 'hit' | 'miss' | 'none'"""
        self.step_results[(step, note)] = result
        self.update()

    def clear_results(self):
        """Сбросить подсветку результатов (например, перед новым запуском)"""
        self.step_results = {}
        self.update()

    def set_num_steps(self, num_steps):
        """Изменить длину секвенса в шагах"""
        self.num_steps = num_steps
        self.notes = [n for n in self.notes if n['step'] < num_steps]
        self._update_min_size()
        self.notes_changed.emit()
        self.update()

    # ------------------------------------------------------------------ #
    #  Отрисовка
    # ------------------------------------------------------------------ #

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        rows = self.max_note - self.min_note + 1
        w = self.KEY_LABEL_WIDTH + self.num_steps * self.COL_WIDTH
        h = rows * self.ROW_HEIGHT

        painter.fillRect(self.rect(), QColor(30, 31, 35))

        # Горизонтальные полосы: имитация чёрных/белых клавиш пианино
        for row in range(rows):
            note = self._note_for_row(row)
            is_black = NOTE_NAMES[note % 12].endswith('#')
            color = QColor(40, 41, 46) if is_black else QColor(48, 49, 55)
            painter.fillRect(self.KEY_LABEL_WIDTH, row * self.ROW_HEIGHT,
                              w - self.KEY_LABEL_WIDTH, self.ROW_HEIGHT, color)

            if note % 12 == 0:  # подписываем C-ноты слева
                painter.setPen(QColor(150, 152, 160))
                painter.setFont(QFont('Arial', 8))
                painter.drawText(
                    QRect(0, row * self.ROW_HEIGHT, self.KEY_LABEL_WIDTH - 4, self.ROW_HEIGHT),
                    Qt.AlignVCenter | Qt.AlignRight,
                    f"C{(note // 12) - 1}"
                )

        # Вертикальные линии шагов (жирнее на границе долей)
        for step in range(self.num_steps + 1):
            x = self.KEY_LABEL_WIDTH + step * self.COL_WIDTH
            pen_color = QColor(65, 67, 74) if step % self.steps_per_beat == 0 else QColor(22, 23, 26)
            painter.setPen(QPen(pen_color, 1))
            painter.drawLine(x, 0, x, h)

        # Плейхед
        if 0 <= self.playhead_step < self.num_steps:
            x = self.KEY_LABEL_WIDTH + self.playhead_step * self.COL_WIDTH
            painter.fillRect(x, 0, self.COL_WIDTH, h, QColor(255, 255, 255, 28))

        # Ноты
        for n in self.notes:
            rect = self._note_rect(n['step'], n['note'], n['length'])
            result = self.step_results.get((n['step'], n['note']))
            if result == 'hit':
                color = QColor(64, 192, 87)
            elif result == 'miss':
                color = QColor(250, 82, 82)
            elif result == 'none':
                color = QColor(134, 142, 150)
            else:
                color = QColor(77, 171, 247)
            painter.setBrush(color)
            painter.setPen(QPen(QColor(20, 21, 24), 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

        # "Призрак" ноты во время создания новой
        if self._drag_mode == 'create' and self._drag_note is not None:
            rect = self._note_rect(self._drag_start_step, self._drag_note, self._drag_current_len)
            painter.setBrush(QColor(77, 171, 247, 140))
            painter.setPen(QPen(QColor(77, 171, 247), 1, Qt.DashLine))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 3, 3)

    # ------------------------------------------------------------------ #
    #  Мышь
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            step, note = self._pos_to_step_note(event.pos())
            if step is not None:
                existing = self._note_at(step, note)
                if existing:
                    self.notes.remove(existing)
                    self.notes_changed.emit()
                    self.update()
            return

        if event.button() != Qt.LeftButton:
            return

        mode, existing = self._hit_test(event.pos())
        if mode is None:
            return

        if mode == 'create':
            step, note = self._pos_to_step_note(event.pos())
            self._drag_mode = 'create'
            self._drag_start_step = step
            self._drag_note = note
            self._drag_current_len = 1
            self._start_preview(note)
            self.update()
            return

        # move / resize_left / resize_right по существующей ноте
        step, note = self._pos_to_step_note(event.pos())
        self._drag_mode = mode
        self._drag_note_ref = existing
        self._drag_orig = dict(existing)
        self._drag_grab_step = step
        self._drag_grab_note = note
        self._start_preview(existing['note'])
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag_mode is None:
            self._update_hover_cursor(event.pos())
            return

        step, note = self._pos_to_step_note_clamped(event.pos())

        if self._drag_mode == 'create':
            if note != self._drag_note:
                self._drag_note = note
                self._start_preview(note)
            length = step - self._drag_start_step + 1
            self._drag_current_len = max(1, min(length, self.num_steps - self._drag_start_step))
            self.update()

        elif self._drag_mode == 'move':
            delta_step = step - self._drag_grab_step
            delta_note = note - self._drag_grab_note
            length = self._drag_orig['length']

            new_step = self._drag_orig['step'] + delta_step
            new_step = max(0, min(new_step, self.num_steps - length))

            new_note = self._drag_orig['note'] + delta_note
            new_note = max(self.min_note, min(new_note, self.max_note))

            if new_note != self._drag_note_ref['note']:
                self._start_preview(new_note)

            self._drag_note_ref['step'] = new_step
            self._drag_note_ref['note'] = new_note
            self.update()

        elif self._drag_mode == 'resize_right':
            new_length = step - self._drag_orig['step'] + 1
            new_length = max(1, min(new_length, self.num_steps - self._drag_orig['step']))
            self._drag_note_ref['length'] = new_length
            self.update()

        elif self._drag_mode == 'resize_left':
            end_step = self._drag_orig['step'] + self._drag_orig['length']
            new_start = min(step, end_step - 1)
            new_start = max(0, new_start)
            self._drag_note_ref['step'] = new_start
            self._drag_note_ref['length'] = end_step - new_start
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._drag_mode is None:
            return

        if self._drag_mode == 'create':
            new_note = {
                'step': self._drag_start_step,
                'note': self._drag_note,
                'length': self._drag_current_len
            }
            self._remove_overlapping_others(new_note)
            self.notes.append(new_note)
            self.notes_changed.emit()
        else:
            # move / resize_left / resize_right: сама нота уже обновлена
            # "на лету" в mouseMoveEvent, осталось убрать соседей, которых
            # она теперь перекрывает
            self._remove_overlapping_others(self._drag_note_ref, keep=self._drag_note_ref)
            self.notes_changed.emit()

        self._drag_mode = None
        self._drag_note_ref = None
        self._drag_orig = None
        self._drag_note = None
        self._stop_preview()
        self.update()

    def leaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)

    # ------------------------------------------------------------------ #
    #  Предпрослушивание звука при редактировании
    # ------------------------------------------------------------------ #

    def _start_preview(self, midi_note):
        if midi_note != self._last_preview_note:
            self._last_preview_note = midi_note
            self.note_preview.emit(midi_note)

    def _stop_preview(self):
        self._last_preview_note = None
        self.preview_stopped.emit()

    # ------------------------------------------------------------------ #
    #  Курсор при наведении (подсказка, что можно сделать в этой точке)
    # ------------------------------------------------------------------ #

    def _update_hover_cursor(self, pos):
        mode, _ = self._hit_test(pos)
        if mode in ('resize_left', 'resize_right'):
            self.setCursor(Qt.SizeHorCursor)
        elif mode == 'move':
            self.setCursor(Qt.SizeAllCursor)
        elif mode == 'create':
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
