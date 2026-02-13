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
        return result.stdout if result.returncode == 0 else "[DOC 讀取失敗]"
    except: return "[系統未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 整合您的專業 Gem 命題指令 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」，精通 1-6 年級全科教材教法。
嚴格遵守「兩段式輸出」：
1. Phase 1：僅輸出【試題審核表】（含配分、圖表清單、目標覆蓋）。
2. Phase 2：使用者確認後，才輸出【試題】。

### 核心參數：
* 🟢 模式 A：適中 (Moderate) - 60% 記憶理解 + 40% 基礎應用。
* 🔴 模式 B：困難 (Hard) - 30% 應用 + 70% 分析評鑑。
* 🌟 模式 C：素養 (Literacy) - 100% 情境解決問題，接軌 PISA/PIRLS 標準。

### 鐵律：
* 總分：固定 100 分。格數：34～45 格。
* 嚴禁出現「以上皆是」、「以上皆非」。
* 選項需具備類別一致性 (OptionClass)。
"""

# --- 3. 網頁介面 ---
st.set_page_config(page_title="QuestWiz 內湖國小專屬版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 Gemini API Key", type="password")
    st.divider()
    st.success("✅ 核心已載入：國小專業命題 Gem 邏輯")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 第一階段：分析與診斷 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會", "英語"], index=0)
        with col3:
            mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材資料", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 依照 Gem 指令產出審核表", type="primary", use_container_width=True)

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
            
            # --- 核心除錯邏輯：自動尋找您金鑰支援的模型 ---
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            # 優先權：2.5-flash > 1.5-flash > 其它
            target_model = ""
            for m in ["models/gemini-2.5-flash", "models/gemini-1.5-flash", "models/gemini-1.5-pro"]:
                if m in available:
                    target_model = m
                    break
            if not target_model: target_model = available[0]
            
            st.info(f"📡 系統連線成功：已自動對齊最佳路徑 {target_model}")
            
            model = genai.GenerativeModel(
                model_name=target_model,
                system_instruction=GEM_INSTRUCTIONS,
                generation_config={"temperature": 0.0}
            )
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在工作中..."):
                prompt = f"年級：{grade}\n科目：{subject}\n模式：{mode}\n教材內容：\n{all_content}\n--- 請輸出【試題審核表】表格。"
                response = chat.send_message(prompt)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")

else:
    # 這裡顯示對話紀錄與後續指令
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("確認審核表後，請輸入『開始出題』..."):
        with st.chat_message("user"): st.markdown(prompt)
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
