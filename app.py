import json
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from arbitration_client import ArbitrationClient
from cache import init_db
from checko_client import CheckoClient
from config import OUT_DIR
from data_newton_extra import DataNewtonExtraClient
from fssp_client import FsspClient
from gigachat_client import GigaChatClient
from report import (
    build_llm_input,
    parse_llm_json,
    render_html,
    render_markdown,
    result_to_dict,
)
from risk_engine import evaluate
from sro_client import SroClient


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Contragent Check", lifespan=lifespan)


def detect_kind(ident: str) -> str:
    n = len(ident)
    if n in (10, 13):
        return "company"
    if n in (12, 15):
        return "entrepreneur"
    raise HTTPException(400, "Ожидается ИНН (10/12) или ОГРН/ОГРНИП (13/15)")


def _load_previous(inn: str) -> dict | None:
    if not inn:
        return None
    files = sorted(OUT_DIR.glob(f"{inn}_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("check_type") in ("express", "full"):
                return data
        except Exception:
            continue
    for f in files:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


@app.get("/", response_class=HTMLResponse)
async def index():
    return (OUT_DIR.parent / "templates" / "index.html").read_text(encoding="utf-8")


@app.post("/check")
async def check(
    ident: str = Form(...),
    check_type: str = Form("express"),
    amount: str = Form("0"),
    skip_llm: bool = Form(False),
):
    ident = ident.strip().replace(" ", "")
    kind = detect_kind(ident)

    if check_type not in ("express", "full", "monitoring"):
        check_type = "express"

    try:
        amount_val = float(amount.replace(" ", "").replace(",", ".")) if amount else 0.0
    except ValueError:
        amount_val = 0.0

    async with CheckoClient() as c:
        base = await c.fetch_subject(kind, ident)
        if not base:
            raise HTTPException(404, "Checko не вернул данных по этому ИНН/ОГРН")
        inn = base.get("ИНН")
        ogrn = base.get("ОГРН") or base.get("ОГРНИП")
        extra = await c.fetch_checks(kind, inn=inn, ogrn=ogrn,
                                     check_type=check_type, base=base)

        if check_type == "full":
            arb = ArbitrationClient()
            extra["third_party"] = await arb.fetch_third_party_stats(inn)

            leader_inn = None
            for r in base.get("Руковод") or []:
                if r.get("ИНН"):
                    leader_inn = r["ИНН"]
                    break
            if leader_inn:
                try:
                    extra["person"] = await c.fetch_person(leader_inn)
                except Exception:
                    extra["person"] = None

    extra["sro"] = await SroClient().fetch_sro_data(inn)
    extra["fssp"] = await FsspClient().fetch_fssp_data(inn, ogrn)
    extra["blocked_accounts"] = await DataNewtonExtraClient().fetch_blocked_accounts(inn)
    extra["check_type"] = check_type
    extra["previous"] = _load_previous(inn) if check_type == "monitoring" else None

    result = evaluate(kind, base, extra)
    result.check_type = check_type
    result.amount = amount_val

    llm_payload = None
    llm_error = None
    if not skip_llm:
        try:
            g = GigaChatClient()
            raw = g.chat(build_llm_input(result))
            llm_payload = parse_llm_json(raw)
            if llm_payload is None:
                llm_error = f"LLM вернул не-JSON. Первые 300 символов ответа: {raw[:300]!r}"
        except Exception as e:
            llm_error = f"LLM error: {e}"

    job_id = f"{inn or ident}_{uuid.uuid4().hex[:8]}"
    data = result_to_dict(result)
    data["llm"] = llm_payload
    data["llm_error"] = llm_error
    data["job_id"] = job_id

    (OUT_DIR / f"{job_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"{job_id}.html").write_text(
        render_html(result, llm_payload, llm_error), encoding="utf-8")
    (OUT_DIR / f"{job_id}.md").write_text(
        render_markdown(result, llm_payload), encoding="utf-8")

    return {"url": f"/report/{job_id}"}


def _find_report(job_id: str, ext: str):
    p = OUT_DIR / f"{job_id}.{ext}"
    if not p.exists():
        candidates = sorted(OUT_DIR.glob(f"{job_id}_*.{ext}"), reverse=True)
        if not candidates:
            raise HTTPException(404, f"Отчёт не найден: {job_id}")
        p = candidates[0]
    return p


@app.get("/report/{job_id}", response_class=HTMLResponse)
async def report_html(job_id: str):
    return _find_report(job_id, "html").read_text(encoding="utf-8")


@app.get("/report/{job_id}/md", response_class=PlainTextResponse)
async def report_md(job_id: str):
    return _find_report(job_id, "md").read_text(encoding="utf-8")


@app.get("/report/{job_id}/json")
async def report_json(job_id: str):
    return JSONResponse(json.loads(_find_report(job_id, "json").read_text(encoding="utf-8")))


@app.get("/healthz")
async def healthz():
    return {"ok": True}