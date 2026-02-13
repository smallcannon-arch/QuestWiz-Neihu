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
        # 解析 Markdown 表格行
        lines = [l for l in md_text.strip().split('\n') if l.startswith('|')]
        if len(lines) < 3: return None
        
        # 提取標題與內容
        headers = [c.strip() for c in lines[0].split('|') if c.strip()]
        data = []
        for l in lines[2:]: # 跳過標題與分隔線
            row = [c.strip() for c in l.split('|') if c.strip()]
            if len(row) == len(headers):
                data.append(row)
        
        df = pd.DataFrame(data, columns=headers)
        
        # 轉為 Excel Bytes
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='試題審核表')
        return output.getvalue()
    except:
        return None

# --- 3. 核心 Gem 命題鐵律 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
1. **第一階段**：產出【試題審核表】。目標原文提取、題號對應、配分權重計算。
2. **第二階段**：產出【試題】與【參考答案卷】。
3. **鐵律**：總分固定 100 分，總格數 34-45 格，嚴禁「以上皆是/皆非」。
"""

# --- 4. 網頁介面設計 (深色高對比質感) ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    /* 深色背景與字體顏色控制 */
    .stApp { background-color: #0F172A; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #CBD5E1 !important; }
    
    /* 標題區塊 */
    .school-header {
        background-color: #1E293B;
        padding: 25px;
        border-radius: 15px;
        text-align: center;
        margin-bottom: 30px;
        border: 1px solid #334155;
    }
    .school-name { font-size: 24px; font-weight: 700; color: #94A3B8; letter-spacing: 2px; }
    .app-title { font-size: 16px; color: #64748B; margin-top: 5px; }

    /* 版權宣告 */
    .footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #0F172A;
        color: #475569;
        text-align: center;
        padding: 15px;
        font-size: 12px;
        border-top: 1px solid #1E293B;
    }
    
    /* 按鈕樣式優化 */
    .stButton>button { border-radius: 8px; font-weight: 600; }
    </style>
    
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">AI 輔助出題系統</div>
    </div>
    """, unsafe_allow_html=True)

# 狀態管理
if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None

# Sidebar
with st.sidebar:
    st.subheader("🔑 系統設定")
    api_input = st.text_area("貼上 API Key (多組請用逗號隔開)", height=100)
    st.divider()
    if st.button("🔄 重置命題進度"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.rerun()

# --- Phase 1 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📋 第一階段：規劃審核表")
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("請選擇年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=0)
        with c2: subject = st.selectbox("請選擇科目", ["", "自然科學", "國語", "數學", "社會", "英語"], index=0)
        with c3: mode = st.selectbox("命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("上傳教材檔案", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出試題審核表", type="primary", use_container_width=True):
            if not grade or not subject or not api_input or not uploaded_files:
                st.error("⚠️ 提醒：請先選擇年級、科目並上傳教材。")
            else:
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
                    with st.spinner("⚡ 正在分析教材目標..."):
                        res = chat.send_message(f"年級：{grade}, 科目：{subject}, 模式：{mode}\n教材：{content}\n--- 請產出【試題審核表】表格。")
                        st.session_state.chat_session = chat
                        st.session_state.chat_history.append({"role": "model", "content": res.text})
                        st.session_state.phase = 2
                        st.rerun()
                except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2 ---
elif st.session_state.phase == 2:
    # 顯示審核表
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"):
        st.markdown(current_md)
        # Excel 下載按鈕
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button(label="📥 下載此審核表 (Excel)", data=excel_data, file_name=f"內湖國小_{subject}_審核表.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()
    with st.container(border=True):
        st.markdown("### 📝 第二階段：確認無誤後產出試卷")
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("✅ 審核表無誤，開始出題", type="primary", use_container_width=True):
                with st.spinner("⚡ 正在產出試題與答案卷..."):
                    res = st.session_state.chat_session.send_message("確認無誤，請開始產出【試題】與【參考答案卷】。")
                    st.session_state.chat_history.append({"role": "model", "content": res.text})
                    st.rerun()
        with cb2:
            if st.button("⬅️ 返回修改", use_container_width=True):
                st.session_state.phase = 1
                st.session_state.chat_history = []
                st.rerun()

    if len(st.session_state.chat_history) > 1:
        for msg in st.session_state.chat_history[1:]:
            with st.chat_message("ai"): st.markdown(msg["content"])
        if prompt := st.chat_input("需要微調題目或答案嗎？"):
            res = st.session_state.chat_session.send_message(prompt)
            st.session_state.chat_history.append({"role": "model", "content": res.text})
            st.rerun()

# Footer
st.markdown("""
    <div class="footer">
        Copyright © 2026 新竹市香山區內湖國小. All Rights Reserved.
    </div>
    """, unsafe_allow_html=True)
