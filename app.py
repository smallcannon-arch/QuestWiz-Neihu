import streamlit as st
import google.generativeai as genai
import io
import pandas as pd
import math
from pypdf import PdfReader
from docx import Document
from pptx import Presentation

# --- 1. 核心設定 ---
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
            filename = file.name.lower()
            file_header = f"\n\n=== 檔案來源：{file.name} ===\n"
            extracted_text = ""

            if filename.endswith('.pdf'):
                pdf_reader = PdfReader(file)
                for page in pdf_reader.pages:
                    extracted_text += (page.extract_text() or "") + "\n"
                if len(extracted_text.strip()) < 10:
                    text_content += file_header + "[警示] 內容過少，可能是掃描檔，請先轉檔。\n"
                else:
                    text_content += file_header + extracted_text

            elif filename.endswith('.docx'):
                doc = Document(file)
                extracted_text = "\n".join([p.text for p in doc.paragraphs])
                text_content += file_header + extracted_text

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
                except:
                    text_content += file_header + "[PPTX 讀取錯誤] 請確認檔案未加密。\n"
            
            elif filename.endswith('.txt'):
                text_content += file_header + str(file.read(), "utf-8")
                
        except Exception as e:
            text_content += f"\n[讀取錯誤] {str(e)}\n"
    return text_content

# --- 3. 邏輯核心：防呆算分系統 ---
def calculate_scores(df):
    # 預先建立必要欄位，防止 KeyError
    if '目標分配節數' not in df.columns: df['目標分配節數'] = 0.0
    if '預計配分' not in df.columns: df['預計配分'] = 0.0

    try:
        # 1. 欄位名稱標準化
        if '授課節數' in df.columns:
            df.rename(columns={'授課節數': '單元總節數'}, inplace=True)
        
        # 2. 強制轉數值 (關鍵！把 "未提供" 變成 1)
        df['單元總節數'] = pd.to_numeric(df['單元總節數'], errors='coerce').fillna(1)
        
        # 3. 計算每個單元有幾條目標
        unit_counts = df['單元名稱'].value_counts()
        
        # 4. 平均分配節數 (單元總節數 / 目標數)
        def distribute_hours(row):
            unit_name = row['單元名稱']
            total_unit_hours = row['單元總節數']
            count = unit_counts.get(unit_name, 1)
            if count == 0: count = 1
            return total_unit_hours / count

        df['目標分配節數'] = df.apply(distribute_hours, axis=1)

        # 5. 計算整份考卷的總權重 (避免重複加總)
        # 我們只取每個單元的第一筆來加總「單元總節數」
        unit_hours_map = df[['單元名稱', '單元總節數']].drop_duplicates()
        total_course_hours = unit_hours_map['單元總節數'].sum()
        if total_course_hours == 0: total_course_hours = 1

        # 6. 計算配分
        df['原始配分'] = (df['目標分配節數'] / total_course_hours) * 100
        df['預計配分'] = df['原始配分'].apply(lambda x: round(x, 1))

        # 7. 微調總分至 100 (修正小數點誤差)
        current_sum = df['預計配分'].sum()
        diff = 100 - current_sum
        if abs(diff) > 0.01: 
            df.iloc[-1, df.columns.get_loc('預計配分')] += diff

        return df
    except Exception as e:
        st.error(f"⚠️ 配分計算發生例外狀況 (已自動略過): {e}")
        return df

# --- 4. Excel 下載 (修復版) ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df = df.copy()
        
        # 只匯出存在的欄位
        desired_cols = ['單元名稱', '單元總節數', '學習目標', '目標分配節數', '預計配分']
        final_cols = [c for c in desired_cols if c in export_df.columns]
        export_df = export_df[final_cols]
        
        if '目標分配節數' in export_df.columns:
            export_df.rename(columns={'目標分配節數': '此目標佔用節數'}, inplace=True)
        
        export_df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        workbook = writer.book
        worksheet = writer.sheets['學習目標審核表']
        
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        num_fmt = workbook.add_format({'num_format': '0.0', 'border': 1, 'align': 'center'})
        
        # 設定欄寬
        worksheet.set_column('A:A', 15, cell_fmt) 
        worksheet.set_column('B:B', 10, num_fmt) 
        worksheet.set_column('C:C', 60, cell_fmt) 
        worksheet.set_column('D:D', 12, num_fmt)
        worksheet.set_column('E:E', 12, num_fmt)
        
        for col_num, value in enumerate(export_df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            
    return output.getvalue()

# --- 5. 模型選擇 ---
def get_available_flash_model(api_key):
    try:
        genai.configure(api_key=api_key)
        valid_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in valid_models:
             if 'flash' in m.lower(): return m
        return "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

# --- 6. Prompt (針對數字分點拆解的特化版) ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請分析以下教材，提取「單元名稱」、「學習目標」與「單元總授課節數」。

**⚠️ 最高指令：數字拆解原則**
1. **看到數字分點 (1., 2., 3...)，必須拆成不同列！**
   - 如果單元內容有：「1. 知道... 2. 察覺... 3. 了解...」
   - 請務必輸出 **3 列** 資料，每一列只放一個目標。
   - **絕對禁止** 把 1, 2, 3 寫在同一格。

**輸出格式規則：**
1. 僅輸出一個 Markdown 表格。
2. 欄位：| 單元名稱 | 學習目標 | 授課節數 |
3. **單元名稱**：若該單元有 10 個目標，請在「單元名稱」欄位重複填寫 10 次該單元的名字。
4. **授課節數**：
   - 請填入該單元的「總節數」(數字)。
   - 如果找不到，請填入 "1"。
   - **不要** 寫文字，只能寫數字。

教材內容：
{content}
"""

# --- 7. 主程式 ---
st.set_page_config(page_title="內湖國小出題系統 (Pro)", layout="wide")

st.markdown("""<div style="background:#1E293B;padding:15px;text-align:center;color:white;border-radius:10px;">
<h2>內湖國小 AI 命題系統 (目標拆解版)</h2></div>""", unsafe_allow_html=True)

if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

with st.sidebar:
    st.header("設定")
    api_key = st.text_input("API Key", type="password")
    if st.button("重置"): 
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()
    
    st.divider()
    with st.expander("🛠️ 轉檔工具箱"):
        st.markdown("[Word 轉檔](https://cloudconvert.com/doc-to-docx)")
        st.markdown("[PPT 轉檔](https://cloudconvert.com/ppt-to-pptx)")
        st.markdown("[PDF 轉文字](https://www.ilovepdf.com/zh-tw/pdf_to_word)")

if st.session_state.step == 1:
    uploaded_files = st.file_uploader("上傳教材", type=["pdf","docx","pptx","txt"], accept_multiple_files=True)
    if st.button("🚀 開始分析", type="primary"):
        if api_key and uploaded_files:
            with st.spinner("AI 正在逐條拆解學習目標..."):
                try:
                    text = extract_text_from_files(uploaded_files)
                    model_name = get_available_flash_model(api_key)
                    model = genai.GenerativeModel(model_name)
                    res = model.generate_content(GEM_EXTRACT_PROMPT.format(content=text[:40000]))
                    
                    lines = [l.strip() for l in res.text.split('\n') if "|" in l and "---" not in l]
                    data = []
                    for l in lines:
                        row = [c.strip() for c in l.split('|') if c.strip()]
                        if len(row) >= 3: data.append(row[:3])
                    
                    if data:
                        df = pd.DataFrame(data[1:], columns=["單元名稱", "學習目標", "授課節數"])
                        df.rename(columns={"授課節數": "單元總節數"}, inplace=True)
                        
                        df_cal = calculate_scores(df)
                        st.session_state.extracted_data = df_cal
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("AI 未偵測到表格資料，請檢查教材內容是否清晰。")
                except Exception as e: st.error(f"發生錯誤: {e}")

elif st.session_state.step == 2:
    st.info("💡 請檢查：如果 AI 抓的目標數正確，請在「單元總節數」輸入該單元的總課時 (如 5)，系統會自動分配權重。")
    
    df_curr = st.session_state.extracted_data
    
    edited_df = st.data_editor(
        df_curr,
        column_config={
            "單元名稱": st.column_config.TextColumn(disabled=True),
            "學習目標": st.column_config.TextColumn(width="large"),
            "單元總節數": st.column_config.NumberColumn("單元總節數", min_value=1, max_value=50, help="修改此數字，該單元所有目標的配分會自動更新"),
            "目標分配節數": st.column_config.NumberColumn("此目標佔用", disabled=True, format="%.2f"),
            "預計配分": st.column_config.NumberColumn("配分 (%)", disabled=True)
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    if not edited_df.equals(df_curr):
        st.session_state.extracted_data = calculate_scores(edited_df)
        st.rerun()

    st.download_button("下載 Excel", df_to_excel(edited_df), "細目審核表.xlsx")
    if st.button("重新上傳"): st.session_state.step=1; st.rerun()
