import json
from dataclasses import asdict
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from risk_engine import Result, Risk, build_stop_factors_comment

SEV_RU = {"critical": "Критический", "high": "Высокий", "medium": "Средний", "low": "Низкий"}

_env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"]),
)


def url_for_source(source: str, subject: dict) -> str | None:
    """Возвращает ссылку на первоисточник по названию источника."""
    if not source:
        return None
    inn = subject.get("inn") or ""
    ogrn = subject.get("ogrn") or ""
    src = source.lower()
    if any(x in src for x in ("егрюл", "егрип")):
        return f"https://egrul.nalog.ru/index.html?query={inn}" if inn else "https://egrul.nalog.ru/"
    if any(x in src for x in ("кад", "суд", "арбитраж")):
        return f"https://kad.arbitr.ru/?search={inn}" if inn else "https://kad.arbitr.ru/"
    if "фссп" in src:
        return f"https://fssp.gov.ru/iss/ip?is%5B0%5D={inn}" if inn else "https://fssp.gov.ru/iss/ip"
    if any(x in src for x in ("федресурс", "ефрсб", "ефрсфдюл")):
        key = inn if inn else ogrn
        return f"https://fedresurs.ru/company/{key}" if key else "https://fedresurs.ru/"
    if any(x in src for x in ("еис", "рнп", "госзакупк")):
        return f"https://zakupki.gov.ru/epz/dishonestsupplier/search/results.html?searchString={inn}" if inn else "https://zakupki.gov.ru/"
    if any(x in src for x in ("гирбо", "финанс")):
        return "https://bo.nalog.ru/"
    if any(x in src for x in ("проверк", "кнм")):
        return f"https://proverki.gov.ru/portal/public-search?inn={inn}" if inn else "https://proverki.gov.ru/"
    if any(x in src for x in ("сро", "нострой", "ноприз")):
        return f"https://reestr.nostroy.ru/search/result?query={inn}" if inn else "https://reestr.nostroy.ru/"
    if "фнс" in src or "налог" in src:
        return f"https://pb.nalog.ru/index.html?query={inn}" if inn else "https://pb.nalog.ru/"
    if "цб" in src:
        return "https://www.cbr.ru/"
    return None


def parse_llm_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                return None
    return None


def build_llm_input(result: Result) -> str:
    fssp_brief = None
    if result.fssp:
        fssp_brief = {
            "total": result.fssp.get("total", 0),
            "open": result.fssp.get("open_count", 0),
            "open_sum": result.fssp.get("open_sum", 0.0),
            "closed": result.fssp.get("closed_count", 0),
            "closed_sum": result.fssp.get("closed_initial_sum", 0.0),
            "by_category": result.fssp.get("by_category", {}),
        }

    related_brief = None
    if result.related_summary:
        related_brief = {
            "checked": result.related_summary.get("checked", 0),
            "problems": (result.related_summary.get("problems") or [])[:5],
        }

    payload = {
        "subject": {
            "type": result.subject.get("type"),
            "inn": result.subject.get("inn"),
            "name": result.subject.get("name_short") or result.subject.get("name_full"),
            "status": result.subject.get("status"),
            "reg_date": result.subject.get("reg_date"),
            "okved": result.subject.get("okved"),
            "okved_name": result.subject.get("okved_name"),
            "leader": result.subject.get("leader"),
            "schr": result.subject.get("schr"),
            "tax_regimes": result.subject.get("tax_regimes"),
            "licenses_count": len(result.subject.get("licenses") or []),
            "trademarks_count": len(result.subject.get("trademarks") or []),
            "branches_count": len(result.subject.get("branches") or []),
        },
        "check_type": result.check_type,
        "verdict": result.verdict,
        "verdict_reason": result.verdict_reason,
        "unconditional_count": result.unconditional_count,
        "conditional_count": result.conditional_count,
        "risks": [
            {"code": r.code, "severity": r.severity, "title": r.title,
             "evidence": r.evidence, "stop_type": r.stop_type}
            for r in result.risks
        ],
        "positives": result.positives,
        "missing": result.missing,
        "not_covered": result.not_covered,
        "reliability": result.reliability,
        "finances": [
            {"year": r.get("year"), "revenue": r.get("revenue_f"),
             "profit": r.get("profit_f"), "equity": r.get("equity_f")}
            for r in (result.finances_summary or [])
        ],
        "fssp": fssp_brief,
        "related": related_brief,
        "contracts": result.contracts_summary,
        "plaintiff": result.plaintiff_summary,
        "fedresurs": result.fedresurs,
        "blocked_accounts": result.blocked_accounts,
    }
    return json.dumps(payload, ensure_ascii=False)


def result_to_dict(result: Result) -> dict:
    return {
        "subject_type": result.subject_type,
        "subject": result.subject,
        "risks": [asdict(r) for r in result.risks],
        "positives": result.positives,
        "missing": result.missing,
        "not_covered": result.not_covered,
        "finances_summary": result.finances_summary,
        "reliability": result.reliability,
        "verdict": result.verdict,
        "verdict_reason": result.verdict_reason,
        "unconditional_count": result.unconditional_count,
        "conditional_count": result.conditional_count,
        "stop_factors_comment": build_stop_factors_comment(result),
        "check_type": result.check_type,
        "amount": getattr(result, "amount", 0.0),
        "fssp": result.fssp,
        "contracts_summary": result.contracts_summary,
        "plaintiff_summary": result.plaintiff_summary,
        "related_summary": result.related_summary,
        "fedresurs": result.fedresurs,
        "blocked_accounts": result.blocked_accounts,
        "changes": result.changes,
        "monitoring_recommendation": result.monitoring_recommendation,
        "previous_found": result.previous_found,
    }


def render_html(result: Result, llm: dict | None, llm_error: str | None = None) -> str:
    tpl = _env.get_template("report.html")
    return tpl.render(
        s=result_to_dict(result),
        llm=llm,
        llm_error=llm_error,
        sev_ru=SEV_RU,
        date=datetime.now().strftime("%d.%m.%Y %H:%M"),
        url_for_source=url_for_source,
    )


def render_markdown(result: Result, llm: dict | None) -> str:
    s = result.subject

    verdict_label = {
        "отказ": "🛑 ОТКАЗ: безусловный стоп-фактор",
        "воздержаться": "🟠 ВОЗДЕРЖАТЬСЯ: 2+ условных стоп-фактора",
        "с условиями": "🟡 С УСЛОВИЯМИ: 1 условный стоп-фактор",
        "заключать": "🟢 ЗАКЛЮЧАТЬ: стоп-факторы не выявлены",
    }.get(result.verdict, f"Вердикт: {result.verdict or '—'}")

    md: list[str] = [
        "# Отчёт о проверке контрагента",
        "",
        f"**{s.get('type')}** · {s.get('name_short') or s.get('name_full')}",
        f"ИНН: {s.get('inn')}",
        "",
        f"## {verdict_label}",
        "",
    ]
    if result.verdict_reason:
        md += [f"_{result.verdict_reason}_", ""]

    if llm and llm.get("headline"):
        md += [f"**{llm['headline']}**", ""]

    if llm and llm.get("summary"):
        md += ["## Кратко о контрагенте", "", llm["summary"], ""]

    def _table(risks: list[Risk]) -> list[str]:
        lines = ["| Стоп-фактор | Подтверждение | Источник |", "|---|---|---|"]
        for r in risks:
            lines.append(f"| {r.title} | {r.evidence} | {r.source or '—'} |")
        return lines

    uncond = [r for r in result.risks if r.stop_type == "unconditional"]
    cond = [r for r in result.risks if r.stop_type == "conditional"]
    info = [r for r in result.risks if r.stop_type == "info"]

    if uncond:
        md += ["## Безусловные стоп-факторы (Приложение № 4)", ""] + _table(uncond) + [""]
    if cond:
        md += ["## Условные стоп-факторы (Приложение № 4)", ""] + _table(cond) + [""]
    if info:
        md += ["## Прочие факторы", ""] + _table(info) + [""]
    if not (uncond or cond or info):
        md += ["Стоп-факторы не выявлены.", ""]

    stop_comment = build_stop_factors_comment(result)
    if stop_comment:
        md += ["## Комментарий по стоп-факторам", "", stop_comment, ""]

    if llm and llm.get("financial_analysis"):
        md += ["## Финансовый анализ (GigaChat)", "", llm["financial_analysis"], ""]

    if result.finances_summary:
        md += ["## Финансовые показатели", "",
               "| Год | Выручка | Прибыль | Собственный капитал | Активы |",
               "|---|---|---|---|---|"]
        for r in result.finances_summary:
            md.append(f"| {r['year']} | {r['revenue_f']} | {r['profit_f']} | {r['equity_f']} | {r['assets_f']} |")
        md.append("")

    if result.subject.get("licenses"):
        md += ["## Лицензии", ""]
        for lic in result.subject["licenses"]:
            acts = lic.get("activities") or []
            md.append(f"- № {lic.get('number') or '—'} от {lic.get('date') or '—'}, "
                      f"до {lic.get('valid_to') or '—'} ({lic.get('authority') or '—'}):")
            for a in acts:
                md.append(f"  - {a}")
        md.append("")

    if result.subject.get("schr") is not None:
        md += [f"**Среднесписочная численность:** {result.subject['schr']} чел.", ""]

    if result.subject.get("tax_regimes"):
        md += [f"**Налоговые режимы:** {', '.join(result.subject['tax_regimes'])}", ""]

    if result.subject.get("trademarks"):
        md += [f"**Товарные знаки:** {len(result.subject['trademarks'])}", ""]

    if result.subject.get("branches"):
        md += [f"**Филиалы:** {len(result.subject['branches'])}", ""]

    if result.reliability:
        md += [
            "## Оценка надёжности Checko", "",
            f"Масштаб бизнеса: {result.reliability.get('scale') or '—'}/100 · "
            f"Финансовые риски: {result.reliability.get('financial_risk') or '—'} · "
            f"Риск номинальности: {result.reliability.get('nominality') or '—'}",
            "",
        ]

    if result.positives:
        md += ["## Формальные положительные признаки", ""]
        md += [f"- {p}" for p in result.positives]
        md.append("")

    if llm and llm.get("recommendation"):
        md += [
            "## Рекомендация", "",
            f"**{llm['recommendation'].upper()}**", "",
            llm.get("recommendation_details", ""), "",
        ]

    if llm and llm.get("for_each_department"):
        md += ["## Заключения подразделений (для Листа согласования)", "",
               "| Подразделение | Заключение |", "|---|---|"]
        for dept, text in llm["for_each_department"].items():
            md.append(f"| **{dept}** | {text} |")
        md.append("")

    if result.not_covered:
        md += ["## Требует ручной проверки (вне автоматических источников)", ""]
        md += [f"- {n}" for n in result.not_covered]
        md.append("")

    if result.missing:
        md += ["## Технически не удалось получить", ""]
        md += [f"- {m}" for m in result.missing]
        md.append("")

    if llm and llm.get("human_summary"):
        md += ["## Резюме проверки (человеческим языком)", "", llm["human_summary"], ""]

    return "\n".join(md)