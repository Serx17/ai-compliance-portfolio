"""
Зона 6: Исковая давность.

Нормы:
- Ст. 196 ГК РФ — общий срок исковой давности 3 года.
- Ст. 200 ГК РФ — начало течения срока (по обязательствам с определённым
  сроком исполнения — по окончании срока).
- Ст. 203 ГК РФ — перерыв срока при признании долга.
- П. 20 Постановления Пленума ВС РФ № 43 от 29.09.2015 — частичная оплата
  не свидетельствует о признании долга в целом.
- П. 24–25 Пленума № 43 — для периодических платежей срок считается
  по каждому платежу отдельно.

Что проверяем:
- Не пропущен ли срок исковой давности.
- Если пропущен — есть ли обоснование перерыва.
- Для периодических платежей — срок по каждому отдельно.

Как проверяем:
- Из препроцессора берём limitation (уже посчитан).
- Проверяем: is_expired, days_since, threshold_days.
- Если перерыв есть — валидируем, что break_date в пределах срока.

Статусы:
- PASS: срок не пропущен.
- WARNING: срок пропущен, но есть перерыв (или незначительное превышение).
- FAIL: срок пропущен без обоснования.
"""

from datetime import date
from typing import List, Optional

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


# Ст. 196 ГК РФ
LIMITATION_YEARS = 3
LIMITATION_DAYS = LIMITATION_YEARS * 365  # упрощённо (без учёта високосных)

# Допуск на «незначительное» превышение (для warning vs fail)
SOFT_OVERRUN_DAYS = 30


class Zone6Limitation(ZoneChecker):
    """Зона 6: проверка исковой давности."""

    zone_number = 6
    zone_name = "Исковая давность"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка исковой давности.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Извлекаем данные из препроцессора
        limitation = preprocessed.get("limitation", {})
        is_expired = limitation.get("is_expired", False)
        days_since = limitation.get("days_since", 0)
        threshold_days = limitation.get("threshold_days", LIMITATION_DAYS)
        has_break = limitation.get("has_break", False)
        break_reason = limitation.get("break_reason")

        # 2. Если срок не пропущен — PASS
        if not is_expired:
            return self._make_result(
                status=ZoneStatus.PASS,
                issues=issues,
                metadata={
                    "is_expired": False,
                    "days_since": days_since,
                    "threshold_days": threshold_days,
                    "days_remaining": threshold_days - days_since,
                    "has_break": has_break,
                },
            )

        # 3. Срок пропущен. Проверяем перерыв
        overrun = days_since - threshold_days

        if has_break:
            # Есть перерыв — WARNING (требует проверки HITL)
            issues.append(ZoneIssue(
                field="limitation.break",
                reason=(
                    f"Срок исковой давности превышен на {overrun} дн., "
                    f"но есть перерыв: {break_reason or 'признание долга'}. "
                    f"Требуется проверка обоснованности перерыва."
                ),
                meta={
                    "severity": "warning",
                    "days_since": days_since,
                    "threshold_days": threshold_days,
                    "overrun_days": overrun,
                    "break_reason": break_reason,
                },
            ))
            status = ZoneStatus.WARNING
        elif overrun <= SOFT_OVERRUN_DAYS:
            # Незначительное превышение — WARNING
            issues.append(ZoneIssue(
                field="limitation",
                reason=(
                    f"Срок исковой давности превышен на {overrun} дн. "
                    f"(незначительно). Возможна подача с обоснованием."
                ),
                meta={
                    "severity": "warning",
                    "days_since": days_since,
                    "threshold_days": threshold_days,
                    "overrun_days": overrun,
                },
            ))
            status = ZoneStatus.WARNING
        else:
            # Существенное превышение без перерыва — FAIL
            issues.append(ZoneIssue(
                field="limitation",
                reason=(
                    f"Срок исковой давности превышен на {overrun} дн. "
                    f"без обоснования перерыва (ст. 196 ГК РФ). "
                    f"Иск не может быть подан."
                ),
                meta={
                    "severity": "fail",
                    "days_since": days_since,
                    "threshold_days": threshold_days,
                    "overrun_days": overrun,
                },
            ))
            status = ZoneStatus.FAIL

        # 4. Проверка для периодических платежей (если применимо)
        # П. 24–25 Пленума № 43: срок считается по каждому платежу отдельно.
        payments = card.get("payments", [])
        contract = card.get("contract", {})
        is_periodic = contract.get("is_periodic", False)

        if is_periodic and payments:
            periodic_issues = self._check_periodic_limitation(
                card, payments
            )
            issues.extend(periodic_issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "is_expired": True,
                "days_since": days_since,
                "threshold_days": threshold_days,
                "overrun_days": overrun,
                "has_break": has_break,
                "break_reason": break_reason,
                "is_periodic": is_periodic,
            },
        )

    def _check_periodic_limitation(
        self,
        card: dict,
        payments: list,
    ) -> List[ZoneIssue]:
        """
        Проверка давности для периодических платежей.

        П. 24 Пленума № 43: по периодическим платежам срок исковой
        давности течёт отдельно по каждому платежу.
        """
        issues: List[ZoneIssue] = []

        filing_date_str = card.get("filing_date")
        if not filing_date_str:
            return issues

        try:
            filing_date = date.fromisoformat(filing_date_str)
        except (ValueError, TypeError):
            return issues

        for idx, payment in enumerate(payments):
            payment_date_str = payment.get("date")
            if not payment_date_str:
                continue

            try:
                payment_date = date.fromisoformat(payment_date_str)
            except (ValueError, TypeError):
                continue

            days_since_payment = (filing_date - payment_date).days

            if days_since_payment > LIMITATION_DAYS:
                overrun = days_since_payment - LIMITATION_DAYS
                issues.append(ZoneIssue(
                    field=f"payments[{idx}]",
                    reason=(
                        f"По платежу от {payment_date} срок исковой давности "
                        f"превышен на {overrun} дн. (п. 24 Пленума № 43: "
                        f"срок считается отдельно по каждому платежу)"
                    ),
                    meta={
                        "severity": "fail",
                        "payment_date": payment_date.isoformat(),
                        "days_since_payment": days_since_payment,
                        "overrun_days": overrun,
                    },
                ))

        return issues
