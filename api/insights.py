# api/insights.py
import os, json
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from hubspot_client import (
    search_cooby_comms, extract_message_text, create_note,
    search_contact_calls, clean_call_summary_html, strip_html
)
from insights_agent import generate_insights_from_transcript, generate_insights_combined

API_TOKEN = os.getenv("AGENT_API_TOKEN")
app = FastAPI(title="Lastro Cooby Insights Agent (Vercel)")

class InsightsRequest(BaseModel):
    contactId: str
    createNote: bool = True
    sinceEpochMs: Optional[int] = None  # filtra mensagens recentes (ms)

def build_cooby_transcript(results, since_ms: Optional[int] = None) -> str:
    msgs = []
    for r in results:
        props = r.get("properties") or {}
        ts = props.get("hs_timestamp")
        if since_ms and ts and int(ts) < since_ms:
            continue
        body = props.get("hs_communication_body", "")
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
    if API_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != API_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    try:
        # 1) WhatsApp (Cooby)
        comms = search_cooby_comms(req.contactId)
        cooby_txt = build_cooby_transcript(comms, req.sinceEpochMs)

        if not cooby_txt.strip():
            return {"ok": False, "reason": "NO_MESSAGES", "message": "Sem mensagens Cooby com Message text."}

        insights_cooby = generate_insights_from_transcript(cooby_txt)

        note_id_cooby = None
        if req.createNote:
            note_id_cooby = create_note(req.contactId, render_note_html("🤖 Insights (Cooby/WhatsApp)", insights_cooby))

        # 2) Ligações (Calls) → resumo/observações
        calls = search_contact_calls(req.contactId)
        calls_txt = build_calls_summary_block(calls, req.sinceEpochMs)

        note_id_general = None
        if calls_txt.strip():
            insights_combined = generate_insights_combined(cooby_txt, calls_txt)
            if req.createNote:
                note_id_general = create_note(req.contactId, render_note_html("🤖 Insights (Geral: WhatsApp + Ligações)", insights_combined))

        return {
            "ok": True,
            "notes": {"cooby": note_id_cooby, "geral": note_id_general},
            "scores_cooby": {"pre": insights_cooby.get("lead_scoring_pre"), "pos": insights_cooby.get("lead_scoring_pos")},
            "label_cooby": insights_cooby.get("label_interacao"),
            "has_calls": bool(calls_txt.strip())
        }
    except Exception as e:
        return {"ok": False, "reason": "ERROR", "error": str(e)}
