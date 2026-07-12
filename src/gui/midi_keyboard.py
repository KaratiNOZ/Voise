"""Виртуальная MIDI-клавиатура"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QFont


class MidiKeyboard(QWidget):
    """Виртуальная MIDI-клавиатура"""
    
    # Сигнал при нажатии клавиши
    note_pressed = pyqtSignal(int)  # MIDI note number
    note_released = pyqtSignal(int)
    
    # Паттерн черных клавиш (1 = черная, 0 = нет черной после этой белой)
    BLACK_KEY_PATTERN = [1, 1, 0, 1, 1, 1, 0]  # C C# D D# E F F# G G# A A# B
    
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    
    def __init__(self, start_octave=2, num_octaves=3, parent=None):
        super().__init__(parent)
        
        self.start_octave = start_octave
        self.num_octaves = num_octaves
        
        # Количество белых клавиш (7 на октаву)
        self.num_white_keys = num_octaves * 7
        
        # Выбранная нота
        self.selected_note = None
        
        # Клавиша под мышью
        self.hover_note = None
        
        self.setMinimumHeight(120)
        self.setMouseTracking(True)
        
    def _get_white_key_rect(self, white_key_index):
        """Получить прямоугольник белой клавиши"""
        white_key_width = self.width() / self.num_white_keys
        x = white_key_index * white_key_width
        return QRect(int(x), 0, int(white_key_width), self.height())
        
    def _get_black_key_rect(self, white_key_index):
        """Получить прямоугольник черной клавиши после данной белой"""
        white_key_width = self.width() / self.num_white_keys
        black_key_width = white_key_width * 0.6
        black_key_height = self.height() * 0.6
        
        x = (white_key_index + 1) * white_key_width - black_key_width / 2
        return QRect(int(x), 0, int(black_key_width), int(black_key_height))
        
    def _white_key_to_midi(self, white_key_index):
        """Конвертировать индекс белой клавиши в MIDI номер"""
        octave = white_key_index // 7
        key_in_octave = white_key_index % 7
        
        # Белые клавиши: C D E F G A B
        white_key_offsets = [0, 2, 4, 5, 7, 9, 11]
        note_in_octave = white_key_offsets[key_in_octave]
        
        midi_note = (self.start_octave + octave) * 12 + note_in_octave
        return midi_note
        
    def _black_key_to_midi(self, white_key_index):
        """Конвертировать черную клавишу в MIDI номер"""
        # Получаем MIDI ноту белой клавиши и добавляем полутон
        white_midi = self._white_key_to_midi(white_key_index)
        return white_midi + 1
        
    def _midi_to_note_name(self, midi_note):
        """Конвертировать MIDI в название ноты"""
        octave = (midi_note // 12) - 1
        note_idx = midi_note % 12
        note_name = self.NOTE_NAMES[note_idx]
        return f"{note_name}{octave}"
        
    def _is_black_key(self, white_key_index):
        """Проверить, есть ли черная клавиша после данной белой"""
        key_in_octave = white_key_index % 7
        return self.BLACK_KEY_PATTERN[key_in_octave] == 1
        
    def _get_note_at_pos(self, pos):
        """Получить MIDI ноту в данной позиции"""
        # Сначала проверяем черные клавиши (они выше)
        for i in range(self.num_white_keys - 1):
            if self._is_black_key(i):
                rect = self._get_black_key_rect(i)
                if rect.contains(pos):
                    return self._black_key_to_midi(i)
                    
        # Затем проверяем белые клавиши
        for i in range(self.num_white_keys):
            rect = self._get_white_key_rect(i)
            if rect.contains(pos):
                return self._white_key_to_midi(i)
                
        return None
        
    def paintEvent(self, event):
        """Отрисовка клавиатуры"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Рисуем белые клавиши
        for i in range(self.num_white_keys):
            rect = self._get_white_key_rect(i)
            midi_note = self._white_key_to_midi(i)
            
            # Цвет клавиши
            if midi_note == self.selected_note:
                color = QColor(100, 150, 255)  # Синий для выбранной
            elif midi_note == self.hover_note:
                color = QColor(230, 230, 230)  # Светло-серый при наведении
            else:
                color = QColor(255, 255, 255)  # Белый
                
            painter.fillRect(rect, color)
            
            # Обводка
            painter.setPen(QPen(Qt.black, 1))
            painter.drawRect(rect)
            
            # Название ноты для C нот
            if midi_note % 12 == 0:  # C нота
                painter.setFont(QFont('Arial', 8))
                note_name = self._midi_to_note_name(midi_note)
                painter.drawText(rect, Qt.AlignBottom | Qt.AlignHCenter, note_name)
                
        # Рисуем черные клавиши
        for i in range(self.num_white_keys - 1):
            if self._is_black_key(i):
                rect = self._get_black_key_rect(i)
                midi_note = self._black_key_to_midi(i)
                
                # Цвет клавиши
                if midi_note == self.selected_note:
                    color = QColor(50, 100, 200)  # Темно-синий для выбранной
                elif midi_note == self.hover_note:
                    color = QColor(60, 60, 60)  # Темно-серый при наведении
                else:
                    color = QColor(0, 0, 0)  # Черный
                    
                painter.fillRect(rect, color)
                
                # Обводка
                painter.setPen(QPen(Qt.black, 1))
                painter.drawRect(rect)
                
    def mousePressEvent(self, event):
        """Обработка нажатия мыши"""
        if event.button() == Qt.LeftButton:
            note = self._get_note_at_pos(event.pos())
            if note is not None:
                # Раньше сигнал не эмитился при повторном клике на уже
                # выбранную ноту (note != self.selected_note), из-за
                # чего звук нельзя было переслушать, не выбрав сперва
                # другую клавишу. Теперь клик всегда проигрывает ноту.
                self.selected_note = note
                self.note_pressed.emit(note)
                self.update()
                
    def mouseReleaseEvent(self, event):
        """Обработка отпускания мыши"""
        if event.button() == Qt.LeftButton:
            if self.selected_note is not None:
                self.note_released.emit(self.selected_note)
            # НЕ сбрасываем selected_note чтобы клавиша осталась подсвеченной
            
    def mouseMoveEvent(self, event):
        """Обработка движения мыши"""
        note = self._get_note_at_pos(event.pos())
        if note != self.hover_note:
            self.hover_note = note
            self.update()
            
    def leaveEvent(self, event):
        """Обработка выхода мыши за пределы виджета"""
        self.hover_note = None
        self.update()
        
    def set_selected_note(self, midi_note):
        """Установить выбранную ноту программно"""
        self.selected_note = midi_note
        self.update()
        
    def clear_selection(self):
        """Очистить выбор"""
        self.selected_note = None
        self.update()
        
    def get_selected_note(self):
        """Получить текущую выбранную ноту"""
        return self.selected_note
