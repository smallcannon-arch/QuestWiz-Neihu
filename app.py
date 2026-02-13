import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image
import pandas as pd
import io

# ==========================================
# 1. 檔案處理工具 (支援 PDF, Word, Excel, CSV)
# ==========================================
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        df = pd.read_csv(file)
        return df.to_string()
    except: return "[CSV讀取失敗]"

def read_excel(file):
    try:
        all_sheets = pd.read_excel(file, sheet_name=None)
        combined_text = ""
        for name, df in all_sheets.items():
            combined_text += f"\n分頁: {name}\n{df.to_string()}\n"
        return combined_text
    except: return "[Excel讀取失敗]"

# ==========================================
# 2. 行政自動化 System Prompt
# ==========================================
SYSTEM_PROMPT = """
你是「內湖國小專用命題與審核 AI」。
你的任務是根據教材內容自動產生「試題審核表」與「高品質素養試卷」。

### ⚡ 行政配分核心指令：
1. **自動偵測節數**：請掃描教材或上傳的審核表，尋找「X節」或「X堂課」的關鍵字。
2. **比例配分公式**：
   - 子單元配分 = (該單元節數 / 總節數) * 100。
   - 確保總分為 100 分。
3. **高品質命題**：結合 PISA、PIRLS、TASA 等國際測驗標準，強調情境化與探究能力。

### 輸出格式：
(一) 【試題審核表】：含權重對照表（單元 | 偵測節數 | 預計佔分）與學習目標覆蓋表。
(二) 【試題】：以題組呈現，情境文本需符合學生生活經驗。
"""

# ==========================================
# 3. 網頁介面
# ==========================================
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 行政自動化命題系統")

with st.sidebar:
    st.header("🔑 系統設定")
    api_key = st.text_input("輸入 Gemini API Key", type="password")
    st.divider()
    st.info("💡 系統已開啟「自動節數偵測」，AI 將自行計算配分。")

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None
    st.session_state.chat_history = []

if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        with col2:
            mode = st.radio("試卷模式", ["🟢 適中 (標準)", "🌟 素養 (PISA/TIMSS)"], index=1)

        uploaded_files = st.file_uploader("上傳教材或審核表 (PDF, Word, Excel, CSV, 圖片)", 
                                         type=["pdf", "docx", "doc", "csv", "xlsx", "jpg", "png"], 
                                         accept_multiple_files=True)
        
        start_btn = st.button("🚀 自動分析並產生審核表", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        all_text = ""
        imgs = []
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_text += f"\n[檔案:{f.name}]\n" + read_pdf(f)
            elif ext == 'docx': all_text += f"\n[檔案:{f.name}]\n" + read_docx(f)
            elif ext == 'csv': all_text += f"\n[資料:{f.name}]\n" + read_csv(f)
            elif ext == 'xlsx': all_text += f"\n[Excel:{f.name}]\n" + read_excel(f)
            elif ext in ['jpg', 'png', 'jpeg']: imgs.append(Image.open(f))
        
        user_msg = f"科目：{subject}\n年級：{grade}\n模式：{mode}\n任務：自動抓取各單元節數並計算配分比例。\n資料內容：{all_text}"
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name="models/gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在掃描節數並計算配分..."):
                response = chat.send_message([user_msg] + imgs)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"初始化失敗：{e}")

else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("確認審核表無誤請輸入「開始出題」..."):
        with st.chat_message("user"): st.markdown(prompt)
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
