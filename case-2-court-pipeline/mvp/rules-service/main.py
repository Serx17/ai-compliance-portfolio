"""
rules-service: FastAPI-обёртка над препроцессором, 7 зонами и LLM.

Endpoints:
- GET  /health            — проверка живости.
- POST /preprocess        — препроцессор (расчёты).
- POST /generate-text     — LLM-генерация текста приказа.
- POST /check             — 7 зон контроля.
- POST /generate-pdf      — PDF (текст LLM + отчёт зон).
- GET  /download-pdf/{id} — скачивание PDF.
"""

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys
MVP_ROOT = Path(__file__).resolve().parent.parent
if str(MVP_ROOT) not in sys.path:
    sys.path.insert(0, str(MVP_ROOT))

from preprocessor.pipeline import Preprocessor
from rules.runner import RulesRunner

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title="Court Rules Service", version="0.3.0")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")


class CardRequest(BaseModel):
    card: dict
    calculation_date: Optional[str] = None

class TextRequest(BaseModel):
    card: dict
    preprocessed: dict

class PdfRequest(BaseModel):
    card: dict
    report: dict
    generated_text: Optional[str] = None
    hitl_decision: Optional[dict] = None

class PdfResponse(BaseModel):
    case_id: str
    pdf_path: str
    status: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "rules-service", "version": "0.3.0"}


@app.post("/preprocess")
def preprocess(request: CardRequest):
    card = request.card
    try:
        calc_date = date.fromisoformat(request.calculation_date) if request.calculation_date else None
        preprocessor = Preprocessor(card=card, calculation_date=calc_date)
        return {"case_id": card.get("case_id"), "preprocessed": preprocessor.run()}
    except Exception as e:
        logger.error("Preprocess failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Препроцессор упал: {e}")


@app.post("/generate-text")
async def generate_text(request: TextRequest):
    """Генерация текста судебного приказа через LLM."""
    card = request.card
    pp = request.preprocessed
    debt = pp.get("debt", {})
    req = pp.get("requisites", {})
    
    prompt = f"""Ты — опытный юрист МФО. Составь текст судебного приказа о взыскании задолженности.
    
Данные:
Взыскатель: {req.get('creditor', {}).get('name')}
Должник: {req.get('respondent', {}).get('fio')}
Адрес должника: {req.get('respondent', {}).get('address')}
Договор займа: № {card.get('contract', {}).get('number')} от {card.get('contract', {}).get('date')}

Расчёт задолженности (СТРОГО используй эти цифры):
- Основной долг: {debt.get('principal')} руб.
- Проценты: {debt.get('interest')} руб.
- Неустойка: {debt.get('penalty')} руб.
- ИТОГО: {debt.get('total')} руб.

Напиши краткий, официальный текст приказа. Укажи, что требование основано на договоре займа, и что сумма подлежит взысканию. Не придумывай свои цифры.
"""
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            })
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            return {"case_id": card.get("case_id"), "generated_text": text}
    except Exception as e:
        logger.error("LLM generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка LLM: {e}")


@app.post("/check")
def check(request: CardRequest):
    card = request.card
    try:
        calc_date = date.fromisoformat(request.calculation_date) if request.calculation_date else None
        preprocessor = Preprocessor(card=card, calculation_date=calc_date)
        preprocessed = preprocessor.run()
        runner = RulesRunner()
        report = runner.run(card=card, preprocessed=preprocessed)
        return {"case_id": card.get("case_id"), "report": report}
    except Exception as e:
        logger.error("Check failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Проверка упала: {e}")


@app.post("/generate-pdf", response_model=PdfResponse)
def generate_pdf(request: PdfRequest):
    card = request.card
    report = request.report
    case_id = card.get("case_id", "unknown")
    try:
        pdf_dir = Path(os.getenv("PDF_OUTPUT_DIR", "/tmp/court-pdfs"))
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{case_id}.pdf"
        _render_pdf(pdf_path, card, report, request.generated_text, request.hitl_decision)
        return PdfResponse(case_id=case_id, pdf_path=str(pdf_path), status="generated")
    except Exception as e:
        logger.error("PDF failed: %s", e)
        raise HTTPException(status_code=400, detail=f"PDF упал: {e}")


@app.get("/download-pdf/{case_id}")
def download_pdf(case_id: str):
    pdf_dir = Path(os.getenv("PDF_OUTPUT_DIR", "/tmp/court-pdfs"))
    pdf_path = pdf_dir / f"{case_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF не найден")
    return FileResponse(path=str(pdf_path), filename=f"order-{case_id}.pdf", media_type="application/pdf")


FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu")]
FONT_REGULAR = ["DejaVuSans.ttf", "arial.ttf"]
FONT_BOLD = ["DejaVuSans-Bold.ttf", "arialbd.ttf"]

def _find_font(names):
    for d in FONT_DIRS:
        for name in names:
            p = d / name
            if p.exists(): return p
    return None

def _render_pdf(path, card, report, generated_text=None, hitl_decision=None):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_regular = _find_font(FONT_REGULAR)
    font_bold = _find_font(FONT_BOLD)
    if not font_regular:
        raise RuntimeError("Шрифт кириллицы не найден. apt-get install fonts-dejavu")

    pdfmetrics.registerFont(TTFont("AppFont", str(font_regular)))
    if font_bold:
        pdfmetrics.registerFont(TTFont("AppFont-Bold", str(font_bold)))
        bold_name = "AppFont-Bold"
    else:
        bold_name = "AppFont"

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm,
        title=f"Судебный приказ — {card.get('case_id')}"
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName=bold_name, fontSize=14, alignment=TA_CENTER, spaceAfter=12)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=bold_name, fontSize=11, spaceAfter=6, spaceBefore=10)
    normal = ParagraphStyle("Normal", parent=styles["Normal"], fontName="AppFont", fontSize=10, leading=14)
    small = ParagraphStyle("Small", parent=normal, fontSize=8)

    story = []
    story.append(Paragraph("СУДЕБНЫЙ ПРИКАЗ", h1))
    story.append(Paragraph(f"(проект, сгенерирован {datetime.now().strftime('%d.%m.%Y %H:%M')})", small))
    story.append(Spacer(1, 8*mm))

    if generated_text:
        story.append(Paragraph("Текст приказа (сгенерирован LLM):", h2))
        safe_text = generated_text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        story.append(Paragraph(safe_text, normal))
        story.append(Spacer(1, 8*mm))
    
    story.append(PageBreak())

    story.append(Paragraph("Реквизиты сторон", h2))
    creditor = card.get("creditor", {})
    respondent = card.get("respondent", {})
    story.append(Paragraph(
        f"<b>Взыскатель:</b> {creditor.get('name')}<br/>"
        f"ИНН: {creditor.get('inn')} | ОГРН: {creditor.get('ogrn')}<br/><br/>"
        f"<b>Должник:</b> {respondent.get('fio')}<br/>"
        f"Дата рождения: {respondent.get('birth_date')}<br/>"
        f"Адрес: {respondent.get('address')}<br/>"
        f"ИНН: {respondent.get('inn')}", normal
    ))
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("Результаты автоматической проверки", h2))
    zones = report.get("zones", [])
    if zones:
        data = [["#", "Зона", "Статус", "Проблем"]]
        for z in zones:
            data.append([str(z.get("zone")), z.get("zone_name"), z.get("status"), str(len(z.get("issues", [])))])
        table = Table(data, colWidths=[10*mm, 80*mm, 25*mm, 20*mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), bold_name),
            ("FONTNAME", (0,1), (-1,-1), "AppFont"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.5, colors.grey),
        ]))
        story.append(table)

    story.append(Spacer(1, 6*mm))
    summary = report.get("summary", {})
    story.append(Paragraph("Сводка", h2))
    story.append(Paragraph(
        f"Всего зон: {summary.get('total_zones')} | "
        f"Пройдено: {summary.get('passed')} | "
        f"Критичных: {summary.get('failed')}<br/>"
        f"<b>Требует HITL: {'ДА' if summary.get('requires_hitl') else 'НЕТ'}</b>", normal
    ))
    doc.build(story)
