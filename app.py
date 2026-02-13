import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import pandas as pd
import subprocess
import os

# --- 1. 檔案讀取工具 ---
def read_pdf(file):
    pdf_reader = PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_doc(file):
    with open("temp.doc", "wb") as f:
        f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[DOC 讀取錯誤]"
    except: return "[系統未安裝 antiword]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 網頁介面 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政助手 (穩定版)")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 Gemini API Key", type="password")
    st.divider()
    st.info("💡 提示：本版已強制關閉 AI 創造力，確保計算精準。")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 第一階段：檔案上傳 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        uploaded_files = st.file_uploader("上傳教材 (PDF/Word/CSV)", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產出試題審核表", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        all_content = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_content += read_pdf(f)
            elif ext == 'docx': all_content += read_docx(f)
            elif ext == 'doc': all_content += read_doc(f)
            elif ext == 'csv': all_content += pd.read_csv(f, encoding_errors='ignore').to_string()
        
        try:
            genai.configure(api_key=api_key)
            
            # 診斷可用型號
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # 優先順序：1.5-flash (最穩) > 1.5-pro > 2.5
            target = ""
            for m in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-2.5-flash"]:
                if m in available:
                    target = m
                    break
            if not target: target = available[0]

            # --- 關鍵修正：加入 generation_config 禁止 AI 亂編故事 ---
            model = genai.GenerativeModel(
                model_name=target,
                generation_config={"temperature": 0.0} # 設為 0 代表最嚴謹，不允許隨機發揮
            )
            
            chat = model.start_chat(history=[])
            with st.spinner(f"正在使用 {target} 嚴謹計算中..."):
                prompt = f"你是內湖國小行政助手。請嚴謹分析以下內容並產出『試題審核表』表格。禁止輸出與教材無關的故事內容。\n科目：{subject}\n內容：{all_content}"
                response = chat.send_message(prompt)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    if prompt := st.chat_input("請輸入指令..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()
