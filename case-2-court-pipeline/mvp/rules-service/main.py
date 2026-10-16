"""
rules-service: FastAPI-обёртка над препроцессором и 7 зонами контроля.

Endpoints:
- GET  /health       — проверка живости сервиса.
- POST /preprocess   — препроцессор: расчёты, реквизиты, давность.
- POST /check        — препроцессор + 7 зон → итоговый отчёт.

Запуск:
    uvicorn rules-service.main:app --host 0.0.0.0 --port 8001

Или через docker-compose (сервис rules-service).
"""

import logging
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Импорт препроцессора и runner'а
import sys
from pathlib import Path

# Добавляем корень mvp/ в sys.path, чтобы импортировать preprocessor и rules
MVP_ROOT = Path(__file__).resolve().parent.parent
if str(MVP_ROOT) not in sys.path:
    sys.path.insert(0, str(MVP_ROOT))

from preprocessor.pipeline import Preprocessor  # noqa: E402
from rules.runner import RulesRunner  # noqa: E402


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


app = FastAPI(
    title="Court Rules Service",
    description="Препроцессор + 7 зон контроля для Кейса №2",
    version="0.1.0",
)


# ---------------------------------------------------------------- #
# Модели запросов и ответов                                         #
# ---------------------------------------------------------------- #

class CardRequest(BaseModel):
    """Запрос с карточкой должника."""
    card: dict = Field(..., description="Карточка должника (JSON)")
    calculation_date: Optional[str] = Field(
        None,
        description="Дата расчёта в формате YYYY-MM-DD (по умолчанию — сегодня)",
    )


class PreprocessResponse(BaseModel):
    """Ответ препроцессора."""
    case_id: str
    preprocessed: dict


class CheckResponse(BaseModel):
    """Ответ проверки (препроцессор + 7 зон)."""
    case_id: str
    report: dict


class HealthResponse(BaseModel):
    """Ответ /health."""
    status: str
    service: str
    version: str


# ---------------------------------------------------------------- #
# Endpoints                                                         #
# ---------------------------------------------------------------- #

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Проверка живости сервиса."""
    return HealthResponse(
        status="ok",
        service="rules-service",
        version="0.1.0",
    )


@app.post("/preprocess", response_model=PreprocessResponse)
def preprocess(request: CardRequest) -> PreprocessResponse:
    """
    Запуск только препроцессора.

    Возвращает подготовленные данные без проверки 7 зон.
    """
    card = request.card
    case_id = card.get("case_id", "unknown")
    logger.info("Preprocess request: case_id=%s", case_id)

    try:
        calc_date = (
            date.fromisoformat(request.calculation_date)
            if request.calculation_date
            else None
        )
        preprocessor = Preprocessor(card=card, calculation_date=calc_date)
        result = preprocessor.run()
        logger.info("Preprocess done: case_id=%s", case_id)
        return PreprocessResponse(case_id=case_id, preprocessed=result)

    except Exception as e:
        logger.error("Preprocess failed: case_id=%s error=%s", case_id, e)
        raise HTTPException(status_code=400, detail=f"Препроцессор упал: {e}")


@app.post("/check", response_model=CheckResponse)
def check(request: CardRequest) -> CheckResponse:
    """
    Запуск препроцессора + 7 зон контроля.

    Возвращает итоговый отчёт: результаты по 7 зонам + сводка.
    """
    card = request.card
    case_id = card.get("case_id", "unknown")
    logger.info("Check request: case_id=%s", case_id)

    try:
        # 1. Препроцессор
        calc_date = (
            date.fromisoformat(request.calculation_date)
            if request.calculation_date
            else None
        )
        preprocessor = Preprocessor(card=card, calculation_date=calc_date)
        preprocessed = preprocessor.run()

        # 2. 7 зон
        runner = RulesRunner()
        report = runner.run(card=card, preprocessed=preprocessed)

        logger.info(
            "Check done: case_id=%s, requires_hitl=%s",
            case_id,
            report["summary"]["requires_hitl"],
        )
        return CheckResponse(case_id=case_id, report=report)

    except Exception as e:
        logger.error("Check failed: case_id=%s error=%s", case_id, e)
        raise HTTPException(status_code=400, detail=f"Проверка упала: {e}")
