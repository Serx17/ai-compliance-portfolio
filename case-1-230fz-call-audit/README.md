# Case 1: 230-FZ Call Audit

Полная статья-демонстрация — в [корневом README](../../README.md).

Детали кейса:
- [passport.md](passport.md)
- [process.md](process.md)
- [architecture.md](architecture.md)
- [metrics.md](metrics.md)
- [limitations.md](limitations.md)

## 📹 Демо-видео

Демонстрация MVP-конвейера: от отправки аудио через webhook до JSON-отчёта о нарушениях.

[▶️ Смотреть демо (mp4, 121 МБ, полное качество)](https://github.com/Serx17/ai-compliance-portfolio/releases/download/case-1-demo-v1/demo-case-1.mp4)


**Что показано:**
- Отправка аудиозвонка через webhook
- ASR-транскрипция (GigaAM-v2 rnnt)
- 4 параллельные LLM-ветки (Qwen 2.5-7B, INT4/AWQ)
- Финальный JSON с `third_party_disclosure`, confidence 0.95
- Production roadmap: LoRA, RAG, HITL, rules engine

**Технические метрики:**
- Время обработки: ~4 секунды (тёплый контур)
- Cold start: ~35 секунд (загрузка модели в VRAM)
- Масштабирование: 400–1000 звонков/ночь на одной RTX 4090 (vLLM)
