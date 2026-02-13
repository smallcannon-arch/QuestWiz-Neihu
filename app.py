import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import pandas as pd
import subprocess
import os

# --- 1. 檔案讀取工具 ---
def read_pdf(file):
    try:
        pdf_reader = PdfReader(file)
        return "".join([p.extract_text() or "" for p in pdf_reader.pages])
    except: return "[PDF 讀取失敗]"

def read_docx(file):
    try:
        doc = Document(file)
        return "\n".join([p.text for p in doc.paragraphs])
    except: return "[DOCX 讀取失敗]"

def read_doc(file):
    with open("temp.doc", "wb") as f:
        f.write(file.getbuffer())
    try:
        # 呼叫 packages.txt 安裝的 antiword
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[DOC 讀取錯誤]"
    except: return "[系統未安裝 antiword]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 網頁介面與設定 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 點我申請免費 API Key](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 Gemini API Key", type="password")
    
    # 讓老師可以選擇模型，增加連線成功率
    model_choice = st.radio("選擇 AI 引擎", ["gemini-1.5-flash (快)", "gemini-1.5-pro (強)"], index=0)
    selected_model = "gemini-1.5-flash" if "flash" in model_choice else "gemini-1.5-pro"
    
    st.divider()
    st.success("✅ 支援格式：.doc, .docx, .pdf, .csv")

# 狀態管理
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# --- 第一階段：檔案上傳與分析 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
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
            # 使用最單純的模型字串，避免 404
            model = genai.GenerativeModel(selected_model)
            chat = model.start_chat(history=[])
            
            with st.spinner(f"正在使用 {selected_model} 分析教材..."):
                prompt = f"你是內湖國小行政助手。請根據以下內容產出試題審核表（包含節數比例與預計配分）。\n科目：{subject}\n內容：{all_content}"
                response = chat.send_message(prompt)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
            st.info("💡 小建議：請嘗試將側邊欄切換為『gemini-1.5-flash』再試一次。")

# --- 第二階段：後續對話 ---
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("確認配分後，請輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
