import streamlit as st
import google.generativeai as genai
import io
import pandas as pd
import math
from pypdf import PdfReader
from docx import Document
from pptx import Presentation  # 需安裝: pip install python-pptx

# --- 1. 核心設定與工具 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "改錯字", "字詞義測驗", "課文理解", "閱讀測驗", "成語運用"],
    "數學": ["選擇題", "填充題", "計算題", "應用題", "畫圖題"],
    "自然科學": ["是非題", "選擇題", "做做看", "科學閱讀", "實驗題"],
    "社會": ["是非題", "選擇題", "勾選題", "連連看", "簡答題", "圖表題"],
    "英語": ["Listen & Check", "Listen & Choose", "Read & Choose", "Look & Write", "Reading Comprehension"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 2. 檔案讀取工具 (全能增強版) ---
@st.cache_data
def extract_text_from_files(files):
    text_content = ""
    for file in files:
        try:
            filename = file.name.lower()
            file_header = f"\n\n=== 檔案來源：{file.name} ===\n"
            extracted_text = ""

            # === PDF 處理 ===
            if filename.endswith('.pdf'):
                pdf_reader = PdfReader(file)
                for page in pdf_reader.pages:
                    extracted_text += (page.extract_text() or "") + "\n"
                
                # 防呆：如果讀出來完全沒字 (可能是掃描檔)
                if len(extracted_text.strip()) < 10:
                    text_content += file_header + "[警示] 檔案內容過少，似乎是圖片掃描檔。請使用側邊欄工具轉檔後再試。\n"
                else:
                    text_content += file_header + extracted_text

            # === Word (.docx) 處理 ===
            elif filename.endswith('.docx'):
                doc = Document(file)
                extracted_text = "\n".join([p.text for p in doc.paragraphs])
                text_content += file_header + extracted_text

            # === PowerPoint (.pptx) 處理 ===
            elif filename.endswith('.pptx'):
                try:
                    prs = Presentation(file)
                    for slide_idx, slide in enumerate(prs.slides):
                        slide_text = []
                        for shape in slide.shapes:
                            if hasattr(shape, "text") and shape.text.strip():
                                slide_text.append(shape.text)
                        if slide_text:
                            extracted_text += f"[Slide {slide_idx+1}]\n" + "\n".join(slide_text) + "\n"
                    text_content += file_header + extracted_text
                except Exception as e:
                    text_content += file_header + f"[PPTX 讀取錯誤] {str(e)}"

            # === 舊版格式 (.doc, .ppt) ===
            elif filename.endswith('.doc') or filename.endswith('.ppt'):
                text_content += file_header + "[系統限制] 請將 .doc/.ppt 舊版檔案另存為 .docx/.pptx 後再上傳，以確保 AI 判讀正確。"

            # === 純文字 (.txt) ===
            elif filename.endswith('.txt'):
                text_content += file_header + str(file.read(), "utf-8")

        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name}] 原因：{str(e)}\n"
            
    return text_content

# --- 3. 數學配分邏輯 (總分 100 鎖定演算法) ---
def calculate_scores(df):
    """
    輸入包含 '授課節數' 的 DataFrame，輸出包含 '預計配分' 的 DataFrame。
    使用最大餘數法確保總分剛好 100 分。
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
        
        if remainder > 0:
            # 找出被捨去最多分數的單元，依序補分
            df['餘數權重'] = df['原始配分'] - df['預計配分']
            indices_to_add = df.nlargest(int(remainder), '餘數權重').index
            df.loc[indices_to_add, '預計配分'] += 1
        elif remainder < 0:
            # 理論上 floor 不會發生這種情況，但以防萬一
             df.iloc[0, df.columns.get_loc('預計配分')] += remainder

        # 移除暫存欄位
        if '原始配分' in df.columns: df = df.drop(columns=['原始配分'])
        if '餘數權重' in df.columns: df = df.drop(columns=['餘數權重'])
        
        return df
    except Exception as e:
        st.error(f"配分計算錯誤: {e}")
        return df

# --- 4. Excel 下載工具 (符合審核表格式) ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 為了符合審核表格式，我們加入空白欄位讓老師填寫題型配分
        export_df = df.copy()
        export_df["選擇題配分"] = "" 
        export_df["非選題配分"] = ""
        
        export_df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        workbook = writer.book
        worksheet = writer.sheets['學習目標審核表']
        
        # 格式設定
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        
        # 設定欄寬
        worksheet.set_column('A:A', 20) # 單元名稱
        worksheet.set_column('B:B', 50) # 學習目標
        worksheet.set_column('C:C', 10) # 節數
        worksheet.set_column('D:D', 12) # 預計配分
        worksheet.set_column('E:F', 15) # 題型配分欄位
        
        # 寫入格式
        for col_num, value in enumerate(export_df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            
    return output.getvalue()

# --- 5. 自動搜尋可用模型 (修復 404 錯誤) ---
def get_available_flash_model(api_key):
    """自動尋找帳號可用的 Flash 模型"""
    try:
        genai.configure(api_key=api_key)
        valid_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # 優先順序：Flash -> Pro -> 任何可用
        for m in valid_models:
            if
