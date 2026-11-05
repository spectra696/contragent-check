import httpx

from config import DATANEWTON_API_KEY


class ArbitrationClient:
    """Статистика арбитражных дел по ролям через DataNewton."""

    STAT_URL = "https://api.datanewton.ru/v1/arbitration/batchCasesStat"

    async def fetch_third_party_stats(self, inn: str) -> dict:
        if not DATANEWTON_API_KEY:
            return {"error": "DATANEWTON_API_KEY не задан", "found": False, "total": 0}

        params = {"key": DATANEWTON_API_KEY}
        body = {"participant": inn}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(self.STAT_URL, params=params, json=body)
                if r.status_code != 200:
                    return {"error": f"HTTP {r.status_code}: {r.text[:200]}",
                            "found": False, "total": 0}
                data = r.json()
        except Exception as e:
            return {"error": str(e), "found": False, "total": 0}

        third = data.get("third_party_stat") or {}
        resolved = third.get("resolved_count") or 0
        considering = third.get("considering_count") or 0
        total = resolved + considering

        # Fallback: если в third_party_stat пусто, берём из stat_by_role
        role_stat = data.get("stat_by_role") or {}
        if total == 0:
            total = role_stat.get("THIRD_PARTY") or 0
            if total and considering == 0 and resolved == 0:
                considering = total  # без разбивки — считаем все активными

        # Статистика по категориям споров (банкротство, экономические и т. п.)
        dispute_stat = data.get("stat_by_dispute") or {}
        bankruptcy_cases = 0
        for k, v in dispute_stat.items():
            kl = k.lower()
            if "несостоятельности" in kl or "банкротств" in kl:
                bankruptcy_cases = int(v or 0)
                break

        return {
            "found": total > 0,
            "total": total,
            "resolved": resolved,
            "considering": considering,
            "bankruptcy_cases": bankruptcy_cases,
            "role_stat": role_stat,
            "dispute_stat": dispute_stat,
            "error": None,
        }