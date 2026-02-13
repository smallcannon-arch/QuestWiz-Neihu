import streamlit as st
import google.generativeai as genai
import random
import io
import re
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

# --- 2. Markdown 表格轉 Excel 工具 ---
def md_to_excel(md_text):
    try:
        # 尋找 Markdown 表格
        tables = re.findall(r'\|(.+)\|', md_text)
        if not tables: return None
        
        # 簡單解析 Markdown 表格轉為 DataFrame
        lines = md_text.strip().split('\n')
        table_lines = [l for l in lines if l.startswith('|')]
        if len(table_lines) < 3: return None
        
        # 處理標題與資料
        headers = [c.strip() for c in table_lines[0].split('|') if c.strip()]
        data = []
        for l in table_lines[2:]: # 跳過標題與分隔線
            row = [c.strip() for c in l.split('|') if c.strip()]
            if len(row) == len(headers): data.append(row)
        
        df = pd.DataFrame(data, columns=headers)
        
        # 轉換為 Excel Byte 流
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='試題審核表')
        return output.getvalue()
    except:
        return None

# --- 3. 核心 Gem 命題鐵律 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
### 命題鐵律：
1. **兩段式輸出**：Phase 1 給審核表，Phase 2 給題目與答案。
2. **目標覆蓋**：每一條學習目標必須原文提取並對應到具體題號。
3. **自動產出答案**：在試題結尾，務必產出【參考答案與解析】，包含正確選項與解題要點。
4. **配分校正**：總分固定 100 分，總格數 34-45 格。
"""

# --- 4. 網頁介面配置 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    .school-name { font-size: 24px; color: #1E3A8A; font-weight: bold; margin-bottom: 0px; }
    .app-title { font-size: 18px; color: #4B5563; margin-top: 0px; margin-bottom: 10px; }
    </style>
    <div class="school-name">新竹市香山區內湖國小</div>
    <div class="app-title">AI 輔助出題系統</div>
    <hr style='margin-top: 0; margin-bottom: 20px;'>
    """, unsafe_allow_html=True)

if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None

with st.sidebar:
    st.header("🔑 系統設定")
    api_input = st.text_area("貼上 API Key (多組請用逗號隔開)", height=100)
    st.divider()
    if st.button("🔄 重設系統"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()

# --- Phase 1 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.subheader("第一步：上傳教材規劃審核表")
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
        with c2: subject = st.selectbox("科目", ["自然科學", "國語", "數學", "社會"], index=0)
        with c3: mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        uploaded_files = st.file_uploader("上傳教材", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出試題審核表", type="primary", use_container_width=True):
            if api_input and uploaded_files:
                keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                genai.configure(api_key=random.choice(keys))
                content = ""
                for f in uploaded_files:
                    ext = f.name.split('.')[-1].lower()
                    if ext == 'pdf': content += read_pdf(f)
                    elif ext == 'docx': content += read_docx(f)
                    elif ext == 'doc': content += read_doc(f)
                
                try:
                    available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    target = "models/gemini-2.5-flash" if "models/gemini-2.5-flash" in available else available[0]
                    model = genai.GenerativeModel(model_name=target, system_instruction=GEM_INSTRUCTIONS, generation_config={"temperature": 0.0})
                    chat = model.start_chat(history=[])
                    with st.spinner("⚡ 正在分析教材..."):
                        res = chat.send_message(f"年級：{grade}, 科目：{subject}, 模式：{mode}\n教材：{content}\n--- 請產出【試題審核表】。")
                        st.session_state.chat_session = chat
                        st.session_state.chat_history.append({"role": "model", "content": res.text})
                        st.session_state.phase = 2
                        st.rerun()
                except Exception as e: st.error(f"錯誤：{e}")

# --- Phase 2 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"):
        st.markdown(current_md)
        # --- 下載 Excel 功能 ---
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button(label="📥 下載此審核表 (Excel)", data=excel_data, file_name="內湖國小試題審核表.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    with st.container(border=True):
        st.subheader("第二步：產出試題與答案")
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("✅ 開始出題 (含參考答案)", type="primary", use_container_width=True):
                with st.spinner("⚡ 正在依照審核表命題中..."):
                    res = st.session_state.chat_session.send_message("審核表確認無誤，請開始出題並在最後附上【參考答案與解析】。")
                    st.session_state.chat_history.append({"role": "model", "content": res.text})
                    st.rerun()
        with c_btn2:
            if st.button("⬅️ 返回修改", use_container_width=True):
                st.session_state.phase = 1
                st.session_state.chat_history = []
                st.rerun()

    # 顯示後續產出的題目與答案
    if len(st.session_state.chat_history) > 1:
        for msg in st.session_state.chat_history[1:]:
            with st.chat_message("ai"): st.markdown(msg["content"])

    if prompt := st.chat_input("需要修改題目或調整答案嗎？"):
        res = st.session_state.chat_session.send_message(prompt)
        st.session_state.chat_history.append({"role": "model", "content": res.text})
        st.rerun()
