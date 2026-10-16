"""
Проверка исковой давности.

Ст. 196 ГК РФ: общий срок исковой давности — 3 года.
Для периодических платежей (проценты, неустойка) — срок считается по каждому платежу отдельно.

Перерыв срока исковой давности:
- признание долга должником (ст. 203 ГК РФ)
- частичная оплата
- подписание акта сверки
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class LimitationResult:
    """Результат проверки исковой давности."""
    is_expired: bool                    # истёк ли срок
    days_since: int                     # дней с начала срока
    threshold_days: int                 # порог (3 года = 1095 дней)
    has_break: bool                     # был ли перерыв
    break_reason: Optional[str] = None  # причина перерыва
    break_date: Optional[date] = None   # дата перерыва
    reason: Optional[str] = None        # пояснение


def check_limitation(
    card: dict,
    filing_date: Optional[date] = None,
    years: int = 3,
) -> LimitationResult:
    """
    Проверка исковой давности для карточки должника.

    Args:
        card: карточка должника.
        filing_date: дата подачи иска (по умолчанию — сегодня).
        years: срок исковой давности (по умолчанию — 3 года).

    Returns:
        LimitationResult.
    """
    filing = filing_date or date.today()
    threshold_days = years * 365  # упрощённо

    contract = card.get("contract", {})
    payments = card.get("payments", [])

    # Начало срока: последний платёж или дата окончания договора
    if payments:
        last_payment_str = max(p["date"] for p in payments)
        start_date = date.fromisoformat(last_payment_str)
    else:
        end_date_str = contract.get("end_date")
        if not end_date_str:
            return LimitationResult(
                is_expired=False,
                days_since=0,
                threshold_days=threshold_days,
                has_break=False,
                reason="Нет данных для расчёта срока",
            )
        start_date = date.fromisoformat(end_date_str)

    days_since = (filing - start_date).days

    # Проверка перерыва: акт сверки, признание долга
    break_info = card.get("limitation_break")
    if break_info:
        break_date_str = break_info.get("date")
        break_reason = break_info.get("reason", "признание долга")
        break_date = date.fromisoformat(break_date_str) if break_date_str else None

        if break_date:
            days_since = (filing - break_date).days
            return LimitationResult(
                is_expired=days_since > threshold_days,
                days_since=days_since,
                threshold_days=threshold_days,
                has_break=True,
                break_reason=break_reason,
                break_date=break_date,
                reason=f"Срок пересчитан с {break_date} ({break_reason})",
            )

    is_expired = days_since > threshold_days

    reason = None
    if is_expired:
        overrun = days_since - threshold_days
        reason = (
            f"Срок исковой давности превышен на {overrun} дней. "
            f"Требуется обоснование перерыва (признание долга, частичная оплата)"
        )

    return LimitationResult(
        is_expired=is_expired,
        days_since=days_since,
        threshold_days=threshold_days,
        has_break=False,
        reason=reason,
    )
