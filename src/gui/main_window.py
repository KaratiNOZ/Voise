# -*- coding: utf-8 -*-
"""Главное окно приложения"""

import time

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTextEdit, QGroupBox,
                             QProgressBar, QAction, QMessageBox, QTabWidget,
                             QSpinBox, QCheckBox, QComboBox, QScrollArea)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont, QKeySequence

from src.audio.analyzer import VoiceAnalyzer
from src.audio.synthesizer import SimpleSynthesizer
from src.audio.worker import AnalysisWorker
from src.audio.sequencer import Sequencer
from src.gui.midi_keyboard import MidiKeyboard
from src.gui.piano_roll import PianoRollWidget
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
        self.sequencer = Sequencer(self.synthesizer, self.analyzer)

        self.is_recording = False
        self.current_analysis = None
        self.analysis_worker = None
        self._recording_started_at = None

        # Состояние оценки текущей ноты секвенсора: пока нота играет,
        # сюда копятся результаты pitch_match из каждого кадра анализа,
        # а когда нота заканчивается - по ним решаем "попал/не попал".
        self._seq_active_note = None   # (step, note) или None
        self._seq_note_matches = []
        self._seq_hits = 0
        self._seq_total = 0

        self.init_ui()
        self._connect_sequencer_signals()

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

        root_layout = QVBoxLayout()
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(12, 12, 12, 12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_free_mode_tab(), "🎤 Свободное пение")
        self.tabs.addTab(self._create_sequencer_tab(), "🎼 Секвенсор")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tabs, stretch=1)

        # Лог сообщений - общий для обеих вкладок
        log_group = QGroupBox("📝 Лог")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(110)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        root_layout.addWidget(log_group)

        central_widget.setLayout(root_layout)

        # Статус-бар
        self.status_bar = self.statusBar()
        self._update_status_bar()

    def _create_free_mode_tab(self):
        """Вкладка свободного пения (исходный режим: одна целевая нота)"""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)

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

        # Регистр (грудной..фальцет) и зажатость (SLS-режим)
        sls_layout = QHBoxLayout()

        register_group = QGroupBox("🎚️ Регистр")
        register_layout = QVBoxLayout()
        self.register_label = QLabel("—")
        self.register_label.setAlignment(Qt.AlignCenter)
        self.register_progress = QProgressBar()
        self.register_progress.setRange(0, 100)
        self.register_progress.setFormat("грудной ⟷ фальцет")
        register_layout.addWidget(self.register_label)
        register_layout.addWidget(self.register_progress)
        register_group.setLayout(register_layout)
        sls_layout.addWidget(register_group)

        strain_group = QGroupBox("😬 Зажатость")
        strain_layout = QVBoxLayout()
        self.strain_label = QLabel("—")
        self.strain_label.setAlignment(Qt.AlignCenter)
        self.strain_progress = QProgressBar()
        self.strain_progress.setRange(0, 100)
        strain_layout.addWidget(self.strain_label)
        strain_layout.addWidget(self.strain_progress)
        strain_group.setLayout(strain_layout)
        sls_layout.addWidget(strain_group)

        results_layout.addLayout(sls_layout)

        self.coach_label = QLabel("")
        self.coach_label.setAlignment(Qt.AlignCenter)
        self.coach_label.setWordWrap(True)
        self.coach_label.setFont(QFont('Segoe UI', 11))
        self.coach_label.setStyleSheet("color: #495057; padding: 4px;")
        results_layout.addWidget(self.coach_label)

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

        tab.setLayout(layout)
        return tab

    def _create_sequencer_tab(self):
        """
        Вкладка "Секвенсор" - пиано-ролл как в FL Studio: расставляете
        ноты мышкой, жмёте Play (или Space) - они играются одна за
        другой как мелодия, а микрофон в реальном времени сверяется с
        каждой нотой и красит её зелёным (попал) или красным (не попал).
        """
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)

        hint = QLabel(
            "ЛКМ на пустом месте - нарисовать ноту (тяните для длины/высоты) · "
            "ЛКМ по телу ноты - передвинуть · ЛКМ по краю - изменить длину · "
            "ПКМ - удалить · Space или ▶ - играть"
        )
        hint.setStyleSheet("color: #868e96; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Пиано-ролл в прокручиваемой области
        self.piano_roll = PianoRollWidget(min_note=48, max_note=84, num_steps=32)
        self.piano_roll.notes_changed.connect(self._on_piano_roll_changed)
        self.piano_roll.note_preview.connect(self._on_piano_roll_preview)
        self.piano_roll.preview_stopped.connect(self._on_piano_roll_preview_stop)

        scroll = QScrollArea()
        scroll.setWidget(self.piano_roll)
        scroll.setWidgetResizable(False)
        scroll.setMinimumHeight(280)
        layout.addWidget(scroll, stretch=1)

        # Транспорт (play/stop, темп, длина, повтор)
        transport_layout = QHBoxLayout()

        self.seq_play_btn = QPushButton("▶ Играть")
        self.seq_play_btn.setObjectName("recordButton")
        self.seq_play_btn.setMinimumHeight(44)
        self.seq_play_btn.clicked.connect(self.toggle_sequencer)
        transport_layout.addWidget(self.seq_play_btn, stretch=2)

        self.seq_clear_btn = QPushButton("Очистить всё")
        self.seq_clear_btn.setObjectName("secondaryButton")
        self.seq_clear_btn.setMinimumHeight(44)
        self.seq_clear_btn.clicked.connect(self._clear_sequencer)
        transport_layout.addWidget(self.seq_clear_btn, stretch=1)

        transport_layout.addWidget(QLabel("Темп:"))
        self.seq_bpm_spin = QSpinBox()
        self.seq_bpm_spin.setRange(40, 240)
        self.seq_bpm_spin.setValue(self.config.get('sequencer', {}).get('default_bpm', 100))
        self.seq_bpm_spin.setSuffix(" BPM")
        self.seq_bpm_spin.valueChanged.connect(
            lambda v: self.sequencer.set_bpm(v)
        )
        transport_layout.addWidget(self.seq_bpm_spin)

        transport_layout.addWidget(QLabel("Длина:"))
        self.seq_length_combo = QComboBox()
        self.seq_length_combo.addItems(["16 шагов", "32 шага", "64 шага"])
        self.seq_length_combo.setCurrentIndex(1)
        self.seq_length_combo.currentIndexChanged.connect(self._on_seq_length_changed)
        transport_layout.addWidget(self.seq_length_combo)

        self.seq_loop_check = QCheckBox("Повтор")
        transport_layout.addWidget(self.seq_loop_check)

        layout.addLayout(transport_layout)

        # Текущее состояние воспроизведения + уровень сигнала
        status_layout = QHBoxLayout()

        self.seq_current_note_label = QLabel("Готово к запуску")
        self.seq_current_note_label.setFont(QFont('Segoe UI', 12, QFont.Bold))
        status_layout.addWidget(self.seq_current_note_label, stretch=2)

        self.seq_score_label = QLabel("Точность: 0/0")
        self.seq_score_label.setAlignment(Qt.AlignRight)
        status_layout.addWidget(self.seq_score_label, stretch=1)

        layout.addLayout(status_layout)

        # Реал-тайм попадание в текущую ноту секвенсора - тот же принцип,
        # что и на вкладке свободного пения, только источник целевой ноты -
        # не клавиатура, а сам секвенсор
        self.seq_match_group = QGroupBox("🎯 Попадание в ноту (реал-тайм)")
        seq_match_layout = QVBoxLayout()
        self.seq_match_label = QLabel("—")
        self.seq_match_label.setAlignment(Qt.AlignCenter)
        self.seq_match_label.setFont(QFont('Segoe UI', 14, QFont.Bold))
        self.seq_match_progress = QProgressBar()
        self.seq_match_progress.setRange(0, 100)
        seq_match_layout.addWidget(self.seq_match_label)
        seq_match_layout.addWidget(self.seq_match_progress)
        self.seq_match_group.setLayout(seq_match_layout)
        layout.addWidget(self.seq_match_group)

        level_layout = QHBoxLayout()
        level_layout.addWidget(QLabel("Уровень сигнала:"))
        self.seq_level_meter = LevelMeter()
        level_layout.addWidget(self.seq_level_meter, stretch=1)
        layout.addLayout(level_layout)

        tab.setLayout(layout)
        return tab

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

        # Секвенсор
        sequencer_menu = menubar.addMenu('Секвенсор')

        # QAction-шорткат надёжнее, чем keyPressEvent: срабатывает,
        # даже если фокус сейчас на кнопке/спинбоксе, а не на пиано-ролле
        self.seq_play_action = QAction('▶ Играть / ⏹ Стоп', self)
        self.seq_play_action.setShortcut(QKeySequence(Qt.Key_Space))
        self.seq_play_action.triggered.connect(self._on_space_pressed)
        sequencer_menu.addAction(self.seq_play_action)

        seq_clear_action = QAction('Очистить пиано-ролл', self)
        seq_clear_action.triggered.connect(self._clear_sequencer)
        sequencer_menu.addAction(seq_clear_action)

        # Помощь
        help_menu = menubar.addMenu('Помощь')

        logs_action = QAction('Открыть папку с логами', self)
        logs_action.triggered.connect(self._open_logs_folder)
        help_menu.addAction(logs_action)

        about_action = QAction('О программе', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ------------------------------------------------------------------ #
    #  MIDI клавиатура (свободное пение)
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
    #  Секвенсор (режим "как в FL Studio")
    # ------------------------------------------------------------------ #

    def _connect_sequencer_signals(self):
        self.sequencer.step_changed.connect(self.piano_roll.set_playhead)
        self.sequencer.note_started.connect(self._on_seq_note_started)
        self.sequencer.note_ended.connect(self._on_seq_note_ended)
        self.sequencer.playback_finished.connect(self._on_seq_finished)

    def toggle_sequencer(self):
        """Запустить/остановить воспроизведение секвенса"""
        if self.sequencer.is_playing():
            self.sequencer.stop()
            self._update_seq_play_button(False)
            self.seq_current_note_label.setText("Остановлено")
            self._reset_seq_live_match()
            self.log("Секвенсор остановлен")
            return

        notes = self.piano_roll.get_notes()
        if not notes:
            QMessageBox.information(
                self, "Секвенсор",
                "Сначала расставьте ноты на пиано-ролле:\n"
                "ЛКМ - поставить ноту (тяните вправо для длительности), "
                "ЛКМ по ноте или ПКМ - удалить."
            )
            return

        # Играть можно только когда идёт запись с микрофона - если она
        # ещё не запущена, включаем её автоматически
        if not self.is_recording:
            self.start_recording()
            if not self.is_recording:
                # start_recording мог не удаться (нет микрофона и т.п.)
                return

        self.piano_roll.clear_results()
        self._seq_hits = 0
        self._seq_total = 0
        self._seq_active_note = None
        self._seq_note_matches = []
        self.seq_score_label.setText("Точность: 0/0")
        self._reset_seq_live_match()

        bpm = self.seq_bpm_spin.value()
        loop = self.seq_loop_check.isChecked()
        num_steps = self.piano_roll.num_steps

        self.sequencer.load(notes, num_steps, bpm, steps_per_beat=4, loop=loop)
        self.sequencer.start()
        self._update_seq_play_button(True)
        self.log(f"Секвенсор запущен: {len(notes)} нот, {bpm} BPM")

    def _update_seq_play_button(self, playing):
        if playing:
            self.seq_play_btn.setText("⏹ Стоп")
            self.seq_play_btn.setObjectName("recordButtonActive")
        else:
            self.seq_play_btn.setText("▶ Играть")
            self.seq_play_btn.setObjectName("recordButton")
        self._refresh_button_style(self.seq_play_btn)

    def _on_space_pressed(self):
        """Space (через QAction) переключает play/stop только на вкладке секвенсора"""
        if self.tabs.currentIndex() == 1:
            self.toggle_sequencer()

    def _on_tab_changed(self, index):
        """При уходе со вкладки секвенсора останавливаем воспроизведение"""
        if index != 1 and self.sequencer.is_playing():
            self.sequencer.stop()
            self._update_seq_play_button(False)
            self.seq_current_note_label.setText("Остановлено (смена вкладки)")
            self.log("Секвенсор остановлен (смена вкладки)")

    def _clear_sequencer(self):
        """Очистить пиано-ролл и сбросить результаты/счёт"""
        if self.sequencer.is_playing():
            self.sequencer.stop()
            self._update_seq_play_button(False)
        self.piano_roll.clear_notes()
        self._seq_hits = 0
        self._seq_total = 0
        self.seq_score_label.setText("Точность: 0/0")
        self.seq_current_note_label.setText("Готово к запуску")
        self.log("Пиано-ролл очищен")

    def _on_piano_roll_changed(self):
        """Пользователь отредактировал ноты - подсветка результатов устарела"""
        if not self.sequencer.is_playing():
            self.piano_roll.clear_results()
            self._seq_hits = 0
            self._seq_total = 0
            self.seq_score_label.setText("Точность: 0/0")

    def _on_seq_length_changed(self, index):
        steps = [16, 32, 64][index]
        self.piano_roll.set_num_steps(steps)

    def _on_seq_note_started(self, step, note, length):
        """Секвенсор начал играть ноту - готовимся собирать результаты попадания"""
        self._seq_active_note = (step, note)
        self._seq_note_matches = []
        note_name = self.analyzer.pitch_detector.midi_to_note_name(note)
        self.seq_current_note_label.setText(f"🎵 Играет: {note_name} - пойте её!")
        self._reset_seq_live_match(waiting=True)

    def _on_seq_note_ended(self, step, note):
        """Нота закончилась - подводим итог по накопленным кадрам анализа"""
        matches = self._seq_note_matches
        self._seq_active_note = None
        self._seq_note_matches = []

        if not matches:
            result = 'none'
        else:
            hit_ratio = sum(1 for m in matches if m) / len(matches)
            result = 'hit' if hit_ratio >= 0.5 else 'miss'

        self.piano_roll.set_note_result(step, note, result)

        self._seq_total += 1
        if result == 'hit':
            self._seq_hits += 1

        pct = (self._seq_hits / self._seq_total * 100) if self._seq_total else 0
        self.seq_score_label.setText(f"Точность: {self._seq_hits}/{self._seq_total} ({pct:.0f}%)")

        note_name = self.analyzer.pitch_detector.midi_to_note_name(note)
        if result == 'hit':
            self.log(f"✅ Попал в {note_name}")
        elif result == 'miss':
            self.log(f"❌ Не попал в {note_name}")
        else:
            self.log(f"— Голос не обнаружен на {note_name}")

    def _on_seq_finished(self):
        """Секвенс доиграл до конца (без повтора)"""
        self._update_seq_play_button(False)
        self.seq_current_note_label.setText("Секвенс закончен")
        self._reset_seq_live_match()
        self.log(f"Секвенсор: воспроизведение завершено. Итог: {self._seq_hits}/{self._seq_total}")

    def _reset_seq_live_match(self, waiting=False):
        """Сбросить реал-тайм шкалу попадания в секвенсоре"""
        self.seq_match_label.setText("Пойте..." if waiting else "—")
        self.seq_match_label.setStyleSheet("")
        self.seq_match_progress.setValue(0)

    def _update_seq_live_match(self, result):
        """Обновить реал-тайм шкалу попадания в ноту секвенсора (вызывается
        на каждом кадре анализа, пока играет нота секвенсора) - работает
        так же, как match_group на вкладке свободного пения"""
        if not result.get('has_voice'):
            self.seq_match_label.setText("Пойте...")
            self.seq_match_label.setStyleSheet("")
            return

        match = result.get('pitch_match')
        if match is None:
            return

        if match['match']:
            self.seq_match_label.setText(f"✅ Попадание! {match['percentage']:.0f}%")
            self.seq_match_label.setStyleSheet("color: #40c057;")
        else:
            cents_off = match['cents_off']
            arrow = "↑" if cents_off > 0 else "↓"
            self.seq_match_label.setText(f"{arrow} {abs(cents_off):.0f} центов")
            self.seq_match_label.setStyleSheet("color: #fa5252; font-weight: bold;")

        self.seq_match_progress.setValue(int(match['percentage']))

    # ------------------------------------------------------------------ #
    #  Предпрослушивание звука при редактировании пиано-ролла
    # ------------------------------------------------------------------ #

    def _on_piano_roll_preview(self, midi_note):
        """Проиграть ноту при её создании/перемещении на пиано-ролле,
        чтобы было слышно, какая высота получается"""
        if self.sequencer.is_playing():
            return
        try:
            self.synthesizer.start_note(midi_note)
        except Exception:
            logger.exception("Ошибка предпрослушивания ноты пиано-ролла")

    def _on_piano_roll_preview_stop(self):
        """Отпустили мышь после редактирования ноты - звук выключить"""
        if self.sequencer.is_playing():
            return
        try:
            self.synthesizer.stop_note()
        except Exception:
            logger.exception("Ошибка остановки предпрослушивания пиано-ролла")

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
        if self.sequencer.is_playing():
            self.sequencer.stop()
            self._update_seq_play_button(False)

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
        self.seq_level_meter.set_level(self.seq_level_meter.min_db)

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
            self.seq_level_meter.set_level(db)
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

        # Если сейчас играет нота секвенсора - копим её результаты
        # попадания независимо от того, какая вкладка сейчас открыта
        if self._seq_active_note is not None:
            self._update_seq_live_match(result)
            if result.get('has_voice'):
                match = result.get('pitch_match')
                if match is not None:
                    self._seq_note_matches.append(bool(match['match']))

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

        # Регистр (плавная шкала грудной..фальцет)
        register = result.get('register')
        if register:
            self.register_label.setText(register['label'])
            self.register_progress.setValue(int(register['register_mix'] * 100))

        # Зажатость / срывы
        strain = result.get('strain')
        if strain:
            self.strain_label.setText(strain['note'])
            self.strain_progress.setValue(int(strain['strain_score'] * 100))
            if strain['break_detected']:
                self.strain_progress.setStyleSheet("QProgressBar::chunk { background-color: #fa5252; }")
            elif strain['strain_score'] > 0.6:
                self.strain_progress.setStyleSheet("QProgressBar::chunk { background-color: #ffa94d; }")
            else:
                self.strain_progress.setStyleSheet("QProgressBar::chunk { background-color: #51cf66; }")

        # Текстовая подсказка "как от препода"
        feedback = self.analyzer.get_coach_feedback(result)
        if feedback:
            self.coach_label.setText(f"{feedback['headline']} — {feedback['detail']}")

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
            self.sequencer.analyzer = self.analyzer
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
            "<li>Секвенсор: пиано-ролл как в FL Studio (перемещение, ресайз, "
            "звук при редактировании) с проверкой пения по нотам в реальном времени</li>"
            "<li>Светлая/тёмная тема</li>"
            "</ul>"
            "<p>Версия: 2.1</p>"
        )

    def log(self, message):
        """Добавить сообщение в лог"""
        self.log_text.append(message)
        logger.debug("UI-лог: %s", message)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        try:
            if self.sequencer.is_playing():
                self.sequencer.stop()
            if self.is_recording:
                self.stop_recording()
            self.synthesizer.cleanup()
        except Exception:
            logger.exception("Ошибка при закрытии приложения")
        event.accept()
