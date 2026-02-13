import streamlit as st
import google.generativeai as genai
import random
import io
import time
from pypdf import PdfReader
from docx import Document
import pandas as pd
import subprocess
import os
import math

# --- 1. 核心設定與工具 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "改錯字", "字詞義測驗", "課文理解", "閱讀測驗", "成語運用"],
    "數學": ["選擇題", "填充題", "計算題", "應用題", "畫圖題"],
    "自然科學": ["是非題", "選擇題", "做做看", "科學閱讀", "實驗題"],
    "社會": ["是非題", "選擇題", "勾選題", "連連看", "簡答題", "圖表題"],
    "英語": ["Listen & Check", "Listen & Choose", "Read & Choose", "Look & Write", "Reading Comprehension"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 2. 檔案讀取工具 ---
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
                pass 
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name}]"
    return text_content

# --- 3. 關鍵優化：數學配分邏輯 ---
def calculate_scores(df):
    try:
        df['授課節數'] = pd.to_numeric(df['授課節數'], errors='coerce').fillna(1)
        total_hours = df['授課節數'].sum()
        if total_hours == 0: total_hours = 1
        
        df['原始配分'] = (df['授課節數'] / total_hours) * 100
        df['預計配分'] = df['原始配分'].apply(math.floor)
        
        current_total = df['預計配分'].sum()
        remainder = 100 - current_total
        
        df['餘數權重'] = df['原始配分'] - df['預計配分']
        indices_to_add = df.nlargest(int(remainder), '餘數權重').index
        df.loc[indices_to_add, '預計配分'] += 1
        
        return df.drop(columns=['原始配分', '餘數權重'])
    except Exception as e:
        st.error(f"配分計算錯誤: {e}")
        return df

# --- 4. Excel 下載工具 ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='審核表')
        workbook = writer.book
        worksheet = writer.sheets['審核表']
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        worksheet.set_column('A:A', 15) 
        worksheet.set_column('B:B', 40) 
        worksheet.set_column('C:C', 10) 
        worksheet.set_column('D:D', 10) 
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
    return output.getvalue()

# --- 5. 自動搜尋可用模型 (修復 404 錯誤的關鍵) ---
def get_available_flash_model():
    """自動尋找帳號可用的 Flash 模型，如果沒有則回傳 Pro"""
    try:
        valid_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                valid_models.append(m.name)
        
        # 優先順序：最新的 Flash -> 任何 Flash -> Pro
        for m in valid_models:
            if 'flash' in m.lower() and '1.5' in m.lower(): return m
        for m in valid_models:
            if 'flash' in m.lower(): return m
        for m in valid_models:
            if 'pro' in m.lower(): return m
            
        return "models/gemini-1.5-flash" # 最後的嘗試
    except Exception:
        return "models/gemini-1.5-flash"

# --- 6. AI 提示詞 ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請分析以下教材內容，並提取「單元名稱」、「學習目標」與「授課節數」。

**輸出規則 (嚴格遵守)：**
1. 僅輸出一個 Markdown 表格。
2. 欄位必須包含：| 單元名稱 | 學習目標 | 授課節數 |
3. 「授課節數」欄位**只能填入數字** (例如: 4, 3, 5)。若教材未提及，請根據內容長度推估一個整數 (1~5)。
4. 學習目標請精簡摘錄重點。
5. **不要**計算分數，**不要**輸出其他廢話。

教材內容：
{content}
"""

# --- 7. 主程式介面 ---
st.set_page_config(page_title="內湖國小出題系統 (Auto-Fix)", layout="wide")

st.markdown("""
    <div style="background-color:#1E293B;padding:20px;border-radius:10px;text-align:center;margin-bottom:20px;">
        <h2 style="color:white;margin:0;">內湖國小 AI 命題與審核系統</h2>
        <p style="color:#94A3B8;margin:5px;">學習目標自動摘取 • 智慧配分 • 雙向細目表生成</p>
    </div>
""", unsafe_allow_html=True)

if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

with st.sidebar:
    st.header("⚙️ 設定與金鑰")
    api_key = st.text_input("Google API Key", type="password")
    
    # 除錯工具：顯示目前可用模型
    if api_key and st.button("🔍 測試 API 連線與模型"):
        try:
            genai.configure(api_key=api_key)
            models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            st.success(f"連線成功！您的可用模型：\n" + "\n".join(models))
        except Exception as e:
            st.error(f"連線失敗：{e}")

    if st.button("🔄 重置系統"):
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()

# --- Step 1: 上傳與參數 ---
if st.session_state.step == 1:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("1. 參數設定")
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("科目", list(SUBJECT_Q_TYPES.keys()))
    with col2:
        st.subheader("2. 上傳教材")
        uploaded_files = st.file_uploader("支援 PDF / Word", accept_multiple_files=True)

    if st.button("🚀 開始分析教材 (生成審核表)", type="primary", use_container_width=True):
        if not api_key or not uploaded_files:
            st.warning("請輸入 API Key 並上傳檔案")
        else:
            with st.spinner("🤖 AI 正在選取最佳模型並閱讀教材..."):
                try:
                    text_content = extract_text_from_files(uploaded_files)
                    
                    # --- 自動修復 404 的關鍵步驟 ---
                    genai.configure(api_key=api_key)
                    best_model_name = get_available_flash_model()
                    st.toast(f"已自動選用模型：{best_model_name}", icon="✅")
                    
                    model = genai.GenerativeModel(best_model_name)
                    # ---------------------------
                    
                    response = model.generate_content(GEM_EXTRACT_PROMPT.format(content=text_content[:30000]))
                    raw_text = response.text
                    
                    lines = [line.strip() for line in raw_text.split('\n') if "|" in line and "---" not in line]
                    data = []
                    for line in lines:
                        row = [cell.strip() for cell in line.split('|') if cell.strip()]
                        if len(row) >= 3:
                            data.append(row[:3])
                    
                    if len(data) > 1:
                        headers = ["單元名稱", "學習目標", "授課節數"]
                        start_idx = 1 if "單元" in data[0][0] else 0
                        df = pd.DataFrame(data[start_idx:], columns=headers)
                        df_calculated = calculate_scores(df)
                        
                        st.session_state.extracted_data = df_calculated
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("AI 無法識別教材結構，請確認檔案內容是否清晰。")
                except Exception as e:
                    st.error(f"發生錯誤: {e}")

# --- Step 2: 確認與下載 ---
elif st.session_state.step == 2:
    st.subheader("✅ 學習目標審核表 (自動配分完畢)")
    df = st.session_state.extracted_data
    
    edited_df = st.data_editor(
        df,
        column_config={
            "預計配分": st.column_config.NumberColumn("預計配分 (%)", help="由系統依節數比例自動計算"),
            "授課節數": st.column_config.NumberColumn("授課節數", help="AI 推估，可修改")
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    current_total = edited_df['預計配分'].sum()
    if current_total != 100:
        st.warning(f"⚠️ 注意：目前總分為 {current_total} 分 (目標 100 分)，請手動調整。")
    else:
        st.success("🎯 總分完美：100 分")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        excel_data = df_to_excel(edited_df)
        st.download_button(
            label="📥 下載審核表 (Excel)",
            data=excel_data,
            file_name="學習目標審核表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with col_d2:
        if st.button("⬅️ 重新上傳教材"):
            st.session_state.step = 1
            st.rerun()
