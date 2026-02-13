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
        lines = [l for l in md_text.strip().split('\n') if l.startswith('|')]
        if len(lines) < 3: return None
        headers = [c.strip() for c in lines[0].split('|') if c.strip()]
        data = [[c.strip() for c in l.split('|') if c.strip()] for l in lines[2:]]
        df = pd.DataFrame(data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='試題審核表')
        return output.getvalue()
    except: return None

# --- 3. 核心 Gem 命題鐵律 (嚴格限制輸出階段) ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
### ⚠️ 輸出控制鐵律 (非常重要)：
1. **Phase 1 (當前階段)**：僅允許產出【試題審核表】表格。禁止產出任何具體的考試題目。 [cite: 2026-02-13]
2. **Phase 2 (待命階段)**：只有當使用者明確輸入『開始出題』後，才可產出試題與【參考答案與解析】。 [cite: 2026-02-13]
3. **目標對應**：學習目標必須原文提取並掛鉤題號。
4. **配分精算**：總分固定 100 分。
"""

# --- 4. 網頁介面視覺設計 (美化版) ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    /* 全域字體與背景 */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;700&display=swap');
    html, body, [class*="st-"] { font-family: 'Noto Sans TC', sans-serif; background-color: #F1F5F9; }
    
    /* 專業深藍標題列 */
    .school-header {
        background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
        padding: 30px;
        border-radius: 20px;
        color: white;
        text-align: center;
        margin-bottom: 30px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .school-name { font-size: 28px; font-weight: 700; letter-spacing: 3px; }
    .app-title { font-size: 18px; font-weight: 300; opacity: 0.9; margin-top: 8px; }
    
    /* 卡片設計 */
    .st-emotion-cache-12w0qpk { 
        background-color: white !important; 
        border-radius: 15px !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05) !important;
        padding: 25px !important;
    }
    </style>
    
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">AI 輔助出題系統</div>
    </div>
    """, unsafe_allow_html=True)

# 初始化進度
if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None
if "show_exam" not in st.session_state: st.session_state.show_exam = False

# --- Sidebar ---
with st.sidebar:
    st.subheader("🔑 系統金鑰設定")
    api_input = st.text_area("多組 Key 請用逗號隔開", height=100)
    st.divider()
    if st.button("🔄 重置命題進度"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.session_state.show_exam = False
        st.rerun()

# --- Phase 1: 上傳與分析 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📋 第一階段：規劃審核表")
        c1, c2, c3 = st.columns(3)
        # 預設空白 (index=0 為 "")
        with c1: grade = st.selectbox("請選擇年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=0)
        with c2: subject = st.selectbox("請選擇科目", ["", "自然科學", "國語", "數學", "社會", "英語"], index=0)
        with c3: mode = st.selectbox("請選擇命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        uploaded_files = st.file_uploader("請上傳教材檔案 (PDF/Word)", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
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
                    
                    with st.spinner("⚡ 正在嚴格計算配分並產出審核表..."):
                        # 特別強調：此階段禁止出題
                        res = chat.send_message(f"年級：{grade}, 科目：{subject}, 模式：{mode}\n教材：{content}\n--- 請產出【試題審核表】。注意：嚴禁在此階段產出試題內容。")
                        st.session_state.chat_session = chat
                        st.session_state.chat_history.append({"role": "model", "content": res.text})
                        st.session_state.phase = 2
                        st.rerun()
                except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2: 確認與出題 ---
elif st.session_state.phase == 2:
    # 僅顯示審核表 (chat_history 的第一項)
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"):
        st.markdown(current_md)
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button("📥 下載此審核表 (Excel)", data=excel_data, file_name=f"內湖國小_{subject}_審核表.xlsx")

    st.divider()
    
    # 只有尚未開始出題時，才顯示「確認出題」按鈕
    if not st.session_state.show_exam:
        with st.container(border=True):
            st.markdown("### 📝 第二階段：確認無誤後開始命題")
            cb1, cb2 = st.columns(2)
            with cb1:
                if st.button("✅ 審核表確認無誤，開始出題", type="primary", use_container_width=True):
                    st.session_state.show_exam = True # 開啟出題門檻
                    with st.spinner("⚡ 正在依照審核表產生試題與參考答案..."):
                        res = st.session_state.chat_session.send_message("審核表確認無誤，請開始產出【試題】與【參考答案卷】。")
                        st.session_state.chat_history.append({"role": "model", "content": res.text})
                        st.rerun()
            with cb2:
                if st.button("⬅️ 返回修改參數", use_container_width=True):
                    st.session_state.phase = 1
                    st.session_state.chat_history = []
                    st.session_state.show_exam = False
                    st.rerun()
    
    # 若已開啟出題，則顯示後續內容
    if st.session_state.show_exam:
        for msg in st.session_state.chat_history[1:]:
            with st.chat_message("ai"):
                st.markdown(msg["content"])
        
        if prompt := st.chat_input("需要對題目或答案進行微調嗎？"):
            res = st.session_state.chat_session.send_message(prompt)
            st.session_state.chat_history.append({"role": "model", "content": res.text})
            st.rerun()
