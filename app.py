import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd
import subprocess  # 用於呼叫 antiword
import os

# --- 增強型讀取工具 ---
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_doc(file):
    """處理舊版 .doc 檔案"""
    with open("temp.doc", "wb") as f:
        f.write(file.getbuffer())
    try:
        # 呼叫 antiword 將 .doc 轉為文字
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return f"【舊版 Word 讀取失敗，請考慮手動貼上內容】"
    finally:
        if os.path.exists("temp.doc"):
            os.remove("temp.doc")

# --- 網頁介面 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請免費 API Key](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("輸入 Gemini API Key", type="password")
    st.divider()
    st.success("✅ 系統已支援：PDF, DOCX, DOC, CSV")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材 (支援新舊 Word/PDF/CSV)", 
                                         type=["pdf", "docx", "doc", "csv"], 
                                         accept_multiple_files=True)
        
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
            model = genai.GenerativeModel("gemini-1.5-pro", 
                    system_instruction="你是內湖國小專用 AI，請根據教材計算節數比例並產出試題審核表。")
            chat = model.start_chat(history=[])
            response = chat.send_message(f"科目：{subject}\n內容：{all_content}")
            st.session_state.chat_session = chat
            st.session_state.chat_history.append({"role": "model", "content": response.text})
            st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    # 對話邏輯保持不變
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    if prompt := st.chat_input("請輸入修改要求..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()
