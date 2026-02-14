import subprocess
import sys
import os
import re

# --- 0. 自動安裝依賴套件 ---
def install_package(package):
    try:
        __import__(package)
    except ImportError:
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

# --- 1. 核心設定區 ---

SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- Prompt 指令集 (🔥 強制表格格式) ---
GEM_INSTRUCTIONS_PHASE1 = """
你是「國小專業定期評量命題 AI」。
Phase 1 任務：閱讀教材，整理【學習目標審核表】。

### ⚠️ 絕對輸出規則 (違反將導致系統崩潰)：
1. **Output Format**: 僅輸出 Markdown 表格，**嚴禁** 任何開場白 (如 "好的"、"以下是表格") 或結語。
2. **Table Headers**: 表格標題列 **必須** 完全一致如下：
   | 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
3. **No Mixed Types**: 對應題型欄位只能選「一種」。(❌ 單選題、配合題 | ✅ 單選題)
4. **Numbers Only**: 預計配分欄位只能填阿拉伯數字 (❌ 10分 | ✅ 10)。
5. **Constraint**: 總分必須剛好 100 分。
"""

GEM_INSTRUCTIONS_PHASE3 = """
你是「國小專業定期評量命題 AI」。
Phase 3 任務：依據審核表與命題模式進行正式出題。

### 1. 核心參數
* 🟢 模式 A (適中)：基礎學力。
* 🔴 模式 B (困難)：邏輯細節。
* 🌟 模式 C (素養)：情境解決問題，接軌 PISA/PIRLS。

### 2. 命題鐵律
* 總分：嚴格遵守配分，總分 100。
* 視覺化：若需圖片，請在題幹插入  標籤。
* 選項品質：禁止「以上皆是/非」。

### 3. 輸出格式
請直接輸出試卷內容，包含題號、題目、選項、配分。
"""

# --- 2. 工具函式 ---

@st.cache_data
def extract_text_from_files(files):
    text_content = ""
    for file in files:
        try:
            file_text = ""
            ext = file.name.split('.')[-1].lower()
            if ext == 'pdf':
                try:
                    pdf_reader = PdfReader(file)
                    for i, page in enumerate(pdf_reader.pages):
                        content = page.extract_text() or ""
                        file_text += f"\n--- Page {i+1} ---\n{content}"
                except: file_text = "(PDF 讀取失敗)"
            elif ext == 'docx':
                try:
                    doc = Document(file)
                    file_text = "\n".join([p.text for p in doc.paragraphs])
                except: file_text = "(DOCX 讀取失敗)"
            elif ext == 'doc':
                file_text = "⚠️ 系統提示：本系統不支援舊版 Word (.doc)。請將檔案「另存新檔」為 .docx 或 .pdf 後重新上傳。"
            
            file_text = re.sub(r'\n\s*\n', '\n\n', file_text)
            text_content += f"\n\n=== 檔案: {file.name} ===\n{file_text}"
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name} - {str(e)}]"
    return text_content

def md_to_excel(df):
    """將 DataFrame 轉為 Excel bytes"""
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='審核表')
            workbook = writer.book
            worksheet = writer.sheets['審核表']
            wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter'})
            header_format = workbook.add_format({'bold': True, 'fg_color': '#D7E4BC', 'border': 1})
            
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            
            worksheet.set_column(0, 0, 15, wrap_format)
            worksheet.set_column(1, 1, 55, wrap_format)
            
        return output.getvalue()
    except: return None

def parse_md_to_df(md_text):
    """解析 Markdown 並清洗"""
    try:
        # 1. 預處理：確保表格換行正確
        cleaned_text = md_text.replace("||", "|\n|")
        lines = cleaned_text.split('\n')
        
        # 2. 抓取表格行
        data = []
        for line in lines:
            if "|" in line and "---" not in line:
                # 去除頭尾空白與 |
                row = [c.strip() for c in line.strip('|').split('|')]
                if len(row) > 1: data.append(row)
        
        if not data: return None
        
        # 3. 建立 DataFrame
        headers = data[0]
        rows = data[1:]
        
        # 防呆：確保欄位數量一致
        max_cols = len(headers)
        cleaned_rows = []
        for r in rows:
            if len(r) == max_cols: cleaned_rows.append(r)
            elif len(r) < max_cols: cleaned_rows.append(r + [''] * (max_cols - len(r)))
            else: cleaned_rows.append(r[:max_cols])

        df = pd.DataFrame(cleaned_rows, columns=headers)
        
        # 4. 強制清洗：題型 (只留第一個)
        type_col = next((c for c in df.columns if "題型" in c), None)
        if type_col:
            df[type_col] = df[type_col].apply(lambda x: str(x).replace(" ", "").split('、')[0].split(',')[0].split('或')[0])

        # 5. 強制清洗：配分 (轉數字)
        score_col = next((c for c in df.columns if "配分" in c), None)
        if score_col:
            def clean_score(x):
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(x))
                return float(nums[0]) if nums else 0.0
            df[score_col] = df[score_col].apply(clean_score)
            
            # 自動配分校正
            current_total = df[score_col].sum()
            if current_total > 0 and current_total != 100:
                df[score_col] = (df[score_col] / current_total) * 100
            df[score_col] = df[score_col].round().astype(int)
            
            # 餘數分配給最高分那題
            diff = 100 - df[score_col].sum()
            if diff != 0:
                df.loc[df[score_col].idxmax(), score_col] += diff
        
        return df
    except Exception as e:
        print(f"Parsing error: {e}")
        return None

def df_to_string(df):
    if df is None: return ""
    return df.to_markdown(index=False)

# --- 5. 智能模型設定 (自動搜尋 + 重試機制) ---
def get_best_model(api_key, mode="fast"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None, "找不到可用模型 (請檢查 API Key)"
        
        target_model = None
        if mode == "fast":
            for m in models:
                if 'flash' in m.lower(): target_model = m; break
            if not target_model: target_model = models[0]
        elif mode == "smart":
            for m in models:
                if 'pro' in m.lower() and '1.5' in m.lower(): target_model = m; break
            if not target_model:
                for m in models:
                    if 'pro' in m.lower(): target_model = m; break
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
            time.sleep((i + 1) * 2)
            if i == max_retries - 1: raise e
    raise Exception("連線逾時")

# --- 6. 介面設計區 ---

st.set_page_config(page_title="內湖國小 AI 出題系統", layout="wide")

if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "df_preview" not in st.session_state: st.session_state.df_preview = None

st.markdown("""
    <style>
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px; color: white;
    }
    </style>
    <div class="school-header">
        <h2>🏫 新竹市香山區內湖國小</h2>
        <p>AI 輔助評量命題系統 (V3.1 終極容錯版)</p>
    </div>
    """, unsafe_allow_html=True)

with st.sidebar:
    st.info("💡 請輸入 Google AI Studio Key")
    api_input = st.text_input("API Key", type="password")
    if st.button("🔄 重置系統"):
        st.session_state.clear()
        st.rerun()

# --- Phase 1: 上傳與設定 ---
if st.session_state.phase == 1:
    col1, col2 = st.columns(2)
    with col1:
        grade = st.selectbox("年級", ["三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("科目", ["國語", "數學", "自然", "社會", "英語"])
    with col2:
        mode = st.selectbox("命題模式", ["適中 (基礎檢測)", "困難 (進階思考)", "素養 (情境解題)"])
        question_types = st.multiselect("包含題型", ["單選題", "配合題", "簡答題", "閱讀測驗"], default=["單選題"])

    uploaded_files = st.file_uploader("請上傳教材 (支援 PDF, DOCX)", accept_multiple_files=True)

    if st.button("🚀 產生審核表", type="primary", use_container_width=True):
        if not api_input or not uploaded_files:
            st.warning("⚠️ 請輸入 API Key 並上傳檔案")
        else:
            with st.spinner("AI 正在分析教材... (這可能需要 10-20 秒)"):
                try:
                    text = extract_text_from_files(uploaded_files)
                    
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="fast")
                    
                    if error_msg: 
                        st.error(f"❌ {error_msg}")
                    else:
                        t_str = "、".join(question_types)
                        prompt = f"""
                        任務：分析以下教材並產出審核表。
                        【參數】年級:{grade}, 科目:{subject}, 模式:{mode}, 題型:{t_str}
                        【教材】{text[:30000]} 
                        (若教材過長已自動截斷以符合 AI 限制)
                        """
                        # 使用 Flash 模型
                        response = get_gemini_response(api_input, model_name, GEM_INSTRUCTIONS_PHASE1, prompt)
                        
                        # 🔥 寬鬆檢查：只要有 | 就嘗試解析，不再檢查「單元」關鍵字
                        if "|" in response:
                            df = parse_md_to_df(response)
                            if df is not None:
                                st.session_state.df_preview = df
                                st.session_state.grade = grade
                                st.session_state.subject = subject
                                st.session_state.mode = mode
                                st.session_state.phase = 2
                                st.rerun()
                            else:
                                st.error("❌ 表格解析失敗。請看下方 AI 原始回覆，可能是格式跑掉了：")
                                st.code(response) # 顯示原始回覆方便除錯
                        else:
                            st.error("❌ 格式異常 (AI 沒產生表格)。以下是 AI 的原始回覆：")
                            st.text(response) # 顯示原始回覆
                            
                except Exception as e:
                    st.error(f"發生系統錯誤：{e}")

# --- Phase 2: 審核與下載 ---
elif st.session_state.phase == 2:
    st.markdown("### 📝 審核與編輯")
    st.info("請在下方表格直接修改，確認無誤後可下載 Excel 或開始出題。")
    
    current_subject = st.session_state.get("subject", "")
    valid_types = SUBJECT_Q_TYPES.get(current_subject, SUBJECT_Q_TYPES[""])

    if st.session_state.df_preview is not None:
        edited_df = st.data_editor(
            st.session_state.df_preview,
            column_config={
                "對應題型": st.column_config.SelectboxColumn("對應題型", options=valid_types, required=True),
                "預計配分": st.column_config.NumberColumn("預計配分", min_value=0, max_value=100, format="%d 分")
            },
            use_container_width=True,
            num_rows="dynamic"
        )
        st.session_state.df_preview = edited_df
        
        total = edited_df["預計配分"].sum()
        if total == 100: st.success(f"✅ 總分：{total} 分")
        else: st.warning(f"⚠️ 總分：{total} 分 (建議調整為 100)")

        excel_data = md_to_excel(edited_df)
        col1, col2 = st.columns(2)
        with col1:
            if excel_data:
                st.download_button("📥 下載 Excel 審核表", excel_data, "review.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        with col2:
            if st.button("⬅️ 返回修改", use_container_width=True):
                st.session_state.phase = 1
                st.rerun()
        
        st.divider()
        if st.button("🎓 確認無誤，開始出題 (Phase 3)", type="primary", use_container_width=True):
            st.session_state.phase = 3
            st.rerun()

# --- Phase 3: 試卷結果 ---
elif st.session_state.phase == 3:
    st.markdown("### 🎓 試卷初稿")
    
    if "exam_content" not in st.session_state:
        with st.spinner("AI 正在命題中 (使用 Pro 模型深度思考)..."):
            try:
                keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                target_key = random.choice(keys)
                model_name, error_msg = get_best_model(target_key, mode="smart")
                
                if error_msg: st.error(error_msg)
                else:
                    df_str = st.session_state.df_preview.to_markdown(index=False)
                    prompt = f"""
                    請根據這份審核表出題。
                    參數：{st.session_state.grade}{st.session_state.subject}, 模式:{st.session_state.mode}
                    審核表：{df_str}
                    """
                    exam_content = get_gemini_response(api_input, model_name, GEM_INSTRUCTIONS_PHASE3, prompt)
                    st.session_state.exam_content = exam_content
                    st.rerun()
            except Exception as e:
                st.error(f"出題失敗：{e}")
                if st.button("重試"): st.rerun()

    if "exam_content" in st.session_state:
        st.text_area("試卷內容", st.session_state.exam_content, height=600)
        st.download_button("📥 下載試卷文字檔", st.session_state.exam_content, "exam.txt", use_container_width=True)
        
        if st.button("🔄 重新開始"):
            st.session_state.clear()
            st.rerun()
