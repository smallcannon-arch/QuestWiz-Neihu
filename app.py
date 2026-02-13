import subprocess
import sys
import os
import re

# --- 0. 自動安裝依賴套件 ---
def install_package(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 正在自動安裝 {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_package("xlsxwriter")
install_package("pypdf")
install_package("docx")
install_package("pandas")
install_package("google.generativeai")
install_package("streamlit")

# -------------------------------------------

import streamlit as st
import google.generativeai as genai
import random
import io
import time
from pypdf import PdfReader
from docx import Document
import pandas as pd

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
@st.cache_data
def extract_text_from_files(files):
    text_content = ""
    for file in files:
        try:
            file_text = ""
            ext = file.name.split('.')[-1].lower()
            if ext == 'pdf':
                pdf_reader = PdfReader(file)
                for i, page in enumerate(pdf_reader.pages):
                    content = page.extract_text() or ""
                    file_text += f"\n--- Page {i+1} ---\n{content}"
            elif ext == 'docx':
                doc = Document(file)
                file_text = "\n".join([p.text for p in doc.paragraphs])
            elif ext == 'doc':
                try:
                    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
                    result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
                    if result.returncode == 0: file_text = result.stdout
                    if os.path.exists("temp.doc"): os.remove("temp.doc")
                except: file_text = "[舊版 .doc 讀取失敗，請轉存為 .docx]"
            
            file_text = re.sub(r'\n\s*\n', '\n\n', file_text)
            text_content += f"\n\n=== 檔案: {file.name} ===\n{file_text}"
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name} - {str(e)}]"
    return text_content

# --- 3. 資料處理工具 (拆分為：解析 Markdown -> DF -> Excel) ---

def parse_md_to_df(md_text):
    """將 Markdown 表格解析為 Pandas DataFrame，並進行清洗與配分校正"""
    try:
        # 1. 基礎清洗
        cleaned_text = md_text.replace("||", "|\n|")
        lines = cleaned_text.strip().split('\n')
        table_lines = []
        is_table_started = False
        
        for line in lines:
            if ("單元" in line or "目標" in line or "配分" in line) and "|" in line:
                is_table_started = True
                table_lines.append(line)
                continue
            if is_table_started:
                if "---" in line: continue
                if "|" in line: table_lines.append(line)
        
        if not table_lines: return None

        # 2. 轉為 List
        data = []
        for line in table_lines:
            row = [cell.strip() for cell in line.strip('|').split('|')]
            data.append(row)

        if len(data) < 2: return None

        headers = data[0]
        rows = data[1:]
        
        # 3. 補齊欄位
        max_cols = len(headers)
        cleaned_rows = []
        for r in rows:
            if len(r) == max_cols: cleaned_rows.append(r)
            elif len(r) < max_cols: cleaned_rows.append(r + [''] * (max_cols - len(r)))
            else: cleaned_rows.append(r[:max_cols])

        df = pd.DataFrame(cleaned_rows, columns=headers)
        
        # --- 🔥 清洗題型 (只留第一個) ---
        type_col = next((col for col in df.columns if "題型" in col), None)
        if type_col:
            def clean_type(x):
                txt = str(x).replace(" ", "")
                if "、" in txt: return txt.split("、")[0]
                if "," in txt: return txt.split(",")[0]
                return txt
            df[type_col] = df[type_col].apply(clean_type)

        # --- 🔥 配分自動校正 ---
        score_col = next((col for col in df.columns if "配分" in col), None)
        if score_col:
            try:
                def clean_number(x):
                    nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(x))
                    return float(nums[0]) if nums else 0.0

                df[score_col] = df[score_col].apply(clean_number)
                current_total = df[score_col].sum()
                
                if current_total > 0 and current_total != 100:
                    df[score_col] = (df[score_col] / current_total) * 100
                
                df[score_col] = df[score_col].round().astype(int)
                
                # 餘數分配
                diff = 100 - df[score_col].sum()
                if diff != 0:
                    max_idx = df[score_col].idxmax()
                    df.loc[max_idx, score_col] += diff
            except: pass
            
        return df
    except Exception as e:
        print(f"解析失敗: {e}")
        return None

def df_to_excel(df):
    """將 DataFrame 轉為美化的 Excel bytes"""
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='學習目標審核表')
            workbook = writer.book
            worksheet = writer.sheets['學習目標審核表']
            
            wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter'})
            header_format = workbook.add_format({
                'bold': True, 'text_wrap': True, 'valign': 'vcenter', 
                'fg_color': '#D7E4BC', 'border': 1
            })
            num_format = workbook.add_format({'valign': 'vcenter', 'align': 'center'})

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            worksheet.set_column(0, 0, 15, wrap_format)
            worksheet.set_column(1, 1, 55, wrap_format) 
            worksheet.set_column(2, 2, 20, wrap_format)
            worksheet.set_column(3, 3, 10, num_format)
                
        return output.getvalue()
    except Exception as e:
        return None

# --- 4. 核心 Gem 命題鐵律 ---
GEM_INSTRUCTIONS_PHASE1 = """
你是「國小專業定期評量命題 AI」。

### ⚠️ Phase 1 任務目標：
請閱讀使用者提供的教材內容，整理出一份【學習目標審核表】。

### 絕對規則：
1. **配分邏輯**：請根據各單元內容的「篇幅長度」與「重要性」，將總分分配為 **剛好 100 分**。
2. **單一題型**：「對應題型」欄位 **只能選擇「一種」最適合的題型** (例如：單選題)。
3. **數字格式**：「預計配分」欄位 **只能填寫阿拉伯數字** (例如：10)。
4. **格式要求**：
   - 僅輸出標準 Markdown 表格。
   - 欄位：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
   - **每一列資料必須強制換行**。
"""

# --- 5. 智能模型設定 ---
def get_best_model(api_key, mode="fast"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None, "找不到可用模型"
        target_model = None
        if mode == "fast":
            for m in models:
                if 'flash' in m.lower(): target_model = m; break
            if not target_model: target_model = models[0]
        elif mode == "smart":
            for m in models:
                if 'pro' in m.lower() and '1.5' in m.lower(): target_model = m; break
            if not target_model: target_model = models[0]
        return target_model, None
    except Exception as e: return None, str(e)

def generate_with_retry(model_or_chat, prompt, stream=True):
    max_retries = 3
    for i in range(max_retries):
        try:
            if hasattr(model_or_chat, 'send_message'):
                return model_or_chat.send_message(prompt, stream=stream)
            else:
                return model_or_chat.generate_content(prompt, stream=stream)
        except Exception as e:
            if "429" in str(e): time.sleep((i + 1) * 3)
            else: raise e
    raise Exception("連線逾時")

# --- 6. 介面設定 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
    footer { display: none !important; visibility: hidden !important; }
    .stApp { background-color: #0F172A; }
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 25px; border-radius: 18px; text-align: center; margin-bottom: 25px; 
        border: 1px solid #475569;
    }
    .school-name { font-size: 26px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 15px; color: #94A3B8; margin-top: 6px; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #E2E8F0 !important; }
    .comfort-box {
        background-color: #1E293B; padding: 15px; border-radius: 10px; 
        margin-bottom: 15px; border-left: 5px solid #3B82F6; 
        font-size: 14px; color: #CBD5E1; line-height: 1.8;
    }
    .comfort-box b { color: #fff; }
    .comfort-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    [data-testid="stSidebar"] .stMarkdown { margin-bottom: 10px; } 
    .stTextArea textarea { min-height: 80px; }
    .stTextArea { margin-bottom: 15px !important; }
    [data-testid="stSidebar"] .stButton > button { 
        display: block; margin: 15px auto !important; 
        width: 100%; border-radius: 8px; height: 42px;
        background-color: #334155; border: 1px solid #475569; font-size: 15px;
    }
    .custom-footer { 
        position: fixed; left: 0; bottom: 0; width: 100%; 
        background-color: #0F172A; color: #475569; 
        text-align: center; padding: 12px; font-size: 11px; 
        border-top: 1px solid #1E293B; z-index: 100; 
    }
    </style>
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">評量命題與學習目標自動化系統</div>
    </div>
    """, unsafe_allow_html=True)

if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_prompt_content" not in st.session_state: st.session_state.last_prompt_content = ""
if "df_preview" not in st.session_state: st.session_state.df_preview = None

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 系統設定")
    api_input = st.text_area("在此輸入 API Key", height=80, placeholder="請貼上 Google AI Studio 金鑰...")
    if st.button("🔄 重置系統"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.session_state.last_prompt_content = ""
        st.session_state.df_preview = None
        st.rerun()

    st.markdown("### 📚 資源連結")
    st.markdown("""
    <div class="comfort-box">
        <b>教材下載：</b><br>
        • <a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒電子書</a><br>
        • <a href="https://edisc3.hle.com.tw/" target="_blank">翰林行動大師</a><br>
        • <a href="https://reader.nani.com.tw/" target="_blank">南一 OneBox</a>
    </div>
    """, unsafe_allow_html=True)

# --- Phase 1: 參數設定與教材上傳 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與教材上傳")
        
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
            if cols[i % len(cols)].checkbox(t, value=True): selected_types.append(t)
        
        st.divider()
        uploaded_files = st.file_uploader("5. 上傳教材檔案 (Word/PDF)", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            if not api_input: st.error("❌ 請輸入 API Key")
            elif not grade or not subject or not uploaded_files or not selected_types:
                st.warning("⚠️ 請確認所有欄位已填寫")
            else:
                with st.spinner("⚡ AI 正在分析教材..."):
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="fast")
                    
                    if error_msg: st.error(f"❌ API 錯誤：{error_msg}")
                    else:
                        content = extract_text_from_files(uploaded_files)
                        try:
                            st.toast(f"⚡ 啟動 AI 引擎 ({model_name})...", icon="🤖")
                            model_fast = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=GEM_INSTRUCTIONS_PHASE1, 
                                generation_config={"temperature": 0.0}
                            )
                            chat = model_fast.start_chat(history=[])
                            t_str = "、".join(selected_types)
                            prompt_content = f"""
                            任務：分析以下教材並產出審核表。
                            【參數】年級：{grade}, 科目：{subject}, 可用題型：{t_str}
                            【教材】{content}
                            【步驟】
                            1. 識別單元結構與學習目標。
                            2. 依重要性與篇幅分配 100 分。
                            3. 輸出 Markdown 表格。
                            """
                            st.session_state.last_prompt_content = prompt_content
                            response = generate_with_retry(chat, prompt_content, stream=False)
                            
                            if "|" in response.text and "單元" in response.text:
                                st.session_state.chat_history.append({"role": "model", "content": response.text})
                                # 預先解析成 DataFrame 並存入 Session
                                st.session_state.df_preview = parse_md_to_df(response.text)
                                st.session_state.phase = 2
                                st.session_state.subject = subject # 記住科目以便 Phase 2 使用
                                st.rerun()
                            else: st.error("❌ 格式異常，請重試")
                        except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2: 線上編輯與下載 ---
elif st.session_state.phase == 2:
    with st.container(border=True):
        st.markdown("### 📝 第二階段：審核與編輯")
        st.info("請在下方表格直接修改「對應題型」或「學習目標」。確認無誤後再下載 Excel。")
        
        # 取得當前科目的可用題型
        current_subject = st.session_state.get("subject", "")
        valid_types = SUBJECT_Q_TYPES.get(current_subject, SUBJECT_Q_TYPES[""])

        # 使用 Data Editor 讓使用者編輯
        # 注意：我們把 "對應題型" 設為 Selectbox (下拉選單)
        if st.session_state.df_preview is not None:
            edited_df = st.data_editor(
                st.session_state.df_preview,
                column_config={
                    "對應題型": st.column_config.SelectboxColumn(
                        "對應題型",
                        help="點擊選擇此題目的考試題型",
                        width="medium",
                        options=valid_types,  # 這裡就是下拉選單的選項
                        required=True,
                    ),
                    "預計配分": st.column_config.NumberColumn(
                        "預計配分",
                        min_value=0,
                        max_value=100,
                        format="%d 分"
                    )
                },
                use_container_width=True,
                num_rows="dynamic", # 允許新增刪除列
                hide_index=True
            )
            
            # 即時計算總分給使用者看
            total_score = edited_df["預計配分"].sum()
            if total_score != 100:
                st.warning(f"⚠️ 目前總分：{total_score} 分 (建議調整為 100 分)")
            else:
                st.success(f"✅ 目前總分：{total_score} 分")

            # Excel 轉換 (使用編輯後的 DataFrame)
            excel_data = df_to_excel(edited_df)
            
            col1, col2 = st.columns([1, 1])
            with col1:
                if excel_data:
                    st.download_button(
                        label="📥 下載 Excel 審核表",
                        data=excel_data,
                        file_name=f"內湖國小_{current_subject}_審核表.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            with col2:
                if st.button("⬅️ 返回重來", use_container_width=True):
                    st.session_state.phase = 1
                    st.session_state.chat_history = []
                    st.session_state.df_preview = None
                    st.rerun()
        else:
            st.error("⚠️ 資料遺失，請重新生成。")
            if st.button("返回"):
                st.session_state.phase = 1
                st.rerun()

    st.divider()
    if st.button("✅ 審核無誤，開始正式命題 (Phase 3)", type="primary", use_container_width=True):
        st.toast("🚀 進入 Phase 3...", icon="🚧")

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
