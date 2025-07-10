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
                df_in = None
                if up2.name.lower().endswith(".csv"):
                    df_in = pd.read_csv(up2)
                elif up2.name.lower().endswith((".xlsx", ".xls")):
                    df_in = pd.read_excel(up2)
                elif up2.name.lower().endswith(".docx"):
                    txt = docx2txt.process(up2)
                    lines = [l.strip() for l in txt.splitlines() if l.strip()]
                    df_in = pd.DataFrame({"OldControlObjective": lines})
                elif up2.name.lower().endswith(".pdf"):
                    txt = extract_text(up2)
                    lines = [l.strip() for l in txt.splitlines() if l.strip()]
                    df_in = pd.DataFrame({"OldControlObjective": lines})
                else:
                    st.error("Unsupported file type")

                if df_in is not None and not df_in.empty:
                    rows = len(df_in)
                    records_json = df_in.to_json(orient="records")
                    df_out = validate_controls(records_json, rows)
                    st.dataframe(df_out, use_container_width=True)
                    download_excel(df_out, "validated_controls.xlsx")
                else:
                    st.warning("No usable rows found in the uploaded file.")
            except Exception as e:
                st.error(f"Validation failed: {e}")(df_out, "validated_controls.xlsx")
        except Exception as e:
            st.error(f"Validation failed: {e}")
