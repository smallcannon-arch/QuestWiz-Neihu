import subprocess, sys, os, re, streamlit as st, google.generativeai as genai, random, io, time, pandas as pd
from pypdf import PdfReader
from docx import Document

# --- 0. 自動安裝依賴套件 (新增 tabulate) ---
def install_package(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for pkg in ["xlsxwriter", "pypdf", "docx", "pandas", "google-generativeai", "streamlit", "tabulate"]:
    install_package(pkg)

# --- 1. 核心邏輯設定 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# 修正：要求 AI 必須窮盡所有單元，解決「抓太少」問題
GEM_INSTRUCTIONS_PHASE1 = """你是「國小命題專家」。任務：閱讀教材並產出【學習目標審核表】。
絕對規則：
1. 完整性：必須「窮盡」所有單元目標，涵蓋整份教材，嚴禁遺漏或只抓部分。
2. 配分：總分剛好 100。
3. 單一題型：一格目標只能填一種題型。
4. 格式：僅輸出 Markdown 表格。
"""

GEM_INSTRUCTIONS_PHASE3 = "請根據審核表正式命題。總分100，包含題目、選項與答案。"

# --- 2. 工具函式 ---
@st.cache_data
def extract_text(files):
    text = ""
    for f in files:
        ext = f.name.split('.')[-1].lower()
        if ext == 'pdf':
            reader = PdfReader(f)
            for page in reader.pages: text += page.extract_text() or ""
        elif ext == 'docx':
            doc = Document(f)
            text += "\n".join([p.text for p in doc.paragraphs])
    return re.sub(r'\n\s*\n', '\n\n', text)

def parse_md_to_df(md_text):
    try:
        lines = [l for l in md_text.replace("||", "|\n|").split('\n') if "|" in l and "---" not in l]
        data = [[c.strip() for c in l.strip('|').split('|')] for l in lines]
        df = pd.DataFrame(data[1:], columns=data[0])
        # 強制清洗題型與配分
        type_col = next((c for c in df.columns if "題型" in c), None)
        if type_col: df[type_col] = df[type_col].apply(lambda x: str(x).split('、')[0])
        score_col = next((c for c in df.columns if "配分" in c), None)
        if score_col: df[score_col] = pd.to_numeric(df[score_col].str.extract('(\d+)')[0], errors='coerce').fillna(0).astype(int)
        return df
    except: return None

# --- 3. 介面與模型調度 (解決 429 限制) ---
st.set_page_config(page_title="內湖國小 AI 出題", layout="wide")
st.markdown('### 🏫 內湖國小 AI 輔助出題系統 (V3.2)')

if "phase" not in st.session_state: st.session_state.phase = 1

with st.sidebar:
    api_input = st.text_area("API Key (多組請用逗號隔開)")
    if st.button("🔄 重置系統"): st.session_state.clear(); st.rerun()

if st.session_state.phase == 1:
    c1, c2 = st.columns(2); grade = c1.selectbox("年級", ["三年級","四年級","五年級","六年級"])
    subject = c1.selectbox("科目", ["國語","數學","自然科學","社會","英語"])
    mode = c2.selectbox("模式", ["🟢 適中","🔴 困難","🌟 素養"]); files = st.file_uploader("上傳教材", accept_multiple_files=True)
    
    if st.button("🚀 產出審核表", use_container_width=True, type="primary"):
        # 分流邏輯：隨機選 Key，且 Phase 1 強制用 Flash 避免 429
        keys = [k.strip() for k in re.split(r'[,\s\n]+', api_input) if k.strip()]
        if not keys: st.error("請輸入 API Key")
        else:
            with st.spinner("正在掃描教材知識點..."):
                genai.configure(api_key=random.choice(keys))
                model = genai.GenerativeModel("gemini-1.5-flash") # Flash 配額較多
                res = model.generate_content(f"{GEM_INSTRUCTIONS_PHASE1}\n教材：{extract_text(files)[:30000]}")
                st.session_state.df_preview = parse_md_to_df(res.text)
                st.session_state.phase = 2; st.rerun()

elif st.session_state.phase == 2:
    edited_df = st.data_editor(st.session_state.df_preview, use_container_width=True)
    if st.button("🔥 正式命題 (Phase 3)", type="primary", use_container_width=True):
        st.session_state.df_preview = edited_df; st.session_state.phase = 3; st.rerun()

elif st.session_state.phase == 3:
    with st.spinner("正在使用 Pro 模型深度出題..."):
        keys = [k.strip() for k in re.split(r'[,\s\n]+', api_input) if k.strip()]
        genai.configure(api_key=random.choice(keys))
        model = genai.GenerativeModel("gemini-1.5-pro") # 出題才動用 Pro
        res = model.generate_content(f"根據此審核表出題：\n{st.session_state.df_preview.to_markdown()}")
        st.text_area("試卷初稿", res.text, height=500)
        st.download_button("📥 下載試卷", res.text, "exam.txt")
