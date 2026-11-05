import httpx

from config import DATANEWTON_API_KEY


class FsspClient:
    """Проверка исполнительных производств через DataNewton API.

    Пагинация по offset (до 5 страниц, 500 записей).
    Категории: salary, tax, arrest, search, exec_fee, bankruptcy,
    credit, utility, fees, fine, generic, non_property, unknown.
    """

    URL = "https://api.datanewton.ru/v1/fssp"
    MAX_PAGES = 5

    async def fetch_fssp_data(self, inn: str, ogrn: str | None = None) -> dict:
        if not DATANEWTON_API_KEY:
            return {"error": "DATANEWTON_API_KEY не задан",
                    "found": False, "items": [], "total": 0}

        params = {"key": DATANEWTON_API_KEY}
        base_payload = {"inn": inn, "limit": 100}
        if ogrn:
            base_payload["ogrn"] = ogrn

        all_items: list[dict] = []
        total = 0
        offset = 0

        for _ in range(self.MAX_PAGES):
            payload = {**base_payload, "offset": offset}
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.post(self.URL, params=params, json=payload)
                    if r.status_code != 200:
                        if not all_items:
                            return {"error": f"HTTP {r.status_code}: {r.text[:300]}",
                                    "found": False, "items": [], "total": 0}
                        break
                    data = r.json()
            except Exception as e:
                if not all_items:
                    return {"error": str(e), "found": False, "items": [], "total": 0}
                break

            page_items = data.get("data") or []
            total = data.get("total", len(page_items) + offset)

            if not page_items:
                break

            all_items.extend(page_items)
            offset = len(all_items)

            if offset >= total:
                break

        items = all_items
        loaded_count = len(items)

        normalized: list[dict] = []
        open_count = 0
        open_sum = 0.0
        closed_count = 0
        closed_initial_sum = 0.0
        unknown_count = 0

        for it in items:
            status_raw = (it.get("status") or "").upper()
            closure = (it.get("closure_category") or "").upper()
            init_sum = self._num(it.get("initial_amount_due"))
            debt = self._num(it.get("debt_remaining_balance"))
            if debt is None:
                debt = self._num(it.get("amount_due")) or 0.0

            # Статус: приоритет у status, closure используется как fallback
            if status_raw in ("OPEN", "ACTIVE") or closure == "IN_PROGRESS":
                kind = "open"
                open_count += 1
                open_sum += debt
            elif status_raw == "CLOSE" or closure in ("BANKRUPTCY", "PAID",
                                                       "NO_DEBTOR_FOUND", "RETURNED"):
                kind = "closed"
                closed_count += 1
                if init_sum:
                    closed_initial_sum += init_sum
            else:
                kind = "unknown"
                unknown_count += 1

            normalized.append({
                "kind": kind,
                "category": self._classify_item(it),
                "number": it.get("p_num") or it.get("ep_num2"),
                "date": it.get("ep_date"),
                "status": it.get("status"),
                "closure_category": it.get("closure_category"),
                "closure_reason": it.get("closure_reason_text"),
                "debt_remaining": debt,
                "initial_amount": init_sum,
                "subject": it.get("executive_obj"),
                "doc_type": it.get("executive_document_type"),
                "doc_obj": it.get("executive_document_obj"),
                "department": it.get("department"),
                "collector_name": it.get("collector_name"),
                "collector_inn": it.get("collector_inn"),
            })

        by_category: dict[str, dict] = {}
        for item in normalized:
            cat = item["category"]
            if cat not in by_category:
                by_category[cat] = {"open": 0, "closed": 0, "unknown": 0,
                                    "open_sum": 0.0, "closed_sum": 0.0, "sample": ""}
            kind = item["kind"]
            by_category[cat][kind] = by_category[cat].get(kind, 0) + 1
            if kind == "open":
                by_category[cat]["open_sum"] += item["debt_remaining"] or 0
            if kind == "closed" and item["initial_amount"]:
                by_category[cat]["closed_sum"] += item["initial_amount"]
            if not by_category[cat]["sample"] and item["subject"]:
                by_category[cat]["sample"] = item["subject"]

        return {
            "found": total > 0,
            "total": total,
            "loaded_count": loaded_count,
            "is_partial": loaded_count < total,
            "items": normalized,
            "by_category": by_category,
            "open_count": open_count,
            "open_sum": open_sum,
            "closed_count": closed_count,
            "closed_initial_sum": closed_initial_sum,
            "unknown_count": unknown_count,
            "error": None,
        }

    @staticmethod
    def _classify_item(item: dict) -> str:
        """Категория производства по тексту executive_obj и closure_category."""
        obj = (item.get("executive_obj") or "").lower()
        closure = (item.get("closure_category") or "").upper()

        if closure == "BANKRUPTCY":
            return "bankruptcy"
        if "исполнительск" in obj and "сбор" in obj:
            return "exec_fee"
        if "оплата труда" in obj or "заработн" in obj or "трудовым правоотношен" in obj:
            return "salary"
        if "арест" in obj:
            return "arrest"
        if "розыск" in obj:
            return "search"
        if "страхов" in obj or "налог" in obj or "енс" in obj:
            return "tax"
        if "кредит" in obj:
            return "credit"
        if ("газ" in obj or "тепло" in obj or "электроэнерг" in obj
                or "коммунальн" in obj or "жилую площадь" in obj
                or "жкх" in obj):
            return "utility"
        if ("госпошлин" in obj or "процессуальн" in obj
                or "экспертиз" in obj or "издержк" in obj):
            return "fees"
        if "штраф" in obj or "гибдд" in obj or "наказан" in obj:
            return "fine"
        if "иные взыскания имущественного" in obj or "иное взыскание имущественного" in obj:
            return "generic"
        if "неимущественного характера" in obj:
            return "non_property"
        if not obj and str(item.get("executive_document_type")) == "3":
            return "generic"
        return "unknown"

    @staticmethod
    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None