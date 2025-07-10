# RCSA Agentic AI – Streamlit App (JSON‑safe with OpenAI v1)
# --------------------------------------------------------
# Adds `response_format={"type": "json_object"}` so GPT **must** reply with
# valid JSON; no more "OpenAI did not return valid JSON" errors.
# ---------------------------------------------------------------------------
# Two tabs:
#   1. 🆕 Generate RCSA  – extract draft controls from policy / SOP
#   2. 🛠️ Validate RCSA – clean & enrich an existing controls sheet
#
# Stateless: documents processed only in RAM; only keyword‑hit snippets reach OpenAI.

# ---------- 1. Imports & constants ----------
import streamlit as st
import pandas as pd
import docx2txt, pdfplumber, re, json, os
from io import BytesIO
from typing import List

from openai import OpenAI  # v1 SDK

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])  # single global client

SYSTEM_PROMPT = (
    "You are a senior operational‑risk analyst. Use banking best‑practice to "
    "draft or refine RCSA controls in clear verb‑object‑condition form and "
    "classify Type, TestingMethod, and Frequency. Respond strictly in JSON."
)

# 👉 keyword list can live in a JSON file; hard‑coded here for brevity
KEYWORDS: List[str] = [
    "Authorise", "Approve", "Limit", "Threshold", "Dual‑sign", "Maker", "Checker",
    "Segregate", "Validate", "Mandatory", "Exception", "Reconcile", "Compare", "Audit‑log",
    "Override", "Escalate", "Lock", "Cut‑off", "Timeout", "Alert", "Ageing", "Suspense",
    "Access", "Role", "Privilege", "Password", "Token", "MFA", "Credential", "Entitlement",
    "Change", "Release", "Deploy", "Patch", "Configuration", "Version", "Rollback",
    "Backup", "Restore", "Fail‑over", "DR", "BIA", "Resilience", "RTO", "RPO",
    "Incident", "Root‑cause", "RCA", "Report", "KCI", "KPI", "Breach", "Loss",
    "Vendor", "Outsource", "Third‑party", "SLA", "Contract", "Due‑diligence", "Onboarding",
    "Performance‑review", "Payment", "Disbursement", "Settlement", "Clearing", "Remittance",
    "Payout", "Transfer", "Transaction‑limit", "Reconciliation", "Break", "Unmatched",
    "Mismatch", "Exception‑ageing", "Write‑off", "Suspense‑clear",
]

# ---------- 2. Helper functions ----------

def extract_text(uploaded_file) -> str:
    """Return raw text from TXT / PDF / DOCX uploads without touching disk."""
    if uploaded_file is None:
        return ""

    ftype = uploaded_file.type

    if ftype == "text/plain":
        return uploaded_file.read().decode("utf‑8", errors="ignore")

    if ftype in [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ]:
        return docx2txt.process(uploaded_file)

    if ftype == "application/pdf":
        blocks = []
        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                blocks.append(page.extract_text() or "")
        return "\n".join(blocks)

    st.warning(f"Unsupported file type: {ftype}")
    return ""


def find_sentences(text: str, keywords: List[str]) -> List[str]:
    splitter = re.compile(r"[.!?]\s+")
    sentences = splitter.split(text)
    kws = [k.lower() for k in keywords]
    return [s.strip() for s in sentences if any(k in s.lower() for k in kws)]


def openai_chat(user_content: str, model: str = "gpt-4o-mini") -> str:
    """Call OpenAI with enforced JSON‑only response."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=1024,
        response_format={"type": "json_object"},  # 💡 guarantees JSON
    )
    return resp.choices[0].message.content.strip()


def generate_controls(sentences: List[str], target_n: int) -> pd.DataFrame:
    prompt = (
        "Extract up to "
        f"{target_n} RCSA controls from the sentences provided. "
        "Return *only* a JSON object with a single key `controls` mapping to a list, "
        "each item containing: ControlObjective, Type (Preventive/Detective/Corrective), "
        "TestingMethod, Frequency."
        "\n\nSentences:\n" + "\n".join(sentences)
    )
    raw = openai_chat(prompt)
    try:
        data = json.loads(raw)
        ctrls = data["controls"]
    except (json.JSONDecodeError, KeyError):
        st.error("OpenAI did not return the expected JSON structure. Please retry.")
        return pd.DataFrame()

    df = pd.json_normalize(ctrls)
    df.insert(0, "Control ID", [f"CO‑{i:03d}" for i in range(1, len(df) + 1)])
    return df


def validate_controls(raw_text: str) -> pd.DataFrame:
    prompt = (
        "Clean, correct and complete each RCSA control below. "
        "Respond with a JSON object having key `controls`. Each element must have: "
        "OldControlObjective, UpdatedControlObjective, Type, TestingMethod, Frequency, OtherDetails."
        f"\n\nControls text:\n{raw_text}"
    )
    raw = openai_chat(prompt)
    try:
        data = json.loads(raw)
        ctrls = data["controls"]
    except (json.JSONDecodeError, KeyError):
        st.error("OpenAI did not return the expected JSON structure. Please retry.")
        return pd.DataFrame()

    df = pd.json_normalize(ctrls)
    df.insert(0, "Control ID", [f"VC‑{i:03d}" for i in range(1, len(df) + 1)])
    return df


def excel_download(df: pd.DataFrame, fname: str):
    buf = BytesIO()
    df.to_excel(buf, index=False)
    st.download_button(
        "Download Excel",
        buf.getvalue(),
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------- 3. Streamlit UI ----------
st.set_page_config(page_title="RCSA Agentic AI", layout="wide")
st.title("📋 RCSA Agentic AI")

TAB_GEN, TAB_VAL = st.tabs(["🆕 Generate RCSA", "🛠️ Validate RCSA"])

with TAB_GEN:
    st.subheader("1️⃣ Upload policy / SOP / manual")
    policy_file = st.file_uploader("Choose DOCX / PDF / TXT", type=["docx", "pdf", "txt"])
    target_n = st.number_input("Target number of controls", 1, 100, 10)

    if st.button("Generate controls") and policy_file:
        text = extract_text(policy_file)
        hits = find_sentences(text, KEYWORDS)
        if not hits:
            st.warning("No keyword‑bearing sentences found.")
        else:
            df_controls = generate_controls(hits, target_n)
            st.dataframe(df_controls, use_container_width=True)
            if not df_controls.empty:
                excel_download(df_controls, "rcsa_controls.xlsx")

with TAB_VAL:
    st.subheader("1️⃣ Upload existing RCSA list (DOCX/PDF/TXT/CSV/XLSX)")
    rcsa_file = st.file_uploader(
        "Choose a file", type=["docx", "pdf", "txt", "csv", "xlsx"], key="val"
    )

    if st.button("Validate controls") and rcsa_file:
        if rcsa_file.type in [
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]:
            raw_text = rcsa_file.getvalue().decode("utf‑8", errors="ignore")
        else:
            raw_text = extract_text(rcsa_file)

        df_valid = validate_controls(raw_text)
        st.dataframe(df_valid, use_container_width=True)
        if not df_valid.empty:
            excel_download(df_valid, "validated_rcsa_controls.xlsx")

# ---------- End of file ----------
