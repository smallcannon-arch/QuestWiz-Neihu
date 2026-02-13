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
st.set_page_config(page_title="QuestWiz 內湖國小診斷版", layout="wide")
st.title("🏫 QuestWiz 試題行政助手 (診斷模式)")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 Gemini API Key", type="password")
    st.divider()
    st.success("✅ 已支援：.doc, .docx, .pdf, .csv")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 第一階段：檔案上傳與診斷 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        uploaded_files = st.file_uploader("上傳教材", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 開始分析", type="primary", use_container_width=True)

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
            
            # --- 核心診斷：自動尋找可用的模型 ---
            available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            
            # 優先權：1.5-flash > 1.5-pro > 1.0-pro
            target_model = ""
            for m in ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-pro"]:
                if m in available_models:
                    target_model = m
                    break
            
            if not target_model:
                target_model = available_models[0] # 真的都沒有就隨便抓第一個
            
            st.info(f"📡 系統診斷：自動選擇最佳連線路徑 {target_model}")
            
            model = genai.GenerativeModel(target_model)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在工作中..."):
                prompt = f"你是內湖國小行政助手。請分析以下內容並產出試題審核表。\n科目：{subject}\n內容：{all_content}"
                response = chat.send_message(prompt)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
            st.write("--- 偵錯資訊 ---")
            try:
                models = [m.name for m in genai.list_models()]
                st.write(f"您的金鑰目前可用的型號有：{models}")
            except:
                st.write("無法取得型號清單，請確認 API Key 是否有效。")

else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    if prompt := st.chat_input("請輸入指令..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()
