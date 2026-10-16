"""
Зона 7: ПДн третьих лиц.

Норма: 152-ФЗ (обработка персональных данных).
Практика: ВС РФ, Определение от 07.06.2016 № 5-КГ16-74.

Прямого запрета упоминания третьих лиц в судебном приказе НЕТ.
Ключевой критерий — СОРАЗМЕРНОСТЬ:
1. Связь с предметом спора (сторона по договору?).
2. Объём раскрытия ПДн (не избыточно ли для цели судопроизводства?).

Что проверяем:
- Упоминания третьих лиц в тексте документа (LLM).
- Связь каждого лица с предметом спора (код, по карточке).
- Объём раскрытых ПДн (код, по списку полей).

Как проверяем (гибридно):
- LLM извлекает упоминания третьих лиц (см. n8n-workflow).
  В этом модуле — принимаем уже извлечённые данные.
- Код проверяет is_party (сторона по договору).
- Код оценивает disclosed_fields (список полей).

Три статуса:
- PASS: связь есть, объём соразмерен.
- WARNING: связь есть, объём избыточен.
- FAIL: связи нет (лицо не связано с обязательством).

Поля ПДн:
- Соразмерно: ФИО, роль.
- Избыточно: адрес, телефон, место работы, паспортные данные.
"""

from typing import List

from .base import ZoneChecker, ZoneIssue, ZoneResult, ZoneStatus


# Поля ПДн: соразмерные vs избыточные
PROPORTIONATE_FIELDS = {"fio", "role", "name"}
DISPROPORTIONATE_FIELDS = {
    "address",
    "phone",
    "workplace",
    "passport",
    "birth_date",
    "inn",
}


class Zone7PdCompliance(ZoneChecker):
    """Зона 7: проверка ПДн третьих лиц на соразмерность."""

    zone_number = 7
    zone_name = "ПДн третьих лиц"

    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка ПДн третьих лиц.

        Args:
            card: карточка должника.
            preprocessed: результат препроцессора.

        Returns:
            ZoneResult со статусом PASS/WARNING/FAIL.
        """
        issues: List[ZoneIssue] = []

        # 1. Извлекаем третьих лиц из карточки
        # (в реальности — извлекаются LLM-ом и передаются в card.third_parties)
        third_parties = card.get("third_parties", [])

        if not third_parties:
            return self._make_result(
                status=ZoneStatus.PASS,
                issues=issues,
                metadata={
                    "third_parties_count": 0,
                    "message": "Третьи лица не упоминаются",
                },
            )

        # 2. Список сторон по договору (для проверки связи)
        parties = self._resolve_parties(card)

        # 3. Проверка каждого третьего лица
        for idx, person in enumerate(third_parties):
            person_issues = self._check_person(person, parties, idx)
            issues.extend(person_issues)

        status = self._resolve_status(issues)

        return self._make_result(
            status=status,
            issues=issues,
            metadata={
                "third_parties_count": len(third_parties),
                "parties_count": len(parties),
                "has_fail": any(
                    i.meta.get("severity") == "fail" for i in issues
                ),
                "has_warning": any(
                    i.meta.get("severity") == "warning" for i in issues
                ),
            },
        )

    # ------------------------------------------------------------------ #
    # Проверка одного лица                                                #
    # ------------------------------------------------------------------ #

    def _check_person(
        self,
        person: dict,
        parties: List[str],
        idx: int,
    ) -> List[ZoneIssue]:
        """
        Проверка одного третьего лица.

        Args:
            person: словарь с данными лица:
                - name: ФИО
                - role: роль (поручитель, цессионарий, агент, родственник)
                - disclosed_fields: список раскрытых полей ПДн
            parties: список сторон по договору (нормализованные ФИО/наименования).
            idx: индекс в списке (для field-метки).

        Returns:
            Список ZoneIssue.
        """
        issues: List[ZoneIssue] = []

        name = person.get("name", f"unknown_{idx}")
        role = person.get("role", "")
        disclosed = person.get("disclosed_fields", [])

        # 1. Проверка: является ли лицо стороной по договору
        is_party = self._is_party(person, parties)

        if not is_party:
            issues.append(ZoneIssue(
                field=f"third_parties[{idx}]",
                reason=(
                    f"Третье лицо «{name}» ({role or 'роль не указана'}) "
                    f"не связано с предметом спора. "
                    f"Упоминание необоснованно."
                ),
                found=name,
                meta={
                    "severity": "fail",
                    "person": name,
                    "role": role,
                    "is_party": False,
                },
            ))
            # Для fail не проверяем объём — сначала связь
            return issues

        # 2. Проверка: соразмерность объёма раскрытия
        disproportionate = [
            f for f in disclosed if f.lower() in DISPROPORTIONATE_FIELDS
        ]

        if disproportionate:
            issues.append(ZoneIssue(
                field=f"third_parties[{idx}].disclosed_fields",
                reason=(
                    f"Третье лицо «{name}» ({role}) — сторона по договору, "
                    f"но объём раскрытия ПДн избыточен: "
                    f"{', '.join(disproportionate)}. "
                    f"Рекомендуется ограничить ФИО и ролью."
                ),
                found=disproportionate,
                meta={
                    "severity": "warning",
                    "person": name,
                    "role": role,
                    "is_party": True,
                    "disproportionate_fields": disproportionate,
                    "all_disclosed_fields": disclosed,
                },
            ))
        else:
            # 3. Всё соразмерно — фиксируем как pass-issue (для аудита)
            issues.append(ZoneIssue(
                field=f"third_parties[{idx}]",
                reason=(
                    f"Третье лицо «{name}» ({role}) — сторона по договору, "
                    f"объём раскрытия соразмерен."
                ),
                found=name,
                meta={
                    "severity": "pass",
                    "person": name,
                    "role": role,
                    "is_party": True,
                },
            ))

        return issues

    # ------------------------------------------------------------------ #
    # Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _resolve_parties(self, card: dict) -> List[str]:
        """
        Список сторон по договору (для проверки связи).

        Включает:
        - Заёмщик (должник).
        - Поручители.
        - Цессионарии.
        - Агенты при выдаче.
        """
        parties: List[str] = []

        # Должник
        respondent = card.get("respondent", {})
        if respondent.get("fio"):
            parties.append(self._normalize(respondent["fio"]))

        # Явные стороны из карточки
        contract_parties = card.get("contract_parties", [])
        for p in contract_parties:
            if isinstance(p, dict):
                name = p.get("name") or p.get("fio")
                if name:
                    parties.append(self._normalize(name))
            elif isinstance(p, str):
                parties.append(self._normalize(p))

        return parties

    def _is_party(self, person: dict, parties: List[str]) -> bool:
        """
        Является ли лицо стороной по договору.

        Проверка:
        1. Явный флаг is_party в данных лица.
        2. Совпадение имени с одной из сторон.
        3. Роль из списка сторон (поручитель, цессионарий, агент).
        """
        # Явный флаг
        if person.get("is_party") is True:
            return True
        if person.get("is_party") is False:
            return False

        # По имени
        person_name = self._normalize(person.get("name", ""))
        if person_name and any(
            person_name in party or party in person_name
            for party in parties
        ):
            return True

        # По роли
        role = self._normalize(person.get("role", ""))
        party_roles = {"поручитель", "цессионарий", "агент", "созаёмщик"}
        if role in party_roles:
            return True

        return False

    @staticmethod
    def _normalize(value: str) -> str:
        """Нормализация строки."""
        if not value:
            return ""
        import re
        return re.sub(r"\s+", " ", value.lower().strip())
