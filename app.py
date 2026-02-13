import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image
import pandas as pd
import io

# ==========================================
# 1. 增強型檔案處理工具 (加入 CSV 支援)
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
        return df.to_string() # 將表格轉為純文字讓 AI 讀取
    except: return "[CSV讀取失敗]"

# ==========================================
# 2. 進化版 System Prompt (強調自動抓取節數)
# ==========================================
SYSTEM_PROMPT = """
你是「內湖國小專用命題與審核 AI」。
你的任務是根據教材內容自動產生「試題審核表」與「高品質試卷」。

### ⚡ 行政配分核心指令：
1. **自動偵測節數**：請掃描教材或上傳的審核表，尋找「X節」或「X堂課」的關鍵字。
   - 例如：看到「3-1 ... 4節」、「3-2 ... 7節」，則總節數為 11 節。
2. **比例配分公式**：
   - 子單元配分 = (該單元節數 / 總節數) * 100。
   - 請在【試題審核表】中精確顯示此計算結果。
3. **兩段式輸出**：先輸出審核表（含配分權重表），確認後才出題。
4. **素養導向**：符合 PISA/TIMSS 標準，使用生活化情境。

### 輸出格式：
(一) 【試題審核表】
- 包含：範圍、模式、總分、配分分解。
- **權重對照表**：單元名稱 | 偵測到節數 | 權重百分比 | 預計佔分。
- 學習目標覆蓋表。
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
    st.info("💡 系統已開啟「自動節數偵測」，AI 將自行從上傳的審核表或教材中計算配分。")

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
            mode = st.radio("試卷模式", ["🟢 適中 (標準)", "🌟 素養 (國際標準)"], index=1)

        st.markdown("---")
        # 多檔上傳
        uploaded_files = st.file_uploader("上傳教材或舊版審核表 (支援 PDF, Word, CSV, 圖片)", 
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
            elif ext == 'csv': all_text += f"\n[資料表:{f.name}]\n" + read_csv(f)
            elif ext in ['jpg', 'png', 'jpeg']: imgs.append(Image.open(f))
        
        user_msg = f"科目：{subject}\n年級：{grade}\n模式：{mode}\n任務：請自動從上傳資料中抓取各單元節數並計算 100 分之配分比例。\n資料內容：{all_text}"
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
        model_name="models/gemini-1.5-pro", 
        system_instruction=SYSTEM_PROMPT
    )
except Exception as e:
    st.error(f"模型初始化失敗，請檢查 API Key 或模型權限。錯誤資訊：{e}")
        chat = model.start_chat(history=[])
        
        with st.spinner("AI 正在掃描節數並計算配分權重..."):
            response = chat.send_message([user_msg] + imgs)
            st.session_state.chat_session = chat
            st.session_state.chat_history.append({"role": "model", "content": response.text})
            st.rerun()

else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])

    if prompt := st.chat_input("確認審核表與配分比例無誤請輸入「開始出題」..."):
        with st.chat_message("user"): st.markdown(prompt)
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (新試卷)"):
        st.session_state.chat_history = []
        st.rerun()

