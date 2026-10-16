# MVP: ИИ-конвейер судебных документов

> Локальный запуск конвейера для демонстрации.
> **Принцип:** LLM для текста, код для проверок.

---

## Что внутри

```
mvp/
├── docker-compose.yml          ← n8n-court (5679) + rules-service (8001)
├── .env.example                ← переменные окружения
├── Dockerfile                  ← (в rules-service/)
├── n8n-workflows/              ← воркфлоу n8n
├── rules/                      ← 7 зон контроля (Python)
├── preprocessor/               ← расчёты, реквизиты, давность
├── rules-service/              ← FastAPI-обёртка (Dockerfile + main.py)
├── scripts/                    ← генератор синтетики, прогон
├── synthetic-data/             ← 50 карточек, 35 багов
└── tests/                      ← тесты
```

---

## Архитектура (кратко)

```
┌──────────────────────────────────────────────────────┐
│  n8n-court (порт 5679)                               │
│  ─ оркестратор конвейера                             │
└───────────────┬──────────────────────────────────────┘
                │ HTTP
                ▼
┌──────────────────────────────────────────────────────┐
│  rules-service (порт 8001)                           │
│  ─ POST /preprocess  → препроцессор                  │
│  ─ POST /check       → препроцессор + 7 зон          │
│  ─ GET  /health      → проверка живости              │
└───────────────┬──────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────┐
│  Ollama (порт 11434, общий с Кейсом №1)              │
│  ─ Qwen 2.5-7B (генерация текста)                    │
└──────────────────────────────────────────────────────┘
```

---

## Требования

- **Docker** + **Docker Compose** (Docker 20.10+)
- **Ollama** с моделью `qwen2.5:7b` (общий с Кейсом №1)
- **RTX 4090** (24 ГБ VRAM) или аналог

---

## Быстрый старт

### 1. Подготовка

```bash
cd case-2-court-pipeline/mvp

# Скопировать переменные окружения
cp .env.example .env
# Отредактировать .env — пароль n8n
```

### 2. Убедиться, что Ollama запущен

Ollama — **общий** с Кейсом №1. Если сервер один:

```bash
cd ~/ai-compliance
docker compose up -d ollama
curl http://localhost:11434/api/tags  # должна быть qwen2.5:7b
```

### 3. Собрать и запустить конвейер

```bash
cd case-2-court-pipeline/mvp
docker compose build rules-service   # первая сборка ~2 мин
docker compose up -d
```

### 4. Проверить, что всё живо

```bash
# rules-service
curl http://localhost:8001/health
# → {"status":"ok","service":"rules-service","version":"0.1.0"}

# n8n-court
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5679
# → 200

# Ollama (из контейнера n8n)
docker exec ai-compliance-n8n-court \
  curl -s http://host.docker.internal:11434/api/tags | head -c 200
```

### 5. Сгенерировать синтетику

```bash
docker compose exec rules-service python scripts/generate_synthetic.py
docker compose exec rules-service python scripts/inject_bugs.py
```

Или локально:

```bash
python3 scripts/generate_synthetic.py
python3 scripts/inject_bugs.py
```

Результат: `synthetic-data/cards/` — 50 карточек, `synthetic-data/injected-bugs/` — 50 с багами.

### 6. Загрузить воркфлоу в n8n

1. Открыть `http://localhost:5679` (логин/пароль из `.env`).
2. **Workflows → Import from File**.
3. Выбрать `n8n-workflows/court-pipeline.json`.
4. **Activate** воркфлоу.

### 7. Прогнать

Через webhook:

```bash
curl -X POST http://localhost:5679/webhook/court-generate \
  -H "Content-Type: application/json" \
  -d @synthetic-data/injected-bugs/case-00041.json
```

Или напрямую в rules-service (для отладки):

```bash
# Только препроцессор
curl -X POST http://localhost:8001/preprocess \
  -H "Content-Type: application/json" \
  -d '{"card": '"$(cat synthetic-data/injected-bugs/case-00041.json)"'}'

# Препроцессор + 7 зон
curl -X POST http://localhost:8001/check \
  -H "Content-Type: application/json" \
  -d '{"card": '"$(cat synthetic-data/injected-bugs/case-00041.json)"'}'
```

---

## Остановка

```bash
docker compose down
```

Ollama **не останавливаем** — он общий с Кейсом №1.

---

## Что делает конвейер

1. **Препроцессор** (Python) — расчёт суммы, периода, реквизитов, давности.
2. **LLM** (Qwen 2.5-7B) — генерация текста приказа.
3. **7 зон контроля** (Python) — формальные проверки.
4. **HITL** (n8n Form) — комплаенс-офицер подтверждает.
5. **PDF** — финальный документ.

---

## 7 зон контроля

| # | Зона | Норма |
|---|---|---|
| 1 | Реквизиты | ст. 124 ГПК РФ |
| 2 | Сумма | ст. 122 ГПК РФ + 353-ФЗ |
| 3 | Период | ст. 122 ГПК РФ |
| 4 | Приложения | ст. 124 ГПК РФ |
| 5 | Подсудность | ст. 123, 28 ГПК РФ |
| 6 | Исковая давность | ст. 196, 203 ГК РФ |
| 7 | ПДн третьих лиц | 152-ФЗ (соразмерность) |

Подробно: [../process.md](../process.md).

---

## Что НЕ делает

- **Не подписывает** документы (только человек).
- **Не отправляет** в суд автоматически (только через ГАС после HITL — в production).
- **Не хранит** ПДн вне контура клиента.

---

## Красная линия

Данные должников **не покидают контур**. Вся обработка — локально.

Соответствие: **152-ФЗ**, **230-ФЗ**, **ГПК РФ**, **353-ФЗ**.

---

## Документация кейса

- [Паспорт боли](../passport.md)
- [7 зон контроля](../process.md)
- [Архитектура](../architecture.md)
- [Метрики](../metrics.md)
- [Ограничения](../limitations.md)
- [Production Roadmap](../production-roadmap.md)

---

## Troubleshooting

| Проблема | Решение |
|---|---|
| `rules-service` unhealthy | `docker compose logs rules-service` |
| n8n не видит Ollama | Проверить `host.docker.internal` в `docker-compose.yml` (Linux — через `extra_hosts`) |
| PDF не генерируется | Проверить `pdf-output/` на хосте, права |
| Карточка не парсится | `curl http://localhost:8001/check -d '{"card": ...}'` для отладки |

---

*MVP · Кейс №2 · Fractional CAIO / AI Architect Portfolio · 2026*
