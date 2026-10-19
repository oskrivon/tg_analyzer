# Архитектура

## Обзор

Двухфазный конвейер анализа публичных Telegram-каналов:

```
resolve channel ──► metadata + recent posts ──► engagement metrics ──► health-score / category
                                                        │
                                        [preliminary triage, no LLM]
                                                        │
                                     прошедшие triage ──► LLM content analysis (category/
                                                          sentiment/quality/toxicity)
                                                        │
                                              PostgreSQL + CSV export
```

Фаза 1 — дешёвая, без LLM: собирает метаданные и вовлечённость, считает health-score
0–100 и категорию по ключевым словам. Фаза 2 — опциональная, платная: для каналов,
прошедших триаж, гоняет LLM-анализ контента.

## Слои

```
config.py                     # env-driven конфиг (секреты из .env)
run_preliminary.py            # CLI фазы 1
run_llm_analysis.py           # CLI фазы 2 (один канал)
run_llm_batch.py              # CLI фазы 2 (батч + CSV + версии промптов)
services/
├── crawler_api.py            # доступ к Telegram API (resolve, участники, посты)
├── channel_analyzer.py       # оркестрация сбора по каналу
├── preliminary_scorer.py     # фаза 1: метрики + health-score + триаж
├── category_detector.py      # keyword-классификатор категории (до LLM)
├── llm_analyzer.py           # фаза 2: анализ контента
├── llm_client.py             # Anthropic Claude (direct)
├── openrouter_client.py      # OpenRouter gateway (опц.)
├── entity_saver.py           # сохранение сущностей в БД
├── link_saver.py             # сохранение извлечённых ссылок
└── request_logger.py         # лог запросов / пейсинг
utils/
├── metrics.py                # ERR, reach, агрегаты вовлечённости
├── link_extractor.py         # извлечение ссылок из текста постов
├── llm_prompts.py            # системный/пользовательский промпты
└── proxy.py                  # парсинг прокси host:port:user:pass
database/
├── connection.py             # async engine / session maker
├── models.py                 # ORM: channels, preliminary_scores, llm_analysis, links, …
└── retry.py                  # хелперы ретраев БД
notebooks/
├── channel_analysis.ipynb    # разведочный анализ (рендерится на GitHub)
└── generate_sample.py        # синтетическая выборка на тех же формулах
```

## Схема данных (основное)

- `channels` — метаданные канала (id, title, username, about, флаги типа, counts,
  slowmode, настройки, ограничения).
- `preliminary_scores` — метрики вовлечённости + health-score (фаза 1).
- `llm_analysis` — результат LLM-прохода (category/sentiment/quality/toxicity).
- Служебные: ссылки, лог запросов. Текст постов не хранится (только агрегаты).

## Ключевые понятия

- **Health-score (0–100)** — прозрачная взвешенная оценка: bot-ratio аудитории/комментаторов,
  активность постинга, число админов, slowmode и др. Бот-дискаунт отделяет накрутку.
- **ERR / reach** — вовлечённость и охват (views / подписчики); engagement падает с ростом
  канала, топ-10% держат ~64% аудитории (см. ноутбук).
- **Триаж** — дорогой LLM включается только для каналов, прошедших дешёвый проход
  (экономия на порядок).

## Внешние зависимости

- Telegram MTProto (Telethon) — публичные данные, что видны обычному клиенту.
- PostgreSQL + asyncpg.
- Anthropic Claude (direct) или OpenRouter.
