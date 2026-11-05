import asyncio
from datetime import datetime, timedelta

import httpx

from cache import cache_get, cache_set
from config import CHECKO_API_KEY


class CheckoClient:
    BASE = "https://api.checko.ru/v2"
    MAX_RELATED = 10

    def __init__(self):
        self.key = CHECKO_API_KEY
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30)
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get(self, endpoint: str, **params) -> dict:
        params["key"] = self.key
        cache_key = endpoint + ":" + "&".join(
            f"{k}={v}" for k, v in sorted(params.items()) if k != "key"
        )
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached
        r = await self._client.get(f"{self.BASE}/{endpoint}", params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("meta", {}).get("status") != "ok":
            raise RuntimeError(data["meta"].get("message", "Checko API error"))
        await cache_set(cache_key, data)
        return data

    async def _safe(self, endpoint: str, **params) -> dict:
        try:
            return await self._get(endpoint, **params)
        except Exception as e:
            return {"_error": str(e)}

    async def fetch_subject(self, kind: str, ident: str) -> dict:
        endpoint = "company" if kind == "company" else "entrepreneur"
        field = "inn" if len(ident) in (10, 12) else "ogrn"
        resp = await self._get(endpoint, **{field: ident})
        return resp.get("data", {})

    async def fetch_person(self, inn: str) -> dict:
        resp = await self._get("person", inn=inn)
        return resp.get("data", {})

    async def _fetch_inspections(self, **params) -> dict:
        all_records = []
        page = 1
        max_pages = 10
        total_pages = 1
        total_count = 0

        while page <= max_pages:
            try:
                r = await self._get("inspections", page=page, limit=100,
                                    sort="-date", **params)
            except Exception as e:
                return {"_error": str(e),
                        "data": {"Записи": all_records, "ЗапВсего": total_count}}

            data = r.get("data") or {}
            records = data.get("Записи") or []
            if not records:
                break

            all_records.extend(records)
            total_pages = data.get("СтрВсего") or 1
            total_count = data.get("ЗапВсего") or len(all_records)

            if page >= total_pages:
                break
            page += 1

        return {
            "data": {
                "Записи": all_records,
                "ЗапВсего": total_count,
                "СтрВсего": total_pages,
                "СтрТекущ": page,
            },
            "meta": {"status": "ok"},
        }

    @staticmethod
    def _collect_related_ogrns(base: dict) -> list[str]:
        ogrns: set[str] = set()
        for r in base.get("Руковод", []):
            ogrns.update(r.get("СвязРуковод") or [])
            ogrns.update(r.get("СвязУчред") or [])
        учред = base.get("Учред") or {}
        for fl in учред.get("ФЛ", []):
            ogrns.update(fl.get("СвязРуковод") or [])
            ogrns.update(fl.get("СвязУчред") or [])
        for u in учред.get("РосОрг", []):
            if u.get("ОГРН"):
                ogrns.add(u["ОГРН"])
        ogrns.discard(base.get("ОГРН"))
        return list(ogrns)

    async def _fetch_related(self, ogrn_list: list[str], max_related: int = MAX_RELATED) -> list[dict]:
        targets = ogrn_list[:max_related]
        if not targets:
            return []

        async def _one(ogrn):
            try:
                d = await self._get("company", ogrn=ogrn)
                return {"ogrn": ogrn, "data": d.get("data", {}), "error": None}
            except Exception as e:
                return {"ogrn": ogrn, "data": None, "error": str(e)}

        return list(await asyncio.gather(*[_one(o) for o in targets]))

    async def fetch_checks(
        self,
        kind: str,
        inn: str | None,
        ogrn: str | None,
        check_type: str = "express",
        base: dict | None = None,
    ) -> dict:
        params: dict = {}
        if inn:
            params["inn"] = inn
        if ogrn:
            params["ogrn"] = ogrn

        date_from = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

        tasks = {
            "finances": self._safe("finances", **params),
            "legal_defendant": self._safe("legal-cases", role="defendant",
                                          sort="-date", date_from=date_from, **params),
            "bankruptcy": self._safe("bankruptcy-messages", sort="-date", **params),
            "inspections": self._fetch_inspections(**params),
            "reliability": self._safe("reliability", **params),
        }

        if check_type == "full":
            tasks["legal_plaintiff"] = self._safe("legal-cases", role="plaintiff",
                                                  sort="-date", date_from=date_from, **params)
            tasks["contracts_44_customer"] = self._safe("contracts", law="44", role="customer", limit=100, **params)
            tasks["contracts_44_supplier"] = self._safe("contracts", law="44", role="supplier", limit=100, **params)
            tasks["contracts_223"] = self._safe("contracts", law="223", limit=100, **params)
            tasks["fedresurs"] = self._safe("fedresurs", sort="-date", **params)

        results = await asyncio.gather(*tasks.values())
        extra = dict(zip(tasks.keys(), results))

        if check_type == "full" and base:
            related_ogrns = self._collect_related_ogrns(base)
            extra["related"] = await self._fetch_related(related_ogrns, self.MAX_RELATED)

        return extra