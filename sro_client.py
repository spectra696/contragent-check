import httpx

from config import DATANEWTON_API_KEY


class SroClient:
    """Проверка членства в СРО через DataNewton API.

    Фактическая структура ответа /v1/sroMembership:
      {
        "sro_infos": [
          {
            "info": {
              "sro_id": "...",
              "sro_name": "СРО ...",
              "sro_ogrn": "...",
              "type": "СРО / Ассоциация / ...",
              "reg_number": "923",
              "sro_date": "2017-12-25",
              "stop_reason": "",       # пусто = членство активно
              "accordance": "...",
              "phones": "..."
            },
            "fund": {"fund_compensate": ..., "fund_secure": ...},
            "right": {...},
            "checks": [...],
            "ensures": [...]
          }
        ],
        "available_count": N,
        "demo_available_count": M
      }
    """

    DATANEWTON_URL = "https://api.datanewton.ru/v1/sroMembership"

    async def fetch_sro_data(self, inn: str) -> dict:
        if not DATANEWTON_API_KEY:
            return self._err("DATANEWTON_API_KEY не задан в .env")

        try:
            params = {"key": DATANEWTON_API_KEY, "inn": inn}
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(self.DATANEWTON_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            return self._err(str(e))

        sro_infos = data.get("sro_infos") or []
        if not sro_infos:
            return {
                "found": False,
                "is_member": None,
                "status": "не найдено",
                "sro_name": None,
                "sro_type": None,
                "reg_number": None,
                "sro_ogrn": None,
                "sro_date": None,
                "stop_reason": None,
                "source": "DataNewton",
                "error": None,
            }

        active: list[dict] = []
        excluded: list[dict] = []
        for rec in sro_infos:
            info = rec.get("info") or {}
            if (info.get("stop_reason") or "").strip():
                excluded.append(info)
            else:
                active.append(info)

        primary = active[0] if active else (excluded[0] if excluded else {})
        is_member = bool(active)

        if is_member:
            status = "Является членом"
        elif excluded:
            status = excluded[0].get("stop_reason") or "Исключён"
        else:
            status = "статус не определён"

        return {
            "found": True,
            "is_member": is_member,
            "status": status,
            "sro_name": primary.get("sro_name"),
            "sro_type": primary.get("type"),
            "reg_number": primary.get("reg_number"),
            "sro_ogrn": primary.get("sro_ogrn"),
            "sro_date": primary.get("sro_date"),
            "stop_reason": primary.get("stop_reason") or None,
            "source": "DataNewton",
            "error": None,
        }

    @staticmethod
    def _err(message: str) -> dict:
        return {
            "found": False,
            "is_member": None,
            "status": "ошибка запроса",
            "sro_name": None,
            "sro_type": None,
            "reg_number": None,
            "sro_ogrn": None,
            "sro_date": None,
            "stop_reason": None,
            "source": "DataNewton",
            "error": message,
        }