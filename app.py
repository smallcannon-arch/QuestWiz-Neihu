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
    """讀取舊版 doc，需配合 packages.txt 安裝 antiword"""
    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[讀取失敗]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 深度對齊圖片格式與教材提取的指令 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
你的任務是從教材中「原文提取」學習目標，並嚴格依照【內湖國小校內 Excel 格式】產出審核表。

### 核心原則：
1. **原文提取**：學習目標必須直接採自使用者提供的教材內容，不得自行編造或簡化。
2. **格式對齊**：輸出結構需符合提供的 Excel 截圖。

### Phase 1：【試題審核表】格式 (對齊圖片)：
請為「每個單元」產出一個獨立的 Markdown 表格：

#### **[第 X 單元 － 單元名稱]**
| 學習目標 (由教材原文提取) | 授課節數 | 選擇題 (佔分%) | 閱讀/其它 (佔分%) |
| :--- | :---: | :---: | :---: |
| 1. [教材目標原文 1] | [節數] | [配分]% | [配分]% |
| 2. [教材目標原文 2] | | | |
| 3. [教材目標原文 3] | | | |

---
**基本檢查欄位：**
* **命題模式**：{mode} | **科目**：{subject}
* **試卷總分**：100 分 | **總格數**：34-45 格
* **圖表清單**：請列出 [Image of...] 標籤。
"""

# --- 3. 網頁介面配置 ---
st.set_page_config(page_title="QuestWiz 內湖國小專屬版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 API Key", type="password")
    st.divider()
    st.info("💡 格式優化：已對齊校內 Excel 審核表規範")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 第一階段：分析 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會", "英語"], index=0)
        with col3:
            mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材 (支援新舊 Word/PDF/CSV)", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產出【內湖格式】試題審核表", type="primary", use_container_width=True)

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
            # 自動連線診斷
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            target = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available else available[0]
            
            # 將模式與科目動態帶入指令
            current_instr = GEM_INSTRUCTIONS.format(mode=mode, subject=subject, grade=grade)
            
            model = genai.GenerativeModel(model_name=target, system_instruction=current_instr, generation_config={"temperature": 0.0})
            chat = model.start_chat(history=[])
            
            with st.spinner("⚡ 正在分析教材目標並規劃格式..."):
                response = chat.send_message(f"教材內容如下：\n{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    # 顯示歷史紀錄與後續指令
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("確認審核表後，請輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
