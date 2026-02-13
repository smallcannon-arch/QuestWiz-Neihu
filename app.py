import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd

# 檔案讀取工具
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        df = pd.read_csv(file)
        return f"【資料表：{file.name}】\n" + df.to_string()
    except: return f"[讀取失敗: {file.name}]"

# 系統指令
SYSTEM_PROMPT = """
你是「內湖國小專用命題助手」。
你的任務是根據教材產生「試題審核表」與「試卷」。
核心任務：
1. 自動從資料中抓取「節數」關鍵字。
2. 依節數比例計算佔分 (單元節數/總節數 * 100)。
3. 先輸出審核表格式，確認後再出題。
"""

st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

# 側邊欄設定
with st.sidebar:
    st.header("🔑 系統設定")
    api_key = st.text_input("輸入您的 Gemini API Key", type="password")
    st.markdown("[按此申請金鑰](https://aistudio.google.com/app/apikey)")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# 第一階段：上傳
if not st.session_state.chat_history:
    with st.container(border=True):
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        uploaded_files = st.file_uploader("上傳教材或 CSV 審核表", type=["pdf", "docx", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 開始分析", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        all_content = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_content += read_pdf(f)
            elif ext == 'docx': all_content += read_docx(f)
            elif ext == 'csv': all_content += read_csv(f)
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            response = chat.send_message(f"年級：{grade}\n科目：{subject}\n內容：{all_content}")
            st.session_state.chat_session = chat
            st.session_state.chat_history.append({"role": "model", "content": response.text})
            st.rerun()
        except Exception as e:
            st.error(f"錯誤：{e}")

# 第二階段：對話
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("請輸入修改指令或『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
