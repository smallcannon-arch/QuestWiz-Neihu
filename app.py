import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image
import io

# ==========================================
# 1. 檔案處理工具
# ==========================================
def read_pdf(file):
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        return "".join([p.extract_text() or "" for p in pdf_reader.pages])
    except: return f"[PDF讀取失敗: {file.name}]"

def read_docx(file):
    try:
        doc = Document(file)
        return "\n".join([p.text for p in doc.paragraphs])
    except: return f"[Word讀取失敗: {file.name}]"

def read_doc_dirty(file):
    try:
        content = file.read()
        return content.decode('big5', errors='ignore')
    except: return f"[舊版.doc讀取失敗: {file.name}]"

# ==========================================
# 2. 核心 System Prompt (內建節數配分邏輯)
# ==========================================
SYSTEM_PROMPT = """
你是「國小定期評量命題與審核 AI」。
你的目標是產生高品質試卷與【試題審核表】，並嚴格遵守「授課節數比例配分」原則。

### 核心規則：
1. **授課節數比例配分**：
   - 子單元配分 = (子單元節數 / 總節數) * 100 分。
   - 在【試題審核表】中，必須明確標註每個單元的預計配分與實際配分。
2. **兩段式輸出**：先出【試題審核表】，確認後才出【試卷】。
3. **題型硬約束**：
   - 總分 100，總格數 34-45 格。
   - 單格最高 3 分。
4. **選項品質 (OptionClass)**：選項必須同性質，禁止「以上皆是/非」。
5. **素養導向**：若模式為「素養」，採用 PISA/TIMSS/PIRLS 架構，強調真實情境與圖表判讀。

### 輸出格式：
(一) 【試題審核表】 (Markdown 表格)
- 包含：範圍、模式、總分、配分分解、圖表清單。
- **子單元權重對照表**：列出「單元名稱 | 節數 | 預計佔分 | 實際題號」。
- 學習目標覆蓋表。

(二) 【試題】
- 依題組呈現，含情境文本(≥50字)。
"""

# ==========================================
# 3. 網頁介面
# ==========================================
st.set_page_config(page_title="QuestWiz 命題助手", layout="wide")
st.title("📝 QuestWiz 校內命題管理系統")

with st.sidebar:
    st.header("🔑 系統設定")
    api_key = st.text_input("Gemini API Key", type="password")
    st.info("💡 模式說明：\n- **適中**：基礎學力檢測\n- **素養**：PISA/TIMSS 標準")

if "chat_session" not in st.session_state:
    st.session_state.chat_session = None
    st.session_state.chat_history = []

if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
            mode = st.radio("試卷模式", ["🟢 適中", "🔴 困難", "🌟 素養"], index=2)
        with col2:
            subject = st.selectbox("科目", ["依教材推定", "國語", "數學", "自然", "社會"], index=3)
            # 新增：節數輸入
            lesson_info = st.text_area("子單元節數分配 (必填)", placeholder="例：\n3-1 水溶液性質：4節\n3-2 酸鹼檢測：7節\n4-1 力的測量：5節")

        uploaded_files = st.file_uploader("上傳教材 (可多檔)", type=["pdf", "docx", "doc", "pptx", "jpg", "png"], accept_multiple_files=True)
        
        start_btn = st.button("🚀 產生試題審核表", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files and lesson_info:
        all_text = ""
        imgs = []
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_text += read_pdf(f)
            elif ext == 'docx': all_text += read_docx(f)
            elif ext == 'doc': all_text += read_doc_dirty(f)
            elif ext in ['jpg', 'png', 'jpeg']: imgs.append(Image.open(f))
        
        user_msg = f"科目：{subject}\n年級：{grade}\n模式：{mode}\n節數分配：{lesson_info}\n教材內容：{all_text}"
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=SYSTEM_PROMPT)
        chat = model.start_chat(history=[])
        
        with st.spinner("正在計算配分並設計審核表..."):
            response = chat.send_message([user_msg] + imgs)
            st.session_state.chat_session = chat
            st.session_state.chat_history.append({"role": "model", "content": response.text})
            st.rerun()

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
        st.rerun()
