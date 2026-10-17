"""
Зона 3: Период задолженности.

Норма: ст. 122 ГПК РФ (требование о взыскании по договору).

ВАЖНОЕ РАЗЛИЧИЕ:
- card.period_end — последний день ПЕРИОДА ЗАДОЛЖЕННОСТИ (из карточки).
  Это день, по который накопился долг (основной долг).
- debt.period.end — дата, до которой начисляются ПРОЦЕНТЫ.
  Совпадает с датой подачи (filing_date), а не с card.period_end.

Эти два поля — РАЗНЫЕ. Их нельзя сравнивать между собой.

Что проверяем:
- Период (debt.period) валиден: start ≤ end, дни пересчитаны.
- Конец периода ≤ даты подачи (filing_date).
- Начало периода > даты окончания договора / последнего платежа.
- card.period_end ≤ filing_date (период задолженности не позже подачи).
- Для разбивки — непрерывность, отсутствие пересечений и дыр.

Статусы:
- PASS: период корректен.
- WARNING: незначительные отклонения.
- FAIL: пропуск, конец в будущем, начало раньше договора.
"""

from datetime import date, timedelta
from typing import List, Optional

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


class Zone3Period(ZoneChecker):
    """Зона 3: проверка периода задолженности (единый или разбивка)."""

    zone_number = 3
    zone_name = "Период задолженности"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """Проверка периода задолженности."""
        issues: List[ZoneIssue] = []

        debt = preprocessed.get("debt", {})
        period = debt.get("period")
        periods = debt.get("periods")

        if periods and isinstance(periods, list):
            return self._check_split(card, periods, issues)

        if period and isinstance(period, dict):
            return self._check_single(card, period, issues)

        issues.append(ZoneIssue(
            field="debt.period",
            reason="Период задолженности отсутствует (ни единого, ни разбивки)",
            meta={"severity": "fail"},
        ))
        return self._make_result(
            status=ZoneStatus.FAIL,
            issues=issues,
            metadata={"error": "period_missing"},
        )

    # ------------------------------------------------------------------ #
    # Единый период                                                       #
    # ------------------------------------------------------------------ #

    def _check_single(self, card: dict, period: dict, issues: List[ZoneIssue]) -> ZoneResult:
        """Проверка единого периода."""
        period_start_str = period.get("start")
        period_end_str = period.get("end")
        days_calculated = period.get("days", 0)

        if not period_start_str or not period_end_str:
            issues.append(ZoneIssue(
                field="debt.period",
                reason="В едином периоде отсутствуют start или end",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"format": "single", "error": "missing_dates"},
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
                metadata={"format": "single", "error": "invalid_dates"},
            )

        self._validate_period_bounds(period_start, period_end, days_calculated, issues)
        self._validate_reference_dates(card, period_start, period_end, issues)

        status = self._resolve_status(issues)
        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "format": "single",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "days": (period_end - period_start).days + 1,
                "card_period_end": card.get("period_end"),
                "filing_date": card.get("filing_date"),
            },
        )

    # ------------------------------------------------------------------ #
    # Разбивка                                                            #
    # ------------------------------------------------------------------ #

    def _check_split(self, card: dict, periods: list, issues: List[ZoneIssue]) -> ZoneResult:
        """Проверка разбивки периодов."""
        parsed: List[tuple] = []

        for idx, p in enumerate(periods):
            start_str = p.get("start")
            end_str = p.get("end")
            days_calc = p.get("days", 0)

            if not start_str or not end_str:
                issues.append(ZoneIssue(
                    field=f"debt.periods[{idx}]",
                    reason=f"В периоде #{idx} отсутствуют start или end",
                    meta={"severity": "fail"},
                ))
                continue

            try:
                start = date.fromisoformat(start_str)
                end = date.fromisoformat(end_str)
            except ValueError as e:
                issues.append(ZoneIssue(
                    field=f"debt.periods[{idx}]",
                    reason=f"Неверный формат дат в периоде #{idx}: {e}",
                    meta={"severity": "fail"},
                ))
                continue

            parsed.append((idx, start, end, days_calc))

        if not parsed:
            issues.append(ZoneIssue(
                field="debt.periods",
                reason="Разбивка периодов пуста или все периоды невалидны",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"format": "split", "periods_count": len(periods)},
            )

        # Каждый период: start ≤ end и пересчёт дней
        for idx, start, end, days_calc in parsed:
            if start > end:
                issues.append(ZoneIssue(
                    field=f"debt.periods[{idx}]",
                    reason=f"Период #{idx}: начало ({start}) позже конца ({end})",
                    meta={"severity": "fail"},
                ))
                continue

            computed_days = (end - start).days + 1
            if computed_days != days_calc:
                issues.append(ZoneIssue(
                    field=f"debt.periods[{idx}].days",
                    reason=(
                        f"Период #{idx}: количество дней не совпадает — "
                        f"в препроцессоре {days_calc}, пересчёт даёт {computed_days}"
                    ),
                    expected=computed_days,
                    found=days_calc,
                    meta={"severity": "fail"},
                ))

        # Проверка стыков
        sorted_periods = sorted(parsed, key=lambda x: x[1])
        for i in range(len(sorted_periods) - 1):
            _, start_cur, end_cur, _ = sorted_periods[i]
            _, start_next, end_next, _ = sorted_periods[i + 1]

            expected_next = end_cur + timedelta(days=1)

            if start_next <= end_cur:
                overlap_days = (end_cur - start_next).days + 1
                severity = "warning" if overlap_days <= 1 else "fail"
                issues.append(ZoneIssue(
                    field=f"debt.periods[{i}]->[{i+1}]",
                    reason=(
                        f"Пересечение периодов: "
                        f"({start_cur}–{end_cur}) и ({start_next}–{end_next}) "
                        f"пересекаются на {overlap_days} дн."
                    ),
                    meta={"severity": severity, "overlap_days": overlap_days},
                ))
            elif start_next > expected_next:
                gap_days = (start_next - expected_next).days
                issues.append(ZoneIssue(
                    field=f"debt.periods[{i}]->[{i+1}]",
                    reason=(
                        f"Пропуск в периодах: между "
                        f"({start_cur}–{end_cur}) и ({start_next}–{end_next}) "
                        f"пропущено {gap_days} дн. (ожидалось начало {expected_next})"
                    ),
                    expected=expected_next.isoformat(),
                    found=start_next.isoformat(),
                    meta={"severity": "fail", "gap_days": gap_days},
                ))

        # Все периоды ≤ дата подачи
        filing_date = self._resolve_filing_date(card)
        if filing_date:
            for idx, start, end, _ in parsed:
                if end > filing_date:
                    issues.append(ZoneIssue(
                        field=f"debt.periods[{idx}].end",
                        reason=(
                            f"Период #{idx}: конец ({end}) "
                            f"позже даты подачи ({filing_date})"
                        ),
                        expected=filing_date.isoformat(),
                        found=end.isoformat(),
                        meta={"severity": "fail"},
                    ))

        # Первый период > даты окончания договора
        contract_end = self._resolve_contract_end(card)
        last_payment = self._resolve_last_payment(card)
        reference_date = last_payment or contract_end

        if reference_date:
            first_start = sorted_periods[0][1]
            if first_start <= reference_date:
                issues.append(ZoneIssue(
                    field="debt.periods[0].start",
                    reason=(
                        f"Первый период начинается ({first_start}) "
                        f"не позже даты окончания договора/последнего платежа "
                        f"({reference_date})"
                    ),
                    expected=(reference_date + timedelta(days=1)).isoformat(),
                    found=first_start.isoformat(),
                    meta={"severity": "fail"},
                ))

        status = self._resolve_status(issues)
        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "format": "split",
                "periods_count": len(parsed),
                "first_start": sorted_periods[0][1].isoformat(),
                "last_end": sorted_periods[-1][2].isoformat(),
                "total_days": sum(
                    (end - start).days + 1 for _, start, end, _ in parsed
                ),
            },
        )

    # ------------------------------------------------------------------ #
    # Общие проверки                                                      #
    # ------------------------------------------------------------------ #

    def _validate_period_bounds(
        self,
        period_start: date,
        period_end: date,
        days_calculated: int,
        issues: List[ZoneIssue],
    ) -> None:
        """Проверка границ единого периода."""
        if period_start > period_end:
            issues.append(ZoneIssue(
                field="debt.period",
                reason=f"Начало периода ({period_start}) позже конца ({period_end})",
                meta={"severity": "fail"},
            ))

        computed_days = (period_end - period_start).days + 1
        if computed_days != days_calculated:
            issues.append(ZoneIssue(
                field="debt.period.days",
                reason=(
                    f"Количество дней не совпадает: "
                    f"в препроцессоре {days_calculated}, пересчёт даёт {computed_days}"
                ),
                expected=computed_days,
                found=days_calculated,
                meta={"severity": "fail"},
            ))

    def _validate_reference_dates(
        self,
        card: dict,
        period_start: date,
        period_end: date,
        issues: List[ZoneIssue],
    ) -> None:
        """
        Проверка единого периода относительно дат договора и подачи.

        ВАЖНО: здесь НЕ сравниваем period_end с card.period_end —
        это разные понятия (см. docstring модуля).
        """
        # 1. Конец периода ≤ дата подачи
        filing_date = self._resolve_filing_date(card)
        if filing_date and period_end > filing_date:
            issues.append(ZoneIssue(
                field="debt.period.end",
                reason=(
                    f"Конец периода ({period_end}) "
                    f"позже даты подачи ({filing_date})"
                ),
                expected=filing_date.isoformat(),
                found=period_end.isoformat(),
                meta={"severity": "fail"},
            ))

        # 2. Начало периода > даты окончания договора / последнего платежа
        contract_end = self._resolve_contract_end(card)
        last_payment = self._resolve_last_payment(card)
        reference_date = last_payment or contract_end

        if reference_date and period_start <= reference_date:
            issues.append(ZoneIssue(
                field="debt.period.start",
                reason=(
                    f"Начало периода ({period_start}) "
                    f"не позже даты окончания договора/последнего платежа "
                    f"({reference_date})"
                ),
                expected=(reference_date + timedelta(days=1)).isoformat(),
                found=period_start.isoformat(),
                meta={"severity": "fail"},
            ))

        # 3. card.period_end ≤ filing_date (если оба заданы)
        card_period_end_str = card.get("period_end")
        if card_period_end_str and filing_date:
            try:
                card_period_end = date.fromisoformat(card_period_end_str)
                if card_period_end > filing_date:
                    issues.append(ZoneIssue(
                        field="period.end",
                        reason=(
                            f"Период задолженности в карточке ({card_period_end}) "
                            f"позже даты подачи ({filing_date})"
                        ),
                        expected=filing_date.isoformat(),
                        found=card_period_end.isoformat(),
                        meta={"severity": "fail"},
                    ))
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _resolve_filing_date(card: dict) -> Optional[date]:
        """Дата подачи заявления."""
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
        """Дата последнего платежа."""
        payments = card.get("payments", [])
        if not payments:
            return None
        try:
            dates = [date.fromisoformat(p["date"]) for p in payments]
            return max(dates)
        except (ValueError, KeyError, TypeError):
            return None
