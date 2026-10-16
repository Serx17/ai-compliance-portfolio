"""
Препроцессор Кейса №2: подготовка данных до LLM.

Модули:
- calculator: расчёт суммы долга, процентов, неустойки
- requisites: формирование и валидация реквизитов (ИНН/ОГРН)
- limitation: проверка исковой давности
- pipeline: объединение шагов в единый препроцессор

Принцип: все критичные поля (суммы, даты, ИНН) — детерминированы.
LLM видит только подготовленные данные и НЕ может их изменить.
"""

from .calculator import calculate_debt
from .requisites import validate_inn, validate_ogrn, format_requisites
from .limitation import check_limitation
from .pipeline import Preprocessor

__all__ = [
    "calculate_debt",
    "validate_inn",
    "validate_ogrn",
    "format_requisites",
    "check_limitation",
    "Preprocessor",
]
