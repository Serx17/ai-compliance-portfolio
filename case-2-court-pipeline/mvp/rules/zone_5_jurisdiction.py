"""
Зона 5: Подсудность.

Нормы:
- Ст. 123 ГПК РФ — заявление о вынесении судебного приказа подаётся
  по общим правилам подсудности.
- Ст. 28 ГПК РФ — иск предъявляется по месту жительства ответчика
  (для организации — по месту нахождения).
- П. 1 ч. 1 ст. 23 ГПК РФ — судебный приказ выдаёт мировой судья.

Что проверяем:
- Суд в документе соответствует месту жительства должника.
- Судебный участок определён корректно.
- Если в карточке есть договорная подсудность — она соблюдена.

Как проверяем:
- Из карточки берём адрес должника.
- Определяем ожидаемый судебный участок по справочнику.
- Сравниваем с судом в документе.

Справочник:
- В MVP — упрощённый: сопоставление региона/города.
- В production — интеграция с ГАС «Правосудие» или ФИАС.

Статусы:
- PASS: суд соответствует месту жительства.
- WARNING: невозможно однозначно определить (нет данных).
- FAIL: суд не соответствует месту жительства.
"""

import re
from typing import List, Optional, Tuple

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


# Упрощённый справочник: регион → код субъекта
# В MVP — для демонстрации логики. В production — полная база судебных участков.
REGION_KEYWORDS = {
    "москва": "77",
    "санкт-петербург": "78",
    "самара": "63",
    "самарская": "63",
    "казань": "16",
    "татарстан": "16",
    "новосибирск": "54",
    "екатеринбург": "66",
    "свердловская": "66",
    "ростов": "61",
    "ростовская": "61",
    "краснодар": "23",
    "краснодарский": "23",
}


class Zone5Jurisdiction(ZoneChecker):
    """Зона 5: проверка подсудности."""

    zone_number = 5
    zone_name = "Подсудность"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка подсудности.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Извлекаем данные
        respondent = card.get("respondent", {})
        respondent_address = respondent.get("address")
        document = card.get("document", {})
        document_court = document.get("court")

        if not respondent_address:
            issues.append(ZoneIssue(
                field="respondent.address",
                reason="Отсутствует адрес должника — невозможно определить подсудность",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"error": "no_address"},
            )

        if not document_court:
            issues.append(ZoneIssue(
                field="document.court",
                reason="В документе не указан суд",
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"error": "no_court"},
            )

        # 2. Извлекаем регион из адреса должника
        respondent_region = self._extract_region(respondent_address)

        # 3. Извлекаем регион из названия суда
        court_region = self._extract_region(document_court)

        # 4. Проверка соответствия
        if respondent_region and court_region:
            if respondent_region != court_region:
                issues.append(ZoneIssue(
                    field="document.court",
                    reason=(
                        f"Суд в документе («{document_court}») "
                        f"не соответствует месту жительства должника "
                        f"(«{respondent_address}»). "
                        f"Нарушение ст. 28 ГПК РФ."
                    ),
                    expected=f"Суд региона {respondent_region}",
                    found=f"Суд региона {court_region}",
                    meta={
                        "severity": "fail",
                        "respondent_region": respondent_region,
                        "court_region": court_region,
                    },
                ))
        elif not respondent_region or not court_region:
            issues.append(ZoneIssue(
                field="document.court",
                reason=(
                    f"Невозможно однозначно определить регион: "
                    f"адрес должника — {respondent_address}, "
                    f"суд — {document_court}. Требуется ручная проверка."
                ),
                meta={
                    "severity": "warning",
                    "respondent_region": respondent_region,
                    "court_region": court_region,
                },
            ))

        # 5. Проверка: упомянут ли мировой судья (для приказа)
        if document_court and "миров" not in document_court.lower():
            issues.append(ZoneIssue(
                field="document.court",
                reason=(
                    f"Судебный приказ выдаёт мировой судья "
                    f"(п. 1 ч. 1 ст. 23 ГПК РФ). "
                    f"В документе указан: «{document_court}»"
                ),
                found=document_court,
                meta={"severity": "warning"},
            ))

        # 6. Проверка: договорная подсудность
        contract = card.get("contract", {})
        contractual_court = contract.get("jurisdiction")
        if contractual_court and document_court:
            if self._normalize(contractual_court) != self._normalize(document_court):
                issues.append(ZoneIssue(
                    field="document.court",
                    reason=(
                        f"Договорная подсудность («{contractual_court}») "
                        f"не совпадает с судом в документе («{document_court}»)"
                    ),
                    expected=contractual_court,
                    found=document_court,
                    meta={"severity": "fail"},
                ))

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "respondent_address": respondent_address,
                "document_court": document_court,
                "respondent_region": respondent_region,
                "court_region": court_region,
                "has_contractual_jurisdiction": bool(contractual_court),
            },
        )

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _extract_region(self, address: str) -> Optional[str]:
        """
        Извлечение региона из адреса.

        Ищем ключевые слова (регионы) в нормализованной строке.
        Возвращаем код региона (ОКТМО-подобный) или None.
        """
        if not address:
            return None

        normalized = self._normalize(address)
        for keyword, code in REGION_KEYWORDS.items():
            if keyword in normalized:
                return code
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        """Нормализация строки: lowercase, strip, множественные пробелы → один."""
        if not value:
            return ""
        return re.sub(r"\s+", " ", value.lower().strip())
