import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
import pandas as pd
import io

# --- 1. 檔案讀取工具 ---
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        # 自動偵測編碼讀取 CSV (處理中文亂碼)
        df = pd.read_csv(file, encoding_errors='ignore')
        return f"【資料表內容：{file.name}】\n" + df.to_string()
    except: return f"[CSV 讀取失敗: {file.name}]"

# --- 2. 系統邏輯設定 (System Prompt) ---
SYSTEM_PROMPT = """
你是「內湖國小專用命題助手」。
你的任務是根據老師上傳的教材，產出精確的「試題審核表」與「試題」。

### ⚡ 核心行政任務：
1. **偵測節數**：從內容中尋找單元對應的「節數」或「堂數」。
2. **計算配分**：
   - 權重 = (該單元節數 / 總節數)
   - 預計配分 = 權重 * 100 分 (請四捨五入)。
3. **產出審核表**：表格需包含「單元」、「節數」、「百分比」、「預計配分」。

輸出規範：第一階段只給【審核表】，確認配分無誤後才進行第二階段【產出試題】。
"""

# --- 3. 網頁介面 UI ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    
    # --- 這裡加入了更明顯的 API 連結 ---
    st.markdown("### 1. 取得通行證")
    st.markdown("[👉 點我前往申請免費 API Key](https://aistudio.google.com/app/apikey)")
    
    st.markdown("### 2. 輸入金鑰")
    api_key = st.text_input("請貼上您的 Gemini API Key", type="password", placeholder="AIzaSy...")
    
    st.divider()
    st.info("💡 提示：本系統僅供校內教學使用。")
    st.warning("⚠️ 舊版 .doc 檔案(Word 97-2003) 容易讀取失敗，建議老師先將檔案「另存新檔」為 **.docx** 再上傳。")

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
        
        # 修正：允許上傳的類型，並處理 .doc 的顯示問題
        uploaded_files = st.file_uploader("上傳教材資料 (支援 PDF, DOCX, CSV)", 
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
                st.error(f"❌ 偵測到舊版檔案 {f.name}。請先在 Word 將其『另存新檔』為 .docx 格式後再重新上傳。")
                st.stop() # 停止執行，避免後續報錯
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在掃描節數並計算配分..."):
                response = chat.send_message(f"科目：{subject}\n年級：{grade}\n內容：{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")

# --- 第二階段：對話與後續指令 ---
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("配分正確嗎？輸入「開始出題」或「修改配分」..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (下一個單元)"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
