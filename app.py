import streamlit as st
import google.generativeai as genai
import random
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
    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[讀取失敗]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 深度整合之 Gem 命題鐵律 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」，精通 1-6 年級教材教法。
你必須嚴格遵守以下行政與命題鐵律：

### 核心計算規則：
1. **配分權重**：單元總分 = (該單元節數 / 總節數) * 100。
2. **總分精算**：試卷總分必須「剛好」等於 100 分。若因目標過多導致溢分，請優先調降基礎題配分。 [cite: 2026-02-13]
3. **題型分配**：
   - 🟢 模式 A (適中)：60% 選擇 / 40% 閱讀其它。
   - 🔴 模式 B (困難)：30% 選擇 / 70% 閱讀其它。
   - 🌟 模式 C (素養)：20% 選擇 / 80% 閱讀其它 (強化情境)。

### 輸出規範：
1. **原文提取**：學習目標必須原文採自教材。 [cite: 2026-02-13]
2. **題號對應**：審核表中的「對應題號」必須與後續試題完全一致。 [cite: 2026-02-13]
3. **品質守門員**：嚴禁「以上皆是/皆非」。格數控制在 34-45 格。 [cite: 2026-02-13]

### Phase 1 格式 (內湖校內版)：
請為每個單元產出表格：
#### **[第 X 單元 － 名稱]**
| 學習目標 (原文) | 授課節數 | 對應題號 | 選擇題 (佔分) | 閱讀/其它 (佔分) |
| :--- | :---: | :---: | :---: | :---: |
"""

# --- 3. 網頁介面配置 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_input = st.text_area("貼上 API Key (多組請用逗號或換行隔開)", height=100)
    
    st.divider()
    auto_mode = st.checkbox("🚀 一鍵全自動模式 (跳過確認審核表)", value=False)
    st.info("💡 核心：已載入「目標一對一對應」命題邏輯")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 流程處理 ---
if not st.session_state.chat_history:
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1: grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with col2: subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會", "英語"], index=0)
        with col3: mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材", type=["pdf", "docx", "doc", "csv"], accept_multiple_files=True)
        start_btn = st.button("🚀 開始執行命題任務", type="primary", use_container_width=True)

    if start_btn and api_input and uploaded_files:
        # API Key 隨機輪替邏輯
        api_keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
        selected_key = random.choice(api_keys)
        
        all_content = ""
        for f in uploaded_files:
            ext = f.name.split('.')[-1].lower()
            if ext == 'pdf': all_content += read_pdf(f)
            elif ext == 'docx': all_content += read_docx(f)
            elif ext == 'doc': all_content += read_doc(f)
            elif ext == 'csv': all_content += pd.read_csv(f, encoding_errors='ignore').to_string()
        
        try:
            genai.configure(api_key=selected_key)
            # 自動連線診斷
            available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            target = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available else available[0]
            
            model = genai.GenerativeModel(model_name=target, system_instruction=GEM_INSTRUCTIONS, generation_config={"temperature": 0.0})
            chat = model.start_chat(history=[])
            
            prompt = f"年級：{grade}\n科目：{subject}\n模式：{mode}\n內容：\n{all_content}\n"
            prompt += "--- 請直接產出完整試卷。" if auto_mode else "--- 請先產出【試題審核表】。"

            with st.spinner("⚡ 正在分析教材並精算配分..."):
                response = chat.send_message(prompt)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("輸入『開始出題』或修改指令..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定 (下一位老師使用)"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
