import os, json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_INSTRUCTIONS = (
    "Analista de vendas. Responda apenas JSON válido em pt-BR."
)

SCHEMA_EXEMPLO = {
  "resumo_bullets": ["..."],
  "principais_objeções": ["preço","prioridade"],
  "sinais_fechamento": ["timeline","budget","pedido_proposta","multi-stakeholder"],
  "proximos_passos": [{"descricao":"Enviar proposta","prazo_iso":""}],
  "label_interacao": "ruim|ok|boa",
  "lead_scoring_pre": 60,
  "lead_scoring_pos": 80,
  "recomendacoes": ["Agendar follow-up em 48h"],
  "top_snippets": ["cliente: 'temos orçamento'"]
}

def generate_insights_from_transcript(text: str) -> dict:
    prompt = (
        "Transcript (WhatsApp Cooby):\n"
        "<<<\n" + text + "\n>>>\n"
        "Retorne SOMENTE JSON seguindo este formato:\n"
        + json.dumps(SCHEMA_EXEMPLO, ensure_ascii=False)
    )
    resp = client.chat.completions.create(
        model="gpt-5-mini",  # ou gpt-4o-mini
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"}
    )
    return json.loads(resp.choices[0].message.content)
