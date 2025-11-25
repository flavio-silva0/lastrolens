# api/insights.py
import os, json
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from hubspot_client import (
    search_cooby_comms, extract_message_text, create_note,
    search_contact_calls, clean_call_summary_html, strip_html,
    search_contact_notes, build_elephan_block
)

from insights_agent import (
    generate_insights_from_transcript,
    generate_insights_combined,
    generate_insights_triple,   
)


API_TOKEN = os.getenv("AGENT_API_TOKEN")
app = FastAPI(title="Lastro Cooby Insights Agent (Vercel)")

class InsightsRequest(BaseModel):
    contactId: str
    createNote: bool = True
    sinceEpochMs: Optional[int] = None  # filtra itens antigos (ms desde epoch)

def build_cooby_transcript(results, since_ms: Optional[int] = None) -> str:
    msgs = []
    for r in results:
        p = r.get("properties") or {}
        ts = p.get("hs_timestamp")
        if since_ms and ts and int(ts) < since_ms:
            continue
        body = p.get("hs_communication_body", "")
        msg = extract_message_text(body)
        if msg:
            msgs.append(f"[{ts}] {msg}")
    msgs.sort()
    return "\n".join(msgs)

def build_calls_summary_block(call_results, since_ms: Optional[int] = None) -> str:
    blocks = []
    for r in call_results:
        p = r.get("properties") or {}
        ts = p.get("hs_timestamp")
        if since_ms and ts and int(ts) < since_ms:
            continue
        raw_sum  = p.get("hs_call_summary") or p.get("call_summary") or ""
        raw_body = p.get("hs_call_body") or ""
        text = clean_call_summary_html(raw_sum) if raw_sum else strip_html(raw_body)
        if text:
            blocks.append(f"[{ts}]\n{text}")
    blocks.sort()
    return "\n\n".join(blocks)

def render_note_html(title: str, insights: dict) -> str:
    def li(items): return "".join(f"<li>{i}</li>" for i in (items or [])) or "<li>—</li>"
    next_li = "".join(f"<li>{p.get('descricao','')}</li>" for p in (insights.get("proximos_passos") or [])) or "<li>—</li>"
    pre  = insights.get("lead_scoring_pre", 0)
    pos  = insights.get("lead_scoring_pos", 0)
    lab  = insights.get("label_interacao", "-")
    html = f"""
    <h3>{title}</h3>
    <ul>
      <li><strong>Lead pré:</strong> {pre} &nbsp;|&nbsp; <strong>pós:</strong> {pos}</li>
      <li><strong>Classificação:</strong> {lab}</li>
    </ul>
    <h4>Resumo</h4><ul>{li(insights.get('resumo_bullets'))}</ul>
    <h4>Objeções</h4><ul>{li(insights.get('principais_objeções'))}</ul>
    <h4>Sinais de fechamento</h4><ul>{li(insights.get('sinais_fechamento'))}</ul>
    <h4>Próximos passos</h4><ul>{next_li}</ul>
    <h4>Recomendações</h4><ul>{li(insights.get('recomendacoes'))}</ul>
    <h4>Trechos relevantes</h4><ul>{li(insights.get('top_snippets'))}</ul>
    """.split("\n")
    return "\n".join(l.strip() for l in html if l.strip())

@app.post("/api/insights")
def insights(req: InsightsRequest, authorization: Optional[str] = Header(None)):
    # auth igual está hoje...
    if API_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != API_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    try:
        # ===== 1) Cooby =====
        comms = search_cooby_comms(req.contactId)
        cooby_txt = build_cooby_transcript(comms, req.sinceEpochMs)

        insights_cooby = None
        note_id_cooby = None
        if cooby_txt.strip():
            insights_cooby = generate_insights_from_transcript(cooby_txt)
            if req.createNote:
                note_id_cooby = create_note(
                    req.contactId,
                    render_note_html("🤖 Insights (Cooby/WhatsApp)", insights_cooby)
                )

        # ===== 2) Calls =====
        calls = search_contact_calls(req.contactId)
        calls_txt = build_calls_summary_block(calls, req.sinceEpochMs)

        insights_calls = None
        note_id_calls = None
        if calls_txt.strip():
            insights_calls = generate_insights_from_transcript(calls_txt)
            if req.createNote:
                note_id_calls = create_note(
                    req.contactId,
                    render_note_html("📞 Insights (Ligações)", insights_calls)
                )

        # ===== 3) Elephan (notas do contato com 'por Elephan') =====
        notes = search_contact_notes(req.contactId)
        elephan_txt = build_elephan_block(notes, req.sinceEpochMs)

        insights_elephan = None
        note_id_elephan = None
        if elephan_txt.strip():
            insights_elephan = generate_insights_from_transcript(elephan_txt)
            if req.createNote:
                note_id_elephan = create_note(
                    req.contactId,
                    render_note_html("📝 Insights (Reunião Elephan)", insights_elephan)
                )

        # Se absolutamente nada tiver dado texto, retornamos um "no data"
        if not (cooby_txt.strip() or calls_txt.strip() or elephan_txt.strip()):
            return {
                "ok": False,
                "reason": "NO_DATA",
                "message": "Nenhum dado encontrado em Cooby, Ligações ou Elephan."
            }

        # ===== 4) Insight Geral (Cooby + Calls + Elephan) =====
        insights_general = generate_insights_triple(
            cooby_txt if cooby_txt.strip() else "",
            calls_txt if calls_txt.strip() else "",
            elephan_txt if elephan_txt.strip() else "",
        )

        note_id_general = None
        if req.createNote:
            note_id_general = create_note(
                req.contactId,
                render_note_html(
                    "🧩 Insights (Geral: WhatsApp + Ligações + Elephan)",
                    insights_general
                )
            )

        return {
            "ok": True,
            "notes": {
                "cooby": note_id_cooby,
                "calls": note_id_calls,
                "elephan": note_id_elephan,
                "geral": note_id_general,
            },
            "has_calls": bool(calls_txt.strip()),
            "has_cooby": bool(cooby_txt.strip()),
            "has_elephan": bool(elephan_txt.strip()),
            "scores": {
                "cooby_pre": (insights_cooby or {}).get("lead_scoring_pre") if insights_cooby else None,
                "cooby_pos": (insights_cooby or {}).get("lead_scoring_pos") if insights_cooby else None,
                "calls_pre": (insights_calls or {}).get("lead_scoring_pre") if insights_calls else None,
                "calls_pos": (insights_calls or {}).get("lead_scoring_pos") if insights_calls else None,
                "elephan_pre": (insights_elephan or {}).get("lead_scoring_pre") if insights_elephan else None,
                "elephan_pos": (insights_elephan or {}).get("lead_scoring_pos") if insights_elephan else None,
                "geral_pre": insights_general.get("lead_scoring_pre"),
                "geral_pos": insights_general.get("lead_scoring_pos"),
            },
        }
    except Exception as e:
        return {"ok": False, "reason": "ERROR", "error": str(e)}