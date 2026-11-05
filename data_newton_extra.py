import httpx

from config import DATANEWTON_API_KEY


class DataNewtonExtraClient:
    """Блокировка банковских счетов через DataNewton.

    DataNewton отдаёт блокировки не отдельным методом, а через
    /v1/counterparty с фильтром OWNER_BLOCK (блокировка по решению ФНС).
    Документация: https://datanewton.ru/docs/api/counterparty
    """

    URL = "https://api.datanewton.ru/v1/counterparty"

    async def fetch_blocked_accounts(self, inn: str) -> dict:
        if not DATANEWTON_API_KEY:
            return {"error": "DATANEWTON_API_KEY не задан",
                    "found": False, "items": [], "total": 0}

        params = {
            "key": DATANEWTON_API_KEY,
            "inn": inn,
            "filters": "OWNER_BLOCK",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(self.URL, params=params)
                if r.status_code != 200:
                    return {"error": f"HTTP {r.status_code}: {r.text[:300]}",
                            "found": False, "items": [], "total": 0}
                data = r.json()
        except Exception as e:
            return {"error": str(e), "found": False, "items": [], "total": 0}

        company = data.get("company") or {}
        block_info = (
            company.get("owner_block")
            or company.get("blocked_accounts")
            or company.get("block")
        )

        items: list[dict] = []
        if isinstance(block_info, list):
            items = block_info
        elif isinstance(block_info, dict) and block_info:
            items = [block_info]

        total = len(items)
        if total == 0 and isinstance(block_info, bool) and block_info:
            total = 1
            items = [{"note": "Есть блокировка (детали не раскрыты)"}]

        return {
            "found": total > 0,
            "total": total,
            "items": items,
            "error": None,
        }