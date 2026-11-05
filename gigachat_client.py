import time
import uuid

import httpx

from config import (
    GIGACHAT_CA_BUNDLE,
    GIGACHAT_CREDENTIALS,
    GIGACHAT_MODEL,
    GIGACHAT_SCOPE,
)

SYSTEM_PROMPT = """Ты — старший аналитик службы экономической безопасности.
Проверка выполняется в соответствии с внутренним Положением о проверке контрагентов.
Стоп-факторы классифицируются по Приложению № 4 на безусловные (1 → отказ)
и условные (2+ → отказ, 1 → с условиями).

Аудитория отчёта — финансовый директор, служба безопасности и руководитель,
подписывающий Лист согласования контрагента.
Пиши деловым, но живым языком, как если бы коллега спрашивал «ну что там по этой компании?».

На вход получаешь JSON с УЖЕ РАССЧИТАННЫМИ стоп-факторами.

=== ФОРМАТ ОТВЕТА ===
Отвечай ОДНИМ валидным JSON-объектом.
БЕЗ markdown, БЕЗ обёрток ```json```, БЕЗ комментариев до или после JSON.
Если не можешь заполнить поле — верни пустую строку, но JSON должен быть валидным.

Схема:
{
  "headline": "Одна фраза-вердикт до 120 символов",
  "summary": "3-5 предложений живым языком: кто это, чем занимается, что главное.",
  "financial_analysis": "3-5 предложений: динамика выручки, прибыли, капитала.",
  "recommendation": "заключать" | "с условиями" | "воздержаться" | "отказ",
  "recommendation_details": "2-4 предложения: обоснование в терминах Положения.",
  "human_summary": "5-10 предложений живым языком. Объясни своими словами: что это за компания, чем занимается, что в ней хорошо, что плохо. Почему вердикт именно такой. Что бы ты сказал финансовому директору на встрече — без канцелярита, с примерами цифр. Это будет прочитано в самом конце отчёта как резюме. Не повторяй структуру выше, это самостоятельный рассказ.",
  "for_each_department": {
    "Инициатор": "1-2 предложения",
    "Экономическая безопасность": "1-2 предложения",
    "Бухгалтерия": "1-2 предложения",
    "Юридическое подразделение": "1-2 предложения"
  },
  "additional_checks": ["строка", "..."]
}

=== ЖЁСТКИЕ ПРАВИЛА ===
- Используй ТОЛЬКО те стоп-факторы и риски, которые явно перечислены в поле "risks" входного JSON.
- НЕ упоминай коды рисков (FIN_STALE, LEADER_MASS и т.п.), которых нет во входных данных.
- НЕ выдумывай риски, которых нет в поле "risks".
- НЕ меняй вердикт (поле "verdict"), посчитанный движком. Только объясняй его.
- Тон: спокойный, деловой, без канцелярита.
- Поля summary и financial_analysis — не более 5 предложений каждое.
- human_summary — это НЕ пересказ summary, а расширенный рассказ с цифрами и выводами. Обычно 5-10 предложений.
"""


class GigaChatClient:
    OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def __init__(self):
        if not GIGACHAT_CREDENTIALS:
            raise RuntimeError("GIGACHAT_CREDENTIALS не задан в .env")
        self.credentials = GIGACHAT_CREDENTIALS
        self.scope = GIGACHAT_SCOPE
        self.model = GIGACHAT_MODEL
        self.verify = GIGACHAT_CA_BUNDLE or False
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _token_value(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        headers = {
            "Authorization": f"Basic {self.credentials}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        with httpx.Client(verify=self.verify, timeout=30) as client:
            r = client.post(self.OAUTH_URL, headers=headers, data={"scope": self.scope})
            r.raise_for_status()
            j = r.json()
        self._token = j["access_token"]
        self._expires_at = j["expires_at"] / 1000.0
        return self._token

    def chat(self, user_prompt: str, temperature: float = 0.2, max_tokens: int = 4000) -> str:
        token = self._token_value()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(verify=self.verify, timeout=120) as client:
            r = client.post(self.API_URL, headers=headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]