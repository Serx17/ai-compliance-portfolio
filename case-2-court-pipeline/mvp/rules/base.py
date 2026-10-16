"""
Базовый класс для всех 7 зон контроля.

Определяет контракт: каждая зона получает данные и возвращает ZoneResult.

Принципы:
- Детерминированность: одна зона — одна логика.
- Типизация: строгие типы на входе и выходе.
- Расширяемость: новая зона — наследник ZoneChecker.
- Объяснимость: каждое срабатывание содержит причину.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class ZoneStatus(str, Enum):
    """Статус проверки зоны."""

    PASS = "pass"          # Всё в порядке
    WARNING = "warning"    # Не критично, но требует внимания
    FAIL = "fail"          # Критичная ошибка, документ нельзя подавать


@dataclass
class ZoneIssue:
    """
    Одно нарушение, найденное зоной.

    Attributes:
        field: Поле документа, где найдено нарушение (например, "claim_amount").
        reason: Человекочитаемое объяснение.
        expected: Ожидаемое значение (опционально).
        found: Найденное значение (опционально).
        meta: Дополнительные данные (для аудита).
    """

    field: str
    reason: str
    expected: Optional[Any] = None
    found: Optional[Any] = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Сериализация в JSON-совместимый dict."""
        result = {
            "field": self.field,
            "reason": self.reason,
        }
        if self.expected is not None:
            result["expected"] = self.expected
        if self.found is not None:
            result["found"] = self.found
        if self.meta:
            result["meta"] = self.meta
        return result


@dataclass
class ZoneResult:
    """
    Результат проверки одной зоны.

    Attributes:
        zone: Номер зоны (1–7).
        zone_name: Название зоны (для отчёта).
        status: PASS / WARNING / FAIL.
        issues: Список найденных нарушений.
        metadata: Дополнительные данные зоны (например, использованная ставка).
    """

    zone: int
    zone_name: str
    status: ZoneStatus
    issues: List[ZoneIssue] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Сериализация в JSON-совместимый dict."""
        return {
            "zone": self.zone,
            "zone_name": self.zone_name,
            "status": self.status.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "metadata": self.metadata,
        }

    @property
    def is_critical(self) -> bool:
        """Является ли результат критичным (требует HITL)."""
        return self.status == ZoneStatus.FAIL


class ZoneChecker(ABC):
    """
    Базовый класс для зоны контроля.

    Каждая зона наследуется от ZoneChecker и реализует метод check().

    Пример:
        class Zone1Requisites(ZoneChecker):
            zone_number = 1
            zone_name = "Реквизиты сторон"

            def check(self, card, preprocessed):
                issues = [...]
                status = ZoneStatus.FAIL if issues else ZoneStatus.PASS
                return ZoneResult(
                    zone=self.zone_number,
                    zone_name=self.zone_name,
                    status=status,
                    issues=issues,
                )
    """

    # Атрибуты класса — переопределяются в наследниках
    zone_number: int = 0
    zone_name: str = ""

    @abstractmethod
    def check(self, card: dict, preprocessed: dict) -> ZoneResult:
        """
        Проверка документа по правилам зоны.

        Args:
            card: исходная карточка должника (dict).
            preprocessed: результат препроцессора (dict) — содержит
                рассчитанные суммы, реквизиты, проверку исковой давности.

        Returns:
            ZoneResult с статусом и списком нарушений.
        """
        raise NotImplementedError

    def _make_result(
        self,
        status: ZoneStatus,
        issues: Optional[List[ZoneIssue]] = None,
        metadata: Optional[dict] = None,
    ) -> ZoneResult:
        """
        Хелпер для создания ZoneResult с автоматическим заполнением
        номера зоны и названия.
        """
        return ZoneResult(
            zone=self.zone_number,
            zone_name=self.zone_name,
            status=status,
            issues=issues or [],
            metadata=metadata or {},
        )

    def _resolve_status(self, issues: List[ZoneIssue]) -> ZoneStatus:
        """
        Определение статуса по списку нарушений.

        Логика:
        - нет issues → PASS
        - все issues со severity='pass' → PASS (для аудита)
        - есть issues с severity='fail' → FAIL
        - иначе (только warning) → WARNING

        Зоны могут переопределить это поведение.
        """
        if not issues:
            return ZoneStatus.PASS

        severities = [
            issue.meta.get("severity", "fail")
            for issue in issues
        ]

        if "fail" in severities:
            return ZoneStatus.FAIL

        # Если есть хоть один warning — WARNING
        if "warning" in severities:
            return ZoneStatus.WARNING

        # Все issues со severity='pass' → PASS
        return ZoneStatus.PASS
