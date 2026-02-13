import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
from docx import Document
import pandas as pd
import subprocess
import os

# --- 1. 檔案讀取工具 (支援 .doc, .docx, .pdf) ---
def read_pdf(file):
    pdf_reader = PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_doc(file):
    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[讀取錯誤]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 核心命題連動邏輯 (深度整合您的 Gem 設定) ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。你必須嚴格執行「目標對應題號」的命題鐵律：

### 核心鐵律 (Core Principle)：
1. **原文照錄**：學習目標必須從教材中原文提取。 [cite: 2026-02-13]
2. **目標全覆蓋**：每條目標至少入題 1 次，並在審核表中明確標註「對應題號」。 [cite: 2026-02-13]
3. **兩段式輸出**：Phase 1 產出含題號的審核表，Phase 2 嚴格依照該表出題。 [cite: 2026-02-13]

### Phase 1 輸出格式 (內湖國小審核表)：
請為每個單元產出表格，結構如下：

#### **[單元名稱]**
| 學習目標 (原文提取) | 授課節數 | 對應題號 | 選擇題 (佔分) | 閱讀/其它 (佔分) |
| :--- | :---: | :---: | :---: | :---: |
| 1. [教材目標 1] | [節數] | 第 1, 2 題 | [得分] | [得分] |
| 2. [教材目標 2] | | 第 3 題 | | |

---
**基本檢查 (依據模式)：**
* **模式**：{mode} (A:60/40, B:30/70, C:20/80)
* **總分**：100 分 | **總格數**：34-45 格
* **圖表需求**：列出 [Image of...] 標籤。
"""

# --- 3. 網頁介面配置 ---
st.set_page_config(page_title="QuestWiz 內湖國小專屬版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 API Key", type="password")
    st.divider()
    st.info("💡 核心：學習目標全覆蓋與題號連動")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2:
            subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會", "英語"], index=0)
        with col3:
            mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 產出「含題號對應」之審核表", type="primary", use_container_width=True)

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
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            target = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available else available[0]
            
            # 將選擇的模式注入指令
            final_instr = GEM_INSTRUCTIONS.format(mode=mode, subject=subject)
            
            model = genai.GenerativeModel(model_name=target, system_instruction=final_instr, generation_config={"temperature": 0.0})
            chat = model.start_chat(history=[])
            
            with st.spinner("⚡ 正在分析目標覆蓋並規劃題號對應..."):
                response = chat.send_message(f"內容：\n{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("確認對應題號無誤後，請輸入『開始出題』..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
