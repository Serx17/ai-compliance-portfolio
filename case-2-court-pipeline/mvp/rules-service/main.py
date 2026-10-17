"""
rules-service: FastAPI-обёртка над препроцессором и 7 зонами контроля.

Endpoints:
- GET  /health       — проверка живости.
- POST /preprocess   — препроцессор: расчёты, реквизиты, давность.
- POST /check        — препроцессор + 7 зон → итоговый отчёт.
- POST /generate-pdf — генерация PDF судебного приказа.

Запуск:
    uvicorn rules-service.main:app --host 0.0.0.0 --port 8001
"""

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import sys
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
    version="0.2.0",
)


# ---------------------------------------------------------------- #
# Модели                                                            #
# ---------------------------------------------------------------- #

class CardRequest(BaseModel):
    card: dict
    calculation_date: Optional[str] = None


class PreprocessResponse(BaseModel):
    case_id: str
    preprocessed: dict


class CheckResponse(BaseModel):
    case_id: str
    report: dict


class PdfRequest(BaseModel):
    card: dict = Field(..., description="Карточка должника")
    report: dict = Field(..., description="Отчёт от /check")
    hitl_decision: Optional[dict] = Field(
        None, description="Решение HITL (approved, comment)"
    )


class PdfResponse(BaseModel):
    case_id: str
    pdf_path: str
    status: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


# ---------------------------------------------------------------- #
# Endpoints                                                         #
# ---------------------------------------------------------------- #

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="rules-service", version="0.2.0")


@app.post("/preprocess", response_model=PreprocessResponse)
def preprocess(request: CardRequest) -> PreprocessResponse:
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
        return PreprocessResponse(case_id=case_id, preprocessed=result)
    except Exception as e:
        logger.error("Preprocess failed: case_id=%s error=%s", case_id, e)
        raise HTTPException(status_code=400, detail=f"Препроцессор упал: {e}")


@app.post("/check", response_model=CheckResponse)
def check(request: CardRequest) -> CheckResponse:
    card = request.card
    case_id = card.get("case_id", "unknown")
    logger.info("Check request: case_id=%s", case_id)
    try:
        calc_date = (
            date.fromisoformat(request.calculation_date)
            if request.calculation_date
            else None
        )
        preprocessor = Preprocessor(card=card, calculation_date=calc_date)
        preprocessed = preprocessor.run()
        runner = RulesRunner()
        report = runner.run(card=card, preprocessed=preprocessed)
        return CheckResponse(case_id=case_id, report=report)
    except Exception as e:
        logger.error("Check failed: case_id=%s error=%s", case_id, e)
        raise HTTPException(status_code=400, detail=f"Проверка упала: {e}")


@app.post("/generate-pdf", response_model=PdfResponse)
def generate_pdf(request: PdfRequest) -> PdfResponse:
    """
    Генерация PDF судебного приказа.

    В MVP — упрощённый PDF: титул + реквизиты + решение по зонам.
    В production — полный шаблон по ст. 124 ГПК РФ.
    """
    card = request.card
    report = request.report
    case_id = card.get("case_id", "unknown")
    logger.info("PDF request: case_id=%s", case_id)

    try:
        pdf_dir = Path(os.getenv("PDF_OUTPUT_DIR", "/tmp/court-pdfs"))
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{case_id}.pdf"

        _render_pdf(pdf_path, card, report, request.hitl_decision)

        logger.info("PDF generated: case_id=%s path=%s", case_id, pdf_path)
        return PdfResponse(
            case_id=case_id,
            pdf_path=str(pdf_path),
            status="generated",
        )
    except Exception as e:
        logger.error("PDF failed: case_id=%s error=%s", case_id, e)
        raise HTTPException(status_code=400, detail=f"PDF упал: {e}")


@app.get("/download-pdf/{case_id}")
def download_pdf(case_id: str):
    """Скачивание готового PDF."""
    pdf_dir = Path(os.getenv("PDF_OUTPUT_DIR", "/tmp/court-pdfs"))
    pdf_path = pdf_dir / f"{case_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF не найден: {case_id}")
    return FileResponse(
        path=str(pdf_path),
        filename=f"court-order-{case_id}.pdf",
        media_type="application/pdf",
    )


# ---------------------------------------------------------------- #
# PDF-рендеринг (упрощённый MVP)                                    #
# ---------------------------------------------------------------- #

def _render_pdf(
    path: Path,
    card: dict,
    report: dict,
    hitl_decision: Optional[dict] = None,
) -> None:
    """
    Рендер PDF через reportlab.

    MVP: титул + реквизиты + отчёт по зонам + HITL-решение.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.lib import colors

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Судебный приказ — {card.get('case_id', '')}",
        author="Court Rules Service (MVP)",
    )

    styles = getSampleStyleSheet()
    style_h1 = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontSize=14, alignment=TA_CENTER, spaceAfter=12,
    )
    style_h2 = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontSize=11, spaceAfter=6, spaceBefore=10,
    )
    style_normal = ParagraphStyle(
        "Normal", parent=styles["Normal"], fontSize=9, leading=12,
    )

    story = []

    # --- Титул ---
    story.append(Paragraph("СУДЕБНЫЙ ПРИКАЗ", style_h1))
    story.append(Paragraph(
        f"(проект, сгенерирован {datetime.now().strftime('%d.%m.%Y %H:%M')})",
        ParagraphStyle("sub", parent=style_normal, alignment=TA_CENTER, fontSize=8),
    ))
    story.append(Spacer(1, 8 * mm))

    # --- Реквизиты ---
    creditor = card.get("creditor", {})
    respondent = card.get("respondent", {})
    contract = card.get("contract", {})
    debt = report.get("zones") and card or {}  # placeholder

    story.append(Paragraph("Взыскатель", style_h2))
    story.append(Paragraph(
        f"{creditor.get('name', '—')}<br/>"
        f"ИНН: {creditor.get('inn', '—')} | ОГРН: {creditor.get('ogrn', '—')}",
        style_normal,
    ))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Должник", style_h2))
    story.append(Paragraph(
        f"{respondent.get('fio', '—')}<br/>"
        f"Дата рождения: {respondent.get('birth_date', '—')}<br/>"
        f"Адрес: {respondent.get('address', '—')}<br/>"
        f"ИНН: {respondent.get('inn', '—')}",
        style_normal,
    ))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Договор", style_h2))
    story.append(Paragraph(
        f"Номер: {contract.get('number', '—')}<br/>"
        f"Дата: {contract.get('date', '—')}<br/>"
        f"Сумма: {contract.get('amount', '—')} ₽<br/>"
        f"Срок: {contract.get('end_date', '—')}",
        style_normal,
    ))
    story.append(Spacer(1, 6 * mm))

    # --- Отчёт по зонам ---
    story.append(Paragraph("Результаты автоматической проверки", style_h2))

    zones = report.get("zones", [])
    if zones:
        data = [["#", "Зона", "Статус", "Проблем"]]
        for z in zones:
            data.append([
                str(z.get("zone", "")),
                z.get("zone_name", ""),
                z.get("status", ""),
                str(len(z.get("issues", []))),
            ])
        table = Table(data, colWidths=[10 * mm, 80 * mm, 25 * mm, 20 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)
    story.append(Spacer(1, 6 * mm))

    # --- Сводка ---
    summary = report.get("summary", {})
    story.append(Paragraph("Сводка", style_h2))
    story.append(Paragraph(
        f"Всего зон: {summary.get('total_zones', 0)}<br/>"
        f"Пройдено: {summary.get('passed', 0)}<br/>"
        f"Предупреждений: {summary.get('warnings', 0)}<br/>"
        f"Критичных: {summary.get('failed', 0)}<br/>"
        f"Требует HITL: {'ДА' if summary.get('requires_hitl') else 'НЕТ'}",
        style_normal,
    ))
    story.append(Spacer(1, 6 * mm))

    # --- HITL-решение ---
    if hitl_decision:
        story.append(Paragraph("Решение комплаенс-офицера", style_h2))
        approved = hitl_decision.get("approved", False)
        comment = hitl_decision.get("comment", "")
        story.append(Paragraph(
            f"Статус: {'ОДОБРЕНО' if approved else 'ОТКЛОНЕНО'}<br/>"
            f"Комментарий: {comment or '—'}",
            style_normal,
        ))

    doc.build(story)
