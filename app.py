import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd
import io

# --- 1. 增強型檔案讀取工具 ---
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        # 處理 Big5 或 UTF-8 編碼問題
        df = pd.read_csv(file, encoding_errors='ignore')
        return f"【審核表數據：{file.name}】\n" + df.to_string()
    except: return f"[讀取失敗: {file.name}]"

# --- 2. 核心行政指令 (System Prompt) ---
SYSTEM_PROMPT = """
你是「內湖國小試題行政助理」。
任務：接收老師上傳的教材，產出精確的【試題審核表】。

### ⚡ 核心行政任務：
1. **自動分析節數**：從上傳的 PDF、Word 或 CSV 中找出「X節」或「X堂」的分配。
2. **產出審核表表格**：表格必須包含「單元名稱」、「授課節數」、「權重百分比」、「預計配分」。
3. **計算公式**：
   - 權重 = (單元節數 / 總節數)
   - 預計配分 = 權重 * 100 (四捨五入至整數)
4. **學習目標對應**：自動摘要教材中的學習目標並列於表中。

### 輸出規範：
- 第一階段只輸出【試題審核表】。
- 待使用者確認配分正確後，才進行第二階段【產出試題】。
"""

# --- 3. 網頁介面 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    api_key = st.text_input("輸入 Gemini API Key", type="password")
    st.divider()
    st.warning("⚠️ 注意：舊版 .doc 檔案讀取成功率較低，建議先另存為 .docx 再上傳。")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# --- 第一階段：檔案上傳 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        
        # 修正：加入 .doc 到支援清單
        uploaded_files = st.file_uploader("上傳教材、舊版審核表 CSV 或 PDF", 
                                         type=["pdf", "docx", "doc", "csv"], 
                                         accept_multiple_files=True)
        
        start_btn = st.button("🚀 產出試題審核表與配分比例", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        all_content = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_content += read_pdf(f)
            elif ext == 'docx': all_content += read_docx(f)
            elif ext == 'csv': all_content += read_csv(f)
            elif ext == 'doc': 
                all_content += f"\n[注意：檔案 {f.name} 為舊版 Word，請 AI 嘗試從原始數據中提取文字資訊]"
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在分析教材節數並規劃審核表格..."):
                response = chat.send_message(f"科目：{subject}\n年級：{grade}\n教材內容：{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")

# --- 第二階段：對話與修正 ---
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("確認配分後請輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (新單元)"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
