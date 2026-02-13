import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader # 使用最新穩定版 pypdf
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
    """讀取舊版 doc，需配合 packages.txt 安裝 antiword"""
    with open("temp.doc", "wb") as f:
        f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "【讀取錯誤：內容可能受損】"
    except:
        return "【舊版 Word 轉檔模組未就緒】"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

def read_csv(file):
    try:
        df = pd.read_csv(file, encoding_errors='ignore')
        return f"\n【參考審核表數據：{file.name}】\n" + df.to_string()
    except: return ""

# --- 2. 核心行政指令 ---
SYSTEM_PROMPT = """
你是「新竹市內湖國小專用命題行政助手」。
任務：根據教材產出「試題審核表」與「素養導向試題」。

### ⚡ 核心行政規範：
1. **掃描節數**：從內容中尋找各單元對應的「節數」。
2. **計算配分**：公式為 (單元節數 / 總節數) * 100。
3. **兩段式流程**：
   - 第一階段：先輸出【試題審核表】表格。
   - 第二階段：待老師確認後，才產出試題。
"""

# --- 3. 網頁介面配置 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("### 1. 取得通行證")
    st.markdown("[👉 點我申請免費 API Key](https://aistudio.google.com/app/apikey)")
    
    st.markdown("### 2. 輸入金鑰")
    api_key = st.text_input("貼上您的 Gemini API Key", type="password")
    
    st.divider()
    st.success("✅ 支援：.doc, .docx, .pdf, .csv")
    st.info("💡 提示：若 .doc 讀取亂碼，請改用 .docx 效果最佳。")

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
        
        uploaded_files = st.file_uploader("上傳教材或舊審核表 (支援 Word/PDF/CSV)", 
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
            elif ext == 'csv': all_content += read_csv(f)
        
        try:
            genai.configure(api_key=api_key)
            # --- 修正後的模型名稱：直接使用 "gemini-1.5-pro" ---
            model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在掃描教材並計算配分比例..."):
                response = chat.send_message(f"年級：{grade}\n科目：{subject}\n內容：{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗，請檢查金鑰與模型設定：{e}")

# --- 第二階段：對話修正 ---
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("確認配分後，請輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (下一單元)"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
