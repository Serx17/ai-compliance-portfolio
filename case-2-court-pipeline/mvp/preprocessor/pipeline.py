"""
Единый препроцессор: объединяет расчёты, реквизиты, исковую давность.

Вход: карточка должника (JSON).
Выход: подготовленные данные для LLM + результаты формальных проверок.

Всё, что делает препроцессор — детерминировано.
LLM получает уже подготовленные данные и НЕ может их изменить.
"""

from datetime import date
from typing import Optional

from .calculator import calculate_debt, DebtCalculation
from .requisites import format_requisites
from .limitation import check_limitation, LimitationResult


class Preprocessor:
    """Единый препроцессор для карточки должника."""

    def __init__(self, card: dict, calculation_date: Optional[date] = None):
        """
        Args:
            card: карточка должника (dict).
            calculation_date: дата расчёта (по умолчанию — сегодня).
        """
        self.card = card
        self.calculation_date = calculation_date or date.today()

    def run(self) -> dict:
        """
        Прогон всех шагов препроцессора.

        Returns:
            dict с ключами:
            - case_id
            - requisites: реквизиты + результаты валидации
            - debt: расчёт задолженности
            - limitation: проверка исковой давности
            - issues: список всех проблем (для передачи в зоны контроля)
        """
        case_id = self.card.get("case_id", "unknown")

        # 1. Реквизиты
        requisites = format_requisites(self.card)

        # 2. Расчёт задолженности
        debt: DebtCalculation = calculate_debt(self.card, self.calculation_date)

        # 3. Исковая давность
        limitation: LimitationResult = check_limitation(
            self.card, filing_date=self.calculation_date
        )

        # Собираем issues
        issues = []
        issues.extend(requisites.get("validation", []))
        issues.extend(debt.issues)

        if limitation.is_expired:
            issues.append({
                "field": "limitation",
                "reason": limitation.reason,
                "days_since": limitation.days_since,
                "threshold_days": limitation.threshold_days,
            })

        return {
            "case_id": case_id,
            "requisites": requisites,
            "debt": {
                "principal": debt.principal,
                "interest": debt.interest,
                "penalty": debt.penalty,
                "total": debt.total,
                "period": {
                    "start": debt.period.start.isoformat(),
                    "end": debt.period.end.isoformat(),
                    "days": debt.period.days(),
                },
            },
            "limitation": {
                "is_expired": limitation.is_expired,
                "days_since": limitation.days_since,
                "threshold_days": limitation.threshold_days,
                "has_break": limitation.has_break,
                "break_reason": limitation.break_reason,
            },
            "issues": issues,
        }
