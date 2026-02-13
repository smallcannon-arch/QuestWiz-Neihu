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

# --- 2. 檔案讀取與工具 (快取優化) ---
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

def process_table_data(md_text):
    """強力解析 Markdown 表格並轉為 DataFrame"""
    try:
        cleaned = md_text.replace("｜", "|").replace("**", "").replace("||", "|\n|")
        # 尋找標題錨點
        header_match = re.search(r'\|\s*單元名稱\s*\|\s*學習目標.*\|\s*對應題型\s*\|\s*預計配分\s*\|', cleaned)
        if not header_match: return None
        # 智慧切分
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

def generate_with_retry(model_or_chat, prompt, stream=True):
    """對應 429 錯誤的自動重試機制"""
    max_retries = 3
    for i in range(max_retries):
        try:
            if hasattr(model_or_chat, 'send_message'): return model_or_chat.send_message(prompt, stream=stream)
            else: return model_or_chat.generate_content(prompt, stream=stream)
        except Exception as e:
            if "429" in str(e):
                wait = (i + 1) * 5
                st.toast(f"⏳ 伺服器忙碌，{wait}秒後重試...", icon="⚠️")
                time.sleep(wait)
            else: raise e
    raise Exception("重試次數過多")

# --- 3. 介面設計 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    header[data-testid="stHeader"], footer { display: none !important; }
    .stApp { background-color: #0F172A; }
    .block-container { max-width: 1200px; padding-top: 1.5rem !important; }
    .school-header { background: linear-gradient(90deg, #1E293B 0%, #334155 100%); padding: 25px; border-radius: 15px; text-align: center; margin-bottom: 25px; border: 1px solid #475569; }
    .school-name { font-size: 24px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 14px; color: #94A3B8; }
    .comfort-box { background-color: #1E293B; padding: 12px; border-radius: 10px; margin-bottom: 12px; border-left: 5px solid #3B82F6; font-size: 13px; color: #CBD5E1; line-height: 1.6; }
    .comfort-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    [data-testid="stSidebar"] .stButton > button { width: 100%; height: 40px; }
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

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 快速指南")
    st.markdown("""<div class="comfort-box"><ol style="margin:0; padding-left:1.2rem;">
        <li>前往 <a href="https://aistudio.google.com/" target="_blank">AI Studio (點我)</a></li>
        <li>登入<b>個人 Google 帳號</b></li>
        <li>點擊 <b>Get API key</b> 並複製貼入下方</li></ol></div>""", unsafe_allow_html=True)
    api_input = st.text_area("在此輸入 API Key", height=70)
    if st.button("🔄 重置系統"):
        for k in ["phase", "chat_history", "last_prompt_content"]: st.session_state[k] = (1 if k=="phase" else [] if k=="chat_history" else "")
        st.rerun()
    st.markdown("### 📚 資源連結")
    st.markdown("""<div class="comfort-box"><b>教材：</b><a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒</a> | <a href="https://edisc3.hle.com.tw/" target="_blank">翰林</a> | <a href="https://reader.nani.com.tw/" target="_blank">南一</a><br><b>參考：</b><a href="https://cirn.moe.edu.tw/Syllabus/index.aspx?sid=1108" target="_blank">108課綱</a> | <a href="https://www.nhps.hc.edu.tw/" target="_blank">校網</a></div>""", unsafe_allow_html=True)

# --- Phase 1: 參數設定與教材上傳 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與教材上傳")
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("1. 年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        with c2: subject = st.selectbox("2. 科目", ["", "國語", "數學", "自然科學", "社會", "英語"])
        with c3: mode = st.selectbox("3. 模式", ["🟢 適中", "🔴 困難", "🌟 素養"])
        
        st.markdown("**4. 勾選欲產出的題型**")
        available_types = SUBJECT_Q_TYPES.get(subject, SUBJECT_Q_TYPES[""])
        cols = st.columns(min(len(available_types), 4))
        selected_types = [t for i, t in enumerate(available_types) if cols[i % len(cols)].checkbox(t, value=True)]
        
        uploaded_files = st.file_uploader("5. 上傳教材 (Word/PDF)", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            if not api_input or not grade or not subject or not uploaded_files:
                st.warning("⚠️ 請補齊 API Key、參數或教材。")
            else:
                with st.spinner("⚡ 正在極速掃描教材並原文提取學習目標..."):
                    genai.configure(api_key=api_input.strip())
                    content = extract_text_from_files(uploaded_files)
                    try:
                        model = genai.GenerativeModel("gemini-1.5-flash", system_instruction="你僅產出表格，欄位：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |。絕對禁止出題！")
                        st.session_state.last_prompt_content = f"年級：{grade}, 科目：{subject}\n題型：{'、'.join(selected_types)}\n命題模式：{mode}\n教材：{content}"
                        
                        with st.chat_message("ai"):
                            placeholder = st.empty()
                            full_res = ""
                            res = generate_with_retry(model, st.session_state.last_prompt_content)
                            for chunk in res:
                                full_res += chunk.text
                                placeholder.markdown(full_res + "▌")
                            placeholder.markdown(full_res)
                        
                        st.session_state.chat_history.append({"role": "model", "content": full_res})
                        st.session_state.phase = 2
                        st.rerun()
                    except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2: 確認與出題 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    with st.chat_message("ai"): st.markdown(current_md)
    
    # 下載按鈕區
    df = process_table_data(current_md)
    if df is not None:
        c_d1, c_d2 = st.columns(2)
        with c_d1:
            try:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='openpyxl') as writer: df.to_excel(writer, index=False)
                st.download_button("📥 下載 Excel 審核表", data=buf.getvalue(), file_name="審核表.xlsx", use_container_width=True)
            except: st.caption("環境不支援 Excel，請用 CSV。")
        with c_d2:
            st.download_button("📥 下載 CSV 審核表 (保險用)", data=df.to_csv(index=False).encode('utf-8-sig'), file_name="審核表.csv", use_container_width=True)

    st.divider()
    with st.container(border=True):
        st.markdown("### 📝 第二階段：正式出題")
        st.caption("🧠 系統將換檔至 **Gemini 1.5 Pro** 以確保題目品質")
        
        if st.button("✅ 確認無誤，開始出題", type="primary", use_container_width=True):
            with st.spinner("🧠 深度命題中，請稍候..."):
                genai.configure(api_key=api_input.strip())
                model_pro = genai.GenerativeModel("gemini-1.5-pro", system_instruction="請根據審核表產出正式試卷與參考答案。")
                
                with st.chat_message("ai"):
                    placeholder = st.empty()
                    full_res = ""
                    res = generate_with_retry(model_pro, f"{st.session_state.last_prompt_content}\n---\n參考審核表：\n{current_md}\n\n請正式出題。")
                    for chunk in res:
                        full_res += chunk.text
                        placeholder.markdown(full_res + "▌")
                    placeholder.markdown(full_res)
                st.session_state.chat_history.append({"role": "model", "content": full_res})

        if st.button("⬅️ 返回修改參數", use_container_width=True):
            st.session_state.phase = 1
            st.rerun()
    
    # 顯示出題後的歷史與微調
    if len(st.session_state.chat_history) > 1:
        for msg in st.session_state.chat_history[1:]:
             with st.chat_message("ai"): st.markdown(msg["content"])
        if prompt := st.chat_input("微調題目？"):
            with st.chat_message("user"): st.markdown(prompt)
            with st.spinner("🔧 修改中..."):
                res = generate_with_retry(genai.GenerativeModel("gemini-1.5-pro").start_chat(history=[]), prompt)
                st.session_state.chat_history.append({"role": "model", "content": res.text})
                st.rerun()

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
