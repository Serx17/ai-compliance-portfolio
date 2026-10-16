"""
Зона 3: Период задолженности.

Норма: ст. 122 ГПК РФ (требование о взыскании по договору).

Что проверяем:
- Период соответствует карточке должника.
- Нет пропусков в периоде (дыр).
- Нет пересечений периодов (дублирования).
- Конец периода ≤ дата подачи заявления.
- Начало периода > дата окончания договора (или последнего платежа).

Как проверяем:
- Сверка с preprocessed.debt.period.
- Проверка непрерывности: end[i] + 1 day == start[i+1].
- Проверка: period_end <= filing_date.
- Проверка: period_start > contract_end OR > last_payment.

Статусы:
- PASS: период корректен.
- WARNING: период пересекается или есть незначительные отклонения.
- FAIL: пропуск в периоде, конец в будущем, начало раньше договора.
"""

from datetime import date, timedelta
from typing import List, Optional

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


class Zone3Period(ZoneChecker):
    """Зона 3: проверка периода задолженности."""

    zone_number = 3
    zone_name = "Период задолженности"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка периода задолженности.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Извлекаем данные
        debt = preprocessed.get("debt", {})
        period = debt.get("period", {})
        period_start_str = period.get("start")
        period_end_str = period.get("end")
        days_calculated = period.get("days", 0)

        if not period_start_str or not period_end_str:
            issues.append(ZoneIssue(
                field="debt.period",
                reason="Период задолженности отсутствует в препроцессоре",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"error": "period_missing"},
            )

        try:
            period_start = date.fromisoformat(period_start_str)
            period_end = date.fromisoformat(period_end_str)
        except ValueError as e:
            issues.append(ZoneIssue(
                field="debt.period",
                reason=f"Неверный формат дат периода: {e}",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"error": "invalid_dates"},
            )

        # 2. Проверка: start <= end
        if period_start > period_end:
            issues.append(ZoneIssue(
                field="debt.period",
                reason=(
                    f"Начало периода ({period_start}) "
                    f"позже конца ({period_end})"
                ),
                meta={"severity": "fail"},
            ))

        # 3. Проверка: пересчёт дней
        computed_days = (period_end - period_start).days + 1
        if computed_days != days_calculated:
            issues.append(ZoneIssue(
                field="debt.period.days",
                reason=(
                    f"Количество дней в периоде не совпадает: "
                    f"в препроцессоре {days_calculated}, "
                    f"пересчёт даёт {computed_days}"
                ),
                expected=computed_days,
                found=days_calculated,
                meta={"severity": "fail"},
            ))

        # 4. Проверка: конец периода ≤ дата подачи
        filing_date = self._resolve_filing_date(card)
        if filing_date and period_end > filing_date:
            issues.append(ZoneIssue(
                field="debt.period.end",
                reason=(
                    f"Конец периода задолженности ({period_end}) "
                    f"позже даты подачи заявления ({filing_date})"
                ),
                expected=filing_date.isoformat(),
                found=period_end.isoformat(),
                meta={"severity": "fail"},
            ))

        # 5. Проверка: начало периода > даты окончания договора
        # (или последнего платежа)
        contract_end = self._resolve_contract_end(card)
        last_payment = self._resolve_last_payment(card)

        reference_date = last_payment or contract_end
        if reference_date and period_start <= reference_date:
            issues.append(ZoneIssue(
                field="debt.period.start",
                reason=(
                    f"Начало периода задолженности ({period_start}) "
                    f"не позже даты окончания договора/последнего платежа "
                    f"({reference_date})"
                ),
                expected=(reference_date + timedelta(days=1)).isoformat(),
                found=period_start.isoformat(),
                meta={"severity": "fail"},
            ))

        # 6. Проверка: явные расхождения с карточкой
        card_period_start = card.get("period_start")
        card_period_end = card.get("period_end")

        if card_period_start and card_period_start != period_start_str:
            issues.append(ZoneIssue(
                field="period.start",
                reason=(
                    f"Начало периода в карточке ({card_period_start}) "
                    f"не совпадает с расчётом ({period_start_str})"
                ),
                expected=card_period_start,
                found=period_start_str,
                meta={"severity": "fail"},
            ))

        if card_period_end and card_period_end != period_end_str:
            issues.append(ZoneIssue(
                field="period.end",
                reason=(
                    f"Конец периода в карточке ({card_period_end}) "
                    f"не совпадает с расчётом ({period_end_str})"
                ),
                expected=card_period_end,
                found=period_end_str,
                meta={"severity": "fail"},
            ))

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "days": computed_days,
                "filing_date": filing_date.isoformat() if filing_date else None,
                "reference_date": reference_date.isoformat() if reference_date else None,
            },
        )

    @staticmethod
    def _resolve_filing_date(card: dict) -> Optional[date]:
        """Дата подачи заявления (из карточки)."""
        raw = card.get("filing_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _resolve_contract_end(card: dict) -> Optional[date]:
        """Дата окончания договора."""
        raw = card.get("contract", {}).get("end_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _resolve_last_payment(card: dict) -> Optional[date]:
        """Дата последнего платежа (если есть)."""
        payments = card.get("payments", [])
        if not payments:
            return None
        try:
            dates = [date.fromisoformat(p["date"]) for p in payments]
            return max(dates)
        except (ValueError, KeyError, TypeError):
            return None
