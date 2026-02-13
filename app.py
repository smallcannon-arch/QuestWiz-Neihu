import streamlit as st
import google.generativeai as genai
import random
import io
import time
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

# --- 2. 核心功能函式 (延續之前進度) ---
@st.cache_data
def extract_text_from_files(files):
    text_content = ""
    for file in files:
        try:
            ext = file.name.split('.')[-1].lower()
            if ext == 'pdf':
                pdf_reader = PdfReader(file)
                text_content += "".join([p.extract_text() or "" for p in pdf_reader.pages])
            elif ext == 'docx':
                doc = Document(file)
                text_content += "\n".join([p.text for p in doc.paragraphs])
            elif ext == 'doc':
                with open("temp.doc", "wb") as f: f.write(file.getbuffer())
                result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
                if result.returncode == 0: text_content += result.stdout
                if os.path.exists("temp.doc"): os.remove("temp.doc")
        except: text_content += f"\n[讀取錯誤: {file.name}]"
    return text_content

def find_available_model(api_key, keyword="flash"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target = next((m for m in models if keyword in m.lower()), models[0])
        return target, None
    except Exception as e: return None, str(e)

def process_table_data(md_text):
    try:
        cleaned = md_text.replace("｜", "|").replace("**", "").replace("||", "|\n|")
        header_match = re.search(r'\|\s*單元名稱\s*\|\s*學習目標.*\|\s*對應題型\s*\|\s*預計配分\s*\|', cleaned)
        if not header_match: return None
        raw_cells = [c.strip() for c in cleaned[header_match.start():].split('|') if c.strip() and '---' not in c]
        num_cols = 4 
        if len(raw_cells) < num_cols: return None
        headers = raw_cells[:num_cols]
        data_cells = raw_cells[num_cols:]
        rows = [data_cells[i:i+num_cols] for i in range(0, len(data_cells), num_cols)]
        for r in rows:
            if len(r) < num_cols: r += [''] * (num_cols - len(r))
        return pd.DataFrame(rows, columns=headers)
    except: return None

# --- 3. 視覺與排版設計 (補回超連結與平均分散) ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    header[data-testid="stHeader"], footer { display: none !important; }
    .stApp { background-color: #0F172A; }
    .block-container { max-width: 1200px; padding-top: 1.5rem !important; }
    
    .school-header { background: linear-gradient(90deg, #1E293B 0%, #334155 100%); padding: 25px; border-radius: 15px; text-align: center; margin-bottom: 25px; border: 1px solid #475569; }
    .school-name { font-size: 24px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 14px; color: #94A3B8; }

    /* 側邊欄平均分散排版 [cite: 2026-02-13] */
    [data-testid="stSidebar"] > div:first-child {
        display: flex;
        flex-direction: column;
        height: 95vh;
    }
    .sb-section { flex-grow: 1; display: flex; flex-direction: column; justify-content: center; }

    .comfort-box { background-color: #1E293B; padding: 15px; border-radius: 10px; border-left: 5px solid #3B82F6; font-size: 13px; color: #CBD5E1; line-height: 1.7; }
    .comfort-box b { color: #60A5FA; }
    .comfort-box a { color: #F87171 !important; text-decoration: none; font-weight: bold; }
    
    /* 防止文字遮擋與按鈕優化 */
    .stTextArea textarea { font-size: 14px; }
    [data-testid="stSidebar"] .stButton > button { width: 100%; height: 45px; border-radius: 8px; font-weight: bold; }
    
    .custom-footer { position: fixed; left: 0; bottom: 0; width: 100%; background-color: #0F172A; color: #475569; text-align: center; padding: 10px; font-size: 11px; z-index: 100; }
    </style>
    
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">評量命題與學習目標自動化系統</div>
    </div>
    """, unsafe_allow_html=True)

# 狀態
if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_prompt_content" not in st.session_state: st.session_state.last_prompt_content = ""

# --- Sidebar: 平均分散排版與圖文連結補回 --- [cite: 2026-02-13]
with st.sidebar:
    # 第一區：圖文指南
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown("### 🚀 快速指南")
    st.markdown("""<div class="comfort-box">
        1️⃣ 前往 <a href="https://aistudio.google.com/" target="_blank">Google AI Studio (點我)</a><br>
        2️⃣ 登入<b>個人 Google 帳號</b> (避開教育版)<br>
        3️⃣ 點擊 <b>"Get API key"</b> 並複製<br>
        4️⃣ 貼入下方欄位即可啟用系統
    </div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # 第二區：API 輸入與重置
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown("### 🔑 金鑰設定")
    api_input = st.text_area("在此貼上 API Key", height=80, placeholder="請貼上金鑰以開始...")
    if st.button("🔄 重置系統進度"):
        for k in ["phase", "chat_history", "last_prompt_content"]: st.session_state[k] = (1 if k=="phase" else [] if k=="chat_history" else "")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # 第三區：資源與校方連結
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown("### 📚 資源連結")
    st.markdown("""<div class="comfort-box">
        <b>📖 教材下載：</b><br>
        • <a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒</a> | <a href="https://edisc3.hle.com.tw/" target="_blank">翰林</a> | <a href="https://reader.nani.com.tw/" target="_blank">南一</a><br><br>
        <b>🏛️ 官方連結：</b><br>
        • <a href="https://cirn.moe.edu.tw/Syllabus/index.aspx?sid=1108" target="_blank">108 課綱資源網</a><br>
        • <a href="https://www.nhps.hc.edu.tw/" target="_blank">內湖國小校網首頁</a>
    </div>""", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Phase 1: 參數設定與教材上傳 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與教材上傳")
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("1. 年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        with c2: subject = st.selectbox("2. 科目", ["", "國語", "數學", "自然科學", "社會", "英語"])
        with c3: mode = st.selectbox("3. 命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"])
        
        st.markdown("**4. 勾選欲產出的題型**")
        available_types = SUBJECT_Q_TYPES.get(subject, SUBJECT_Q_TYPES[""])
        cols = st.columns(min(len(available_types), 4))
        selected_types = [t for i, t in enumerate(available_types) if cols[i % len(cols)].checkbox(t, value=True)]
        
        uploaded_files = st.file_uploader("5. 上傳教材檔案 (Word/PDF/Doc)", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            if not api_input or not grade or not subject or not uploaded_files:
                st.warning("⚠️ 提醒：請確認 API Key、年級、科目與教材檔案均已備妥。")
            else:
                with st.spinner("⚡ 正在分析教材並提取學習目標..."):
                    target_key = api_input.strip()
                    model_name, error = find_available_model(target_key, "flash")
                    if error: st.error(f"❌ 連線失敗：{error}")
                    else:
                        content = extract_text_from_files(uploaded_files)
                        try:
                            model = genai.GenerativeModel(model_name, system_instruction="僅產出表格：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |。嚴禁產出試題！")
                            chat = model.start_chat(history=[])
                            prompt = f"年級：{grade}, 科目：{subject}\n題型：{'、'.join(selected_types)}\n教材：{content}"
                            st.session_state.last_prompt_content = prompt
                            res = chat.send_message(prompt)
                            st.session_state.chat_history.append({"role": "model", "content": res.text})
                            st.session_state.phase = 2
                            st.rerun()
                        except Exception as e: st.error(f"分析失敗：{e}")

# --- Phase 2: 確認與出題 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"): st.markdown(current_md)
    
    df = process_table_data(current_md)
    if df is not None:
        c_d1, c_d2 = st.columns(2)
        with c_d1:
            try:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as writer: df.to_excel(writer, index=False)
                st.download_button("📥 下載 Excel 審核表", data=buf.getvalue(), file_name=f"內湖國小_{subject}_審核表.xlsx", use_container_width=True)
            except: st.caption("優先使用 CSV 匯出 (Excel 相容)。")
        with c_d2:
            st.download_button("📥 下載 CSV 審核表 (保險用)", data=df.to_csv(index=False).encode('utf-8-sig'), file_name=f"內湖國小_{subject}_審核表.csv", use_container_width=True)

    st.divider()
    if st.button("✅ 確認無誤，開始出題", type="primary", use_container_width=True):
        with st.spinner("🧠 正在使用深度命題大腦，請稍候..."):
            model_name_pro, _ = find_available_model(api_input.strip(), "pro")
            model_pro = genai.GenerativeModel(model_name_pro)
            res = model_pro.generate_content(f"{st.session_state.last_prompt_content}\n---\n參考審核表：\n{current_md}\n\n請正式產出試題。")
            st.session_state.chat_history.append({"role": "model", "content": res.text})
            st.rerun()
    
    if len(st.session_state.chat_history) > 1:
        for msg in st.session_state.chat_history[1:]:
             with st.chat_message("ai"): st.markdown(msg["content"])

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
