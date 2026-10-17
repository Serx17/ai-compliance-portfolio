"""
Единый препроцессор: объединяет расчёты, реквизиты, исковую давность.

Вход: карточка должника (JSON).
Выход: подготовленные данные для LLM + результаты формальных проверок.

Всё, что делает препроцессор — детерминировано.
LLM получает уже подготовленные данные и НЕ может их изменить.

Юридические ограничения учтены в calculator.py:
- 353-ФЗ, ч. 23 ст. 5: максимальная ставка
- 353-ФЗ, ч. 24 ст. 5: потолок переплаты
- 353-ФЗ, ч. 21 ст. 5: потолок неустойки

ВАЖНО: calculation_date передаётся в calculator.py как None,
если явно не задана. Тогда calculator.py сам решит:
- filing_date из карточки → period_end
- date.today() → fallback.
"""

from datetime import date
from typing import Optional

from .calculator import (
    calculate_debt,
    DebtCalculation,
    MAX_OVERPAYMENT_RATIO,
    PENALTY_DAILY_RATE,
    PENALTY_MAX_DAILY_RATE,
)
from .requisites import format_requisites
from .limitation import check_limitation, LimitationResult


class Preprocessor:
    """Единый препроцессор для карточки должника."""

    def __init__(self, card: dict, calculation_date: Optional[date] = None):
        """
        Args:
            card: карточка должника (dict).
            calculation_date: дата расчёта.
                - Если задана явно → используется.
                - Если None → calculator.py берёт filing_date из карточки,
                  иначе date.today().
        """
        self.card = card
        self.calculation_date = calculation_date  # ← НЕ подменяем на today!

    def run(self) -> dict:
        """
        Прогон всех шагов препроцессора.

        Returns:
            dict с ключами:
            - case_id
            - requisites: реквизиты + результаты валидации
            - debt: расчёт задолженности (с учётом 353-ФЗ)
            - limitation: проверка исковой давности
            - issues: список всех проблем (для передачи в зоны контроля)
        """
        case_id = self.card.get("case_id", "unknown")

        # 1. Реквизиты
        requisites = format_requisites(self.card)

        # 2. Расчёт задолженности (с учётом 353-ФЗ)
        # calculation_date=None → calculator.py сам решит (filing_date → today)
        debt: DebtCalculation = calculate_debt(self.card, self.calculation_date)

        # 3. Исковая давность
        # Для проверки давности явно передаём дату подачи (или сегодня)
        filing_date_for_limitation = self.calculation_date
        if filing_date_for_limitation is None:
            filing_date_str = self.card.get("filing_date")
            if filing_date_str:
                try:
                    filing_date_for_limitation = date.fromisoformat(filing_date_str)
                except (ValueError, TypeError):
                    filing_date_for_limitation = date.today()
            else:
                filing_date_for_limitation = date.today()

        limitation: LimitationResult = check_limitation(
            self.card, filing_date=filing_date_for_limitation
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
                "raw_interest": debt.raw_interest,
                "raw_penalty": debt.raw_penalty,
                "cap_applied": debt.cap_applied,
                "max_overpayment_ratio": MAX_OVERPAYMENT_RATIO,
                "penalty_rate_used": debt.penalty_rate_used,
                "penalty_max_rate": PENALTY_MAX_DAILY_RATE,
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
