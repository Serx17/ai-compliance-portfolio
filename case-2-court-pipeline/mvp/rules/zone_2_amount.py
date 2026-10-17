"""
Зона 2: Сумма иска.

Нормы:
- Ст. 122–124 ГПК РФ (требования к судебному приказу).
- 353-ФЗ, ч. 23 ст. 5 — максимальная ставка (0,8% в день).
- 353-ФЗ, ч. 24 ст. 5 — потолок переплаты (100% с 01.04.2026).
- 353-ФЗ, ч. 21 ст. 5 — потолок неустойки (0,1% в день).

Что проверяем:
1. Сумма в документе == расчёт препроцессора (сверка).
2. Расчёт препроцессора не нарушает потолок 353-ФЗ.
3. Арифметика разбивки: основной долг + проценты + неустойка == итого.
4. Сумма прописью (если есть) == сумма цифрами.

Как проверяем:
- Сверка с preprocessed.debt.total.
- Проверка preprocessed.debt.cap_applied (если True — фиксируем warning).
- Парсинг суммы из документа (если есть document.claim_amount).
- Проверка разбивки.

Статусы:
- PASS: всё сходится, потолок не нарушен.
- WARNING: потолок применён (расчёт обрезан) — это норма, но требует
  внимания HITL.
- FAIL: сумма в документе != расчётной, ИЛИ арифметика не сходится,
  ИЛИ ставка превышает максимум.
"""

from typing import List, Optional

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus
from preprocessor.calculator import (
    parse_amount_from_text,
    MAX_OVERPAYMENT_RATIO,
    MAX_DAILY_RATE,
    PENALTY_MAX_DAILY_RATE,
)


# Допуск для сверки сумм (в рублях) — на случай округления
AMOUNT_TOLERANCE = 0.01


class Zone2Amount(ZoneChecker):
    """Зона 2: проверка суммы иска."""

    zone_number = 2
    zone_name = "Сумма иска"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка суммы иска.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        debt = preprocessed.get("debt", {})
        principal = debt.get("principal", 0.0)
        interest = debt.get("interest", 0.0)
        penalty = debt.get("penalty", 0.0)
        total_calculated = debt.get("total", 0.0)
        cap_applied = debt.get("cap_applied", False)

        # 1. Проверка арифметики: principal + interest + penalty == total
        expected_total = round(principal + interest + penalty, 2)
        if abs(expected_total - total_calculated) > AMOUNT_TOLERANCE:
            issues.append(ZoneIssue(
                field="debt.total",
                reason=(
                    f"Арифметика не сходится: "
                    f"{principal} + {interest} + {penalty} = {expected_total}, "
                    f"но total = {total_calculated}"
                ),
                expected=expected_total,
                found=total_calculated,
                meta={"severity": "fail"},
            ))

        # 2. Потолок переплаты 353-ФЗ (информационно)
        if cap_applied:
            raw_interest = debt.get("raw_interest", 0.0)
            raw_penalty = debt.get("raw_penalty", 0.0)
            issues.append(ZoneIssue(
                field="debt.cap_applied",
                reason=(
                    f"Потолок переплаты {int(MAX_OVERPAYMENT_RATIO * 100)}% "
                    f"применён (353-ФЗ, ч. 24 ст. 5). "
                    f"Сырые: проценты {raw_interest} ₽, неустойка {raw_penalty} ₽. "
                    f"После обрезки: проценты {interest} ₽, неустойка {penalty} ₽."
                ),
                meta={
                    "severity": "warning",
                    "cap_ratio": MAX_OVERPAYMENT_RATIO,
                    "raw_interest": raw_interest,
                    "raw_penalty": raw_penalty,
                },
            ))

        # 3. Проверка ставки (если она есть в карточке)
        contract = card.get("contract", {})
        rate = contract.get("rate")
        if rate is not None and rate > MAX_DAILY_RATE:
            issues.append(ZoneIssue(
                field="contract.rate",
                reason=(
                    f"Ставка {rate}% в день превышает максимум "
                    f"{MAX_DAILY_RATE}% (353-ФЗ, ч. 23 ст. 5)"
                ),
                found=rate,
                expected=MAX_DAILY_RATE,
                meta={"severity": "fail"},
            ))

        # 4. Сверка суммы из документа с расчётной (если есть)
        document_amount = self._extract_document_amount(card)
        if document_amount is not None:
            diff = abs(document_amount - total_calculated)
            if diff > AMOUNT_TOLERANCE:
                issues.append(ZoneIssue(
                    field="document.claim_amount",
                    reason=(
                        f"Сумма в документе ({document_amount} ₽) "
                        f"не совпадает с расчётной ({total_calculated} ₽). "
                        f"Разница: {round(diff, 2)} ₽"
                    ),
                    expected=total_calculated,
                    found=document_amount,
                    meta={
                        "severity": "fail",
                        "difference": round(diff, 2),
                        "difference_percent": round(
                            diff / total_calculated * 100, 2
                        ) if total_calculated else 0,
                    },
                ))

        # 5. Проверка суммы прописью (если есть)
        amount_words = card.get("document", {}).get("claim_amount_words")
        if amount_words and document_amount is not None:
            parsed_words = parse_amount_from_text(amount_words)
            if parsed_words is not None and abs(parsed_words - document_amount) > AMOUNT_TOLERANCE:
                issues.append(ZoneIssue(
                    field="document.claim_amount_words",
                    reason=(
                        f"Сумма прописью ({parsed_words} ₽) "
                        f"не совпадает с суммой цифрами ({document_amount} ₽)"
                    ),
                    expected=document_amount,
                    found=parsed_words,
                    meta={"severity": "fail"},
                ))

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "principal": principal,
                "interest": interest,
                "penalty": penalty,
                "total_calculated": total_calculated,
                "document_amount": document_amount,
                "cap_applied": cap_applied,
                "max_overpayment_ratio": MAX_OVERPAYMENT_RATIO,
                "max_daily_rate": MAX_DAILY_RATE,
                "penalty_max_daily_rate": PENALTY_MAX_DAILY_RATE,
            },
        )

    @staticmethod
    def _extract_document_amount(card: dict) -> Optional[float]:
        """
        Извлечение суммы из документа.

        Приоритет:
        1. card.document.claim_amount (число).
        2. card.document.claim_amount_text (строка) — парсинг.
        3. None, если ничего нет.
        """
        document = card.get("document", {})

        amount = document.get("claim_amount")
        if amount is not None:
            try:
                return float(amount)
            except (ValueError, TypeError):
                pass

        amount_text = document.get("claim_amount_text")
        if amount_text:
            return parse_amount_from_text(amount_text)

        return None
