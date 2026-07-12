# -*- coding: utf-8 -*-
"""Главное окно приложения"""

import time

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTextEdit, QGroupBox,
                             QProgressBar, QAction, QMessageBox)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

from src.audio.analyzer import VoiceAnalyzer
from src.audio.synthesizer import SimpleSynthesizer
from src.audio.worker import AnalysisWorker
from src.gui.midi_keyboard import MidiKeyboard
from src.gui.settings import SettingsDialog
from src.gui.level_meter import LevelMeter
from src.gui.theme import APP_STYLESHEET
from src.crash_logger import get_logger, open_logs_folder, LOG_DIR

logger = get_logger()


class MainWindow(QMainWindow):
    """Главное окно приложения"""

    def __init__(self, config):
        super().__init__()

        self.config = config
        self.analyzer = VoiceAnalyzer(config)
        self.synthesizer = SimpleSynthesizer(config['audio']['sample_rate'])

        self.is_recording = False
        self.current_analysis = None
        self.analysis_worker = None
        self._recording_started_at = None

        self.init_ui()

        # VU-метр обновляем лёгким UI-таймером - это не тяжёлые вычисления,
        # а просто чтение уже посчитанного значения из recorder, поэтому
        # держать это в главном потоке безопасно и не создаёт лагов.
        self.level_timer = QTimer(self)
        self.level_timer.timeout.connect(self._update_level_meter)
        self.level_timer.setInterval(50)

        # Таймер статус-бара (время записи)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status_bar)
        self.status_timer.setInterval(500)

        logger.info("Главное окно инициализировано")

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #

    def init_ui(self):
        """Инициализация UI"""
        self.setWindowTitle("Voise - Анализатор вокала")
        self.setGeometry(
            100, 100,
            self.config['gui']['window_width'],
            self.config['gui']['window_height']
        )
        self.setMinimumSize(760, 620)

        self._create_menu()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        # MIDI клавиатура
        keyboard_group = QGroupBox("🎹 MIDI клавиатура")
        keyboard_layout = QVBoxLayout()

        self.midi_keyboard = MidiKeyboard(start_octave=2, num_octaves=5)
        self.midi_keyboard.note_pressed.connect(self.on_note_pressed)
        self.midi_keyboard.note_released.connect(self.on_note_released)
        keyboard_layout.addWidget(self.midi_keyboard)

        self.target_note_label = QLabel("Выберите ноту на клавиатуре")
        self.target_note_label.setAlignment(Qt.AlignCenter)
        self.target_note_label.setFont(QFont('Segoe UI', 12))
        keyboard_layout.addWidget(self.target_note_label)

        keyboard_group.setLayout(keyboard_layout)
        layout.addWidget(keyboard_group)

        # Кнопки управления + индикатор уровня сигнала
        control_layout = QHBoxLayout()

        self.record_btn = QPushButton("🎤 Начать запись")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.setMinimumHeight(48)
        self.record_btn.clicked.connect(self.toggle_recording)
        control_layout.addWidget(self.record_btn, stretch=2)

        self.clear_btn = QPushButton("Очистить ноту")
        self.clear_btn.setObjectName("secondaryButton")
        self.clear_btn.setMinimumHeight(48)
        self.clear_btn.clicked.connect(self.clear_target_note)
        control_layout.addWidget(self.clear_btn, stretch=1)

        layout.addLayout(control_layout)

        # Уровень сигнала
        level_layout = QHBoxLayout()
        level_layout.addWidget(QLabel("Уровень сигнала:"))
        self.level_meter = LevelMeter()
        level_layout.addWidget(self.level_meter, stretch=1)
        layout.addLayout(level_layout)

        # Результаты анализа
        results_group = QGroupBox("📊 Результаты анализа")
        results_layout = QVBoxLayout()

        self.info_label = QLabel("Нажмите 'Начать запись' для анализа")
        self.info_label.setObjectName("infoLabel")
        self.info_label.setFont(QFont('Segoe UI', 14, QFont.Bold))
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setMinimumHeight(60)
        self.info_label.setStyleSheet("background-color: #eef1f5;")
        results_layout.addWidget(self.info_label)

        details_layout = QHBoxLayout()

        # Pitch
        pitch_group = QGroupBox("Высота тона")
        pitch_layout = QVBoxLayout()
        self.pitch_label = QLabel("—")
        self.pitch_label.setObjectName("sectionValue")
        self.pitch_label.setAlignment(Qt.AlignCenter)
        pitch_layout.addWidget(self.pitch_label)
        pitch_group.setLayout(pitch_layout)
        details_layout.addWidget(pitch_group)

        # Качество
        quality_group = QGroupBox("Качество")
        quality_layout = QVBoxLayout()
        self.quality_label = QLabel("—")
        self.quality_label.setAlignment(Qt.AlignCenter)
        self.quality_progress = QProgressBar()
        self.quality_progress.setRange(0, 100)
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_progress)
        quality_group.setLayout(quality_layout)
        details_layout.addWidget(quality_group)

        # Тип голоса
        voice_type_group = QGroupBox("Тип голоса")
        voice_type_layout = QVBoxLayout()
        self.voice_type_label = QLabel("—")
        self.voice_type_label.setAlignment(Qt.AlignCenter)
        voice_type_layout.addWidget(self.voice_type_label)
        voice_type_group.setLayout(voice_type_layout)
        details_layout.addWidget(voice_type_group)

        results_layout.addLayout(details_layout)

        # Попадание в ноту
        self.match_group = QGroupBox("🎯 Попадание в ноту")
        match_layout = QVBoxLayout()
        self.match_label = QLabel("—")
        self.match_label.setAlignment(Qt.AlignCenter)
        self.match_label.setFont(QFont('Segoe UI', 16, QFont.Bold))
        self.match_progress = QProgressBar()
        self.match_progress.setRange(0, 100)
        match_layout.addWidget(self.match_label)
        match_layout.addWidget(self.match_progress)
        self.match_group.setLayout(match_layout)
        self.match_group.setVisible(False)
        results_layout.addWidget(self.match_group)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        # Лог сообщений
        log_group = QGroupBox("📝 Лог")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(110)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        central_widget.setLayout(layout)

        # Статус-бар
        self.status_bar = self.statusBar()
        self._update_status_bar()

    def _create_menu(self):
        """Создать меню"""
        menubar = self.menuBar()

        # Файл
        file_menu = menubar.addMenu('Файл')

        exit_action = QAction('Выход', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Настройки
        settings_menu = menubar.addMenu('Настройки')

        settings_action = QAction('Параметры...', self)
        settings_action.setShortcut('Ctrl+,')
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)

        # Помощь
        help_menu = menubar.addMenu('Помощь')

        logs_action = QAction('Открыть папку с логами', self)
        logs_action.triggered.connect(self._open_logs_folder)
        help_menu.addAction(logs_action)

        about_action = QAction('О программе', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------------ #
    #  MIDI клавиатура
    # ------------------------------------------------------------------ #

    def on_note_pressed(self, midi_note):
        """Обработка нажатия клавиши"""
        try:
            self.synthesizer.start_note(midi_note)

            self.analyzer.set_target_note(midi_note)
            note_name = self.analyzer.pitch_detector.midi_to_note_name(midi_note)
            freq = self.analyzer.pitch_detector.midi_to_hz(midi_note)

            self.target_note_label.setText(
                f"Целевая нота: {note_name} ({freq:.1f} Hz)"
            )
            self.match_group.setVisible(True)

            self.log(f"Выбрана нота: {note_name} ({freq:.1f} Hz)")
        except Exception:
            logger.exception("Ошибка on_note_pressed")
            self.log("⚠️ Ошибка при выборе ноты (см. лог)")

    def on_note_released(self, midi_note):
        """Обработка отпускания клавиши"""
        try:
            self.synthesizer.stop_note()
        except Exception:
            logger.exception("Ошибка on_note_released")

    def clear_target_note(self):
        """Очистить целевую ноту"""
        self.analyzer.clear_target_note()
        self.midi_keyboard.clear_selection()
        self.target_note_label.setText("Выберите ноту на клавиатуре")
        self.match_group.setVisible(False)
        self.log("Целевая нота очищена")

    # ------------------------------------------------------------------ #
    #  Запись и анализ
    # ------------------------------------------------------------------ #

    def toggle_recording(self):
        """Переключить состояние записи"""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Начать запись"""
        try:
            self.analyzer.start_recording()
        except Exception:
            logger.exception("Не удалось начать запись")
            QMessageBox.warning(
                self, "Ошибка записи",
                "Не удалось получить доступ к микрофону.\n"
                "Проверьте, что микрофон подключен и разрешён в системе."
            )
            return

        self.is_recording = True
        self._recording_started_at = time.monotonic()
        self.record_btn.setText("⏹ Остановить запись")
        self.record_btn.setObjectName("recordButtonActive")
        self._refresh_button_style(self.record_btn)

        interval_ms = self.config['analysis'].get('update_interval_ms', 50)

        self.analysis_worker = AnalysisWorker(self.analyzer, interval_ms=interval_ms)
        self.analysis_worker.result_ready.connect(self.update_analysis)
        self.analysis_worker.error_occurred.connect(self._on_analysis_error)
        self.analysis_worker.start()

        self.level_timer.start()
        self.status_timer.start()

        self.log("Запись начата")

    def stop_recording(self):
        """Остановить запись"""
        if self.analysis_worker is not None:
            self.analysis_worker.stop()
            self.analysis_worker = None

        try:
            self.analyzer.stop_recording()
        except Exception:
            logger.exception("Ошибка при остановке записи")

        self.is_recording = False
        self._recording_started_at = None
        self.record_btn.setText("🎤 Начать запись")
        self.record_btn.setObjectName("recordButton")
        self._refresh_button_style(self.record_btn)

        self.level_timer.stop()
        self.status_timer.stop()
        self.level_meter.set_level(self.level_meter.min_db)

        self._update_status_bar()
        self.log("Запись остановлена")

    def _refresh_button_style(self, button):
        """Форсировать перерисовку стиля после смены objectName"""
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def _on_analysis_error(self, message):
        """Обработка ошибки из фонового потока анализа"""
        self.log(f"⚠️ Ошибка анализа: {message}")

    def _update_level_meter(self):
        """Обновить индикатор уровня сигнала (лёгкая операция в GUI-потоке)"""
        try:
            db = self.analyzer.get_input_level_db()
            self.level_meter.set_level(db)
        except Exception:
            logger.exception("Ошибка обновления VU-метра")

    def _update_status_bar(self):
        """Обновить статус-бар"""
        parts = []
        if self.is_recording and self._recording_started_at:
            elapsed = int(time.monotonic() - self._recording_started_at)
            mins, secs = divmod(elapsed, 60)
            parts.append(f"🔴 Запись: {mins:02d}:{secs:02d}")
        else:
            parts.append("⏸ Запись остановлена")

        parts.append(f"Частота дискретизации: {self.config['audio']['sample_rate']} Гц")
        interval = self.config['analysis'].get('update_interval_ms', 50)
        parts.append(f"Обновление: {interval} мс")

        self.status_bar.showMessage("   |   ".join(parts))

    def update_analysis(self, result):
        """Обновить результаты анализа (вызывается сигналом из фонового потока)"""
        self.current_analysis = result

        if not result.get('has_voice'):
            self.info_label.setText(result.get('message', 'Нет голоса'))
            self.info_label.setStyleSheet("background-color: #eef1f5;")
            return

        pitch = result['pitch']
        quality = result['quality']
        voice_type = result['voice_type']

        self.pitch_label.setText(
            f"{pitch['note_name']}\n{pitch['frequency']:.1f} Hz"
        )

        quality_score = quality['quality_score']
        self.quality_label.setText(f"{quality_score:.0f}/100")
        self.quality_progress.setValue(int(quality_score))

        if quality['is_clean']:
            self.quality_progress.setStyleSheet("QProgressBar::chunk { background-color: #51cf66; }")
        else:
            self.quality_progress.setStyleSheet("QProgressBar::chunk { background-color: #ffa94d; }")

        type_desc = self.analyzer.voice_type_detector.get_voice_type_description(voice_type)
        self.voice_type_label.setText(type_desc)

        if result.get('pitch_match'):
            match = result['pitch_match']
            cents_off = match['cents_off']

            if match['match']:
                self.match_label.setText(f"✅ Попал! {match['percentage']:.0f}%")
                self.match_label.setStyleSheet("color: #40c057;")
                self.info_label.setText("Отлично! Вы попали в ноту!")
                self.info_label.setStyleSheet(
                    "background-color: #51cf66; color: white;"
                )
            else:
                if cents_off > 0:
                    # Спетая нота ВЫШЕ цели -> нужно опуститься
                    deviation_label = "⬆️ ВЫШЕ ЦЕЛИ"
                    arrow = "↑"
                    suggestion = "ниже"
                else:
                    # Спетая нота НИЖЕ цели -> нужно подняться
                    deviation_label = "⬇️ НИЖЕ ЦЕЛИ"
                    arrow = "↓"
                    suggestion = "выше"

                self.match_label.setText(f"{arrow} {abs(cents_off):.0f} центов {deviation_label}")
                self.match_label.setStyleSheet("color: #fa5252; font-size: 18px; font-weight: bold;")
                self.info_label.setText(f"Не попал: пой {suggestion}")
                self.info_label.setStyleSheet(
                    "background-color: #ff6b6b; color: white;"
                )

            self.match_progress.setValue(int(match['percentage']))
        else:
            self.info_label.setText("Поет! (выберите ноту для проверки)")
            self.info_label.setStyleSheet(
                "background-color: #4dabf7; color: white;"
            )

    # ------------------------------------------------------------------ #
    #  Настройки / прочее
    # ------------------------------------------------------------------ #

    def open_settings(self):
        """Открыть окно настроек"""
        dialog = SettingsDialog(self.config, self)
        dialog.settings_changed.connect(self.on_settings_changed)

        if dialog.exec_():
            self.config = dialog.get_config()
            self.log("Настройки применены")

    def on_settings_changed(self, new_config):
        """Обработка изменения настроек"""
        was_recording = self.is_recording

        if was_recording:
            self.stop_recording()

        old_theme = self.config.get('gui', {}).get('theme', 'light')
        self.config = new_config

        try:
            self.analyzer = VoiceAnalyzer(self.config)
        except Exception:
            logger.exception("Не удалось применить новые настройки анализатора")
            QMessageBox.warning(
                self, "Ошибка настроек",
                "Не удалось применить новые настройки. Проверьте выбранное аудио устройство."
            )
            return

        new_theme = self.config.get('gui', {}).get('theme', 'light')
        if new_theme != old_theme:
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().setStyleSheet(APP_STYLESHEET.get(new_theme, ""))

        self._update_status_bar()

        if was_recording:
            self.start_recording()

    def _open_logs_folder(self):
        """Открыть папку с логами и crash-report'ами"""
        open_logs_folder()
        self.log(f"Папка с логами: {LOG_DIR}")

    def show_about(self):
        """Показать информацию о программе"""
        QMessageBox.about(
            self,
            "О программе",
            "<h2>Voise</h2>"
            "<p>Анализатор вокала в реальном времени</p>"
            "<p>Возможности:</p>"
            "<ul>"
            "<li>Определение высоты тона</li>"
            "<li>Проверка попадания в ноту</li>"
            "<li>Анализ качества звука</li>"
            "<li>Определение типа голоса (фальцет/грудной)</li>"
            "<li>Индикатор уровня сигнала</li>"
            "<li>Светлая/тёмная тема</li>"
            "</ul>"
            "<p>Версия: 2.0</p>"
        )

    def log(self, message):
        """Добавить сообщение в лог"""
        self.log_text.append(message)
        logger.debug("UI-лог: %s", message)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        try:
            if self.is_recording:
                self.stop_recording()
            self.synthesizer.cleanup()
        except Exception:
            logger.exception("Ошибка при закрытии приложения")
        event.accept()
