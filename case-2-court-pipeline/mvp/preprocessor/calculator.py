"""
Расчёт суммы задолженности.

Ключевое: все расчёты — детерминированы. LLM не участвует в арифметике.

Состав долга:
- основной долг (сумма займа)
- проценты по ставке (по 230-ФЗ — ограничена)
- неустойка (пени за просрочку)

Период задолженности: от даты просрочки до даты расчёта.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional
import re


@dataclass
class Period:
    """Период задолженности."""
    start: date
    end: date

    def days(self) -> int:
        """Количество дней в периоде (включительно)."""
        return (self.end - self.start).days + 1


@dataclass
class DebtCalculation:
    """Результат расчёта задолженности."""
    principal: float          # основной долг
    interest: float           # проценты
    penalty: float            # неустойка
    total: float              # итого
    period: Period            # период задолженности
    issues: List[dict] = field(default_factory=list)


def _parse_date(value: str) -> date:
    """Парсинг даты из ISO-формата (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Неверный формат даты: {value!r} ({e})")


def calculate_debt(card: dict, calculation_date: Optional[date] = None) -> DebtCalculation:
    """
    Расчёт суммы задолженности из карточки.

    Args:
        card: карточка должника.
        calculation_date: дата расчёта (по умолчанию — сегодня).

    Returns:
        DebtCalculation с разбивкой и списком issues.
    """
    issues = []

    contract = card.get("contract", {})
    principal = float(contract.get("amount", 0))
    rate = float(contract.get("rate", 0.8))  # 0.8% в день (типично для МФО)
    contract_end = contract.get("end_date")

    if not contract_end:
        raise ValueError("В карточке нет contract.end_date")

    contract_end_date = _parse_date(contract_end)
    calc_date = calculation_date or date.today()

    # Период задолженности: с дня после окончания договора
    period_start = contract_end_date + timedelta(days=1)

    # Если есть payments — период начинается с последнего платежа
    payments = card.get("payments", [])
    if payments:
        last_payment = max(_parse_date(p["date"]) for p in payments)
        period_start = last_payment + timedelta(days=1)

    period_end = calc_date
    period = Period(start=period_start, end=period_end)

    if period.days() <= 0:
        issues.append({
            "field": "period",
            "reason": f"Период задолженности некорректен: {period.start} — {period.end}",
        })
        return DebtCalculation(
            principal=principal,
            interest=0.0,
            penalty=0.0,
            total=principal,
            period=period,
            issues=issues,
        )

    # Проценты по ставке (упрощённо: rate% в день от основного долга)
    days = period.days()
    interest = round(principal * (rate / 100) * days, 2)

    # Неустойка: 0.1% в день от суммы долга (упрощённо)
    penalty = round(principal * 0.001 * days, 2)

    total = round(principal + interest + penalty, 2)

    return DebtCalculation(
        principal=principal,
        interest=interest,
        penalty=penalty,
        total=total,
        period=period,
        issues=issues,
    )


def parse_amount_from_text(text: str) -> Optional[float]:
    """
    Парсинг суммы из текста документа.

    Используется в Зоне 2 для сверки суммы из документа с расчётной.

    Примеры:
        "75 000,00 руб." → 75000.00
        "75000.00" → 75000.00
        "75 000 рублей" → 75000.00
    """
    if not text:
        return None

    # Убираем пробелы-разделители тысяч, заменяем запятую на точку
    cleaned = re.sub(r"\s+", "", text)
    cleaned = cleaned.replace(",", ".")

    # Ищем первое число
    match = re.search(r"\d+\.?\d*", cleaned)
    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None
