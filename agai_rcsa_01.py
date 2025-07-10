# RCSA Agentic AI – Streamlit App (v1.1)
# ------------------------------------------------------------------
# • Type column now spelled out **Preventive / Detective / Corrective**
#   everywhere (generation + validation + normaliser).
# • Prompt texts updated so GPT always returns full words, not letters.
# • Normaliser maps P/D/C → full word for backward compatibility.
# • Basic guard: if validator response is empty, show error instead of null.
# ------------------------------------------------------------------

import streamlit as st
import pandas as pd
import docx2txt, pdfplumber, re, json
from io import BytesIO
from typing import List
from openai import OpenAI

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

SYSTEM_PROMPT = (
    "You are a senior operational‑risk analyst creating an RCSA. "
    "For each control you draft or correct, ensure: "
    "1) ControlObjective is specific (numeric or explicit textual condition). "
    "2) Type must be Preventive, Detective, or Corrective. "
    "3) Frequency must be Monthly, Quarterly, Semi‑Annual, or Annual. "
    "Return answers strictly in JSON as per schema."
)

KEYWORDS: List[str] = [
    "authorise", "approve", "limit", "threshold", "dual‑sign", "maker", "checker",
    "segregate", "validate", "mandatory", "exception", "reconcile", "compare", "audit‑log",
    "override", "escalate", "lock", "cut‑off", "timeout", "alert", "ageing", "suspense",
    "access", "role", "privilege", "password", "token", "mfa", "credential", "entitlement",
    "change", "release", "deploy", "patch", "configuration", "version", "rollback",
    "backup", "restore", "fail‑over", "dr", "bia", "resilience", "rto", "rpo",
    "incident", "root‑cause", "rca", "report", "kci", "kpi", "breach", "loss",
    "vendor", "outsource", "third‑party", "sla", "contract", "due‑diligence", "onboarding",
    "performance‑review", "payment", "disbursement", "settlement", "clearing", "remittance",
    "payout", "transfer", "transaction‑limit", "reconciliation", "break", "unmatched",
    "mismatch", "exception‑ageing", "write‑off", "suspense‑clear",
]

ALLOWED_TYPES_FULL = {"PREVENTIVE": "Preventive", "DETECTIVE": "Detective", "CORRECTIVE": "Corrective"}
ALLOWED_TYPE_LETTERS = {"P": "Preventive", "D": "Detective", "C": "Corrective"}
ALLOWED_FREQ = {
    "MONTHLY": "Monthly",
    "QUARTERLY": "Quarterly",
    "SEMI‑ANNUAL": "Semi-Annual",
    "SEMI ANNUAL": "Semi-Annual",
    "SEMIANNUAL": "Semi-Annual",
    "BI-ANNUAL": "Semi-Annual",
    "BI ANNUAL": "Semi-Annual",
    "BIANNUAL": "Semi-Annual",
    "ANNUAL": "Annual",
}

# ---------- helper functions ----------

def extract_text(upload):
    if not upload:
        return ""
    kind = upload.type
    if kind == "text/plain":
        return upload.read().decode("utf‑8", errors="ignore")
    if kind in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ]:
        return docx2txt.process(upload)
    if kind == "application/pdf":
        out = []
        with pdfplumber.open(upload) as pdf:
            for p in pdf.pages:
                out.append(p.extract_text() or "")
        return "\n".join(out)
    st.warning(f"Unsupported type {kind}")
    return ""


def find_sentences(text: str, keywords: List[str], window: int = 1):
    parts = re.split(r"[.!?]\s+", text)
    kws = [k.lower() for k in keywords]
    hits = []
    for i, s in enumerate(parts):
        if any(k in s.lower() for k in kws):
            start = max(i - window, 0)
            end = min(i + window + 1, len(parts))
            hits.append(" ".join(parts[start:end]).strip())
    return hits


def chat_json(user_msg: str, max_tokens: int, model: str = "gpt-4o-mini"):
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def safe_load_json(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _norm_type(val: str):
    if not val:
        return "Preventive"
    v = val.strip().upper()
    if v in ALLOWED_TYPES_FULL:
        return ALLOWED_TYPES_FULL[v]
    if v in ALLOWED_TYPE_LETTERS:
        return ALLOWED_TYPE_LETTERS[v]
    if "PREV" in v:
        return "Preventive"
    if "DET" in v:
        return "Detective"
    if "COR" in v:
        return "Corrective"
    return "Preventive"


def _norm_freq(val: str):
    if not val:
        return "Annual"
    v = val.strip().upper().replace("-", " ")
    for k, std in ALLOWED_FREQ.items():
        if k in v:
            return std
    return "Annual"


def _apply_normalisation(df: pd.DataFrame):
    if "Type" in df.columns:
        df["Type"] = df["Type"].apply(_norm_type)
    if "Frequency" in df.columns:
        df["Frequency"] = df["Frequency"].apply(_norm_freq)
    return df


def generate_controls(sentences: List[str], n: int):
    prompt = (
        f"Create **at least** {n} RCSA controls from the sentences below. "
        "Each ControlObjective must be specific (numeric or explicit textual condition). "
        "Use exactly these choices: Type → Preventive / Detective / Corrective; "
        "Frequency → Monthly / Quarterly / Semi-Annual / Annual. "
        "Schema: {\"controls\": [ {\"ControlObjective\": str, \"Type\": str, \"TestingMethod\": str, \"Frequency\": str} ]}. "
        "Do not include any keys other than 'controls'.\n\nSentences:\n" + "\n".join(sentences)
    )
    mtok = min(4096, max(1024, n * 60 + 200))
    data = safe_load_json(chat_json(prompt, max_tokens=mtok))
    df = pd.json_normalize(data.get("controls", []))
    if df.empty:
        raise ValueError("GPT returned no controls – try lowering target or check document.")
    df.insert(0, "Control ID", [f"CO-{i+1:03d}" for i in range(len(df))])
    df = _apply_normalisation(df)
    return df


def validate_controls(records_json: str, rows: int):
    """Send existing controls to GPT for clean‑up, enforcing row‑parity.
    Returns a normalised DataFrame.
    """
    prompt = f"""
You will receive a JSON array named `input_records`.
For every element, return **one** element with keys: OldControlObjective, UpdatedControlObjective, Type, TestingMethod, Frequency, OtherDetails.
Type must be Preventive / Detective / Corrective; Frequency must be Monthly / Quarterly / Semi-Annual / Annual.
Return the result **as a JSON array with exactly {rows} elements** — do NOT wrap it in any additional object or key.

input_records = {records_json}
"""

    mtok = min(4096, max(1024, rows * 60 + 200))
    raw = chat_json(prompt, max_tokens=mtok)
    data = safe_load_json(raw)

    # If GPT still wrapped the list, unwrap common wrappers
    if isinstance(data, dict):
        for k in ("output_records", "results", "records"):
            if k in data and isinstance(data[k], list):
                data = data[k]
                break
    if not isinstance(data, list):
        raise ValueError("Validator response not a JSON array; please retry.")
    if len(data) != rows:
        raise ValueError(f"Row count mismatch: expected {rows}, got {len(data)} – retry.")

    df = pd.json_normalize(data)
    if df.empty:
        raise ValueError("Validator returned empty array – please retry.")
    df.insert(0, "Control ID", [f"VC-{i+1:03d}" for i in range(len(df))])
    df = _apply_normalisation(df)
    return df


def download_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        "📥 Download Excel",
        buf.getvalue(),
        file_name=name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------- UI ----------

st.set_page_config(page_title="RCSA Agentic AI", layout="wide")

st.title("📋 RCSA Agentic AI")
tabs = st.tabs(["🆕 Generate RCSA", "🛠️ Validate RCSA"])

# --- Tab 1: Generate ---
with tabs[0]:
    st.subheader("Generate draft controls from a policy / procedure")
    up1 = st.file_uploader("Upload policy / SOP (PDF, DOCX, TXT)")
    tgt = st.number_input("Target number of controls", 5, 100, value=20)
    if st.button("Generate controls", key="gen") and up1:
        txt = extract_text(up1)
        sents = find_sentences(txt, KEYWORDS, window=1)
        if not sents:
            st.warning("No keyword hits found – try another file or adjust keywords.")
        else:
            try:
                df = generate_controls(sents, tgt)
                st.dataframe(df, use_container_width=True)
                download_excel(df, "rcsa_controls.xlsx")
            except Exception as e:
                st.error(f"Generation failed: {e}")

# --- Tab 2: Validate ---
with tabs[1]:
    st.subheader("Validate / clean an existing RCSA control list")
    up2 = st.file_uploader("Upload CSV or XLSX of controls", key="val")
    if st.button("Validate controls", key="valbtn") and up2:
        try:
            if up2.type == "text/csv":
                df_in = pd.read_csv(up2)
            elif up2.type in [
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            ]:
                df_in = pd.read_excel(up2)
            else:
                st.error("Unsupported file type")
                df_in = None
            if df_in is not None:
                rows = len(df_in)
                records_json = df_in.to_json(orient="records")
                df_out = validate_controls(records_json, rows)
                st.dataframe(df_out, use_container_width=True)
                download_excel(df_out, "validated_controls.xlsx")
        except Exception as e:
            st.error(f"Validation failed: {e}")
