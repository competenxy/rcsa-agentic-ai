# RCSA Agentic AI – Streamlit App (v0.5)
# -------------------------------------------------------------
# Fixes JSONDecodeError when GPT reply is truncated or wrapped.
# Changes:
# 1.  Dynamic max_tokens based on requested control count (n * 60 + 200),
#     capped at 4096.
# 2.  Robust JSON parsing fallback: if first json.loads fails, regex‑extract
#     the first {...} block.
# 3.  Default target controls set to 20 (you can raise it if the doc is big).
# 4.  Prompts unchanged – still demand specific numeric/textual controls.
# -------------------------------------------------------------

import streamlit as st
import pandas as pd
import docx2txt, pdfplumber, re, json
from io import BytesIO
from typing import List
from openai import OpenAI

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

SYSTEM_PROMPT = (
    "You are a senior operational‑risk analyst creating an RCSA. "
    "For each control you draft or correct, ensure the ControlObjective is **specific**: "
    "include either a numeric threshold *or* an explicitly described textual condition (e.g., 'obtain approval from approvers as per escalation matrix level‑3'). "
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
        raise  # re‑raise for Streamlit to show traceback


def generate_controls(sentences: List[str], n: int):
    prompt = (
        f"Create **at least** {n} RCSA controls from the sentences below. "
        "Each ControlObjective must be specific (numeric or explicit textual condition). "
        "Schema: {\"controls\": [ {\"ControlObjective\": str, \"Type\": str, \"TestingMethod\": str, \"Frequency\": str} ]}. "
        "Do not include any keys other than 'controls'.\n\nSentences:\n" + "\n".join(sentences)
    )
    mtok = min(4096, max(1024, n * 60 + 200))
    data = safe_load_json(chat_json(prompt, max_tokens=mtok))
    df = pd.json_normalize(data["controls"])
    df.insert(0, "Control ID", [f"CO-{i+1:03d}" for i in range(len(df))])
    return df


def validate_controls(raw_text: str, rows: int):
    prompt = (
        "For each input control row, produce a JSON element with keys: "
        "OldControlObjective, UpdatedControlObjective (specific), Type, TestingMethod, Frequency, OtherDetails. "
        "Return **exactly the same number of elements** as in the input. If a row is vague, set UpdatedControlObjective='REVIEW_NEEDED'.\n\nInput:\n"
        + raw_text
    )
    mtok = min(4096, max(1024, rows * 60 + 200))
    data = safe_load_json(chat_json(prompt, max_tokens=mtok))
    df = pd.json_normalize(data["controls"])
    df.insert(0, "Control ID", [f"VC-{i+1:03d}" for i in range(len(df))])
    return df


def download_excel(df, name):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button("📥 Download Excel", buf.getvalue(), file_name=name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---------- UI ----------

st.set_page_config(page_title="RCSA Agentic AI", layout="wide")
st.title("📋 RCSA Agentic AI")

tab_gen, tab_val = st.tabs(["🆕 Generate RCSA", "🛠️ Validate RCSA"])

with tab_gen:
    st.header("Generate draft controls")
    up = st.file_uploader("Policy / SOP (DOCX, PDF, TXT)", type=["docx", "pdf", "txt"])
    tgt = st.number_input("Target controls", 1, 150, 20)
    if st.button("Generate") and up:
        txt = extract_text(up)
        sents = find_sentences(txt, KEYWORDS)
        if not sents:
            st.warning("No keyword hits – try another document or update keywords.")
        else:
            try:
                df = generate_controls(sents, tgt)
                st.dataframe(df, use_container_width=True)
                if not df.empty:
                    download_excel(df, "rcsa_controls.xlsx")
            except Exception as e:
                st.error(f"Failed to parse JSON reply: {e}")

with tab_val:
    st.header("Validate / refine existing controls")
    up2 = st.file_uploader("Controls sheet or text (DOCX/PDF/TXT/CSV/XLSX)", type=["docx", "pdf", "txt", "csv", "xlsx"], key="val")
    if st.button("Validate") and up2:
        if up2.type in ["text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]:
            raw = up2.getvalue().decode("utf-8", errors="ignore")
            rows = raw.count("\n")
        else:
            raw = extract_text(up2)
            rows = raw.count("\n")
        try:
            dfv = validate_controls(raw, max(1, rows))
            st.dataframe(dfv, use_container_width=True)
            if not dfv.empty:
                download_excel(dfv, "validated_rcsa_controls.xlsx")
        except Exception as e:
            st.error(f"Failed to parse JSON reply: {e}")
