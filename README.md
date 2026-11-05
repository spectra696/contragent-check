# Contragent Check

Веб-сервис проверки контрагентов: Checko.ru API v2 → детерминированный риск-скоринг → GigaChat → отчёт HTML/Markdown/JSON.

## Быстрый старт

```bash
tar xzf contragent-check.tar.gz
cd contragent-check

cp .env.example .env
# откройте .env и задайте CHECKO_API_KEY (обязательно) и GIGACHAT_CREDENTIALS (опционально)

./run.sh
