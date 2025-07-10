import streamlit as st
import pandas as pd
import json
import re
from io import BytesIO
from openai import OpenAI
import docx2txt
import pdfplumber

# Initialize OpenAI client
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# Text extraction function
def extract_text(uploaded) -> str:
    name = uploaded.name.lower()
    if name.endswith('.docx'):
        return docx2txt.process(uploaded)
    if name.endswith('.pdf'):
        with pdfplumber.open(uploaded) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return uploaded.read().decode('utf-8', errors='ignore')

# GPT Chat helper
def chat_json(prompt: str, max_tokens: int = 2048) -> dict:
    resp = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": "You're a precise Operational Risk assistant for banks."},
                  {"role": "user", "content": prompt}],
    )
    return json.loads(resp.choices[0].message.content)

# Normalization helpers
def norm_type(val: str) -> str:
    return val.strip().capitalize()

def norm_freq(val: str) -> str:
    mapping = {'monthly':'Monthly','quarterly':'Quarterly','semi-annual':'Semi-Annual','annual':'Annual'}
    val = val.strip().lower()
    return mapping.get(val, val.capitalize())

# Generate RCSA controls
def generate_controls(text: str, target_n: int) -> pd.DataFrame:
    keywords = ["approval","limit","threshold","reconcile","review","authorise",
                "exception","segregation","dual","signoff","compliance","validate","checker"]
    sentences = [s.strip() for s in re.split(r'[.!?\n]', text) if any(k in s.lower() for k in keywords) and len(s.strip()) > 20]
    
    if not sentences:
        st.warning("No control-like sentences found.")
        return pd.DataFrame()

    prompt = f"""
    Extract exactly {target_n} highly specific, measurable RCSA controls using verb-object-condition from:

    Sentences:
    {sentences}

    Controls must explicitly state measurable conditions (time-bound, numeric limits, approver roles).
    Return a JSON array 'controls' with exact keys: ControlID, ControlObjective, Type (Preventive, Detective, Corrective), TestingMethod, Frequency (Monthly, Quarterly, Semi-Annual, Annual).
    """
    
    data = chat_json(prompt)
    controls = data.get('controls', [])

    for idx, ctrl in enumerate(controls, 1):
        ctrl['ControlID'] = ctrl.get('ControlID', f'GC-{idx:03d}')
        ctrl['Type'] = norm_type(ctrl['Type'])
        ctrl['Frequency'] = norm_freq(ctrl['Frequency'])

    return pd.DataFrame(controls)

# Validate existing RCSA controls
def validate_controls(raw_text: str) -> pd.DataFrame:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    prompt = f"""
    Rewrite these RCSA controls explicitly in measurable verb-object-condition format, discarding vague ones:

    {lines}

    Classify clearly:
    - Type: Preventive, Detective, Corrective
    - TestingMethod (measurable)
    - Frequency: Monthly, Quarterly, Semi-Annual, Annual

    Return JSON array 'controls' exactly containing keys:
    OldControlObjective, UpdatedControlObjective, Type, TestingMethod, Frequency.
    Maintain original order without dropping controls.
    """

    data = chat_json(prompt)
    controls = data.get('controls', [])

    validated = []
    for i, ctrl in enumerate(controls):
        validated.append({
            "ControlID": f"VC-{i+1:03d}",
            "OldControlObjective": ctrl['OldControlObjective'],
            "UpdatedControlObjective": ctrl['UpdatedControlObjective'],
            "Type": norm_type(ctrl['Type']),
            "TestingMethod": ctrl['TestingMethod'],
            "Frequency": norm_freq(ctrl['Frequency']),
        })

    return pd.DataFrame(validated)

# Download to Excel helper
def download_excel(df: pd.DataFrame, fname: str):
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    st.download_button("📥 Download Excel", buffer.getvalue(), file_name=fname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Streamlit UI
st.set_page_config(page_title="RCSA Agentic AI", layout="wide")
st.title("📋 RCSA Agentic AI")

# Tabs
new_tab, validate_tab = st.tabs(["🆕 Generate New Controls", "🛠️ Validate Controls"])

with new_tab:
    st.subheader("Generate RCSA Controls")
    uploaded = st.file_uploader("Upload document (PDF, DOCX, TXT)", type=["pdf","docx","txt"])
    target_controls = st.number_input("Target Number of Controls", min_value=1, max_value=100, value=10)

    if st.button("Generate"):
        if not uploaded:
            st.warning("Please upload a document.")
        else:
            text = extract_text(uploaded)
            df_generated = generate_controls(text, target_controls)
            if not df_generated.empty:
                st.dataframe(df_generated, use_container_width=True)
                download_excel(df_generated, "generated_controls.xlsx")

with validate_tab:
    st.subheader("Validate Existing RCSA Controls")
    uploaded_existing = st.file_uploader("Upload RCSA controls (DOCX, PDF, TXT, CSV, XLSX)", type=["docx","pdf","txt","csv","xlsx"])

    if st.button("Validate"):
        if not uploaded_existing:
            st.warning("Please upload a file.")
        else:
            file_name = uploaded_existing.name.lower()
            df_existing = pd.read_csv(uploaded_existing) if file_name.endswith('.csv') else pd.read_excel(uploaded_existing) if file_name.endswith(('.xlsx','.xls')) else None
            
            if df_existing is not None:
                col = next((c for c in ['ControlObjective', 'Control Objective'] if c in df_existing.columns), df_existing.columns[1])
                raw_text = "\n".join(df_existing[col].astype(str).tolist())
            else:
                raw_text = extract_text(uploaded_existing)

            df_validated = validate_controls(raw_text)
            if not df_validated.empty:
                st.dataframe(df_validated, use_container_width=True)
                download_excel(df_validated, "validated_controls.xlsx")
