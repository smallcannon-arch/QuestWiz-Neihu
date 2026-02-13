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

# --- 1. 定義學科與題型映射 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 2. 檔案讀取工具 ---
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

# --- 3. Excel 下載工具 ---
def md_to_excel(md_text):
    try:
        lines = [l for l in md_text.strip().split('\n') if l.startswith('|')]
        if len(lines) < 3: return None
        headers = [c.strip() for c in lines[0].split('|') if c.strip()]
        data = [[c.strip() for c in l.split('|') if c.strip()] for l in lines[2:]]
        df = pd.DataFrame(data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        return output.getvalue()
    except: return None

# --- 4. 核心 Gem 命題鐵律 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
1. **科目守門員**：若教材與科目明顯不符，僅回覆：『ERROR_SUBJECT_MISMATCH』。
2. **目標對應**：學習目標必須原文採自教材。每一條目標在整份試卷中至少出現一次。
3. **分階段輸出**：Phase 1 審核表，Phase 2 試卷與答案。
"""

# --- 5. 網頁介面視覺設計 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0F172A; }
    .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 5rem; }
    
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 30px; border-radius: 20px; text-align: center; margin-bottom: 30px; 
        border: 1px solid #475569;
    }
    .school-name { font-size: 28px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 16px; color: #94A3B8; margin-top: 8px; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #E2E8F0 !important; }
    
    /* 詳細版卡片樣式 */
    .step-box {
        background-color: #1E293B; padding: 12px; border-radius: 10px; 
        margin-bottom: 12px; border-left: 5px solid #3B82F6; font-size: 13px;
        color: #CBD5E1;
    }
    .step-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    .step-box a:hover { text-decoration: underline; }
    
    /* 側邊欄按鈕強制置中 */
    [data-testid="stSidebar"] .stButton > button { display: block; margin: 0 auto !important; }
    
    .footer { position: fixed; left: 0; bottom: 0; width: 100%; background-color: #0F172A; color: #475569; text-align: center; padding: 15px; font-size: 11px; border-top: 1px solid #1E293B; z-index: 100; }
    </style>
    
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">評量命題與學習目標自動化系統</div>
    </div>
    """, unsafe_allow_html=True)

# 狀態管理
if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None

# --- Sidebar: 詳細引導 ---
with st.sidebar:
    st.markdown("### 🖥️ 快速開始指南")
    st.markdown("""
    <div class="step-box">
        <b>Step 1. 前往官網</b><br>
        🔗 <a href="https://aistudio.google.com/" target="_blank">Google AI Studio (點我)</a>
    </div>
    <div class="step-box">
        <b>Step 2. 登入帳號</b><br>
        👤 請登入您的教育 Google 帳號
    </div>
    <div class="step-box">
        <b>Step 3. 取得金鑰</b><br>
        🆕 點擊 <b>"Get API key"</b> 並複製
    </div>
    <div class="step-box">
        <b>Step 4. 啟用系統</b><br>
        📋 貼到下方框內即可開始
    </div>
    """, unsafe_allow_html=True)
    
    api_input = st.text_area("在此輸入 API Key", height=70, placeholder="必填欄位")
    
    st.divider()
    
    # --- 資源區塊 (全數更新) ---
    st.markdown("### 📂 資源快速連結")
    st.markdown("""
    <div class="step-box">
        <b>📖 教材資源下載</b><br>
        - <a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒電子書</a><br>
        - <a href="https://edisc3.hle.com.tw/" target="_blank">翰林行動大師 (新)</a><br>
        - <a href="https://reader.nani.com.tw/" target="_blank">南一 OneBox</a>
    </div>
    <div class="step-box">
        <b>🏛️ 官方參考資料</b><br>
        - <a href="https://cirn.moe.edu.tw/Syllabus/index.aspx?sid=1108" target="_blank">108 課綱資源網 (CIRN)</a><br>
        - <a href="https://www.nhps.hc.edu.tw/" target="_blank">內湖國小校網</a>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    if st.button("🔄 重置系統進度"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.rerun()

# --- Phase 1: 規劃審核表 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與學習目標規劃")
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("1. 選擇年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=0)
        with c2: subject = st.selectbox("2. 選擇科目", ["", "國語", "數學", "自然科學", "社會", "英語"], index=0)
        with c3: mode = st.selectbox("3. 命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        st.divider()
        st.markdown("**4. 勾選欲產出的題型**")
        available_types = SUBJECT_Q_TYPES.get(subject, SUBJECT_Q_TYPES[""])
        cols = st.columns(min(len(available_types), 4))
        selected_types = []
        for i, t in enumerate(available_types):
            if cols[i % len(cols)].checkbox(t, value=True):
                selected_types.append(t)
        
        st.divider()
        uploaded_files = st.file_uploader("5. 上傳教材檔案", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        # --- 🔴 嚴格防呆區：只有按下按鈕才會執行以下判斷 ---
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            # 1. 檢查 API
            if not api_input:
                st.error("❌ 動作中止：尚未輸入 API Key。")
            # 2. 檢查參數與檔案
            elif not grade or not subject or not uploaded_files or not selected_types:
                st.warning("⚠️ 動作中止：請確認年級、科目、題型與教材已備妥。")
            # 3. 若都通過，才開始執行
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
                    with st.spinner("⚡ 正在分析教材內容並原文提取學習目標..."):
                        t_str = "、".join(selected_types)
                        res = chat.send_message(f"年級：{grade}, 科目：{subject}\n題型：{t_str}\n教材：{content}")
                        # 4. 檢查科目內容相符性
                        if "ERROR_SUBJECT_MISMATCH" in res.text:
                            st.error(f"❌ 防呆啟動：偵測到教材內容與『{subject}』不符，請重新確認檔案。")
                        else:
                            st.session_state.chat_session = chat
                            st.session_state.chat_history.append({"role": "model", "content": res.text})
                            st.session_state.phase = 2
                            st.rerun()
                except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2: 出題 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"):
        st.markdown(current_md)
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button(label="📥 匯出此學習目標審核表 (Excel 格式)", data=excel_data, file_name=f"內湖國小_{subject}_審核表.xlsx", use_container_width=True)

    st.divider()
    with st.container(border=True):
        st.markdown("### 📝 第二階段：試卷正式生成")
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("✅ 審核表確認無誤，開始出題", type="primary", use_container_width=True):
                with st.spinner("⚡ 命題中..."):
                    res = st.session_state.chat_session.send_message("確認無誤，請依照此表產出【試題】與【參考答案卷】。")
                    st.session_state.chat_history.append({"role": "model", "content": res.text})
                    st.rerun()
        with cb2:
            if st.button("⬅️ 返回修改參數", use_container_width=True):
                st.session_state.phase = 1
                st.session_state.chat_history = []
                st.rerun()

    if len(st.session_state.chat_history) > 1:
        for msg in st.session_state.chat_history[1:]:
            with st.chat_message("ai"): st.markdown(msg["content"])
        if prompt := st.chat_input("微調試題？"):
            res = st.session_state.chat_session.send_message(prompt)
            st.session_state.chat_history.append({"role": "model", "content": res.text})
            st.rerun()

st.markdown('<div class="footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
