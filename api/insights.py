# api/insights.py
import os, json
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from hubspot_client import search_cooby_comms, extract_message_text, create_note
from insights_agent import generate_insights_from_transcript

API_TOKEN = os.getenv("AGENT_API_TOKEN")  # defina em Environment Variables na Vercel
app = FastAPI(title="Lastro Cooby Insights Agent (Vercel)")

class InsightsRequest(BaseModel):
    contactId: str
    createNote: bool = True
    sinceEpochMs: Optional[int] = None  # filtra mensagens recentes (ms)

def build_transcript_text(results, since_ms: Optional[int] = None) -> str:
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

@app.post("/api/insights")
def insights(req: InsightsRequest, authorization: Optional[str] = Header(None)):
    # autenticação por Bearer
    if API_TOKEN:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        if token != API_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

    try:
        comms = search_cooby_comms(req.contactId)
        transcript = build_transcript_text(comms, req.sinceEpochMs)
        if not transcript.strip():
            return {"ok": False, "reason": "NO_MESSAGES", "message": "Sem mensagens Cooby com Message text."}

        insights = generate_insights_from_transcript(transcript)

        note_id = None
        if req.createNote:
            def li(items): 
                return "".join(f"<li>{i}</li>" for i in (items or [])) or "<li>—</li>"
            next_li = "".join(f"<li>{p.get('descricao','')}</li>" for p in (insights.get("proximos_passos") or [])) or "<li>—</li>"
            html = f"""
            <h3>🤖 Insights (Cooby/WhatsApp)</h3>
            <ul>
              <li><strong>Lead pré:</strong> {insights.get('lead_scoring_pre',0)} &nbsp;|&nbsp;
                  <strong>pós:</strong> {insights.get('lead_scoring_pos',0)}</li>
              <li><strong>Classificação:</strong> {insights.get('label_interacao','-')}</li>
            </ul>
            <h4>Resumo</h4><ul>{li(insights.get('resumo_bullets'))}</ul>
            <h4>Objeções</h4><ul>{li(insights.get('principais_objeções'))}</ul>
            <h4>Sinais de fechamento</h4><ul>{li(insights.get('sinais_fechamento'))}</ul>
            <h4>Próximos passos</h4><ul>{next_li}</ul>
            <h4>Recomendações</h4><ul>{li(insights.get('recomendacoes'))}</ul>
            <h4>Trechos relevantes</h4><ul>{li(insights.get('top_snippets'))}</ul>
            """.split("\n")
            html = "\n".join([l.strip() for l in html if l.strip()])

            note_id = create_note(req.contactId, html)

        return {
            "ok": True,
            "noteId": note_id,
            "scores": {"pre": insights.get("lead_scoring_pre"), "pos": insights.get("lead_scoring_pos")},
            "label": insights.get("label_interacao"),
        }
    except Exception as e:
        return {"ok": False, "reason": "ERROR", "error": str(e)}
