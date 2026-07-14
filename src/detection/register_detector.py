"""
register_detector.py
Плавная шкала регистра вместо бинарного fach/фальцет-грудной.

Идея: вместо classify(voice) -> "chest" | "falsetto"
считаем непрерывный register_mix в диапазоне [0.0, 1.0]:
    0.0 = чистый грудной
    0.5 = микст (то, что тренирует SLS)
    1.0 = чистый фальцет

Метрики, которые используем (все уже частично есть в вашем LPC/спектральном анализе):
    - formant_ratio: F1/F2 через LPC (грудной голос обычно даёт более высокий F1
      относительно F0, у фальцета F1 проседает ближе к F0)
    - spectral_tilt: наклон спектра в дБ/октаву (у фальцета меньше высоких
      обертонов -> более крутой отрицательный наклон)
    - hnr: гармоники к шуму (у фальцета обычно ниже, больше "воздуха" в звуке)

Это ЭВРИСТИКА, не готовая ground truth модель. Её нужно откалибровать
на собственном голосе: спойте заведомо грудным, заведомо фальцетом,
запишите сырые значения formant_ratio/spectral_tilt/hnr и подставьте
их как REFERENCE_CHEST / REFERENCE_FALSETTO ниже.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class RegisterReading:
    register_mix: float      # 0.0 chest ... 1.0 falsetto
    label: str                # "грудной" | "нижний микст" | "микст" | "верхний микст" | "фальцет"
    confidence: float         # 0..1, насколько мы уверены в оценке (зависит от HNR/шума)


# ЗАГЛУШКИ — замени на свои реальные калибровочные замеры.
# Пример: спой ноту A3 грудным, потом фальцетом, посмотри что выдаёт
# твой текущий LPC-модуль (formant analysis) и HNR-модуль (quality.py),
# и впиши сюда реальные числа.
REFERENCE_CHEST = {
    "formant_ratio": 2.8,   # F1/F0 типичное для грудного на средних нотах
    "spectral_tilt": -6.0,  # дБ/октаву, более пологий (больше высоких обертонов)
    "hnr": 18.0,
}
REFERENCE_FALSETTO = {
    "formant_ratio": 1.3,
    "spectral_tilt": -14.0,  # круче, меньше обертонов
    "hnr": 10.0,
}


def _normalize(value: float, low: float, high: float) -> float:
    """Линейно проецирует value в [0,1] между low(chest) и high(falsetto)."""
    if high == low:
        return 0.5
    x = (value - low) / (high - low)
    return float(np.clip(x, 0.0, 1.0))


def estimate_register(formant_ratio: float, spectral_tilt: float, hnr: float) -> RegisterReading:
    """
    formant_ratio, spectral_tilt, hnr — берутся из уже существующих
    src/detection/voice_type.py (LPC) и src/detection/quality.py (HNR).
    """
    f_score = _normalize(formant_ratio, REFERENCE_CHEST["formant_ratio"],
                          REFERENCE_FALSETTO["formant_ratio"])
    t_score = _normalize(spectral_tilt, REFERENCE_CHEST["spectral_tilt"],
                          REFERENCE_FALSETTO["spectral_tilt"])
    h_score = _normalize(hnr, REFERENCE_CHEST["hnr"], REFERENCE_FALSETTO["hnr"])

    # Формантное соотношение — самый надёжный признак, весим больше
    register_mix = 0.5 * f_score + 0.3 * t_score + 0.2 * h_score

    if register_mix < 0.2:
        label = "грудной"
    elif register_mix < 0.4:
        label = "нижний микст"
    elif register_mix < 0.6:
        label = "микст"
    elif register_mix < 0.8:
        label = "верхний микст"
    else:
        label = "фальцет"

    # Уверенность падает, если HNR низкий (шумно/нестабильно поёт)
    confidence = float(np.clip(hnr / REFERENCE_CHEST["hnr"], 0.0, 1.0))

    return RegisterReading(register_mix=register_mix, label=label, confidence=confidence)
