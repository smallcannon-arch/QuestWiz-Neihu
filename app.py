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
    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[讀取錯誤]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 2. 核心命題與計算邏輯 (Gem 設定) ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」，請嚴格執行以下行政與命題任務：

### 第一步：權重與配分計算 (核心任務)
1. **提取節數**：從教材中識別各單元的「授課節數」。
2. **總分與權重**：
   - 總分固定 100 分。
   - 單元配分 = (該單元節數 / 總節數) * 100。
3. **題型分配邏輯** (依據模式調整)：
   - 🟢 **模式 A (適中)**：該單元配分之 60% 分配給「選擇題」，40% 分配給「閱讀/其它」。
   - 🔴 **模式 B (困難)**：該單元配分之 30% 分配給「選擇題」，70% 分配給「閱讀/其它」。
   - 🌟 **模式 C (素養)**：該單元配分之 20% 分配給「選擇題」，80% 分配給「閱讀/其它」(含情境題)。

### 第二步：輸出【內湖版試題審核表】格式
請為每個單元產出獨立表格，格式需與 Excel 截圖一致：

#### **[單元名稱]**
| 學習目標 (由教材原文提取) | 授課節數 | 選擇題 (佔分) | 閱讀/其它 (佔分) |
| :--- | :---: | :---: | :---: |
| 1. [原文目標 1] | [節數] | [計算後得分] | [計算後得分] |
| 2. [原文目標 2] | | | |

---
**基本檢查：**
* **命題模式**：{mode} | **科目**：{subject}
* **總格數規範**：34-45 格 (單選 2-3分, 多選/簡答 3分)
* **圖表標記**：列出本單元所需的 [Image of...] 標籤。
"""

# --- 3. 網頁介面配置 ---
st.set_page_config(page_title="QuestWiz 內湖國小版", layout="wide")
st.title("🏫 QuestWiz 試題行政自動化系統")

with st.sidebar:
    st.header("🔑 系統設定")
    st.markdown("[👉 申請金鑰](https://aistudio.google.com/app/apikey)")
    api_key = st.text_input("貼上您的 API Key", type="password")
    st.divider()
    st.success("✅ 邏輯：授課節數自動換算配分比例")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# --- 流程開始 ---
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
        start_btn = st.button("🚀 執行【節數比例分析】並產出審核表", type="primary", use_container_width=True)

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
            
            # 將選擇的模式與科目注入指令
            final_instr = GEM_INSTRUCTIONS.format(mode=mode, subject=subject)
            
            model = genai.GenerativeModel(model_name=target, system_instruction=final_instr, generation_config={"temperature": 0.0})
            chat = model.start_chat(history=[])
            
            with st.spinner("⚡ 正在掃描教材並精算配分權重..."):
                response = chat.send_message(f"年級：{grade}\n科目：{subject}\n教材內容：\n{all_content}")
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
        except Exception as e:
            st.error(f"連線失敗：{e}")
else:
    # 顯示歷史紀錄
    for msg in st.session_state.chat_history:
        with st.chat_message("ai" if msg["role"] == "model" else "user"):
            st.markdown(msg["content"])
    
    if prompt := st.chat_input("配分正確嗎？輸入『開始出題』或修改指令..."):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()
