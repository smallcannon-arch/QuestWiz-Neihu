import streamlit as st
import google.generativeai as genai
import random
import io
import time
import re
import subprocess
import sys
import pandas as pd
from pypdf import PdfReader
from docx import Document

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

# --- 1. 核心邏輯區 (只修補這裡，不改介面) ---

SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 🔥 自動搜尋可用模型 (解決 404 錯誤的關鍵) ---
def get_available_model_name(api_key, preference="flash"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None
        
        # 優先找偏好的模型 (flash 或 pro)
        for m in models:
            if preference in m.lower(): return m
        
        # 找不到偏好的，就回傳第一個能用的
        return models[0]
    except:
        return "gemini-1.5-flash" # 最後手段

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

def md_to_excel(md_text):
    try:
        # 1. 寬鬆解析
        lines = md_text.replace("||", "|\n|").split('\n')
        data = []
        for line in lines:
            if "|" in line and "---" not in line:
                row = [c.strip() for c in line.strip('|').split('|')]
                if len(row) > 1: data.append(row)
        
        if not data: return None
        
        headers = data[0]
        rows = data[1:]
        max_cols = len(headers)
        cleaned_rows = []
        for r in rows:
            if len(r) == max_cols: cleaned_rows.append(r)
            elif len(r) < max_cols: cleaned_rows.append(r + [''] * (max_cols - len(r)))
            else: cleaned_rows.append(r[:max_cols])

        df = pd.DataFrame(cleaned_rows, columns=headers)
        
        # 2. 強制清洗題型 (只留第一個)
        type_col = next((c for c in df.columns if "題型" in c), None)
        if type_col:
            df[type_col] = df[type_col].apply(lambda x: str(x).split('、')[0].split(',')[0].split('或')[0])

        # 3. 強制清洗配分
        score_col = next((c for c in df.columns if "配分" in c), None)
        if score_col:
            def clean_score(x):
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", str(x))
                return float(nums[0]) if nums else 0.0
            df[score_col] = df[score_col].apply(clean_score)
            
            # 自動校正
            current_total = df[score_col].sum()
            if current_total > 0 and current_total != 100:
                 df[score_col] = (df[score_col] / current_total) * 100
            df[score_col] = df[score_col].round().astype(int)
            
            diff = 100 - df[score_col].sum()
            if diff != 0:
                df.loc[df[score_col].idxmax(), score_col] += diff
        
        # 4. 輸出 Excel
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
    except Exception as e:
        return None

def get_gemini_response(api_key, preference, prompt):
    # 🔥 自動找名字，不再報錯 404
    model_name = get_available_model_name(api_key, preference)
    if not model_name:
        raise Exception("找不到可用的 Gemini 模型，請檢查 API Key")
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text

# --- 2. 介面設計區 (完全保留您熟悉的介面) ---

st.set_page_config(page_title="內湖國小 AI 出題系統", layout="wide")

if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []

st.markdown("""
    <style>
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px; color: white;
    }
    </style>
    <div class="school-header">
        <h2>🏫 新竹市香山區內湖國小</h2>
        <p>AI 輔助評量命題系統 (V2.1 修復版)</p>
    </div>
    """, unsafe_allow_html=True)

with st.sidebar:
    st.info("💡 請輸入您的 Google AI Studio Key")
    api_input = st.text_input("API Key", type="password")
    if st.button("🔄 重置系統"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.rerun()

# --- Phase 1: 上傳與設定 ---
if st.session_state.phase == 1:
    col1, col2 = st.columns(2)
    with col1:
        grade = st.selectbox("年級", ["", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("科目", ["", "國語", "數學", "自然", "社會"])
    with col2:
        mode = st.selectbox("命題模式", ["適中 (基礎檢測)", "困難 (進階思考)", "素養 (情境解題)"])
        question_types = st.multiselect("包含題型", ["單選題", "配合題", "簡答題", "閱讀測驗"], default=["單選題"])

    uploaded_files = st.file_uploader("請上傳教材 (支援 PDF, DOCX)", accept_multiple_files=True)

    if st.button("🚀 產生審核表", type="primary", use_container_width=True):
        if not api_input or not uploaded_files:
            st.warning("⚠️ 請輸入 API Key 並上傳檔案")
        else:
            with st.spinner("AI 正在閱讀教材中... (自動搜尋最佳模型)"):
                try:
                    text = extract_text_from_files(uploaded_files)
                    
                    prompt = f"""
                    你是國小命題專家。請根據教材產出【審核表】。
                    參數：{grade}{subject}, 模式:{mode}, 題型:{','.join(question_types)}
                    規則：
                    1. 總分 100，只能出一種題型 (嚴禁貪心)。
                    2. 配分只能填數字。
                    3. 僅輸出 Markdown 表格。
                    表格欄位：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
                    教材內容：
                    {text}
                    """
                    
                    # 🔥 使用自動搜尋 (preference="flash" 代表優先用便宜快速的)
                    response = get_gemini_response(api_input, "flash", prompt)
                    
                    st.session_state.chat_history.append(response)
                    st.session_state.phase = 2
                    st.rerun()
                except Exception as e:
                    st.error(f"發生錯誤：{e}")

# --- Phase 2: 審核與下載 ---
elif st.session_state.phase == 2:
    st.success("✅ 審核表已生成！請檢查並下載。")
    
    md_content = st.session_state.chat_history[-1]
    st.markdown(md_content)
    
    # 轉 Excel (包含自動配分校正與題型清洗)
    excel_data = md_to_excel(md_content)
    
    c1, c2 = st.columns(2)
    with c1:
        if excel_data:
            st.download_button("📥 下載 Excel 審核表", excel_data, "review.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    with c2:
        if st.button("⬅️ 返回修改", use_container_width=True):
            st.session_state.phase = 1
            st.session_state.chat_history = []
            st.rerun()
            
    st.divider()
    
    if st.button("🎓 確認無誤，開始出題 (Phase 3)", type="primary", use_container_width=True):
        with st.spinner("AI 正在命題中 (自動切換至 Pro 模型深度思考)..."):
            try:
                prompt = f"""
                你是命題 AI。請根據這份審核表出題。
                請直接輸出試卷內容。
                審核表：
                {md_content}
                """
                # 🔥 Phase 3 優先找 "pro" 模型，若找不到會自動降級用 flash，保證不報錯
                exam_response = get_gemini_response(api_input, "pro", prompt)
                
                st.session_state.chat_history.append(exam_response)
                st.session_state.phase = 3
                st.rerun()
            except Exception as e:
                st.error(f"出題失敗：{e}")

# --- Phase 3: 試卷結果 ---
elif st.session_state.phase == 3:
    st.balloons()
    st.title("📝 試卷初稿")
    
    exam_content = st.session_state.chat_history[-1]
    st.text_area("試卷內容", exam_content, height=600)
    
    st.download_button("📥 下載試卷文字檔", exam_content, "exam.txt", use_container_width=True)
    
    if st.button("🔄 重新開始"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.rerun()
