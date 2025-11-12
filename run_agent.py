import argparse
from hubspot_client import search_cooby_comms, extract_message_text, create_note
from insights_agent import generate_insights_from_transcript

def build_transcript_text(results):
    msgs = []
    for r in results:
        props = r.get("properties") or {}
        body = props.get("hs_communication_body", "")
        msg = extract_message_text(body)
        if msg:
            ts = props.get("hs_timestamp", "")
            msgs.append(f"[{ts}] {msg}")
    msgs.sort()  # ordena por timestamp textual
    return "\n".join(msgs)

def format_note_html(contact_id: str, insights: dict) -> str:
    resumo_items = "".join(f"<li>{p}</li>" for p in insights.get("resumo_bullets", []) or [])
    obje_items   = "".join(f"<li>{o}</li>" for o in insights.get("principais_objeções", []) or [])
    sinais_items = "".join(f"<li>{s}</li>" for s in insights.get("sinais_fechamento", []) or [])
    next_items   = "".join(f"<li>{p.get('descricao','')}</li>" for p in insights.get("proximos_passos", []) or [])
    # campos opcionais enriquecidos (ver Patch 2 abaixo)
    recs_items   = "".join(f"<li>{r}</li>" for r in insights.get("recomendacoes", []) or [])
    snip_items   = "".join(f"<li><em>“{s}”</em></li>" for s in insights.get("top_snippets", []) or [])

    pre  = insights.get("lead_scoring_pre", 0)
    pos  = insights.get("lead_scoring_pos", 0)
    lab  = insights.get("label_interacao", "-")

    html = f"""
    <h3>🤖 Insights (Cooby/WhatsApp) — contato {contact_id}</h3>
    <ul>
      <li><strong>Lead pré:</strong> {pre} &nbsp;|&nbsp; <strong>pós:</strong> {pos}</li>
      <li><strong>Classificação:</strong> {lab}</li>
    </ul>

    <h4>Resumo</h4>
    <ul>{resumo_items or "<li>—</li>"}</ul>

    <h4>Objeções</h4>
    <ul>{obje_items or "<li>—</li>"}</ul>

    <h4>Sinais de fechamento</h4>
    <ul>{sinais_items or "<li>—</li>"}</ul>

    <h4>Próximos passos</h4>
    <ul>{next_items or "<li>—</li>"}</ul>

    {"<h4>Recomendações</h4><ul>"+(recs_items or "<li>—</li>")+"</ul>" if recs_items else ""}

    {"<h4>Trechos relevantes</h4><ul>"+(snip_items or "<li>—</li>")+"</ul>" if snip_items else ""}
    """
    # remove múltiplos espaços/linhas
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contact-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    comms = search_cooby_comms(args.contact_id)
    txt = build_transcript_text(comms)
    if not txt.strip():
        print("Sem mensagens Cooby com 'Message text:' para este contato.")
        return

    insights = generate_insights_from_transcript(txt)
    note_md = format_note_html(args.contact_id, insights)

    if args.dry_run:
        print(note_md)
    else:
        note_id = create_note(args.contact_id, note_md)
        print("Nota criada:", note_id)

if __name__ == "__main__":
    main()
