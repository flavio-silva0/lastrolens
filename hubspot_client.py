import os, re, requests, time

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
BASE = "https://api.hubapi.com"
HDRS = {"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"}

COOBY_MSG_RE = re.compile(r"Message text:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)
ELEPHAN_RE = re.compile(r"por\s+Elephan", re.IGNORECASE)

def search_cooby_comms(contact_id: str, limit: int = 100):
    url = f"{BASE}/crm/v3/objects/communications/search"
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "associations.contact", "operator": "EQ", "value": contact_id},
                {"propertyName": "hs_communication_body", "operator": "CONTAINS_TOKEN", "value": "Cooby.co"}
            ]
        }],
        "properties": ["hs_communication_body","hs_timestamp","hs_communication_channel_type","hs_direction"],
        "limit": limit,
        "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}]
    }
    r = requests.post(url, headers=HDRS, json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def build_elephan_block(note_results, since_ms: int | None = None) -> str:
    """
    Junta todas as notas que parecem ser resumos da Elephan
    (contêm 'por Elephan') em um texto único.
    """
    blocks = []
    for r in note_results:
        p = r.get("properties") or {}
        ts = p.get("hs_timestamp")
        if since_ms and ts and int(ts) < since_ms:
            continue
        body = p.get("hs_note_body") or ""
        txt = strip_html(body)
        if txt and ELEPHAN_RE.search(txt):
            blocks.append(f"[{ts}]\n{txt}")
    blocks.sort()
    return "\n\n".join(blocks)

def extract_message_text(body: str):
    if not body:
        return None
    txt = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
    txt = re.sub(r"<.*?>", "", txt)
    m = COOBY_MSG_RE.search(txt)
    return m.group(1).strip() if m else None

def create_note(contact_id: str, html: str) -> str:
    # cria a nota e associa ao contato (v3 textual; com fallback v4 se precisar)
    # inclui hs_timestamp requerido
    url = f"{BASE}/crm/v3/objects/notes"
    now_ms = int(time.time() * 1000)
    payload = {"properties": {"hs_note_body": html, "hs_timestamp": now_ms}}
    r = requests.post(url, headers=HDRS, json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"[CreateNote] {r.status_code} {r.text}")
    note_id = r.json().get("id")
    assoc_url = f"{BASE}/crm/v3/objects/notes/{note_id}/associations/contacts/{contact_id}/note_to_contact"
    assoc = requests.put(assoc_url, headers=HDRS, timeout=30)
    if assoc.status_code == 404:
        v4_url = f"{BASE}/crm/v4/objects/notes/{note_id}/associations/contacts/{contact_id}"
        body = {"inputs": [{"types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}]}
        assoc = requests.post(v4_url, headers=HDRS, json=body, timeout=30)
    if assoc.status_code >= 300:
        raise RuntimeError(f"[AssociateNote] {assoc.status_code} {assoc.text}")
    return note_id

def search_contact_calls(contact_id: str, limit: int = 50):
    """
    Busca chamadas (calls) associadas ao contato.
    Tenta trazer 'hs_call_summary' ou 'call_summary' (se existirem) e cai para 'hs_call_body'.
    """
    url = f"{BASE}/crm/v3/objects/calls/search"
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "associations.contact", "operator": "EQ", "value": str(contact_id)}
            ]
        }],
        "properties": [
            "hs_call_title",
            "hs_call_outcome",
            "hs_call_duration",
            "hs_call_body",       # HTML das observações
            "hs_call_summary",    # alguns portais
            "call_summary",       # variação de internal name
            "hs_timestamp"
        ],
        "limit": limit,
        "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}]
    }
    r = requests.post(url, headers=HDRS, json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def search_contact_notes(contact_id: str, limit: int = 50):
    """
    Busca notas (engagements NOTE) associadas ao contato.
    Usaremos para encontrar os resumos de reunião da Elephan.
    """
    url = f"{BASE}/crm/v3/objects/notes/search"
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "associations.contact", "operator": "EQ", "value": str(contact_id)}
            ]
        }],
        "properties": ["hs_note_body", "hs_timestamp"],
        "limit": limit,
        "sorts": [{"propertyName": "hs_timestamp", "direction": "DESCENDING"}]
    }
    r = requests.post(url, headers=HDRS, json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


# ——— limpeza do HTML do summary para texto simples com bullets
_RE_BR   = re.compile(r"<br\s*/?>", re.I)
_RE_LI_1 = re.compile(r"\s*<li>\s*", re.I)
_RE_LI_2 = re.compile(r"\s*</li>\s*", re.I)
_RE_UL_OL = re.compile(r"</?(ul|ol)\s*[^>]*>", re.I)
_RE_H = re.compile(r"</?h[1-6]\s*[^>]*>", re.I)
_RE_B = re.compile(r"</?b\s*[^>]*>", re.I)
_RE_I = re.compile(r"</?i\s*[^>]*>", re.I)
_RE_HR = re.compile(r"<hr\s*[^>]*>", re.I)
_RE_TAGS = re.compile(r"<[^>]+>", re.I | re.S)

def strip_html(text: str) -> str:
    """Remove tags HTML simples (para hs_call_body)."""
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    t = re.sub(r"<.*?>", "", t)
    lines = [ln.strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)

def clean_call_summary_html(html: str) -> str:
    """
    Converte HTML do 'Call summary' para texto legível:
    - <li> -> "- ..."
    - remove <hr>, estilos e tags restantes
    """
    if not html:
        return ""
    t = _RE_BR.sub("\n", html)
    t = _RE_LI_1.sub("- ", t)
    t = _RE_LI_2.sub("\n", t)
    t = _RE_UL_OL.sub("\n", t)
    t = _RE_H.sub("\n", t)
    t = _RE_B.sub("", t)
    t = _RE_I.sub("", t)
    t = _RE_HR.sub("\n", t)
    t = _RE_TAGS.sub("", t)
    lines = [ln.strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)
