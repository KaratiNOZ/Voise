"""Главный модуль анализа вокала"""

from src.audio.recorder import AudioRecorder
from src.audio.processor import AudioProcessor
from src.detection.pitch import PitchDetector
from src.detection.quality import QualityAnalyzer
from src.detection.voice_type import VoiceTypeDetector
from src.crash_logger import get_logger

logger = get_logger()


class VoiceAnalyzer:
    """Главный анализатор вокала"""
    
    def __init__(self, config):
        self.config = config
        
        # Инициализируем компоненты
        self.recorder = AudioRecorder(config)
        self.processor = AudioProcessor(config)
        self.pitch_detector = PitchDetector(config)
        self.quality_analyzer = QualityAnalyzer(config)
        self.voice_type_detector = VoiceTypeDetector(config)
        
        # Целевая нота для проверки
        self.target_frequency = None
        self.target_midi_note = None
        
        # Кэш для оптимизации
        self._voice_type_cache = None
        self._voice_type_counter = 0
        
    def set_target_note(self, midi_note):
        """
        Установить целевую ноту для проверки попадания
        
        Args:
            midi_note: MIDI номер ноты (например, 60 = C4)
        """
        self.target_midi_note = midi_note
        self.target_frequency = self.pitch_detector.midi_to_hz(midi_note)
        
    def clear_target_note(self):
        """Очистить целевую ноту"""
        self.target_frequency = None
        self.target_midi_note = None
        
    def start_recording(self):
        """Начать запись с микрофона"""
        self.recorder.start()
        
    def stop_recording(self):
        """Остановить запись"""
        self.recorder.stop()
        
    def analyze_chunk(self):
        """
        Проанализировать один кусок аудио
        
        Returns:
            dict с результатами анализа или None если нет данных
        """
        try:
            # Получаем аудио данные (в любом случае вычищаем очередь
            # рекордера, чтобы не накапливать задержку - см. recorder.py)
            audio_chunk = self.recorder.get_audio_chunk()

            if audio_chunk is None:
                return None

            # Обрабатываем (фильтрация, шумоподавление)
            processed = self.processor.process(audio_chunk)
            
            if processed is None:
                return {
                    'has_voice': False,
                    'message': 'Нет голоса или слишком тихо'
                }
                
            # Детекция высоты тона
            pitch_data = self.pitch_detector.detect_pitch(processed)
            
            if pitch_data is None:
                return {
                    'has_voice': False,
                    'message': 'Голос не обнаружен'
                }
                
            # Анализ качества
            quality_data = self.quality_analyzer.analyze_quality(processed)
            
            # Если качество не определено, используем заглушку
            if quality_data is None:
                quality_data = {
                    'hnr': 0,
                    'spectral_centroid': 0,
                    'zcr': 0,
                    'flatness': 0,
                    'quality_score': 50,
                    'is_clean': False
                }
            
            # Определение типа голоса (делаем реже для производительности - каждые 5 кадров)
            self._voice_type_counter += 1
            if self._voice_type_counter >= 5 or self._voice_type_cache is None:
                voice_type_result = self.voice_type_detector.detect_voice_type(
                    processed, 
                    pitch_data
                )
                if voice_type_result is not None:
                    self._voice_type_cache = voice_type_result
                self._voice_type_counter = 0
                
            voice_type_data = self._voice_type_cache
            
            # Если тип голоса не определён, используем заглушку
            if voice_type_data is None:
                voice_type_data = {
                    'type': 'chest',
                    'confidence': 0.5,
                    'features': {}
                }
            
            # Проверка попадания в ноту (если задана целевая нота)
            pitch_match = None
            if self.target_frequency is not None:
                tolerance = self.config['analysis']['cent_tolerance']
                pitch_match = self.pitch_detector.check_pitch_match(
                    pitch_data['frequency'],
                    self.target_frequency,
                    tolerance
                )
                
            # Формируем результат
            result = {
                'has_voice': True,
                'pitch': pitch_data,
                'quality': quality_data,
                'voice_type': voice_type_data,
                'pitch_match': pitch_match,
                'target_note': {
                    'midi': self.target_midi_note,
                    'frequency': self.target_frequency,
                    'name': self.pitch_detector.midi_to_note_name(self.target_midi_note) 
                            if self.target_midi_note else None
                } if self.target_frequency else None
            }
            
            return result
            
        except Exception as e:
            logger.exception("Ошибка в analyze_chunk")
            return {
                'has_voice': False,
                'message': f'Ошибка анализа: {str(e)}'
            }
        
    def get_summary_message(self, analysis_result):
        """
        Получить текстовое резюме результатов анализа
        
        Args:
            analysis_result: результат от analyze_chunk
            
        Returns:
            str с описанием результатов
        """
        if not analysis_result or not analysis_result.get('has_voice'):
            return analysis_result.get('message', 'Нет данных')
            
        messages = []
        
        # Высота тона
        pitch = analysis_result['pitch']
        messages.append(f"🎵 Нота: {pitch['note_name']} ({pitch['frequency']:.1f} Hz)")
        
        # Попадание в ноту
        if analysis_result.get('pitch_match'):
            match = analysis_result['pitch_match']
            if match['match']:
                messages.append(f"✅ Попал в ноту! Точность: {match['percentage']:.1f}%")
            else:
                direction = "выше" if match['cents_off'] > 0 else "ниже"
                messages.append(f"❌ Не попал: {abs(match['cents_off']):.0f} центов {direction}")
                
        # Качество
        quality = analysis_result['quality']
        if quality['is_clean']:
            messages.append(f"✨ Чистый звук ({quality['quality_score']:.0f}/100)")
        else:
            messages.append(f"⚠️ Звук недостаточно чистый ({quality['quality_score']:.0f}/100)")
            issues = self.quality_analyzer.detect_issues(None)  # Используем кэшированные данные
            
        # Тип голоса
        voice_type = analysis_result['voice_type']
        type_desc = self.voice_type_detector.get_voice_type_description(voice_type)
        
        if voice_type['type'] == 'falsetto':
            messages.append(f"🎤 {type_desc}")
        else:
            messages.append(f"🎤 {type_desc}")
            
        return "\n".join(messages)
        
    def get_device_list(self):
        """Получить список доступных аудио устройств"""
        return AudioRecorder.list_devices()

    def get_input_level_db(self):
        """Текущий уровень входного сигнала в дБ (для VU-метра)"""
        return self.recorder.get_level_db()

    def get_recorder_error(self):
        """Ошибка потока записи, если она произошла (например, устройство отвалилось)"""
        return self.recorder.get_last_error()
