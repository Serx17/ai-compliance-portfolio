"""
Расчёт суммы задолженности.

Ключевое: все расчёты — детерминированы. LLM не участвует в арифметике.

Юридические ограничения (353-ФЗ «О потребительском кредите»):
- Ставка не более 0,8% в день (ч. 23 ст. 5) — валидируется в requisites.py
- Потолок переплаты: проценты + неустойка ≤ 100% от основного долга
  (ч. 24 ст. 5, ред. с 01.04.2026; до этой даты — 130%)
- ПСК не более 292% годовых (ч. 11 ст. 6)

Без учёта этих ограничений любой иск с завышенной суммой
будет отменён судом по ч. 24 ст. 5 353-ФЗ.

Состав долга:
- основной долг (сумма займа)
- проценты по ставке (с учётом потолка переплаты)
- неустойка (пени за просрочку, с учётом потолка)

Период задолженности: от даты просрочки до даты расчёта.
"""

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional
import re


# 353-ФЗ, ч. 24 ст. 5: потолок переплаты
# До 01.04.2026 — 130% (1.30)
# С 01.04.2026 — 100% (1.00)
MAX_OVERPAYMENT_RATIO = float(os.getenv("MAX_OVERPAYMENT_RATIO", "1.00"))

# 353-ФЗ, ч. 23 ст. 5: максимальная ставка
MAX_DAILY_RATE = 0.8  # % в день


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
    principal: float                      # основной долг
    interest: float                       # проценты (после обрезки по потолку)
    penalty: float                        # неустойка (после обрезки по потолку)
    total: float                          # итого
    period: Period                        # период задолженности
    raw_interest: float = 0.0             # проценты до обрезки (для аудита)
    raw_penalty: float = 0.0              # неустойка до обрезки (для аудита)
    cap_applied: bool = False             # был ли применён потолок переплаты
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

    Учитывает потолок переплаты по 353-ФЗ (ч. 24 ст. 5):
    проценты + неустойка ≤ MAX_OVERPAYMENT_RATIO × основной долг.

    Args:
        card: карточка должника.
        calculation_date: дата расчёта (по умолчанию — сегодня).

    Returns:
        DebtCalculation с разбивкой и списком issues.
    """
    issues = []

    contract = card.get("contract", {})
    principal = float(contract.get("amount", 0))
    rate = float(contract.get("rate", 0.8))
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

    # 1. Сырые проценты (до потолка)
    days = period.days()
    raw_interest = round(principal * (rate / 100) * days, 2)

    # 2. Сырая неустойка: 0.1% в день (упрощённо)
    raw_penalty = round(principal * 0.001 * days, 2)

    # 3. Применение потолка переплаты по 353-ФЗ, ч. 24 ст. 5
    total_charges = raw_interest + raw_penalty
    max_charges = principal * MAX_OVERPAYMENT_RATIO

    cap_applied = False
    if total_charges > max_charges:
        ratio = max_charges / total_charges
        interest = round(raw_interest * ratio, 2)
        penalty = round(raw_penalty * ratio, 2)
        cap_applied = True
        issues.append({
            "field": "overpayment_cap",
            "reason": (
                f"Проценты и неустойка обрезаны до потолка "
                f"{int(MAX_OVERPAYMENT_RATIO * 100)}% от основного долга "
                f"(353-ФЗ, ч. 24 ст. 5). "
                f"Сырые: проценты {raw_interest} ₽, неустойка {raw_penalty} ₽. "
                f"После обрезки: проценты {interest} ₽, неустойка {penalty} ₽."
            ),
            "raw_interest": raw_interest,
            "raw_penalty": raw_penalty,
            "cap_amount": round(max_charges, 2),
        })
    else:
        interest = raw_interest
        penalty = raw_penalty

    # 4. Валидация ставки (353-ФЗ, ч. 23 ст. 5)
    if rate > MAX_DAILY_RATE:
        issues.append({
            "field": "contract.rate",
            "reason": (
                f"Ставка {rate}% в день превышает максимум "
                f"{MAX_DAILY_RATE}% (353-ФЗ, ч. 23 ст. 5)"
            ),
            "rate": rate,
            "max_rate": MAX_DAILY_RATE,
        })

    total = round(principal + interest + penalty, 2)

    return DebtCalculation(
        principal=principal,
        interest=interest,
        penalty=penalty,
        total=total,
        period=period,
        raw_interest=raw_interest,
        raw_penalty=raw_penalty,
        cap_applied=cap_applied,
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

    cleaned = re.sub(r"\s+", "", text)
    cleaned = cleaned.replace(",", ".")

    match = re.search(r"\d+\.?\d*", cleaned)
    if not match:
        return None

    try:
        return float(match.group())
    except ValueError:
        return None
