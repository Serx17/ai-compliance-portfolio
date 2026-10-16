"""
Зона 1: Реквизиты сторон.

Норма: ст. 124 ГПК РФ (требования к судебному приказу).

Что проверяем:
- Наличие обязательных полей у истца и ответчика.
- Совпадение реквизитов в документе с исходной карточкой.
- Валидность ИНН/ОГРН (через препроцессор).

Как проверяем:
- Все обязательные поля — из карточки.
- Валидация ИНН/ОГРН уже выполнена в препроцессоре — здесь
  проверяем, что в preprocessed.requisites нет validation issues.
- Если в документе указаны реквизиты, отличные от карточки,
  фиксируем FAIL.

Обязательные поля:
- Истец: наименование, ИНН, ОГРН.
- Ответчик: ФИО, дата рождения, адрес.

Возможные статусы:
- PASS: все поля на месте, ИНН/ОГРН валидны, нет расхождений.
- FAIL: отсутствует обязательное поле ИЛИ реквизиты не совпадают
  ИЛИ ИНН/ОГРН невалидны.
"""

from typing import List

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


# Обязательные поля
REQUIRED_CREDITOR_FIELDS = ["name", "inn", "ogrn"]
REQUIRED_RESPONDENT_FIELDS = ["fio", "birth_date", "address"]


class Zone1Requisites(ZoneChecker):
    """Зона 1: проверка реквизитов сторон."""

    zone_number = 1
    zone_name = "Реквизиты сторон"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка реквизитов.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Обязательные поля ответчика
        respondent = card.get("respondent", {})
        for field_name in REQUIRED_RESPONDENT_FIELDS:
            if not respondent.get(field_name):
                issues.append(ZoneIssue(
                    field=f"respondent.{field_name}",
                    reason=f"Отсутствует обязательное поле ответчика: {field_name}",
                    meta={"severity": "fail"},
                ))

        # 2. Обязательные поля истца
        creditor = card.get("creditor", {})
        for field_name in REQUIRED_CREDITOR_FIELDS:
            if not creditor.get(field_name):
                issues.append(ZoneIssue(
                    field=f"creditor.{field_name}",
                    reason=f"Отсутствует обязательное поле истца: {field_name}",
                    meta={"severity": "fail"},
                ))

        # 3. Ошибки валидации ИНН/ОГРН из препроцессора
        validation_issues = preprocessed.get("requisites", {}).get("validation", [])
        for v_issue in validation_issues:
            issues.append(ZoneIssue(
                field=f"{v_issue.get('party', 'unknown')}.{v_issue.get('field', 'unknown')}",
                reason=v_issue.get("reason", "Ошибка валидации реквизита"),
                found=v_issue.get("value"),
                meta={"severity": "fail", "source": "preprocessor"},
            ))

        # 4. Расхождение реквизитов документа с карточкой
        # (если документ содержит свои реквизиты — сверяем)
        document_requisites = card.get("document_requisites")
        if document_requisites:
            doc_issues = self._compare_requisites(card, document_requisites)
            issues.extend(doc_issues)

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "required_creditor_fields": REQUIRED_CREDITOR_FIELDS,
                "required_respondent_fields": REQUIRED_RESPONDENT_FIELDS,
                "validation_issues_from_preprocessor": len(validation_issues),
            },
        )

    def _compare_requisites(self, card: dict, document_requisites: dict) -> List[ZoneIssue]:
        """
        Сверка реквизитов из документа с карточкой.

        Проверяем ключевые поля: наименование истца, ФИО ответчика,
        ИНН, ОГРН. Если в документе указано иное — FAIL.
        """
        issues: List[ZoneIssue] = []

        # Истец
        doc_creditor = document_requisites.get("creditor", {})
        card_creditor = card.get("creditor", {})

        for field_name in ["name", "inn", "ogrn"]:
            doc_value = doc_creditor.get(field_name)
            card_value = card_creditor.get(field_name)
            if doc_value and card_value and doc_value != card_value:
                issues.append(ZoneIssue(
                    field=f"document.creditor.{field_name}",
                    reason=(
                        f"Реквизит истца «{field_name}» в документе "
                        f"не совпадает с карточкой"
                    ),
                    expected=card_value,
                    found=doc_value,
                    meta={"severity": "fail"},
                ))

        # Ответчик
        doc_respondent = document_requisites.get("respondent", {})
        card_respondent = card.get("respondent", {})

        for field_name in ["fio", "birth_date", "address", "inn"]:
            doc_value = doc_respondent.get(field_name)
            card_value = card_respondent.get(field_name)
            if doc_value and card_value and doc_value != card_value:
                issues.append(ZoneIssue(
                    field=f"document.respondent.{field_name}",
                    reason=(
                        f"Реквизит ответчика «{field_name}» в документе "
                        f"не совпадает с карточкой"
                    ),
                    expected=card_value,
                    found=doc_value,
                    meta={"severity": "fail"},
                ))

        return issues
