"""
7 зон контроля судебного документа (Кейс №2).

Каждая зона — детерминированный модуль проверки.
LLM не участвует в проверках — только в генерации текста.

Модули:
- base: базовый класс ZoneChecker + ZoneResult
- runner: запуск всех зон
- zone_1_requisites: реквизиты сторон
- zone_2_amount: сумма иска (+ потолок 353-ФЗ)
- zone_3_period: период задолженности
- zone_4_appendix: приложения (ст. 124 ГПК РФ)
- zone_5_jurisdiction: подсудность (ст. 123, 28 ГПК РФ)
- zone_6_limitation: исковая давность (ст. 196, 203 ГК РФ)
- zone_7_pd_compliance: ПДн третьих лиц (соразмерность)
"""

from .base import ZoneChecker, ZoneResult, ZoneStatus
from .runner import RulesRunner

__all__ = ["ZoneChecker", "ZoneResult", "ZoneStatus", "RulesRunner"]
