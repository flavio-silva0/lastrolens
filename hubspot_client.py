import os, re, requests, time

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
BASE = "https://api.hubapi.com"
HDRS = {"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"}

COOBY_MSG_RE = re.compile(r"Message text:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

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
