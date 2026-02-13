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

# --- 2. 檔案讀取工具 (不變) ---
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
                # 需安裝 antiword, 若無環境可略過或提示
                pass 
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name}]"
    return text_content

# --- 3. 關鍵優化：數學配分邏輯 (Python 接手計算) ---
def calculate_scores(df):
    """
    輸入包含 '授課節數' 的 DataFrame，輸出包含 '預計配分' 的 DataFrame。
    確保總分剛好 100 分。
    """
    try:
        # 1. 清理數據：轉為數字，無效值設為 1 節
        df['授課節數'] = pd.to_numeric(df['授課節數'], errors='coerce').fillna(1)
        
        # 2. 計算總節數
        total_hours = df['授課節數'].sum()
        if total_hours == 0: total_hours = 1
        
        # 3. 初步分配 (無條件捨去)
        df['原始配分'] = (df['授課節數'] / total_hours) * 100
        df['預計配分'] = df['原始配分'].apply(math.floor)
        
        # 4. 餘數處理 (補足到 100 分)
        current_total = df['預計配分'].sum()
        remainder = 100 - current_total
        
        # 找出小數點被捨去最多的單元，依序補分
        df['餘數權重'] = df['原始配分'] - df['預計配分']
        # 根據餘數大小排序，取前 N 個 (N = remainder) 加 1 分
        indices_to_add = df.nlargest(int(remainder), '餘數權重').index
        df.loc[indices_to_add, '預計配分'] += 1
        
        # 移除暫存欄位
        return df.drop(columns=['原始配分', '餘數權重'])
    except Exception as e:
        st.error(f"配分計算錯誤: {e}")
        return df

# --- 4. Excel 下載工具 (符合審核表格式) ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='審核表')
        workbook = writer.book
        worksheet = writer.sheets['審核表']
        
        # 格式設定
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        
        # 設定欄寬
        worksheet.set_column('A:A', 15) # 單元名稱
        worksheet.set_column('B:B', 40) # 學習目標
        worksheet.set_column('C:C', 10) # 節數
        worksheet.set_column('D:D', 10) # 配分
        
        # 寫入格式
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            
    return output.getvalue()

# --- 5. AI 提示詞 (極簡化：只做摘取) ---
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

# --- 6. 主程式介面 ---
st.set_page_config(page_title="內湖國小出題系統 (Pro)", layout="wide")

# 標題區
st.markdown("""
    <div style="background-color:#1E293B;padding:20px;border-radius:10px;text-align:center;margin-bottom:20px;">
        <h2 style="color:white;margin:0;">內湖國小 AI 命題與審核系統</h2>
        <p style="color:#94A3B8;margin:5px;">學習目標自動摘取 • 智慧配分 • 雙向細目表生成</p>
    </div>
""", unsafe_allow_html=True)

# 狀態初始化
if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

# 側邊欄
with st.sidebar:
    st.header("⚙️ 設定與金鑰")
    api_key = st.text_input("Google API Key", type="password")
    
    st.divider()
    st.info("💡 提示：此模式利用 Python 進行數學運算，確保配分總和為 100，並節省 AI 用量。")
    
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
            with st.spinner("🤖 AI 正在閱讀教材並摘取結構 (使用 Flash 模型)..."):
                try:
                    # 1. 讀檔
                    text_content = extract_text_from_files(uploaded_files)
                    
                    # 2. 設定 AI (使用 Flash 省錢)
                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel('gemini-1.5-flash') # 指定 Flash
                    
                    # 3. 發送請求 (只摘取，不計算)
                    response = model.generate_content(GEM_EXTRACT_PROMPT.format(content=text_content[:30000]))
                    raw_text = response.text
                    
                    # 4. 解析表格 (Markdown to DataFrame)
                    # 處理一些常見的 AI 格式問題
                    lines = [line.strip() for line in raw_text.split('\n') if "|" in line and "---" not in line]
                    data = []
                    for line in lines:
                        row = [cell.strip() for cell in line.split('|') if cell.strip()]
                        if len(row) >= 3: # 確保有抓到三欄
                            data.append(row[:3]) # 只取前三欄
                    
                    if len(data) > 1:
                        # 第一列通常是標題，如果 AI 聽話的話
                        headers = ["單元名稱", "學習目標", "授課節數"]
                        # 簡單判斷第一列是不是標題，如果是就跳過
                        start_idx = 1 if "單元" in data[0][0] else 0
                        
                        df = pd.DataFrame(data[start_idx:], columns=headers)
                        
                        # 5. 呼叫 Python 進行配分計算
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
    
    # 顯示可編輯表格 (讓老師可以手動微調節數或分數)
    edited_df = st.data_editor(
        df,
        column_config={
            "預計配分": st.column_config.NumberColumn("預計配分 (%)", help="由系統依節數比例自動計算"),
            "授課節數": st.column_config.NumberColumn("授課節數", help="AI 推估，可修改")
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # 即時檢查總分
    current_total = edited_df['預計配分'].sum()
    if current_total != 100:
        st.warning(f"⚠️ 注意：目前總分為 {current_total} 分 (目標 100 分)，請手動調整。")
    else:
        st.success("🎯 總分完美：100 分")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        # 下載 Excel
        excel_data = df_to_excel(edited_df)
        st.download_button(
            label="📥 下載審核表 (Excel)",
            data=excel_data,
            file_name="學習目標審核表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with col_d2:
        # 下載 CSV
        csv = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載審核表 (CSV)",
            data=csv,
            file_name="學習目標審核表.csv",
            mime="text/csv",
            use_container_width=True
        )

    st.divider()
    if st.button("⬅️ 重新上傳教材"):
        st.session_state.step = 1
        st.rerun()
