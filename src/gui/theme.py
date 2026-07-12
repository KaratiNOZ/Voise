# -*- coding: utf-8 -*-
"""Стили оформления приложения (светлая/тёмная тема)"""

LIGHT_QSS = """
QWidget {
    background-color: #f4f5f7;
    color: #23272f;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}
QMainWindow {
    background-color: #f4f5f7;
}
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e0e2e6;
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    color: #4b5563;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #6b7280;
}
QPushButton {
    background-color: #4dabf7;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #339af0;
}
QPushButton:pressed {
    background-color: #1c7ed6;
}
QPushButton:disabled {
    background-color: #ced4da;
    color: #868e96;
}
QPushButton#recordButton {
    background-color: #40c057;
    font-size: 15px;
}
QPushButton#recordButton:hover {
    background-color: #37b24d;
}
QPushButton#recordButtonActive {
    background-color: #fa5252;
    font-size: 15px;
}
QPushButton#recordButtonActive:hover {
    background-color: #e03131;
}
QPushButton#secondaryButton {
    background-color: #e9ecef;
    color: #495057;
}
QPushButton#secondaryButton:hover {
    background-color: #dee2e6;
}
QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #e9ecef;
    text-align: center;
    height: 16px;
    color: #495057;
    font-weight: 600;
}
QProgressBar::chunk {
    border-radius: 6px;
    background-color: #4dabf7;
}
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #e0e2e6;
    border-radius: 8px;
    padding: 4px;
}
QLabel#infoLabel {
    border-radius: 8px;
    padding: 14px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#sectionValue {
    font-size: 16px;
    font-weight: 700;
    color: #1c7ed6;
}
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e2e6;
}
QMenuBar::item:selected {
    background-color: #e7f5ff;
    border-radius: 4px;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #e0e2e6;
}
QMenu::item:selected {
    background-color: #e7f5ff;
}
QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #e0e2e6;
    color: #6b7280;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #e9ecef;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4dabf7;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QComboBox, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    padding: 4px 8px;
}
"""

DARK_QSS = """
QWidget {
    background-color: #1a1b1e;
    color: #e4e6eb;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    font-size: 13px;
}
QMainWindow {
    background-color: #1a1b1e;
}
QGroupBox {
    background-color: #242529;
    border: 1px solid #33343a;
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    color: #a1a5ad;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #babec7;
}
QPushButton {
    background-color: #4dabf7;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #339af0;
}
QPushButton:pressed {
    background-color: #1c7ed6;
}
QPushButton:disabled {
    background-color: #3a3b40;
    color: #6c6f76;
}
QPushButton#recordButton {
    background-color: #40c057;
    font-size: 15px;
}
QPushButton#recordButton:hover {
    background-color: #37b24d;
}
QPushButton#recordButtonActive {
    background-color: #fa5252;
    font-size: 15px;
}
QPushButton#recordButtonActive:hover {
    background-color: #e03131;
}
QPushButton#secondaryButton {
    background-color: #33343a;
    color: #e4e6eb;
}
QPushButton#secondaryButton:hover {
    background-color: #3f4046;
}
QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #33343a;
    text-align: center;
    height: 16px;
    color: #e4e6eb;
    font-weight: 600;
}
QProgressBar::chunk {
    border-radius: 6px;
    background-color: #4dabf7;
}
QTextEdit {
    background-color: #242529;
    border: 1px solid #33343a;
    border-radius: 8px;
    padding: 4px;
    color: #e4e6eb;
}
QLabel#infoLabel {
    border-radius: 8px;
    padding: 14px;
    font-size: 15px;
    font-weight: 700;
}
QLabel#sectionValue {
    font-size: 16px;
    font-weight: 700;
    color: #74c0fc;
}
QMenuBar {
    background-color: #242529;
    border-bottom: 1px solid #33343a;
}
QMenuBar::item:selected {
    background-color: #2c3e50;
    border-radius: 4px;
}
QMenu {
    background-color: #242529;
    border: 1px solid #33343a;
}
QMenu::item:selected {
    background-color: #2c3e50;
}
QStatusBar {
    background-color: #242529;
    border-top: 1px solid #33343a;
    color: #a1a5ad;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #33343a;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #4dabf7;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QComboBox, QSpinBox {
    background-color: #242529;
    border: 1px solid #3a3b40;
    border-radius: 6px;
    padding: 4px 8px;
    color: #e4e6eb;
}
"""

APP_STYLESHEET = {
    "light": LIGHT_QSS,
    "dark": DARK_QSS,
}
