# rules-service: FastAPI-обёртка над препроцессором и 7 зонами
# Базовый образ — Python 3.10 (совместим с локальной разработкой)

FROM python:3.10-slim

# Метаданные
LABEL maintainer="Serx17"
LABEL description="Court Rules Service — препроцессор + 7 зон контроля (Кейс №2)"
LABEL version="0.1.0"

# Переменные окружения
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Системные зависимости для weasyprint и reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Зависимости (копируем отдельно для кэширования слоёв)
COPY rules-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Код проекта
COPY preprocessor /app/preprocessor
COPY rules /app/rules
COPY rules-service /app/rules-service

# Скрипты генерации синтетики и тестов
COPY scripts /app/scripts

# Директория для синтетики и PDF
RUN mkdir -p /app/synthetic-data/cards /app/synthetic-data/injected-bugs /tmp/court-pdfs

# Порт
EXPOSE 8001

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

# Запуск
CMD ["uvicorn", "rules-service.main:app", "--host", "0.0.0.0", "--port", "8001"]
