# -*- coding: utf-8 -*-
"""Виджет индикатора уровня входного сигнала (VU-метр)"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QLinearGradient


class LevelMeter(QWidget):
    """Горизонтальный индикатор уровня громкости в дБ"""

    def __init__(self, min_db=-60, max_db=0, parent=None):
        super().__init__(parent)
        self.min_db = min_db
        self.max_db = max_db
        self._level_db = min_db
        self._peak_db = min_db
        self._peak_hold_counter = 0
        self.setMinimumHeight(18)
        self.setMinimumWidth(120)

    def set_level(self, db_value):
        """Обновить текущий уровень (в дБ)"""
        db_value = max(self.min_db, min(self.max_db, db_value))
        self._level_db = db_value

        if db_value >= self._peak_db:
            self._peak_db = db_value
            self._peak_hold_counter = 0
        else:
            self._peak_hold_counter += 1
            if self._peak_hold_counter > 20:
                self._peak_db = max(self.min_db, self._peak_db - 0.8)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        radius = rect.height() / 2

        # Фон
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 30))
        painter.drawRoundedRect(rect, radius, radius)

        # Заполнение уровня
        ratio = (self._level_db - self.min_db) / (self.max_db - self.min_db)
        ratio = max(0.0, min(1.0, ratio))
        fill_width = rect.width() * ratio

        if fill_width > 1:
            gradient = QLinearGradient(0, 0, rect.width(), 0)
            gradient.setColorAt(0.0, QColor(64, 192, 87))
            gradient.setColorAt(0.7, QColor(255, 212, 59))
            gradient.setColorAt(1.0, QColor(250, 82, 82))

            fill_rect = QRectF(0, 0, fill_width, rect.height())
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill_rect, radius, radius)

        # Пиковый маркер
        peak_ratio = (self._peak_db - self.min_db) / (self.max_db - self.min_db)
        peak_ratio = max(0.0, min(1.0, peak_ratio))
        peak_x = rect.width() * peak_ratio
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawRoundedRect(QRectF(max(0, peak_x - 2), 1, 3, rect.height() - 2), 1.5, 1.5)
