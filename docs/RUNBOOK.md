# Как запустить / починить

## Быстрый старт

```bash
# 1. venv + зависимости
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. конфиг — скопировать шаблон и заполнить
cp .env.example .env
# TELEGRAM_API_ID, TELEGRAM_API_HASH (https://my.telegram.org), DATABASE_URL, LLM-ключи (опц.)

# 3. PostgreSQL должен быть доступен по DATABASE_URL (схема инициализируется автоматически)
```

## Фаза 1 — preliminary (без LLM)

```bash
python run_preliminary.py --session sessions/acc.session --limit 100
# опции: --proxy host:port:user:pass, --min-subs, --max-requests (flood-safety)
```

## Фаза 2 — LLM-анализ

```bash
python run_llm_analysis.py --session sessions/acc.session --channel <username>
python run_llm_batch.py    --session sessions/acc.session --top 10 --output results/
python run_llm_batch.py prompts                 # список версий промптов
python run_llm_batch.py save-prompt v1 "note"   # сохранить версию промпта
```

## Ноутбук (разведка)

```bash
pip install -r requirements-notebook.txt
python notebooks/generate_sample.py     # data/sample/channels_sample.csv
jupyter notebook notebooks/channel_analysis.ipynb
```

## Переменные окружения (ключевое)

| Переменная | Назначение |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | доступ к Telegram API (обязательно) |
| `DATABASE_URL` | PostgreSQL (`postgresql+asyncpg://…`) |
| `ANTHROPIC_API_KEY` / `LLM_MODEL` | Claude direct (опц.) |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | OpenRouter gateway (опц.) |
| `REQUEST_DELAY`, `MAX_RETRIES`, `PARTICIPANTS_BATCH_SIZE` | пейсинг/ретраи |
| `OUTPUT_DIR`, `LOG_LEVEL`, `LOG_FILE` | экспорт/логи |

## Частые проблемы

- **FloodWait / лимиты Telegram** — уменьши `--limit`/`--max-requests`, увеличь `REQUEST_DELAY`,
  используй `--proxy`.
- **Нет `TELEGRAM_API_ID/HASH`** — `validate_config()` бросит ошибку; заполни `.env`.
- **Канал не резолвится** — проверь `username`/ссылку, публичность и доступ клиента.
- **Логи** — `logs/preliminary_<дата>.log`, `analyzer.log`.
