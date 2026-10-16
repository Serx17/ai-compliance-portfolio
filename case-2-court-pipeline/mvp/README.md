# MVP: ИИ-конвейер судебных документов

> Локальный запуск конвейера для демонстрации.
> **Принцип:** LLM для текста, код для проверок.

---

## Что внутри

```
mvp/
├── docker-compose.yml          ← n8n на порту 5679
├── .env.example                ← переменные окружения
├── n8n-workflows/              ← воркфлоу n8n
├── rules/                      ← 7 зон контроля (Python)
├── preprocessor/               ← расчёты, реквизиты
├── scripts/                    ← генератор синтетики, прогон
├── synthetic-data/             ← 50 карточек, 35 багов
└── tests/                      ← тесты
```

---

## Требования

- **Docker** + **Docker Compose**
- **Python 3.10+** (для скриптов и правил)
- **Ollama** с моделью `qwen2.5:7b` (общий с Кейсом №1)
- **RTX 4090** (24 ГБ VRAM) или аналог

---

## Быстрый старт

### 1. Подготовка

```bash
cd case-2-court-pipeline/mvp

# Скопировать переменные окружения
cp .env.example .env
# Отредактировать .env — пароль n8n, URL Ollama
```

### 2. Убедиться, что Ollama запущен

Ollama — **общий** с Кейсом №1. Если сервер один — поднять в `~/ai-compliance/`:

```bash
cd ~/ai-compliance
docker compose up -d ollama
curl http://localhost:11434/api/tags  # должна быть qwen2.5:7b
```

### 3. Запустить n8n-court

```bash
cd case-2-court-pipeline/mvp
docker compose up -d
```

n8n будет доступен: `http://localhost:5679` (логин/пароль из `.env`).

### 4. Сгенерировать синтетику

```bash
python3 scripts/generate_synthetic.py
python3 scripts/inject_bugs.py
```

Результат: `synthetic-data/` заполнится 50 карточками + 35 багами.

### 5. Загрузить воркфлоу в n8n

1. Открыть `http://localhost:5679`
2. **Workflows → Import from File**
3. Выбрать `n8n-workflows/court-pipeline.json`
4. Активировать воркфлоу

### 6. Прогнать

Через webhook:
```bash
curl -X POST http://localhost:5679/webhook/court-generate \
  -F "data=@synthetic-data/injected-bugs/case-00042.json"
```

Или локально без n8n:
```bash
python3 scripts/run_pipeline.py --case synthetic-data/injected-bugs/case-00042.json
```

---

## Остановка

```bash
docker compose down
```

Ollama **не останавливаем** — он общий с Кейсом №1.

---

## Что делает конвейер

1. **Препроцессор** (Python) — расчёт суммы, периода, реквизитов.
2. **LLM** (Qwen 2.5-7B) — генерация текста приказа.
3. **7 зон контроля** (Python) — проверка по формальным требованиям.
4. **HITL** (n8n Form) — комплаенс-офицер подтверждает.
5. **PDF** — финальный документ.

---

## Что НЕ делает

- **Не подписывает** документы (только человек).
- **Не отправляет** в суд автоматически (только через ГАС после HITL — в production).
- **Не хранит** ПДн вне контура клиента.

---

## Красная линия

Данные должников **не покидают контур**. Вся обработка — локально. Соответствие **152-ФЗ**, **230-ФЗ**, **ГПК РФ**.

---

## Документация кейса

- [Паспорт боли](../passport.md)
- [7 зон контроля](../process.md)
- [Архитектура](../architecture.md)
- [Метрики](../metrics.md)
- [Ограничения](../limitations.md)
- [Production Roadmap](../production-roadmap.md)

---

*MVP · Кейс №2 · Fractional CAIO / AI Architect Portfolio · 2026*
