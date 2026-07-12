"""Окно настроек приложения"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QSlider, QSpinBox, QPushButton,
                             QGroupBox, QFormLayout)
from PyQt5.QtCore import Qt, pyqtSignal
import sounddevice as sd

from src.crash_logger import get_logger

logger = get_logger()


class SettingsDialog(QDialog):
    """Диалог настроек"""
    
    # Сигнал при изменении настроек
    settings_changed = pyqtSignal(dict)
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        
        self.config = config.copy()
        self.init_ui()
        
    def init_ui(self):
        """Инициализация UI"""
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Аудио настройки
        audio_group = self._create_audio_group()
        layout.addWidget(audio_group)
        
        # Настройки анализа
        analysis_group = self._create_analysis_group()
        layout.addWidget(analysis_group)
        
        # Настройки детекции голоса
        voice_group = self._create_voice_detection_group()
        layout.addWidget(voice_group)

        # Внешний вид
        appearance_group = self._create_appearance_group()
        layout.addWidget(appearance_group)

        # Кнопки
        button_layout = QHBoxLayout()
        
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.clicked.connect(self.apply_settings)
        
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept_settings)
        self.ok_btn.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(self.apply_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.ok_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
    def _create_audio_group(self):
        """Создать группу аудио настроек"""
        group = QGroupBox("Аудио")
        layout = QFormLayout()
        
        # Выбор устройства
        self.device_combo = QComboBox()
        try:
            devices = sd.query_devices()
            input_devices = [(i, d['name']) for i, d in enumerate(devices)
                            if d['max_input_channels'] > 0]
        except Exception:
            logger.exception("Не удалось получить список аудио устройств")
            input_devices = []

        if not input_devices:
            self.device_combo.addItem("Устройства не найдены", None)
        for idx, name in input_devices:
            self.device_combo.addItem(name, idx)
            
        # Устанавливаем текущее устройство
        current_device = self.config['audio'].get('device_index')
        if current_device is not None:
            index = self.device_combo.findData(current_device)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
                
        layout.addRow("Микрофон:", self.device_combo)
        
        # Размер буфера
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(512, 8192)
        self.chunk_size_spin.setSingleStep(512)
        self.chunk_size_spin.setValue(self.config['audio']['chunk_size'])
        layout.addRow("Размер буфера:", self.chunk_size_spin)
        
        group.setLayout(layout)
        return group
        
    def _create_analysis_group(self):
        """Создать группу настроек анализа"""
        group = QGroupBox("Анализ")
        layout = QFormLayout()
        
        # Порог уверенности определения высоты
        self.pitch_threshold_slider = QSlider(Qt.Horizontal)
        self.pitch_threshold_slider.setRange(0, 100)
        self.pitch_threshold_slider.setValue(
            int(self.config['analysis']['pitch_threshold'] * 100)
        )
        self.pitch_threshold_label = QLabel(
            f"{self.config['analysis']['pitch_threshold']:.2f}"
        )
        self.pitch_threshold_slider.valueChanged.connect(
            lambda v: self.pitch_threshold_label.setText(f"{v/100:.2f}")
        )
        
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(self.pitch_threshold_slider)
        threshold_layout.addWidget(self.pitch_threshold_label)
        
        layout.addRow("Порог уверенности pitch:", threshold_layout)
        
        # Noise gate
        self.noise_gate_spin = QSpinBox()
        self.noise_gate_spin.setRange(-60, 0)
        self.noise_gate_spin.setValue(self.config['analysis']['noise_gate_db'])
        self.noise_gate_spin.setSuffix(" дБ")
        layout.addRow("Noise gate:", self.noise_gate_spin)
        
        # Допуск в центах
        self.cent_tolerance_spin = QSpinBox()
        self.cent_tolerance_spin.setRange(10, 100)
        self.cent_tolerance_spin.setValue(self.config['analysis']['cent_tolerance'])
        self.cent_tolerance_spin.setSuffix(" центов")
        layout.addRow("Допуск попадания:", self.cent_tolerance_spin)
        
        # Порог качества
        self.quality_threshold_slider = QSlider(Qt.Horizontal)
        self.quality_threshold_slider.setRange(0, 100)
        self.quality_threshold_slider.setValue(
            int(self.config['analysis']['quality_threshold'] * 100)
        )
        self.quality_threshold_label = QLabel(
            f"{self.config['analysis']['quality_threshold']:.2f}"
        )
        self.quality_threshold_slider.valueChanged.connect(
            lambda v: self.quality_threshold_label.setText(f"{v/100:.2f}")
        )
        
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(self.quality_threshold_slider)
        quality_layout.addWidget(self.quality_threshold_label)
        
        layout.addRow("Порог качества:", quality_layout)

        # Скорость обновления анализа
        self.update_interval_spin = QSpinBox()
        self.update_interval_spin.setRange(20, 500)
        self.update_interval_spin.setSingleStep(10)
        self.update_interval_spin.setValue(
            self.config['analysis'].get('update_interval_ms', 50)
        )
        self.update_interval_spin.setSuffix(" мс")
        self.update_interval_spin.setToolTip(
            "Меньше = чаще обновляется анализ (более отзывчиво, больше нагрузка на CPU)"
        )
        layout.addRow("Скорость обновления:", self.update_interval_spin)

        group.setLayout(layout)
        return group
        
    def _create_voice_detection_group(self):
        """Создать группу настроек детекции голоса"""
        group = QGroupBox("Детекция голоса")
        layout = QFormLayout()
        
        # Минимальная частота
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(40, 200)
        self.min_freq_spin.setValue(self.config['voice_detection']['min_frequency'])
        self.min_freq_spin.setSuffix(" Гц")
        layout.addRow("Мин. частота:", self.min_freq_spin)
        
        # Максимальная частота
        self.max_freq_spin = QSpinBox()
        self.max_freq_spin.setRange(500, 2000)
        self.max_freq_spin.setValue(self.config['voice_detection']['max_frequency'])
        self.max_freq_spin.setSuffix(" Гц")
        layout.addRow("Макс. частота:", self.max_freq_spin)
        
        # Порог фальцета
        self.falsetto_threshold_slider = QSlider(Qt.Horizontal)
        self.falsetto_threshold_slider.setRange(0, 100)
        self.falsetto_threshold_slider.setValue(
            int(self.config['voice_detection']['falsetto_threshold'] * 100)
        )
        self.falsetto_threshold_label = QLabel(
            f"{self.config['voice_detection']['falsetto_threshold']:.2f}"
        )
        self.falsetto_threshold_slider.valueChanged.connect(
            lambda v: self.falsetto_threshold_label.setText(f"{v/100:.2f}")
        )
        
        falsetto_layout = QHBoxLayout()
        falsetto_layout.addWidget(self.falsetto_threshold_slider)
        falsetto_layout.addWidget(self.falsetto_threshold_label)
        
        layout.addRow("Порог фальцета:", falsetto_layout)
        
        group.setLayout(layout)
        return group
        
    def _create_appearance_group(self):
        """Создать группу настроек внешнего вида"""
        group = QGroupBox("Внешний вид")
        layout = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        current_theme = self.config.get('gui', {}).get('theme', 'light')
        index = self.theme_combo.findData(current_theme)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        layout.addRow("Тема:", self.theme_combo)

        note = QLabel("Смена темы применится после нажатия \"OK\" или \"Применить\"")
        note.setStyleSheet("color: #868e96; font-size: 11px;")
        layout.addRow(note)

        group.setLayout(layout)
        return group

    def apply_settings(self):
        """Применить настройки"""
        # Аудио
        self.config['audio']['device_index'] = self.device_combo.currentData()
        self.config['audio']['chunk_size'] = self.chunk_size_spin.value()
        
        # Анализ
        self.config['analysis']['pitch_threshold'] = self.pitch_threshold_slider.value() / 100
        self.config['analysis']['noise_gate_db'] = self.noise_gate_spin.value()
        self.config['analysis']['cent_tolerance'] = self.cent_tolerance_spin.value()
        self.config['analysis']['quality_threshold'] = self.quality_threshold_slider.value() / 100
        self.config['analysis']['update_interval_ms'] = self.update_interval_spin.value()
        
        # Детекция голоса
        self.config['voice_detection']['min_frequency'] = self.min_freq_spin.value()
        self.config['voice_detection']['max_frequency'] = self.max_freq_spin.value()
        self.config['voice_detection']['falsetto_threshold'] = self.falsetto_threshold_slider.value() / 100
        
        # Внешний вид
        if 'gui' not in self.config:
            self.config['gui'] = {}
        self.config['gui']['theme'] = self.theme_combo.currentData()

        # Отправляем сигнал
        self.settings_changed.emit(self.config)
        
    def accept_settings(self):
        """Применить и закрыть"""
        self.apply_settings()
        self.accept()
        
    def get_config(self):
        """Получить текущую конфигурацию"""
        return self.config
