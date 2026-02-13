import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from PIL import Image
import pandas as pd
import io

# 1. 檔案讀取工具：確保每個功能都獨立運作
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
    except Exception as e:
        return f"[CSV 讀取失敗: {e}]"

# 2. 核心 AI 指令：設定校內審核表與配分邏輯
SYSTEM_PROMPT = """
你是「內湖國小專用命題助手」。
任務：根據教材產生「試題審核表」與「高品質試卷」。
行政規範：
1. 自動偵測教材或 CSV 中的「節數」關鍵字 (如：3-1 佔 4節)。
2. 計算權重：(該單元節數 / 總節數) * 100 = 該單元配分。
3. 輸出：先給出審核表格，確認後再出題。
"""

# 3. 網頁介面配置
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 行政自動化命題系統")

# 側邊欄：金鑰讀取邏輯
with st.sidebar:
    st.header("🔑 系統設定")
    # 優先從 Streamlit Secrets 讀取，讓老師免輸入
    if "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]
        st.success("✅ 已自動載入校用 API Key")
    else:
        api_key = st.text_input("輸入 Gemini API Key", type="password")
    st.divider()
    st.info("💡 提示：上傳包含『節數』的審核表 CSV，AI 會自動計算佔分。")

# 狀態管理
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# 第一階段：參數設定與檔案上傳
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材或審核表資料", type=["pdf", "docx", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產生審核表與建議配分", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        combined_content = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': combined_content += f"\n[檔案:{f.name}]\n" + read_pdf(f)
            elif ext == 'docx': combined_content += f"\n[檔案:{f.name}]\n" + read_docx(f)
            elif ext == 'csv': combined_content += f"\n[數據:{f.name}]\n" + read_csv(f)
        
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name="models/gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
            chat = model.start_chat(history=[])
            
            with st.spinner("AI 正在分析節數權重並設計題目中..."):
                response = chat.send_message(f"科目：{subject}\n年級：{grade}\n教材內容：{combined_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"系統暫時無法連線：{e}")

# 第二階段：對話互動區
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("對審核表有意見？直接告訴 AI 修改..."):
        with st.chat_message("user"): st.markdown(prompt)
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (新試卷)"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
