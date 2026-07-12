"""Оценка качества и чистоты звука"""

import numpy as np
from scipy import signal
from scipy.stats import kurtosis, skew

from src.crash_logger import get_logger

logger = get_logger()


class QualityAnalyzer:
    """Анализатор качества и чистоты звука"""
    
    def __init__(self, config):
        self.sample_rate = config['audio']['sample_rate']
        self.quality_threshold = config['analysis']['quality_threshold']
        
    def calculate_hnr(self, audio_data):
        """
        Вычислить HNR (Harmonics-to-Noise Ratio)
        Отношение гармоник к шуму - показатель чистоты звука
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            HNR в дБ (выше = чище)
        """
        # Автокорреляция для выделения периодической составляющей
        autocorr = np.correlate(audio_data, audio_data, mode='full')
        autocorr = autocorr[len(autocorr)//2:]
        
        # Находим первый пик (основной период)
        peaks, _ = signal.find_peaks(autocorr[1:], height=0)
        
        if len(peaks) == 0:
            return 0.0
            
        # Энергия гармонической части (пик автокорреляции)
        harmonic_energy = autocorr[peaks[0] + 1]
        
        # Общая энергия
        total_energy = autocorr[0]
        
        # Энергия шума
        noise_energy = total_energy - harmonic_energy
        
        if noise_energy <= 0:
            return 40.0  # Максимальное значение

        if harmonic_energy <= 0:
            # log10(0) сам по себе кидает RuntimeWarning "divide by zero",
            # хотя результат в этом случае предсказуем - сигнал не периодичен
            return 0.0

        # HNR в дБ
        hnr = 10 * np.log10(harmonic_energy / noise_energy)
        
        return max(0.0, min(40.0, hnr))
        
    def calculate_spectral_centroid(self, audio_data):
        """
        Вычислить спектральный центроид
        Показывает "яркость" звука
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            Спектральный центроид в Hz
        """
        # FFT
        spectrum = np.abs(np.fft.rfft(audio_data))
        freqs = np.fft.rfftfreq(len(audio_data), 1/self.sample_rate)
        
        # Взвешенное среднее частот
        if np.sum(spectrum) > 0:
            centroid = np.sum(freqs * spectrum) / np.sum(spectrum)
        else:
            centroid = 0
            
        return centroid
        
    def calculate_zero_crossing_rate(self, audio_data):
        """
        Вычислить Zero Crossing Rate
        Показывает частоту пересечений нуля
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            ZCR (нормализованное значение 0-1)
        """
        # Подсчет пересечений нуля
        zero_crossings = np.sum(np.abs(np.diff(np.sign(audio_data)))) / 2
        zcr = zero_crossings / len(audio_data)
        
        return zcr
        
    def calculate_spectral_flatness(self, audio_data):
        """
        Вычислить спектральную плоскостность (Spectral Flatness)
        Показывает, насколько спектр похож на белый шум
        0 = тональный звук, 1 = шум
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            Spectral flatness (0-1)
        """
        # FFT
        spectrum = np.abs(np.fft.rfft(audio_data))
        spectrum = spectrum + 1e-10  # Избегаем деления на ноль
        
        # Геометрическое среднее
        geometric_mean = np.exp(np.mean(np.log(spectrum)))
        
        # Арифметическое среднее
        arithmetic_mean = np.mean(spectrum)
        
        if arithmetic_mean > 0:
            flatness = geometric_mean / arithmetic_mean
        else:
            flatness = 0
            
        return flatness
        
    def analyze_quality(self, audio_data):
        """
        Комплексный анализ качества звука (оптимизированная версия)
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            dict с метриками качества
        """
        if audio_data is None or len(audio_data) < 512:
            return None
        
        try:
            # Вычисляем только основные метрики для скорости
            hnr = self.calculate_hnr(audio_data)
            zcr = self.calculate_zero_crossing_rate(audio_data)
            
            # Упрощённый расчёт flatness (быстрее чем полный спектральный анализ)
            spectrum = np.abs(np.fft.rfft(audio_data[:1024]))  # Берём только первые 1024 сэмпла
            spectrum = spectrum + 1e-10
            geometric_mean = np.exp(np.mean(np.log(spectrum)))
            arithmetic_mean = np.mean(spectrum)
            flatness = geometric_mean / arithmetic_mean if arithmetic_mean > 0 else 0
            
            # Нормализуем метрики
            hnr_normalized = hnr / 40.0
            flatness_score = 1.0 - flatness
            zcr_score = 1.0 - abs(zcr - 0.1) / 0.1
            zcr_score = max(0.0, min(1.0, zcr_score))
            
            # Общий балл качества (взвешенная сумма)
            quality_score = (
                hnr_normalized * 0.6 +      # HNR - самый важный (увеличен вес)
                flatness_score * 0.3 +       # Тональность
                zcr_score * 0.1              # Частота пересечений (уменьшен вес)
            ) * 100
            
            is_clean = quality_score >= (self.quality_threshold * 100)
            
            return {
                'hnr': float(hnr),
                'spectral_centroid': 0.0,  # Пропускаем для скорости
                'zcr': float(zcr),
                'flatness': float(flatness),
                'quality_score': float(quality_score),
                'is_clean': is_clean
            }
            
        except Exception:
            logger.exception("Ошибка анализа качества")
            return None
        
    def detect_issues(self, audio_data):
        """
        Определить проблемы со звуком
        
        Args:
            audio_data: numpy array с аудио данными
            
        Returns:
            list строк с описанием проблем
        """
        issues = []
        
        quality = self.analyze_quality(audio_data)
        if quality is None:
            return ["Недостаточно данных"]
            
        if quality['hnr'] < 10:
            issues.append("Много шума в сигнале")
            
        if quality['flatness'] > 0.5:
            issues.append("Звук похож на шум")
            
        if quality['zcr'] > 0.3:
            issues.append("Слишком много высоких частот")
            
        if not issues:
            issues.append("Звук чистый")
            
        return issues
