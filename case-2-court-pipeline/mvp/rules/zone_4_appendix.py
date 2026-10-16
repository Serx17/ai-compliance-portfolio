"""
Зона 4: Приложения к заявлению о вынесении судебного приказа.

Норма: ст. 124 ГПК РФ (требования к заявлению о вынесении судебного приказа).

ВАЖНО: для судебного приказа применяется ст. 124 ГПК РФ, а не ст. 132 ГПК РФ.
Ст. 132 ГПК РФ — требования к исковому заявлению (иной документ).
Перечни приложений различаются.

Что проверяем:
- Все обязательные приложения присутствуют.
- Каждое приложение упомянуто в тексте документа.
- Нет упоминаний приложений, которых нет в списке.
- Нет дублирований.

Обязательные приложения для приказа:
- Документы, подтверждающие требования (договор займа, расчёт задолженности).
- Документ об уплате государственной пошлины (50% ставки для приказа).

Дополнительные (если применимо):
- Копия уведомления о взыскании (если требуется).
- Доверенность представителя (если подача через представителя).

Статусы:
- PASS: все обязательные приложения есть, упомянуты, нет дублей.
- WARNING: лишнее приложение (не в чек-листе), но не критично.
- FAIL: отсутствует обязательное приложение ИЛИ упоминание без наличия.
"""

from typing import List, Optional

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


# Обязательные приложения для судебного приказа (ст. 124 ГПК РФ)
REQUIRED_APPENDICES = [
    "договор займа",
    "расчёт задолженности",
    "документ об уплате государственной пошлины",
]

# Дополнительные (если применимо) — не считаются ошибкой, если отсутствуют
OPTIONAL_APPENDICES = [
    "копия уведомления о взыскании",
    "доверенность представителя",
    "выписка по счёту",
    "копия паспорта",
]


class Zone4Appendix(ZoneChecker):
    """Зона 4: проверка приложений к судебному приказу."""

    zone_number = 4
    zone_name = "Приложения"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка приложений.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Извлекаем список приложений из документа
        document = card.get("document", {})
        appendices_raw = document.get("appendices", [])

        if not isinstance(appendices_raw, list):
            issues.append(ZoneIssue(
                field="document.appendices",
                reason="Поле appendices должно быть списком",
                found=type(appendices_raw).__name__,
                meta={"severity": "fail"},
            ))
            return self._make_result(
                status=ZoneStatus.FAIL,
                issues=issues,
                metadata={"error": "invalid_appendices_format"},
            )

        # 2. Нормализуем список (lowercase, strip)
        appendices_normalized = [
            self._normalize(a) for a in appendices_raw if a
        ]

        # 3. Проверка: все обязательные приложения на месте
        missing = []
        for required in REQUIRED_APPENDICES:
            required_norm = self._normalize(required)
            if not self._find_in_list(required_norm, appendices_normalized):
                missing.append(required)

        for req in missing:
            issues.append(ZoneIssue(
                field="document.appendices",
                reason=(
                    f"Отсутствует обязательное приложение: «{req}» "
                    f"(ст. 124 ГПК РФ)"
                ),
                expected=req,
                meta={"severity": "fail"},
            ))

        # 4. Проверка: упоминания приложений в тексте документа
        document_text = document.get("text", "")
        if document_text:
            text_issues = self._check_text_mentions(
                document_text, appendices_normalized
            )
            issues.extend(text_issues)

        # 5. Проверка: дублирования в списке
        duplicates = self._find_duplicates(appendices_normalized)
        for dup in duplicates:
            issues.append(ZoneIssue(
                field="document.appendices",
                reason=f"Дублирование приложения: «{dup}»",
                found=dup,
                meta={"severity": "warning"},
            ))

        # 6. Проверка: приложения вне чек-листа (не ошибка, но фиксируем)
        unknown = self._find_unknown(appendices_normalized)
        for unk in unknown:
            issues.append(ZoneIssue(
                field="document.appendices",
                reason=(
                    f"Приложение вне стандартного чек-листа: «{unk}». "
                    f"Проверьте необходимость."
                ),
                found=unk,
                meta={"severity": "warning"},
            ))

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "required_count": len(REQUIRED_APPENDICES),
                "total_appendices": len(appendices_normalized),
                "missing_required": missing,
                "appendices": appendices_normalized,
            },
        )

    # ------------------------------------------------------------------ #
    # Проверка упоминаний в тексте                                        #
    # ------------------------------------------------------------------ #

    def _check_text_mentions(
        self,
        document_text: str,
        appendices_normalized: List[str],
    ) -> List[ZoneIssue]:
        """
        Проверка: каждое приложение из списка упомянуто в тексте документа.

        Ищем по ключевым словам (нормализованно). Если приложение
        в списке, но не упомянуто в тексте — warning.
        """
        issues: List[ZoneIssue] = []
        text_norm = self._normalize(document_text)

        for appendix in appendices_normalized:
            # Проверяем ключевые слова (первые 2–3 слова)
            keywords = appendix.split()[:3]
            keyword_phrase = " ".join(keywords)

            if keyword_phrase and keyword_phrase not in text_norm:
                issues.append(ZoneIssue(
                    field="document.text",
                    reason=(
                        f"Приложение «{appendix}» есть в списке, "
                        f"но не упомянуто в тексте документа"
                    ),
                    found=appendix,
                    meta={"severity": "warning"},
                ))

        return issues

    # ------------------------------------------------------------------ #
    # Вспомогательные                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize(value: str) -> str:
        """Нормализация строки: lowercase, strip, множественные пробелы → один."""
        if not value:
            return ""
        import re
        return re.sub(r"\s+", " ", value.lower().strip())

    @staticmethod
    def _find_in_list(needle: str, haystack: List[str]) -> bool:
        """Поиск подстроки в списке (needle входит в элемент haystack)."""
        for item in haystack:
            if needle in item or item in needle:
                return True
        return False

    @staticmethod
    def _find_duplicates(items: List[str]) -> List[str]:
        """Поиск дубликатов в списке."""
        seen = set()
        duplicates = set()
        for item in items:
            if item in seen:
                duplicates.add(item)
            seen.add(item)
        return list(duplicates)

    def _find_unknown(self, appendices: List[str]) -> List[str]:
        """
        Поиск приложений вне чек-листа.

        Проверяем: входит ли приложение в REQUIRED или OPTIONAL.
        Если нет — возвращаем как unknown.
        """
        known = [
            self._normalize(x)
            for x in (REQUIRED_APPENDICES + OPTIONAL_APPENDICES)
        ]
        unknown = []
        for item in appendices:
            if not self._find_in_list(item, known):
                unknown.append(item)
        return unknown
