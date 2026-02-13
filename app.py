import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from PIL import Image
import pandas as pd
import io

# 1. 檔案讀取工具 (確保功能獨立)
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        df = pd.read_csv(file)
        return df.to_string()
    except: return "[CSV讀取失敗]"

# 2. 核心 AI 指令
SYSTEM_PROMPT = """
你是「內湖國小專用命題助手」。
任務：根據教材產生「試題審核表」與「試題」。
規則：
1. 自動偵測教材中的「節數」關鍵字。
2. 配分 = (該單元節數 / 總節數) * 100。
"""

# 3. 網頁介面
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 行政自動化命題系統")

# 側邊欄設定 (包含 Secrets 邏輯)
with st.sidebar:
    st.header("🔑 系統設定")
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ 已自動載入校用金鑰")
    else:
        api_key = st.text_input("輸入 Gemini API Key", type="password")
    st.divider()
    st.info("💡 系統已開啟自動配分功能")

# 初始化對話
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# 第一階段：設定與上傳
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材或審核表", type=["pdf", "docx", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產生審核表", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        all_text = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_text += read_pdf(f)
            elif ext == 'docx': all_text += read_docx(f)
            elif ext == 'csv': all_text += read_csv(f)
        
        try:
            genai.configure(api_key=api_key)
            # 這裡改回最穩定的名稱
            model = genai.GenerativeModel(model_name="gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在計算配分並規劃審核表..."):
                response = chat.send_message(f"科目：{subject}\n內容：{all_text}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")

# 第二階段：後續對話
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("輸入指令..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"
