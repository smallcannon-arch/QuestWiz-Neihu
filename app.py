import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import pandas as pd
import subprocess
import os

# --- 1. 檔案讀取工具 (保持輕量) ---
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
        return result.stdout if result.returncode == 0 else "[DOC讀取錯誤]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 您的 Gem 指令 (簡化以提速) ---
GEM_INSTRUCTIONS = """
你是內湖國小行政助理。
任務：精準計算教材節數配分並產出審核表。
要求：
1. 輸出務必簡潔，直接顯示【試題審核表】表格。
2. 嚴格執行配分計算：(單元節數/總節數)*100。
3. 繁體中文輸出，禁止廢話。
"""

# --- 3. UI 介面 ---
st.set_page_config(page_title="QuestWiz 極速版", layout="wide")
st.title("⚡ QuestWiz 行政自動化 (加速模式)")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 API Key", type="password")
    st.divider()
    st.success("🚀 已切換至穩定加速引擎：1.5-flash")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        uploaded_files = st.file_uploader("上傳教材", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產出審核表", type="primary", use_container_width=True)

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
            # 強制使用 1.5-flash，這是目前公認最快的
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=GEM_INSTRUCTIONS,
                generation_config={"temperature": 0} 
            )
            chat = model.start_chat(history=[])
            
            with st.spinner("⚡ 正在極速掃描並計算配分..."):
                # 加入回應限制，讓它不要寫長篇大論，只給表格
                response = chat.send_message(f"科目：{subject}\n內容：{all_content}\n請直接輸出審核表表格。")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    if prompt := st.chat_input("輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()
