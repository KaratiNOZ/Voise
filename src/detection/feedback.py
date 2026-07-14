"""
feedback.py
Собирает вывод register_detector + strain_detector + pitch accuracy
в одну человеческую фразу — как будто препод сказал, а не индикатор мигнул.
"""

from dataclasses import dataclass
from register_detector import RegisterReading
from strain_detector import StrainReading


@dataclass
class CoachFeedback:
    headline: str    # короткая главная фраза
    detail: str        # что именно поправить


def generate_feedback(register: RegisterReading, strain: StrainReading,
                       cents_off: float) -> CoachFeedback:
    """
    cents_off: отклонение от целевой ноты в центах (можно брать из твоего
    существующего pitch.py, он уже это считает).
    """

    # Приоритет: сначала срыв, потом зажатость, потом просто точность ноты
    if strain.break_detected:
        return CoachFeedback(
            headline="Был срыв на переходе",
            detail="Сбавь громкость и скорость ровно в точке перехода регистра, "
                   "дай гортани не дёргаться — попробуй петь тише в этом месте.",
        )

    if strain.strain_score > 0.6:
        return CoachFeedback(
            headline="Голос зажат",
            detail="Слышно напряжение — расслабь челюсть и корень языка, "
                   "попробуй петь на зевке, будто удивлён.",
        )

    if register.label in ("нижний микст", "микст", "верхний микст") and strain.strain_score < 0.3:
        return CoachFeedback(
            headline=f"Хороший {register.label}",
            detail="Именно так и должен звучать SLS-микст — держи это ощущение.",
        )

    if abs(cents_off) > 40:
        direction = "выше" if cents_off < 0 else "ниже"
        return CoachFeedback(
            headline=f"Мимо ноты, нужно {direction}",
            detail=f"Отклонение {abs(cents_off):.0f} центов — подстрой высоту.",
        )

    if register.label == "фальцет" and strain.strain_score < 0.3:
        return CoachFeedback(
            headline="Чистый фальцет",
            detail="Хорошо и легко, но попробуй чуть больше опоры дыхания, "
                   "чтобы приблизиться к миксту.",
        )

    if register.label == "грудной" and strain.strain_score < 0.3:
        return CoachFeedback(
            headline="Хороший грудной регистр",
            detail="Уверенно и свободно — можно пробовать подниматься выше в микст.",
        )

    return CoachFeedback(
        headline="Неплохо",
        detail="Стабильно, без явных проблем — продолжай в том же духе.",
    )
