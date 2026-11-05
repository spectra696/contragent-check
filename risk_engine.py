from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

UNCONDITIONAL = "unconditional"
CONDITIONAL = "conditional"
INFO = "info"

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

OFFSHORE_COUNTRIES = {
    "кипр", "британские виргинские", "виргинские", "панама", "сейшелы", "сейшельские",
    "белиз", "багамы", "багамские", "лихтенштейн", "мальта", "люксембург",
    "нидерланды", "гонконг", "сингапур", "швейцария", "ирландия", "оаэ",
    "объединенные арабские эмираты",
}

LICENSED_OKVED = (
    "86", "85", "49.3", "49.4", "52.2", "61", "64.19", "65", "66.12",
    "69.1", "71.12.1", "74.20", "92",
)


@dataclass
class Risk:
    code: str
    severity: str
    title: str
    evidence: str
    group: str
    stop_type: str = INFO
    source: str = ""


@dataclass
class Result:
    subject_type: str
    subject: dict
    risks: list[Risk] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    not_covered: list[str] = field(default_factory=list)
    finances_summary: list[dict] = field(default_factory=list)
    reliability: dict | None = None
    verdict: str = ""
    verdict_reason: str = ""
    unconditional_count: int = 0
    conditional_count: int = 0
    fssp: dict | None = None
    check_type: str = "express"
    contracts_summary: dict | None = None
    plaintiff_summary: dict | None = None
    related_summary: dict | None = None
    changes: list[dict] = field(default_factory=list)
    monitoring_recommendation: str = ""
    previous_found: bool = False
    fedresurs: dict | None = None
    blocked_accounts: dict | None = None


def evaluate(subject_type: str, base: dict, extra: dict) -> Result:
    if subject_type == "company":
        return _eval_company(base, extra)
    return _eval_entrepreneur(base, extra)


def _get(d: dict, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _fmt_money(v) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v/1e9:.2f} млрд ₽"
    if a >= 1_000_000:
        return f"{v/1e6:.2f} млн ₽"
    if a >= 1_000:
        return f"{v/1e3:.1f} тыс. ₽"
    return f"{v:.0f} ₽"


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _v(row, code):
    if not isinstance(row, dict):
        return None
    v = row.get(str(code))
    if v is None:
        v = row.get(code)
    if isinstance(v, dict):
        v = v.get("СумОтч")
    return _to_float(v)


def _years(fin_data: dict) -> list[str]:
    return sorted([y for y in fin_data if str(y).isdigit()], key=int)


def _check_finances(risks, positives, fin_data) -> list[dict]:
    years = _years(fin_data)
    if not years:
        return []

    rows = []
    for y in years[-5:]:
        row = fin_data[y]
        rev = _v(row, 2110)
        prof = _v(row, 2400)
        rows.append({
            "year": y,
            "revenue": rev,
            "profit": prof,
            "revenue_f": _fmt_money(rev),
            "profit_f": _fmt_money(prof),
            "equity_f": _fmt_money(_v(row, 1300)),
            "assets_f": _fmt_money(_v(row, 1600)),
        })

    try:
        from datetime import date as _date
        last_year = int(years[-1])
        deadline = _date(last_year + 1, 3, 31)
        days_overdue = (datetime.now().date() - deadline).days
        if days_overdue > 365:
            risks.append(Risk("FIN_STALE", "critical",
                              "Непредоставление налоговой отчётности более года",
                              f"Последняя отчётность за {last_year} год; срок сдачи истёк "
                              f"{deadline.strftime('%d.%m.%Y')} ({days_overdue} дней назад)",
                              "Финансы", UNCONDITIONAL, "ГИРБО через Checko"))
        elif days_overdue > 180:
            risks.append(Risk("FIN_DELAY", "low",
                              "Просрочка сдачи налоговой отчётности",
                              f"Отчётность за {last_year} год должна была быть сдана до "
                              f"{deadline.strftime('%d.%m.%Y')} ({days_overdue} дней назад)",
                              "Финансы", INFO, "ГИРБО через Checko"))
    except (ValueError, TypeError):
        pass

    last = fin_data[years[-1]]
    eq = _v(last, 1300)
    if eq is not None and eq < 0:
        risks.append(Risk("EQUITY_NEGATIVE", "high", "Отрицательный собственный капитал",
                          f"{_fmt_money(eq)} за {years[-1]}", "Финансы", CONDITIONAL, "ГИРБО"))
    elif eq and eq > 0:
        positives.append("Положительный собственный капитал")

    profits = [_v(fin_data[y], 2400) for y in years[-2:]]
    if len(profits) == 2 and all(p is not None and p < 0 for p in profits):
        risks.append(Risk("LOSS_2Y", "high", "Убытки 2 года подряд",
                          f"{years[-2]}: {_fmt_money(profits[0])}, {years[-1]}: {_fmt_money(profits[1])}",
                          "Финансы", CONDITIONAL, "ГИРБО"))
    elif profits and profits[-1] is not None and profits[-1] > 0:
        positives.append("Прибыль по последней отчётности")

    revs = [_v(fin_data[y], 2110) for y in years[-2:]]
    if len(revs) >= 2 and all(r is not None and r == 0 for r in revs):
        risks.append(Risk("NO_REVENUE", "high", "Нулевая выручка 2 года подряд",
                          f"{years[-2]}: 0, {years[-1]}: 0 — возможна недействующая компания",
                          "Финансы", CONDITIONAL, "ГИРБО"))

    if len(years) >= 2:
        prev_rev = _v(fin_data[years[-2]], 2110) or 0
        cur_rev = _v(last, 2110) or 0
        if prev_rev > 0 and cur_rev < prev_rev * 0.5:
            risks.append(Risk("REVENUE_DROP", "medium", "Резкое падение выручки",
                              f"{years[-2]}: {_fmt_money(prev_rev)} → {years[-1]}: {_fmt_money(cur_rev)}",
                              "Финансы", INFO, "ГИРБО"))
    return rows


def _last_revenue(fin_rows: list[dict] | None) -> float | None:
    if not fin_rows:
        return None
    try:
        v = fin_rows[-1].get("revenue")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fssp_severity(sum_val: float, rev: float | None) -> tuple[str, str]:
    if not rev or rev <= 0:
        return ("high" if sum_val > 1_000_000 else "medium", CONDITIONAL)
    ratio = sum_val / rev
    if ratio >= 0.01:
        return "high", CONDITIONAL
    if ratio >= 0.001:
        return "medium", CONDITIONAL
    return "low", INFO


def _normalize_contacts(d: dict) -> dict:
    """Checko может отдавать Тел/Емэйл как строку или как массив — нормализуем."""
    raw_phones = _get(d, "Контакты", "Тел")
    raw_emails = _get(d, "Контакты", "Емэйл")
    if isinstance(raw_phones, str):
        raw_phones = [raw_phones] if raw_phones else []
    if isinstance(raw_emails, str):
        raw_emails = [raw_emails] if raw_emails else []
    return {
        "phones": raw_phones or [],
        "emails": raw_emails or [],
        "website": _get(d, "Контакты", "ВебСайт"),
    }


def _eval_blocked_accounts(risks, positives, extra) -> dict | None:
    ba = extra.get("blocked_accounts")
    if not ba:
        return None
    if ba.get("error"):
        return {"error": ba["error"]}
    if ba.get("found") and ba.get("total", 0) > 0:
        items = ba.get("items") or []
        sample = ""
        if items:
            first = items[0]
            bank = first.get("bank_name") or first.get("bank") or "—"
            date = first.get("decision_date") or first.get("date") or "—"
            sample = f" Первое: {bank}, {date}."
        risks.append(Risk(
            "ACCOUNTS_BLOCKED", "critical",
            "Приостановление операций по банковским счетам (ФНС)",
            f"Заблокировано счетов: {ba['total']}.{sample}",
            "Налоги", UNCONDITIONAL, "ФНС / DataNewton"))
    else:
        positives.append("Нет сведений о блокировке банковских счетов")
    return {"total": ba.get("total", 0), "items": ba.get("items") or []}


def _eval_fedresurs(risks, positives, extra) -> dict | None:
    """Анализ Федресурса с выделением намерений банкротства, залогов, лизинга."""
    data = extra.get("fedresurs")
    if not data:
        return None
    if "_error" in data:
        return None
    d = data.get("data") or {}
    records = d.get("Записи") or []
    total = d.get("ЗапВсего")
    if total is None:
        total = len(records)
    if total == 0:
        return {"total": 0}

    types: dict[str, int] = {}
    bankruptcy_intents: list[dict] = []
    pledges: list[dict] = []
    leases: list[dict] = []

    for r in records:
        t = r.get("ТипНаим") or r.get("Тип") or "—"
        tcode = (r.get("Тип") or "").lower()
        tlow = t.lower()
        types[t] = types.get(t, 0) + 1

        rec = {
            "url": r.get("URL"),
            "date": r.get("Дата"),
            "title": t,
            "type_code": r.get("Тип"),
        }

        # Намерения обратиться с банкротством (кредитора / должника / работника / уполномоченного органа)
        if ("intention" in tcode and "court" in tcode) or \
           ("намерение" in tlow and "банкротств" in tlow):
            bankruptcy_intents.append(rec)
        # Залоги (возникновение / изменение права залога)
        elif "pledge" in tcode or "залог" in tlow:
            pledges.append(rec)
        # Лизинг
        elif "lease" in tcode or "лизинг" in tlow:
            leases.append(rec)

    # Считаем намерения кредиторов и должников отдельно
    n_creditors = sum(
        1 for b in bankruptcy_intents
        if "кредитор" in b["title"].lower()
    )
    n_debtors = sum(
        1 for b in bankruptcy_intents
        if "должник" in b["title"].lower()
    )
    n_other_intents = len(bankruptcy_intents) - n_creditors - n_debtors

    # Риск: намерения обратиться с банкротством
    if bankruptcy_intents:
        parts = []
        if n_creditors:
            parts.append(f"кредиторов: {n_creditors}")
        if n_debtors:
            parts.append(f"должника: {n_debtors}")
        if n_other_intents:
            parts.append(f"прочих: {n_other_intents}")
        detail = ", ".join(parts)
        sev = "medium" if (n_creditors + n_debtors) >= 2 else "low"
        risks.append(Risk(
            "FEDRESURS_BANKRUPTCY_INTENT", sev,
            "Сообщения о намерении обратиться в суд с заявлением о банкротстве",
            f"{len(bankruptcy_intents)} сообщений ({detail}) — превентивный сигнал "
            f"о возможной процедуре банкротства",
            "Федресурс", CONDITIONAL, "Федресурс"))

    # Риск: залоги
    if pledges:
        sev = "medium" if len(pledges) >= 5 else "low"
        risks.append(Risk(
            "FEDRESURS_PLEDGE", sev,
            "Залоги имущества (Федресурс)",
            f"{len(pledges)} сообщений о возникновении или изменении права залога — "
            f"имущество обременено, приоритет у залоговых кредиторов",
            "Федресурс", INFO, "Федресурс"))

    # Риск: лизинг
    if leases:
        risks.append(Risk(
            "FEDRESURS_LEASING", "low",
            "Договоры финансовой аренды (лизинга)",
            f"{len(leases)} сообщений о заключении договоров лизинга — "
            f"долгосрочные обязательства по лизинговым платежам",
            "Федресурс", INFO, "Федресурс"))

    return {
        "total": total,
        "loaded": len(records),
        "types": types,
        "bankruptcy_intents": bankruptcy_intents[:10],
        "pledges": pledges[:10],
        "leases": leases[:10],
        "n_creditors": n_creditors,
        "n_debtors": n_debtors,
    }


def _eval_extra_fields(risks, positives, subject, base, fin_rows) -> None:
    schr = subject.get("schr")
    if schr is not None:
        try:
            schr_val = int(schr)
        except (TypeError, ValueError):
            schr_val = None
        if schr_val is not None:
            if schr_val == 0:
                risks.append(Risk("NO_EMPLOYEES", "medium",
                                  "Нет сотрудников (СЧР = 0)",
                                  "Среднесписочная численность — 0 человек",
                                  "Ресурсы", CONDITIONAL, "ФНС"))
            elif schr_val <= 2:
                risks.append(Risk("LOW_EMPLOYEES", "low",
                                  f"Мало сотрудников (СЧР = {schr_val})",
                                  f"Среднесписочная численность — {schr_val} чел.",
                                  "Ресурсы", INFO, "ФНС"))
            elif schr_val >= 100:
                positives.append(f"Штат {schr_val} сотрудников")

    tax_regimes = subject.get("tax_regimes") or []
    revenue = _last_revenue(fin_rows)
    if tax_regimes:
        positives.append("Налоговые режимы: " + ", ".join(str(t) for t in tax_regimes))
        if "УСН" in tax_regimes and revenue and revenue > 200_000_000:
            risks.append(Risk("USN_LIMIT_EXCEEDED", "medium",
                              "УСН при выручке свыше 200 млн ₽",
                              f"Выручка {_fmt_money(revenue)} при применении УСН",
                              "Налоги", CONDITIONAL, "ФНС"))

    tax_paid = subject.get("tax_paid")
    if tax_paid and revenue and revenue > 0:
        try:
            load = float(tax_paid) / revenue
        except (TypeError, ValueError):
            load = None
        if load is not None:
            if load < 0.01:
                risks.append(Risk("LOW_TAX_BURDEN", "low",
                                  "Низкая налоговая нагрузка",
                                  f"{load * 100:.2f}% от выручки (уплачено {_fmt_money(tax_paid)})",
                                  "Налоги", INFO, "ФНС"))
            elif load > 0.1:
                positives.append(f"Налоговая нагрузка {load * 100:.1f}% от выручки")

    licenses = subject.get("licenses") or []
    okved = (subject.get("okved") or "").strip()
    needs_license = any(okved.startswith(prefix) for prefix in LICENSED_OKVED)
    if licenses:
        positives.append(f"Лицензии: {len(licenses)} записей")
    elif needs_license:
        risks.append(Risk("NO_LICENSE", "medium",
                          "Не найдены лицензии при лицензируемом ОКВЭД",
                          f"ОКВЭД {okved} требует лицензии, но сведений нет",
                          "Лицензии", CONDITIONAL, "ЕГРЮЛ"))

    founders = subject.get("founders") or {}
    for f in founders.get("foreign_orgs") or []:
        country = (f.get("country") or "").lower()
        if any(off in country for off in OFFSHORE_COUNTRIES):
            risks.append(Risk("OFFSHORE_FOUNDER", "medium",
                              "Иностранный учредитель из офшорной юрисдикции",
                              f"{f.get('name')} ({f.get('country')}), доля {f.get('share')}%",
                              "Учредители", CONDITIONAL, "ЕГРЮЛ"))
            break
    for fl in founders.get("physical") or []:
        if fl.get("encumbered"):
            risks.append(Risk("PLEDGED_SHARE", "low",
                              "Доля учредителя заложена",
                              f"{fl.get('name')}: {fl.get('share')}%",
                              "Учредители", INFO, "ЕГРЮЛ"))

    trademarks = subject.get("trademarks") or []
    if trademarks:
        positives.append(f"Зарегистрированные товарные знаки: {len(trademarks)}")

    branches = subject.get("branches") or []
    reps = subject.get("representative_offices") or []
    if branches:
        positives.append(f"Филиалы: {len(branches)}")
    if reps:
        positives.append(f"Представительства: {len(reps)}")

    predecessors = subject.get("predecessors") or []
    if predecessors:
        positives.append(
            f"Создана в результате реорганизации ({len(predecessors)} правопредшественников): "
            + ", ".join(str(p.get("name") or p.get("ogrn")) for p in predecessors[:3])
        )

    shareholder_registrar = subject.get("shareholder_registrar")
    if shareholder_registrar:
        positives.append(f"Реестр акционеров ведёт независимый регистратор: "
                         f"{shareholder_registrar.get('name') or '—'}"
                         + (f" (ОГРН {shareholder_registrar['ogrn']})"
                            if shareholder_registrar.get("ogrn") else ""))

    msme = subject.get("msme")
    if msme and isinstance(msme, dict) and msme.get("category"):
        positives.append(f"Входит в реестр МСП: {msme['category']}"
                         + (f" (с {msme['included_date']})" if msme.get("included_date") else ""))
    elif msme is False and revenue and revenue > 2_000_000_000:
        positives.append("Не входит в реестр МСП (норма для крупных компаний)")

    contacts = subject.get("contacts") or {}
    if contacts.get("phones") or contacts.get("emails") or contacts.get("website"):
        parts = []
        if contacts.get("phones"):
            parts.append(f"тел. {len(contacts['phones'])}")
        if contacts.get("emails"):
            parts.append(f"email {len(contacts['emails'])}")
        if contacts.get("website"):
            parts.append("сайт")
        positives.append("Контакты: " + ", ".join(parts))

    egrul_date = subject.get("egrul_date")
    if egrul_date:
        dt = None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(egrul_date), fmt)
                break
            except (ValueError, TypeError):
                continue
        if dt:
            days_old = (datetime.now() - dt).days
            if days_old > 30:
                risks.append(Risk("EGRUL_STALE", "low",
                                  "Данные выписки могут быть устаревшими",
                                  f"Последняя выписка: {egrul_date} ({days_old} дней назад)",
                                  "Доступ", INFO, "ЕГРЮЛ/ЕГРИП"))


def _eval_contracts(risks, positives, extra) -> dict | None:
    if not extra:
        return None
    customer = extra.get("contracts_44_customer") or {}
    supplier = extra.get("contracts_44_supplier") or {}
    c223 = extra.get("contracts_223") or {}
    if "_error" in customer and "_error" in supplier and "_error" in c223:
        return None

    total_count = 0
    loaded_count = 0
    loaded_sum = 0.0
    by_law: dict[str, dict] = {}

    for law_key, d in (("44-customer", customer), ("44-supplier", supplier), ("223", c223)):
        if "_error" in d:
            continue
        data = d.get("data") or {}
        recs = data.get("Записи") or []
        declared = data.get("ЗапВсего")
        if declared is None:
            declared = len(recs)
        s = 0.0
        for r in recs:
            try:
                s += float(r.get("Цена") or 0)
            except (TypeError, ValueError):
                pass
        by_law[law_key] = {"count": len(recs), "declared_count": declared, "sum": s}
        total_count += declared
        loaded_count += len(recs)
        loaded_sum += s

    if total_count == 0 and loaded_count == 0:
        risks.append(Risk("NO_CONTRACTS", "low", "Нет опыта государственных контрактов",
                          "По 44-ФЗ и 223-ФЗ контрактов не найдено",
                          "Госзакупки", INFO, "ЕИС"))
    else:
        if loaded_count < total_count:
            positives.append(
                f"Опыт госконтрактов: всего {total_count} (в выборке {loaded_count} "
                f"на сумму {_fmt_money(loaded_sum)})")
        else:
            positives.append(
                f"Опыт госконтрактов: {total_count} на сумму {_fmt_money(loaded_sum)}")
        if total_count >= 20 and loaded_sum >= 100_000_000:
            positives.append("Активный участник госзакупок")

    return {"total_count": total_count, "loaded_count": loaded_count,
            "loaded_sum": loaded_sum, "by_law": by_law}


def _eval_plaintiff(risks, extra, fin_rows: list[dict] | None = None) -> dict | None:
    data = extra.get("legal_plaintiff")
    if not data or "_error" in data:
        return None
    d = data.get("data") or {}
    records = d.get("Записи") or []
    declared = d.get("ЗапВсего")
    if declared is None:
        declared = len(records)
    loaded = len(records)

    if declared == 0 and loaded == 0:
        return {"count": 0, "declared_count": 0, "sum": 0.0, "sum_is_partial": False}

    total = 0.0
    for r in records:
        try:
            total += float(r.get("СуммИск") or 0)
        except (TypeError, ValueError):
            pass
    sum_is_partial = loaded < declared

    if declared > 500:
        risks.append(Risk("PLAINTIFF_ACTIVE", "low",
                          "Активно выступает истцом в арбитраже",
                          f"Всего {declared} дел в роли истца"
                          + (f" (в выборке {loaded} на {_fmt_money(total)}, "
                             f"сумма по всем не рассчитана)"
                             if sum_is_partial
                             else f" на сумму {_fmt_money(total)}"),
                          "Суды", INFO, "КАД"))

    return {"count": loaded, "declared_count": declared,
            "sum": total, "sum_is_partial": sum_is_partial}


def _eval_related(risks, positives, extra) -> dict | None:
    related = extra.get("related")
    if not related:
        return None

    problems = []
    checked = 0
    for r in related:
        if r.get("error") or not r.get("data"):
            continue
        checked += 1
        d = r["data"]
        status = (_get(d, "Статус", "Наим") or "").lower()
        reason = ""
        if "ликвидац" in status or "прекращ" in status or "не действ" in status:
            reason = "ликвидирована/не действует"
        elif "реорганиз" in status:
            reason = "реорганизация"
        elif d.get("НедобПост"):
            reason = "в РНП"
        elif d.get("ЕФРСБ"):
            reason = "банкротство"
        elif _get(d, "ЮрАдрес", "Недост") or any(x.get("Недост") for x in (d.get("Руковод") or [])):
            reason = "недостоверные сведения"

        if reason:
            problems.append({
                "ogrn": r["ogrn"],
                "name": d.get("НаимСокр") or d.get("НаимПолн") or "—",
                "reason": reason,
            })

    if not checked:
        return None

    if problems:
        if len(problems) >= 3:
            risks.append(Risk("RELATED_MULTIPLE", "high",
                              f"Несколько связанных юрлиц с проблемами ({len(problems)} из {checked})",
                              "; ".join(f"{p['name']} ({p['reason']})" for p in problems[:5]),
                              "Связи", CONDITIONAL, "ЕГРЮЛ"))
        else:
            risks.append(Risk("RELATED_PROBLEM", "medium",
                              "Связанные юрлица с проблемами",
                              "; ".join(f"{p['name']} ({p['reason']})" for p in problems),
                              "Связи", CONDITIONAL, "ЕГРЮЛ"))
    elif checked >= 3:
        positives.append(f"Связанные юрлица ({checked}) без проблем")

    return {"checked": checked, "problems": problems}


def _finalize(result: Result) -> Result:
    unc = sum(1 for r in result.risks if r.stop_type == UNCONDITIONAL)
    cond = sum(1 for r in result.risks if r.stop_type == CONDITIONAL)
    result.unconditional_count = unc
    result.conditional_count = cond

    if unc > 0:
        result.verdict = "отказ"
        result.verdict_reason = (
            f"Выявлен безусловный стоп-фактор ({unc}). "
            "Согласно п. 3.9.3 Положения заключение договора не допускается.")
    elif cond >= 2:
        result.verdict = "воздержаться"
        result.verdict_reason = (
            f"Выявлено {cond} условных стоп-фактора. "
            "Согласно Приложению № 4 их сочетание является основанием для отказа от договора. "
            "Требуется дополнительное рассмотрение.")
    elif cond == 1:
        result.verdict = "с условиями"
        result.verdict_reason = (
            "Выявлен один условный стоп-фактор. "
            "Заключение возможно при устранении или принятии на себя остаточного риска.")
    else:
        result.verdict = "заключать"
        result.verdict_reason = (
            "Безусловные и условные стоп-факторы по Приложению № 4 не выявлены "
            "(в пределах автоматически проверяемых источников).")

    result.risks.sort(key=lambda r: (
        0 if r.stop_type == UNCONDITIONAL else 1 if r.stop_type == CONDITIONAL else 2,
        SEVERITY_ORDER[r.severity],
        r.code,
    ))
    return result


def _rnp_summary(d: dict) -> str:
    recs = d.get("НедобПостЗап") or []
    if not recs:
        return "Организация включена в РНП"
    r = recs[0]
    return f"Запись {r.get('РеестрНомер', '')} от {r.get('ДатаПуб', '')}"


_NOT_COVERED_COMMON = [
    "Сверка предоставленных контрагентом документов с данными ЕГРЮЛ/ЕГРИП (п. 3.9.1 Положения)",
]

_NOT_COVERED_ORG = [
    "Руководитель/участник контрагента как руководитель/участник проблемных должников Общества (внутренние данные)",
    "Наличие просроченной дебиторской задолженности перед Обществом (внутренние данные)",
    "Факты недобросовестного исполнения перед Обществом за последние 3 года (внутренние данные)",
    "Права на недвижимость и оборудование (ЕГРН, документы контрагента) — при применимости",
]

_NOT_COVERED_EXPRESS = [
    "Госконтракты, иски в роли истца, связанные юрлица, третьи лица, Федресурс — только в полной проверке",
]


def _build_subject(d: dict) -> dict:
    leader = (d.get("Руковод") or [{}])[0]

    def _founders_list(key: str):
        return _get(d, "Учред", key) or []

    reg = d.get("ДержРеестрАО") or {}
    shareholder_registrar = None
    if reg:
        shareholder_registrar = {
            "name": reg.get("НаимПолн") or reg.get("НаимСокр"),
            "ogrn": reg.get("ОГРН"),
            "inn": reg.get("ИНН"),
        }

    rms = d.get("РМСП")
    msme = False
    if isinstance(rms, dict) and rms.get("Кат"):
        msme = {
            "category": rms.get("Кат"),
            "included_date": rms.get("ДатаВкл"),
        }

    return {
        "type": "ЮЛ",
        "inn": d.get("ИНН"),
        "ogrn": d.get("ОГРН"),
        "kpp": d.get("КПП"),
        "name_short": d.get("НаимСокр"),
        "name_full": d.get("НаимПолн"),
        "status": _get(d, "Статус", "Наим") or "",
        "reg_date": d.get("ДатаРег"),
        "egrul_date": d.get("ДатаВып"),
        "region": _get(d, "Регион", "Наим"),
        "address": _get(d, "ЮрАдрес", "АдресРФ"),
        "okved": _get(d, "ОКВЭД", "Код"),
        "okved_name": _get(d, "ОКВЭД", "Наим"),
        "leader": leader.get("ФИО"),
        "leader_position": leader.get("НаимДолжн"),
        "capital": _get(d, "УстКап", "Сумма"),
        "schr": d.get("СЧР"),
        "tax_regimes": _get(d, "Налоги", "ОсобРежим") or [],
        "tax_paid": _get(d, "Налоги", "СумУпл"),
        "tax_paid_details": _get(d, "Налоги", "СведУпл") or [],
        "contacts": _normalize_contacts(d),
        "licenses": [
            {
                "number": lic.get("Номер"),
                "date": lic.get("Дата"),
                "activities": lic.get("ВидДеят") or [],
                "authority": lic.get("ЛицОрг"),
                "valid_to": lic.get("ДатаОконч"),
            }
            for lic in (d.get("Лиценз") or [])
        ],
        "founders": {
            "physical": [
                {"name": f.get("ФИО"), "share": _get(f, "Доля", "Процент"),
                 "encumbered": bool(f.get("Обрем"))}
                for f in _founders_list("ФЛ")
            ],
            "russian_orgs": [
                {"name": o.get("НаимСокр") or o.get("НаимПолн"),
                 "ogrn": o.get("ОГРН"), "share": _get(o, "Доля", "Процент")}
                for o in _founders_list("РосОрг")
            ],
            "foreign_orgs": [
                {"name": o.get("НаимПолн"), "country": o.get("Страна"),
                 "share": _get(o, "Доля", "Процент")}
                for o in _founders_list("ИнОрг")
            ],
            "state": bool(_get(d, "Учред", "РФ")),
        },
        "trademarks": [
            {"id": t.get("ID"), "date": t.get("ДатаРег"), "valid_to": t.get("ДатаОконч")}
            for t in (d.get("ТоварЗнак") or [])
        ],
        "branches": [
            {"name": b.get("НаимПолн"), "address": b.get("Адрес")}
            for b in (_get(d, "Подразд", "Филиал") or [])
        ],
        "representative_offices": [
            {"name": r.get("НаимПолн"), "address": r.get("Адрес")}
            for r in (_get(d, "Подразд", "Представ") or [])
        ],
        "predecessors": [
            {"ogrn": p.get("ОГРН"), "name": p.get("НаимПолн")}
            for p in (d.get("Правопредш") or [])
        ],
        "successors": [
            {"ogrn": p.get("ОГРН"), "name": p.get("НаимПолн")}
            for p in (d.get("Правопреем") or [])
        ],
        "shareholder_registrar": shareholder_registrar,
        "msme": msme,
    }


def _eval_company(base: dict, extra: dict) -> Result:
    risks: list[Risk] = []
    positives: list[str] = []
    missing: list[str] = []
    not_covered: list[str] = []

    check_type = extra.get("check_type", "express")

    d = base
    subject = _build_subject(d)
    status_name = subject["status"]

    low = status_name.lower()
    if "ликвидац" in low:
        risks.append(Risk("STATUS_LIQ", "critical", "Организация в процессе ликвидации",
                          status_name, "Статус", UNCONDITIONAL, "ЕГРЮЛ"))
    elif "прекращ" in low or _get(d, "Ликвид", "Дата"):
        risks.append(Risk("STATUS_DEAD", "critical", "Деятельность прекращена",
                          status_name, "Статус", UNCONDITIONAL, "ЕГРЮЛ"))
    elif "реорганиз" in low:
        risks.append(Risk("STATUS_REORG", "critical", "Реорганизация",
                          status_name, "Статус", UNCONDITIONAL, "ЕГРЮЛ"))
    elif "действ" in low:
        positives.append("Организация действующая")

    if _get(d, "ЮрАдрес", "Недост"):
        risks.append(Risk("ADDR_INVALID", "critical", "Недостоверный юридический адрес",
                          _get(d, "ЮрАдрес", "НедостОпис") or "ФНС отметила недостоверность",
                          "Адрес", UNCONDITIONAL, "ЕГРЮЛ"))

    for r in d.get("Руковод") or []:
        fio = r.get("ФИО") or "руководитель"
        if r.get("Недост"):
            risks.append(Risk("LEADER_INVALID", "critical",
                              f"Недостоверные сведения о руководителе ({fio})",
                              r.get("НедостОпис") or "", "Руководитель", UNCONDITIONAL, "ЕГРЮЛ"))
        if r.get("ДисквЛицо"):
            risks.append(Risk("LEADER_DISQ", "critical", f"Дисквалифицированный руководитель ({fio})",
                              f"{r.get('ДисквДатаНач','')}–{r.get('ДисквДатаОконч','')}",
                              "Руководитель", UNCONDITIONAL, "ЕГРЮЛ"))

    if d.get("НедобПост"):
        risks.append(Risk("RNP", "critical", "В реестре недобросовестных поставщиков",
                          _rnp_summary(d), "Госзакупки", UNCONDITIONAL, "ЕИС / РНП"))

    efrsb = d.get("ЕФРСБ") or []
    if efrsb:
        risks.append(Risk("EFRSB", "critical", "Сообщения в реестре банкротств (ЕФРСБ)",
                          f"{len(efrsb)} сообщений", "Банкротство", UNCONDITIONAL, "ЕФРСБ"))

    if d.get("НелегалФин"):
        risks.append(Risk("ILLEGAL_FIN", "critical",
                          "Признак нелегальной деятельности на финансовом рынке",
                          d.get("НелегалФинСтатус") or "по данным ЦБ РФ",
                          "Регулятор", UNCONDITIONAL, "ЦБ РФ"))

    mass_addr = _get(d, "ЮрАдрес", "МассАдрес") or []
    if len(mass_addr) > 10:
        risks.append(Risk("ADDR_MASS", "high", "Массовый юридический адрес",
                          f"{len(mass_addr)} организаций по тому же адресу",
                          "Адрес", CONDITIONAL, "ЕГРЮЛ"))
    elif len(mass_addr) > 3:
        risks.append(Risk("ADDR_SHARED", "low", "Адрес используется несколькими организациями",
                          f"{len(mass_addr)} организаций", "Адрес", INFO, "ЕГРЮЛ"))

    for r in d.get("Руковод") or []:
        fio = r.get("ФИО") or "руководитель"
        if r.get("МассРуковод"):
            risks.append(Risk("LEADER_MASS", "high", f"Массовый руководитель ({fio})",
                              "ФНС включила в список массовых руководителей",
                              "Руководитель", CONDITIONAL, "ЕГРЮЛ"))
        linked = (r.get("СвязРуковод") or []) + (r.get("СвязУчред") or [])
        if len(linked) > 20:
            risks.append(Risk("LEADER_MANY_LINKS", "medium",
                              f"Руководитель связан с {len(linked)} организациями ({fio})",
                              "Требует проверки связанных юрлиц",
                              "Связи", CONDITIONAL, "ЕГРЮЛ / /person"))

    if d.get("МассУчред"):
        risks.append(Risk("FOUNDER_MASS", "medium", "Есть массовые учредители",
                          "ФНС отметила учредителей как массовых",
                          "Учредители", CONDITIONAL, "ЕГРЮЛ"))

    if _get(d, "Статус", "ОгрДоступ") is False:
        risks.append(Risk("OGR_HIDDEN", "high", "Ограничен доступ к сведениям ЕГРЮЛ",
                          "ФНС ограничила раскрытие данных",
                          "Доступ", CONDITIONAL, "ЕГРЮЛ"))

    try:
        if subject["reg_date"]:
            rd = datetime.strptime(subject["reg_date"], "%d.%m.%Y")
            if (datetime.now() - rd).days < 365:
                risks.append(Risk("YOUNG", "medium", "Срок деятельности менее 1 года",
                                  f"Дата регистрации {subject['reg_date']}",
                                  "Регистрация", CONDITIONAL, "ЕГРЮЛ"))
    except (ValueError, TypeError):
        pass

    debt_raw = _get(d, "Налоги", "СумНедоим")
    try:
        debt = float(debt_raw) if debt_raw not in (None, "", "—", "-") else 0.0
    except (TypeError, ValueError):
        debt = 0.0
    if debt > 0:
        risks.append(Risk("TAX_DEBT", "high" if debt >= 100_000 else "medium",
                          "Задолженность по налогам",
                          f"{_fmt_money(debt)} на {_get(d,'Налоги','НедоимДата') or 'дату сведений'}",
                          "Налоги", CONDITIONAL, "ФНС «Проверь себя и контрагента»"))
    else:
        positives.append("Нет сведений о налоговой задолженности")

    blocked_accounts = _eval_blocked_accounts(risks, positives, extra)
    if blocked_accounts and blocked_accounts.get("error"):
        missing.append(f"Проверка блокировки счетов: {blocked_accounts['error']}")

    sro_data = extra.get("sro")
    if sro_data:
        okved = (subject.get("okved") or "").strip()
        needs_sro = okved.startswith(("41", "42", "43", "71.11", "71.12"))
        if sro_data.get("error"):
            missing.append(f"Проверка СРО: {sro_data['error']}")
        elif sro_data.get("found"):
            status = (sro_data.get("status") or "").lower()
            is_member = "является членом" in status
            is_excluded = not is_member and ("исключ" in status or sro_data.get("stop_reason"))
            sro_name = sro_data.get("sro_name") or "—"
            details = [sro_name]
            if sro_data.get("sro_type"): details.append(sro_data["sro_type"])
            if sro_data.get("reg_number"): details.append(f"рег. № {sro_data['reg_number']}")
            if sro_data.get("sro_date"): details.append(f"от {sro_data['sro_date']}")
            sro_details = ", ".join(str(p) for p in details)
            if is_member:
                positives.append(f"Является членом СРО: {sro_details}")
            elif is_excluded:
                risks.append(Risk("SRO_EXCLUDED", "high", "Исключён из СРО",
                                  f"{sro_details}. Причина: {sro_data.get('stop_reason') or sro_data.get('status')}",
                                  "СРО", CONDITIONAL, sro_data.get("source", "DataNewton")))
            elif needs_sro:
                risks.append(Risk("SRO_NOT_MEMBER", "high",
                                  "Не является членом СРО (обязательно для строительных/проектных работ)",
                                  sro_data.get("status", "статус не определён"),
                                  "СРО", CONDITIONAL, sro_data.get("source", "DataNewton")))
        elif needs_sro:
            risks.append(Risk("SRO_NOT_FOUND", "high",
                              "Членство в СРО не найдено (обязательно для данного ОКВЭД)",
                              "DataNewton не вернул записей о членстве в СРО",
                              "СРО", CONDITIONAL, sro_data.get("source", "DataNewton")))

    fssp_data = extra.get("fssp")
    fssp_summary = None
    if fssp_data:
        if fssp_data.get("error"):
            missing.append(f"Проверка ФССП: {fssp_data['error']}")
        elif fssp_data.get("found"):
            by_cat = fssp_data.get("by_category") or {}
            open_count = fssp_data.get("open_count", 0)
            open_sum = fssp_data.get("open_sum", 0.0)
            closed_count = fssp_data.get("closed_count", 0)
            closed_initial_sum = fssp_data.get("closed_initial_sum", 0.0)
            total_fssp = fssp_data.get("total", 0)
            loaded_fssp = fssp_data.get("loaded_count", closed_count + open_count)
            is_partial = fssp_data.get("is_partial", False)

            fssp_summary = {
                "total": total_fssp,
                "loaded_count": loaded_fssp,
                "is_partial": is_partial,
                "open_count": open_count, "open_sum": open_sum,
                "closed_count": closed_count,
                "closed_initial_sum": closed_initial_sum,
                "unknown_count": fssp_data.get("unknown_count", 0),
                "by_category": by_cat,
                "items": fssp_data.get("items") or [],
            }

            suffix = f" (загружено {loaded_fssp} из {total_fssp})" if is_partial else ""

            fin = extra.get("finances") or {}
            fin_data = fin.get("data") if "_error" not in fin else None
            revenue_for_fssp = None
            if fin_data:
                years_f = _years(fin_data)
                if years_f:
                    revenue_for_fssp = _v(fin_data[years_f[-1]], 2110)

            salary = by_cat.get("salary") or {}
            if salary.get("open", 0) > 0:
                sev, stop = _fssp_severity(salary.get("open_sum", 0), revenue_for_fssp)
                if sev == "low":
                    sev, stop = "medium", CONDITIONAL
                risks.append(Risk(
                    "FSSP_SALARY", sev,
                    "Действующая задолженность по заработной плате (ФССП)",
                    f"{salary['open']} открытых ИП на {_fmt_money(salary.get('open_sum'))}{suffix}",
                    "ФССП", stop, "DataNewton / ФССП"))

            tax = by_cat.get("tax") or {}
            if tax.get("open", 0) > 0:
                sev, stop = _fssp_severity(tax.get("open_sum", 0), revenue_for_fssp)
                if sev == "low":
                    sev, stop = "medium", CONDITIONAL
                risks.append(Risk(
                    "FSSP_TAX", sev,
                    "Взыскание налогов и страховых взносов через ФССП",
                    f"{tax['open']} открытых ИП на {_fmt_money(tax.get('open_sum'))}{suffix}",
                    "ФССП", stop, "DataNewton / ФССП"))

            utility = by_cat.get("utility") or {}
            if utility.get("open", 0) > 0:
                sev, stop = _fssp_severity(utility.get("open_sum", 0), revenue_for_fssp)
                risks.append(Risk(
                    "FSSP_UTILITY", sev,
                    "Действующая задолженность по коммунальным платежам (ФССП)",
                    f"{utility['open']} открытых ИП на {_fmt_money(utility.get('open_sum'))}{suffix}",
                    "ФССП", stop, "DataNewton / ФССП"))

            credit = by_cat.get("credit") or {}
            if credit.get("open", 0) > 0:
                sev, stop = _fssp_severity(credit.get("open_sum", 0), revenue_for_fssp)
                risks.append(Risk(
                    "FSSP_CREDIT", sev,
                    "Действующая задолженность по кредитам (ФССП)",
                    f"{credit['open']} открытых ИП на {_fmt_money(credit.get('open_sum'))}{suffix}",
                    "ФССП", stop, "DataNewton / ФССП"))

            arrest = by_cat.get("arrest") or {}
            if arrest.get("open", 0) > 0:
                risks.append(Risk(
                    "FSSP_ARREST", "high",
                    "Действующий арест имущества (ФССП)",
                    f"{arrest['open']} производств{suffix}",
                    "ФССП", CONDITIONAL, "DataNewton / ФССП"))

            search = by_cat.get("search") or {}
            if search.get("open", 0) > 0:
                risks.append(Risk(
                    "FSSP_SEARCH", "high",
                    "Действующий розыск имущества (ФССП)",
                    f"{search['open']} производств{suffix}",
                    "ФССП", CONDITIONAL, "DataNewton / ФССП"))

            exec_fee = by_cat.get("exec_fee") or {}
            if exec_fee.get("open", 0) > 0:
                risks.append(Risk(
                    "FSSP_EXEC_FEE", "medium",
                    "Взыскивается исполнительский сбор",
                    f"{exec_fee['open']} производств на {_fmt_money(exec_fee.get('open_sum'))}{suffix}",
                    "ФССП", INFO, "DataNewton / ФССП"))

            generic = by_cat.get("generic") or {}
            if generic.get("open", 0) > 0:
                sev, stop = _fssp_severity(generic.get("open_sum", 0), revenue_for_fssp)
                risks.append(Risk(
                    "FSSP_OPEN", sev,
                    "Действующие исполнительные производства (имущественные взыскания)",
                    f"{generic['open']} ИП на {_fmt_money(generic.get('open_sum'))}{suffix}",
                    "ФССП", stop, "DataNewton / ФССП"))

            fees = by_cat.get("fees") or {}
            fine = by_cat.get("fine") or {}
            if fees.get("open", 0) or fine.get("open", 0):
                parts = []
                if fees.get("open"): parts.append(f"госпошлина/издержки: {fees['open']}")
                if fine.get("open"): parts.append(f"штрафы: {fine['open']}")
                risks.append(Risk(
                    "FSSP_FINES", "low",
                    "Действующие производства по штрафам и сборам",
                    "; ".join(parts) + suffix,
                    "ФССП", INFO, "DataNewton / ФССП"))

            bankruptcy = by_cat.get("bankruptcy") or {}
            if bankruptcy.get("closed", 0) > 0:
                risks.append(Risk(
                    "FSSP_BANKRUPTCY_HISTORY", "medium",
                    "Исполнительные производства, закрытые в связи с банкротством",
                    f"{bankruptcy['closed']} производств с категорией BANKRUPTCY{suffix}",
                    "ФССП", INFO, "DataNewton / ФССП"))

            for cat, label, code in [
                ("arrest", "арест имущества", "FSSP_ARREST_HISTORY"),
                ("search", "розыск имущества", "FSSP_SEARCH_HISTORY"),
                ("utility", "коммунальные платежи", "FSSP_UTILITY_HISTORY"),
                ("credit", "кредитные платежи", "FSSP_CREDIT_HISTORY"),
                ("salary", "заработная плата", "FSSP_SALARY_HISTORY"),
                ("tax", "налоги и взносы", "FSSP_TAX_HISTORY"),
            ]:
                c = by_cat.get(cat) or {}
                if c.get("open", 0) == 0 and c.get("closed", 0) > 0:
                    n = c["closed"]
                    sev = "medium" if n >= 3 else "low"
                    risks.append(Risk(
                        code, sev,
                        f"История: {label} ({n})",
                        f"{n} закрытых производств" +
                        (f" на общую сумму {_fmt_money(c.get('closed_sum'))}" if c.get("closed_sum") else "")
                        + suffix,
                        "ФССП", INFO, "DataNewton / ФССП"))

            no_debtor = sum(
                1 for item in fssp_data.get("items") or []
                if (item.get("closure_category") or "").upper() == "NO_DEBTOR_FOUND"
            )
            if no_debtor > 0:
                risks.append(Risk(
                    "FSSP_NO_DEBTOR", "low",
                    "Приставы не находили должника по адресу",
                    f"{no_debtor} производств закрыты с категорией NO_DEBTOR_FOUND{suffix}",
                    "ФССП", INFO, "DataNewton / ФССП"))

            has_history_issues = (
                bankruptcy.get("closed", 0) or arrest.get("closed", 0)
                or search.get("closed", 0) or exec_fee.get("closed", 0)
                or utility.get("closed", 0) or salary.get("closed", 0)
                or tax.get("closed", 0) or credit.get("closed", 0)
            )
            if open_count == 0 and closed_count > 0 and not is_partial and not has_history_issues:
                sum_str = f"на общую сумму {_fmt_money(closed_initial_sum)}" if closed_initial_sum else ""
                positives.append(
                    f"Исполнительные производства ({closed_count}) все завершены"
                    + (f", {sum_str}" if sum_str else ""))

    if d.get("Санкции"):
        countries = ", ".join(d.get("СанкцииСтраны") or []) or "страны не указаны"
        risks.append(Risk("SANCTIONS", "medium", "Организация под санкциями",
                          countries, "Санкции", CONDITIONAL, "Санкционные списки"))

    try:
        capital = float(subject["capital"]) if subject["capital"] not in (None, "") else 0.0
    except (TypeError, ValueError):
        capital = 0.0
    if 0 < capital < 10_000:
        risks.append(Risk("CAPITAL_LOW", "low", "Минимальный уставный капитал",
                          _fmt_money(capital), "Устав", INFO, "ЕГРЮЛ"))

    fin = extra.get("finances") or {}
    fin_data = fin.get("data") if "_error" not in fin else None
    fin_rows: list[dict] = []
    if not fin_data:
        missing.append("Финансовая отчётность")
        if "YOUNG" not in [r.code for r in risks]:
            risks.append(Risk("NO_FIN", "high", "Финансовая отчётность отсутствует",
                              "ГИРБО не вернул данные", "Финансы", CONDITIONAL, "ГИРБО"))
    else:
        fin_rows = _check_finances(risks, positives, fin_data)

    _eval_extra_fields(risks, positives, subject, base, fin_rows)

    legal = extra.get("legal_defendant") or {}
    if "_error" in legal:
        missing.append("Арбитражные дела")
    else:
        records = (legal.get("data") or {}).get("Записи") or []
        if records:
            total = sum(r.get("СуммИск") or 0 for r in records)
            revenue = _last_revenue(fin_rows)
            if revenue and revenue > 0:
                ratio = total / revenue
                if ratio >= 0.15:
                    sev = "high"
                elif ratio >= 0.05:
                    sev = "medium"
                else:
                    sev = "low"
                risks.append(Risk("COURT_DEFENDANT", sev,
                                  "Судебные иски к организации (за 3 года)",
                                  f"{len(records)} дел на сумму {_fmt_money(total)} "
                                  f"({ratio * 100:.1f}% от выручки)",
                                  "Суды",
                                  CONDITIONAL if sev != "low" else INFO,
                                  "КАД"))
            elif total > 1_000_000 or len(records) >= 5:
                risks.append(Risk("COURT_DEFENDANT", "high",
                                  "Негативная судебная практика (за 3 года)",
                                  f"{len(records)} дел на сумму {_fmt_money(total)}",
                                  "Суды", CONDITIONAL, "КАД"))
            else:
                risks.append(Risk("COURT_DEFENDANT", "low",
                                  "Единичные иски к организации",
                                  f"{len(records)} дел на сумму {_fmt_money(total)}",
                                  "Суды", INFO, "КАД"))

    bnk = extra.get("bankruptcy") or {}
    if "_error" in bnk:
        missing.append("Записи ЕФРСБ")
    else:
        records = (bnk.get("data") or {}).get("Записи") or []
        if records:
            types = sorted({r.get("ТипНаим", "") for r in records if r.get("ТипНаим")})
            risks.append(Risk("BANKRUPTCY", "critical", "Процедура банкротства",
                              f"{len(records)} сообщений: {', '.join(types[:3])}",
                              "Банкротство", UNCONDITIONAL, "ЕФРСБ"))

    insp = extra.get("inspections") or {}
    if "_error" in insp:
        missing.append("Проверки и КНМ")
    else:
        insp_data = insp.get("data") or {}
        records = insp_data.get("Записи") or []
        declared = insp_data.get("ЗапВсего") or len(records)
        viol = [r for r in records if r.get("Наруш")]

        if viol:
            severity = "high" if len(viol) >= 2 else "medium"
            risks.append(Risk(
                "INSPECTIONS_VIOLATIONS", severity,
                "Выявлены нарушения при проверках",
                f"{len(viol)} проверок с нарушениями из {declared}",
                "Проверки", CONDITIONAL, "Единый реестр проверок"))
        elif records:
            positives.append(f"Проверки ({declared}) без выявленных нарушений")
        elif declared == 0:
            positives.append("Проверки не проводились")

    contracts_summary = None
    plaintiff_summary = None
    related_summary = None
    fedresurs_summary = None
    if check_type == "full":
        contracts_summary = _eval_contracts(risks, positives, extra)
        plaintiff_summary = _eval_plaintiff(risks, extra, fin_rows)
        related_summary = _eval_related(risks, positives, extra)

        fedresurs_summary = _eval_fedresurs(risks, positives, extra)
        if fedresurs_summary is None:
            fed = extra.get("fedresurs") or {}
            if "_error" in fed:
                missing.append(f"Федресурс: {fed['_error']}")

        third = extra.get("third_party")
        if third and third.get("found"):
            total = third.get("total", 0)
            considering = third.get("considering", 0)
            risks.append(Risk(
                "THIRD_PARTY_CASES", "low",
                "Участие в арбитражных делах в роли третьего лица",
                f"{total} дел в роли третьего лица"
                + (f", из них {considering} рассматривается" if considering else "")
                + " — проверить характер споров",
                "Суды", INFO, "DataNewton / КАД"))

            bankruptcy_cases = third.get("bankruptcy_cases", 0)
            if bankruptcy_cases > 0:
                risks.append(Risk(
                    "ARBITRATION_BANKRUPTCY", "low",
                    "Участие в делах о банкротстве",
                    f"{bankruptcy_cases} дел о банкротстве в любой роли",
                    "Суды", INFO, "DataNewton / КАД"))
        elif third and not third.get("error"):
            positives.append("Не участвует в арбитражных делах как третье лицо")

        person = extra.get("person")
        if person:
            links = (person.get("Руковод") or []) + (person.get("Учред") or [])
            n = len(links)
            if n > 30:
                risks.append(Risk(
                    "LEADER_MANY_CONNECTIONS", "medium",
                    f"Руководитель связан с {n} организациями",
                    "Высокая связанность руководителя — риск номинальности",
                    "Связи", CONDITIONAL, "Checko /person"))
            elif n > 10:
                positives.append(f"Руководитель связан с {n} организациями (в пределах нормы)")

    rel = extra.get("reliability") or {}
    rel_out = None
    if "_error" not in rel and rel.get("data"):
        rel_out = {
            "scale": rel["data"].get("Масштаб"),
            "financial_risk": (rel["data"].get("ФинРиски") or {}).get("Наим"),
            "nominality": (rel["data"].get("Номинальность") or {}).get("Наим"),
            "balance": rel["data"].get("Баланс"),
        }

    not_covered = _NOT_COVERED_COMMON + _NOT_COVERED_ORG
    if check_type == "express":
        not_covered = _NOT_COVERED_COMMON + _NOT_COVERED_EXPRESS + _NOT_COVERED_ORG

    res = Result("company", subject, risks, positives, missing,
                 not_covered, fin_rows, rel_out)
    res.check_type = check_type
    res.fssp = fssp_summary
    res.contracts_summary = contracts_summary
    res.plaintiff_summary = plaintiff_summary
    res.related_summary = related_summary
    res.fedresurs = fedresurs_summary
    res.blocked_accounts = blocked_accounts

    if check_type == "monitoring":
        _apply_monitoring(res, extra.get("previous"))

    return _finalize(res)


def _eval_entrepreneur(base: dict, extra: dict) -> Result:
    risks: list[Risk] = []
    positives: list[str] = []
    missing: list[str] = []
    check_type = extra.get("check_type", "express")

    d = base
    status_name = _get(d, "Статус", "Наим") or ""

    address = d.get("НасПункт") or _get(d, "ЮрАдрес", "АдресРФ") or ""

    rms = d.get("РМСП")
    msme = False
    if isinstance(rms, dict) and rms.get("Кат"):
        msme = {
            "category": rms.get("Кат"),
            "included_date": rms.get("ДатаВкл"),
        }

    trademarks = [
        {"id": t.get("ID"), "date": t.get("ДатаРег"), "valid_to": t.get("ДатаОконч")}
        for t in (d.get("ТоварЗнак") or [])
    ]

    contacts = _normalize_contacts(d)

    subject = {
        "type": "ИП",
        "inn": d.get("ИНН"),
        "ogrn": d.get("ОГРНИП"),
        "name_full": d.get("ФИО"),
        "name_short": d.get("ФИО"),
        "status": status_name,
        "reg_date": d.get("ДатаРег"),
        "egrul_date": d.get("ДатаВып"),
        "region": _get(d, "Регион", "Наим"),
        "address": address,
        "okved": _get(d, "ОКВЭД", "Код"),
        "okved_name": _get(d, "ОКВЭД", "Наим"),
        "tax_regimes": _get(d, "Налоги", "ОсобРежим") or [],
        "contacts": contacts,
        "licenses": [
            {"number": lic.get("Номер"), "activities": lic.get("ВидДеят") or [],
             "date": lic.get("Дата"), "valid_to": lic.get("ДатаОконч"),
             "authority": lic.get("ЛицОрг")}
            for lic in (d.get("Лиценз") or [])
        ],
        "trademarks": trademarks,
        "branches": [],
        "representative_offices": [],
        "predecessors": [],
        "successors": [],
        "founders": {},
        "shareholder_registrar": None,
        "msme": msme,
        "schr": None,
        "tax_paid": _get(d, "Налоги", "СумУпл"),
        "tax_paid_details": _get(d, "Налоги", "СведУпл") or [],
    }

    low = status_name.lower()
    if "прекращ" in low or _get(d, "Прекращ", "Дата"):
        risks.append(Risk("STATUS_DEAD", "critical", "Деятельность ИП прекращена",
                          status_name, "Статус", UNCONDITIONAL, "ЕГРИП"))
    elif "действ" in low:
        positives.append("ИП действующий")

    try:
        if subject["reg_date"]:
            rd = datetime.strptime(subject["reg_date"], "%d.%m.%Y")
            if (datetime.now() - rd).days < 365:
                risks.append(Risk("YOUNG", "medium", "Срок деятельности менее 1 года",
                                  f"Дата регистрации {subject['reg_date']}",
                                  "Регистрация", CONDITIONAL, "ЕГРИП"))
    except (ValueError, TypeError):
        pass

    if d.get("НедобПост"):
        risks.append(Risk("RNP", "critical", "В реестре недобросовестных поставщиков",
                          _rnp_summary(d), "Госзакупки", UNCONDITIONAL, "ЕИС / РНП"))
    if d.get("ЕФРСБ"):
        risks.append(Risk("EFRSB", "critical", "Сообщения ЕФРСБ",
                          f"{len(d['ЕФРСБ'])} сообщений", "Банкротство", UNCONDITIONAL, "ЕФРСБ"))
    if d.get("МассРуковод"):
        risks.append(Risk("MASS_LEADER", "high", "ИП в списке массовых руководителей",
                          "ФНС отметила как массового руководителя",
                          "Руководитель", CONDITIONAL, "ЕГРИП"))
    if d.get("МассУчред"):
        risks.append(Risk("MASS_FOUNDER", "medium", "ИП в списке массовых учредителей",
                          "ФНС отметила как массового учредителя",
                          "Учредитель", CONDITIONAL, "ЕГРИП"))

    sro_data = extra.get("sro")
    if sro_data:
        if sro_data.get("error"):
            missing.append(f"Проверка СРО: {sro_data['error']}")
        elif sro_data.get("found"):
            status = (sro_data.get("status") or "").lower()
            if "является членом" in status:
                positives.append(f"Является членом СРО: {sro_data.get('sro_name') or '—'}")
            elif "исключ" in status or sro_data.get("stop_reason"):
                risks.append(Risk("SRO_EXCLUDED", "high", "Исключён из СРО",
                                  f"{sro_data.get('sro_name') or '—'}. {sro_data.get('stop_reason') or status}",
                                  "СРО", CONDITIONAL, sro_data.get("source", "DataNewton")))

    fssp_data = extra.get("fssp")
    fssp_summary = None
    if fssp_data and not fssp_data.get("error") and fssp_data.get("found"):
        by_cat = fssp_data.get("by_category") or {}
        oc = fssp_data.get("open_count", 0)
        os_ = fssp_data.get("open_sum", 0.0)
        cc = fssp_data.get("closed_count", 0)
        cs = fssp_data.get("closed_initial_sum", 0.0)
        fssp_summary = {"total": fssp_data.get("total", 0),
                        "loaded_count": fssp_data.get("loaded_count", oc + cc),
                        "is_partial": fssp_data.get("is_partial", False),
                        "open_count": oc, "open_sum": os_,
                        "closed_count": cc, "closed_initial_sum": cs,
                        "unknown_count": fssp_data.get("unknown_count", 0),
                        "by_category": by_cat,
                        "items": fssp_data.get("items") or []}

        salary = by_cat.get("salary") or {}
        if salary.get("open", 0) > 0:
            risks.append(Risk("FSSP_SALARY", "high",
                              "Действующая задолженность по заработной плате (ФССП)",
                              f"{salary['open']} открытых ИП на {_fmt_money(salary.get('open_sum'))}",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        tax = by_cat.get("tax") or {}
        if tax.get("open", 0) > 0:
            risks.append(Risk("FSSP_TAX", "high",
                              "Взыскание налогов и страховых взносов через ФССП",
                              f"{tax['open']} открытых ИП на {_fmt_money(tax.get('open_sum'))}",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        utility = by_cat.get("utility") or {}
        if utility.get("open", 0) > 0:
            sev = "high" if utility.get("open_sum", 0) > 1_000_000 else "medium"
            risks.append(Risk("FSSP_UTILITY", sev,
                              "Действующая задолженность по коммунальным платежам (ФССП)",
                              f"{utility['open']} открытых ИП на {_fmt_money(utility.get('open_sum'))}",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        credit = by_cat.get("credit") or {}
        if credit.get("open", 0) > 0:
            sev = "high" if credit.get("open_sum", 0) > 1_000_000 else "medium"
            risks.append(Risk("FSSP_CREDIT", sev,
                              "Действующая задолженность по кредитам (ФССП)",
                              f"{credit['open']} открытых ИП на {_fmt_money(credit.get('open_sum'))}",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        generic = by_cat.get("generic") or {}
        if generic.get("open", 0) > 0:
            sev = "high" if generic.get("open_sum", 0) > 500_000 else "medium"
            risks.append(Risk("FSSP_OPEN", sev,
                              "Действующие исполнительные производства (имущественные взыскания)",
                              f"{generic['open']} ИП на {_fmt_money(generic.get('open_sum'))}",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        arrest = by_cat.get("arrest") or {}
        if arrest.get("open", 0) > 0:
            risks.append(Risk("FSSP_ARREST", "high", "Действующий арест имущества (ФССП)",
                              f"{arrest['open']} производств",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        search = by_cat.get("search") or {}
        if search.get("open", 0) > 0:
            risks.append(Risk("FSSP_SEARCH", "high", "Действующий розыск имущества (ФССП)",
                              f"{search['open']} производств",
                              "ФССП", CONDITIONAL, "DataNewton / ФССП"))

        exec_fee = by_cat.get("exec_fee") or {}
        if exec_fee.get("open", 0) > 0:
            risks.append(Risk("FSSP_EXEC_FEE", "medium",
                              "Взыскивается исполнительский сбор",
                              f"{exec_fee['open']} производств на {_fmt_money(exec_fee.get('open_sum'))}",
                              "ФССП", INFO, "DataNewton / ФССП"))

        bankruptcy = by_cat.get("bankruptcy") or {}
        if bankruptcy.get("closed", 0) > 0:
            risks.append(Risk("FSSP_BANKRUPTCY_HISTORY", "medium",
                              "Исполнительные производства, закрытые в связи с банкротством",
                              f"{bankruptcy['closed']} производств с категорией BANKRUPTCY",
                              "ФССП", INFO, "DataNewton / ФССП"))

        arrest_h = by_cat.get("arrest") or {}
        if arrest_h.get("open", 0) == 0 and arrest_h.get("closed", 0) > 0:
            n = arrest_h["closed"]
            sev = "medium" if n >= 3 else "low"
            risks.append(Risk("FSSP_ARREST_HISTORY", sev,
                              f"История: арест имущества ({n})",
                              f"{n} закрытых производств",
                              "ФССП", INFO, "DataNewton / ФССП"))

        search_h = by_cat.get("search") or {}
        if search_h.get("open", 0) == 0 and search_h.get("closed", 0) > 0:
            n = search_h["closed"]
            sev = "medium" if n >= 2 else "low"
            risks.append(Risk("FSSP_SEARCH_HISTORY", sev,
                              f"История: розыск имущества ({n})",
                              f"{n} закрытых производств",
                              "ФССП", INFO, "DataNewton / ФССП"))

        if cc > 0 and oc == 0 and not bankruptcy.get("closed", 0) and not exec_fee.get("closed", 0):
            positives.append(f"Исполнительные производства ({cc}) завершены")
    elif fssp_data and fssp_data.get("error"):
        missing.append(f"Проверка ФССП: {fssp_data['error']}")

    bnk = extra.get("bankruptcy") or {}
    if "_error" in bnk:
        missing.append("Записи ЕФРСБ")
    elif (bnk.get("data") or {}).get("Записи"):
        risks.append(Risk("BANKRUPTCY", "critical", "Записи о банкротстве",
                          f"{len(bnk['data']['Записи'])} сообщений",
                          "Банкротство", UNCONDITIONAL, "ЕФРСБ"))

    legal = extra.get("legal_defendant") or {}
    if "_error" in legal:
        missing.append("Арбитражные дела")
    elif (legal.get("data") or {}).get("Записи"):
        records = legal["data"]["Записи"]
        total = sum(r.get("СуммИск") or 0 for r in records)
        stop = CONDITIONAL if total > 500_000 or len(records) >= 3 else INFO
        risks.append(Risk("COURT_DEFENDANT", "high" if stop == CONDITIONAL else "low",
                          "Иски к ИП (за 3 года)", f"{len(records)} дел на {_fmt_money(total)}",
                          "Суды", stop, "КАД"))

    insp = extra.get("inspections") or {}
    if "_error" in insp:
        missing.append("Проверки и КНМ")
    else:
        insp_data = insp.get("data") or {}
        records = insp_data.get("Записи") or []
        declared = insp_data.get("ЗапВсего") or len(records)
        viol = [r for r in records if r.get("Наруш")]
        if viol:
            risks.append(Risk("INSPECTIONS", "high" if len(viol) >= 2 else "medium",
                              "Выявлены нарушения при проверках",
                              f"{len(viol)} проверок с нарушениями из {declared}",
                              "Проверки", CONDITIONAL, "Единый реестр проверок"))

    _eval_extra_fields(risks, positives, subject, base, None)

    contracts_summary = None
    plaintiff_summary = None
    if check_type == "full":
        contracts_summary = _eval_contracts(risks, positives, extra)
        plaintiff_summary = _eval_plaintiff(risks, extra, None)

    not_covered = _NOT_COVERED_COMMON + [
        "ИП как руководитель/участник проблемных должников Общества (внутренние данные)",
        "Наличие просроченной дебиторской задолженности перед Обществом (внутренние данные)",
        "Факты недобросовестного исполнения перед Обществом за последние 3 года (внутренние данные)",
        "Среднесписочная численность для ИП не отдаётся — ЕГРИП не содержит этого поля",
    ]
    if check_type == "express":
        not_covered = not_covered + _NOT_COVERED_EXPRESS

    res = Result("entrepreneur", subject, risks, positives, missing, not_covered)
    res.check_type = check_type
    res.fssp = fssp_summary
    res.contracts_summary = contracts_summary
    res.plaintiff_summary = plaintiff_summary

    if check_type == "monitoring":
        _apply_monitoring(res, extra.get("previous"))

    return _finalize(res)


def _compute_changes(previous: dict, current: Result) -> list[dict]:
    prev_risks = {r.get("code"): r for r in (previous.get("risks") or [])}
    curr_risks = {r.code: r for r in current.risks}
    changes: list[dict] = []

    for code, r in curr_risks.items():
        if code not in prev_risks:
            sev = "critical" if r.stop_type == UNCONDITIONAL else ("warning" if r.stop_type == CONDITIONAL else "info")
            changes.append({"field": f"new_{code}", "title": f"Новый риск: {r.title}",
                            "old": None, "new": r.evidence, "severity": sev})
        elif prev_risks[code].get("evidence") != r.evidence:
            changes.append({"field": f"changed_{code}", "title": f"Изменились данные: {r.title}",
                            "old": prev_risks[code].get("evidence"), "new": r.evidence,
                            "severity": "info"})

    for code, pr in prev_risks.items():
        if code not in curr_risks:
            changes.append({"field": f"resolved_{code}", "title": f"Риск устранён: {pr.get('title')}",
                            "old": pr.get("title"), "new": None, "severity": "info"})
    return changes


def _apply_monitoring(result: Result, previous: dict | None) -> None:
    result.previous_found = previous is not None
    if not previous:
        result.monitoring_recommendation = (
            "Нет предыдущей проверки — проведите полную проверку перед следующим мониторингом.")
        return

    changes = _compute_changes(previous, result)
    result.changes = changes

    critical = [c for c in changes if c["severity"] == "critical"]
    warning = [c for c in changes if c["severity"] == "warning"]

    if critical:
        result.monitoring_recommendation = (
            "Рассмотреть прекращение отношений: появились новые безусловные стоп-факторы.")
        result.risks.append(Risk(
            "MONITORING_NEW_CRITICAL", "critical",
            "Новые безусловные стоп-факторы с прошлой проверки",
            "; ".join(c["title"] for c in critical),
            "Мониторинг", CONDITIONAL, "Сравнение проверок"))
    elif warning:
        result.monitoring_recommendation = (
            "Усилить контроль: появились новые условные стоп-факторы.")
        result.risks.append(Risk(
            "MONITORING_NEW_WARNING", "medium",
            "Новые условные стоп-факторы с прошлой проверки",
            "; ".join(c["title"] for c in warning),
            "Мониторинг", INFO, "Сравнение проверок"))
    else:
        result.monitoring_recommendation = "Продолжать отношения: значимых изменений нет."


def build_stop_factors_comment(result: Result) -> str:
    unc = [r for r in result.risks if r.stop_type == UNCONDITIONAL]
    cond = [r for r in result.risks if r.stop_type == CONDITIONAL]
    info = [r for r in result.risks if r.stop_type == INFO]
    parts: list[str] = []

    if unc:
        parts.append(f"Безусловные стоп-факторы ({len(unc)}): "
                     + "; ".join(r.title for r in unc)
                     + ". Согласно п. 3.9.3 Положения заключение договора не допускается.")
    else:
        parts.append("Безусловных стоп-факторов не выявлено.")

    if cond:
        titles = "; ".join(r.title for r in cond)
        if len(cond) >= 2:
            parts.append(f"Условные стоп-факторы ({len(cond)}): {titles}. "
                         "Их сочетание согласно Приложению № 4 является основанием для отказа.")
        else:
            parts.append(f"Условный стоп-фактор ({len(cond)}): {titles}. "
                         "Требует условий или дополнительной проверки.")
    else:
        parts.append("Условных стоп-факторов не выявлено.")

    if info:
        parts.append(f"Информационные факторы ({len(info)}): "
                     + "; ".join(r.title for r in info) + ".")

    parts.append(f"Итоговый вердикт: {result.verdict}.")
    return " ".join(parts)