"""
Runner: запуск всех 7 зон контроля.

Единая точка входа для проверки документа.

Принципы:
- Все 7 зон запускаются последовательно.
- Если одна зона падает с ошибкой — остальные всё равно выполняются.
- Итоговый отчёт содержит: статус по каждой зоне, сводку, признак HITL.
- Логирование — структурированное, с уровнями INFO/WARNING/ERROR.

Использование:
    from rules.runner import RulesRunner

    runner = RulesRunner()
    report = runner.run(card=card_dict, preprocessed=preprocessed_dict)

    if report["summary"]["requires_hitl"]:
        # отправить на HITL
        ...
"""

import logging
import traceback
from dataclasses import dataclass, field
from typing import List, Optional

from .base import ZoneChecker, ZoneResult, ZoneStatus
from .zone_1_requisites import Zone1Requisites
from .zone_2_amount import Zone2Amount
from .zone_3_period import Zone3Period
from .zone_4_appendix import Zone4Appendix
from .zone_5_jurisdiction import Zone5Jurisdiction
from .zone_6_limitation import Zone6Limitation
from .zone_7_pd_compliance import Zone7PdCompliance


logger = logging.getLogger(__name__)


# Регистрация зон — порядок важен для отчёта
DEFAULT_ZONES: List[type] = [
    Zone1Requisites,
    Zone2Amount,
    Zone3Period,
    Zone4Appendix,
    Zone5Jurisdiction,
    Zone6Limitation,
    Zone7PdCompliance,
]


@dataclass
class ReportSummary:
    """Сводка по всем зонам."""

    total_zones: int = 0
    passed: int = 0
    warnings: int = 0
    failed: int = 0
    critical_issues: int = 0
    requires_hitl: bool = False

    def to_dict(self) -> dict:
        return {
            "total_zones": self.total_zones,
            "passed": self.passed,
            "warnings": self.warnings,
            "failed": self.failed,
            "critical_issues": self.critical_issues,
            "requires_hitl": self.requires_hitl,
        }


class RulesRunner:
    """
    Запуск всех 7 зон контроля для одного документа.

    Attributes:
        zones: список классов зон (по умолчанию — все 7).
        hitl_threshold: порог critical_issues для HITL (по умолчанию 0 — любой FAIL).
    """

    def __init__(
        self,
        zones: Optional[List[type]] = None,
        hitl_threshold: int = 0,
    ):
        """
        Args:
            zones: список классов-наследников ZoneChecker.
                По умолчанию — DEFAULT_ZONES (7 зон).
            hitl_threshold: минимальное число критичных issues,
                при котором документ требует HITL. По умолчанию 0 —
                любой FAIL требует проверки.
        """
        self.zones = zones or DEFAULT_ZONES
        self.hitl_threshold = hitl_threshold

    def run(self, card: dict, preprocessed: dict) -> dict:
        """
        Запуск всех зон контроля.

        Args:
            card: исходная карточка должника (dict).
            preprocessed: результат препроцессора (dict).

        Returns:
            dict — итоговый отчёт:
            {
                "case_id": "...",
                "zones": [ {zone, zone_name, status, issues}, ... ],
                "summary": {
                    "total_zones": 7,
                    "passed": 3,
                    "warnings": 1,
                    "failed": 3,
                    "critical_issues": 3,
                    "requires_hitl": true
                }
            }
        """
        case_id = card.get("case_id", "unknown")
        logger.info("Runner started for case_id=%s", case_id)

        results: List[ZoneResult] = []

        for zone_cls in self.zones:
            zone_instance: ZoneChecker = zone_cls()
            zone_num = zone_instance.zone_number
            zone_name = zone_instance.zone_name

            try:
                logger.info("Zone %d (%s) — checking...", zone_num, zone_name)
                result = zone_instance.check(card, preprocessed)
                results.append(result)
                self._log_zone_result(result)

            except Exception as e:
                # Зона упала — не роняем весь конвейер.
                # Возвращаем FAIL с описанием ошибки.
                logger.error(
                    "Zone %d (%s) — FAILED with exception: %s",
                    zone_num,
                    zone_name,
                    e,
                    exc_info=True,
                )
                results.append(ZoneResult(
                    zone=zone_num,
                    zone_name=zone_name,
                    status=ZoneStatus.FAIL,
                    issues=[{
                        "field": "internal_error",
                        "reason": f"Зона упала с ошибкой: {e}",
                        "meta": {
                            "traceback": traceback.format_exc(),
                        },
                    }],
                    metadata={"error": str(e)},
                ))

        summary = self._build_summary(results)

        logger.info(
            "Runner finished: case_id=%s, passed=%d, warnings=%d, failed=%d, "
            "requires_hitl=%s",
            case_id,
            summary.passed,
            summary.warnings,
            summary.failed,
            summary.requires_hitl,
        )

        return {
            "case_id": case_id,
            "zones": [r.to_dict() for r in results],
            "summary": summary.to_dict(),
        }

    def _log_zone_result(self, result: ZoneResult) -> None:
        """Логирование результата одной зоны."""
        status = result.status.value
        count = len(result.issues)

        if result.status == ZoneStatus.PASS:
            logger.info(
                "Zone %d (%s) — PASS",
                result.zone,
                result.zone_name,
            )
        elif result.status == ZoneStatus.WARNING:
            logger.warning(
                "Zone %d (%s) — WARNING (%d issues)",
                result.zone,
                result.zone_name,
                count,
            )
        else:
            logger.error(
                "Zone %d (%s) — FAIL (%d issues)",
                result.zone,
                result.zone_name,
                count,
            )

    def _build_summary(self, results: List[ZoneResult]) -> ReportSummary:
        """
        Построение сводки по результатам всех зон.

        Логика:
        - passed / warnings / failed — счётчики по статусам зон.
        - critical_issues — суммарное число зон со статусом FAIL.
        - requires_hitl — True, если critical_issues > hitl_threshold.
        """
        summary = ReportSummary(total_zones=len(results))

        for r in results:
            if r.status == ZoneStatus.PASS:
                summary.passed += 1
            elif r.status == ZoneStatus.WARNING:
                summary.warnings += 1
            elif r.status == ZoneStatus.FAIL:
                summary.failed += 1

        # Критичные issues = зоны со статусом FAIL
        summary.critical_issues = summary.failed
        summary.requires_hitl = summary.critical_issues > self.hitl_threshold

        return summary


def run_rules(card: dict, preprocessed: dict) -> dict:
    """
    Удобная функция-обёртка для запуска всех зон.

    Использование:
        from rules.runner import run_rules
        report = run_rules(card, preprocessed)
    """
    return RulesRunner().run(card, preprocessed)
