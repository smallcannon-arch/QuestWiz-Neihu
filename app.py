import streamlit as st
import google.generativeai as genai
import io
import pandas as pd
import math
from pypdf import PdfReader
from docx import Document
from pptx import Presentation

# --- 1. 核心設定 (不變) ---
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
            filename = file.name.lower()
            file_header = f"\n\n=== 檔案來源：{file.name} ===\n"
            extracted_text = ""

            if filename.endswith('.pdf'):
                pdf_reader = PdfReader(file)
                for page in pdf_reader.pages:
                    extracted_text += (page.extract_text() or "") + "\n"
                if len(extracted_text.strip()) < 10:
                    text_content += file_header + "[警示] 檔案內容過少，似乎是圖片掃描檔。\n"
                else:
                    text_content += file_header + extracted_text

            elif filename.endswith('.docx'):
                doc = Document(file)
                extracted_text = "\n".join([p.text for p in doc.paragraphs])
                text_content += file_header + extracted_text

            elif filename.endswith('.pptx'):
                prs = Presentation(file)
                for slide_idx, slide in enumerate(prs.slides):
                    slide_text = []
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            slide_text.append(shape.text)
                    if slide_text:
                        extracted_text += f"[Slide {slide_idx+1}]\n" + "\n".join(slide_text) + "\n"
                text_content += file_header + extracted_text
            
            elif filename.endswith('.txt'):
                text_content += file_header + str(file.read(), "utf-8")
                
        except Exception as e:
            text_content += f"\n[讀取錯誤] {str(e)}\n"
    return text_content

# --- 3. 邏輯大改：單元時數均分演算法 ---
def calculate_scores(df):
    try:
        # 1. 確保數據格式正確
        # 我們讓 '單元總節數' 成為該單元的總量，'權重' 則是這條目標分到的時數
        if '單元總節數' not in df.columns:
            # 如果是第一次生成，可能只有 '授課節數'，先轉換過來
            df['單元總節數'] = pd.to_numeric(df['授課節數'], errors='coerce').fillna(1)
        
        # 2. 計算每個單元有多少個目標 (Row count per unit)
        unit_counts = df['單元名稱'].value_counts()
        
        # 3. 重新計算每一列的實際節數 (權重)
        # 邏輯：如果使用者填寫單元 4-1 是 5 節，且 AI 抓出 10 條目標，則每條自動分 0.5 節
        def distribute_hours(row):
            unit_name = row['單元名稱']
            total_unit_hours = row['單元總節數']
            count = unit_counts.get(unit_name, 1)
            return total_unit_hours / count

        # 創造一個新欄位「目標分配節數」，這才是真正用來算分的權重
        df['目標分配節數'] = df.apply(distribute_hours, axis=1)

        # 4. 計算整張考卷的總時數
        # 注意：不能直接 sum(目標分配節數)，因為浮點數會有誤差，我們改用 sum(單元總節數) / count 邏輯反推
        # 但最簡單的方式是：將所有單元的總節數加總 (去重複後)
        
        # 建立一個單元對照表
        unit_hours_map = df[['單元名稱', '單元總節數']].drop_duplicates()
        total_course_hours = unit_hours_map['單元總節數'].sum()
        
        if total_course_hours == 0: total_course_hours = 1

        # 5. 計算配分
        # 公式：(該目標分到的節數 / 總課程時數) * 100
        df['原始配分'] = (df['目標分配節數'] / total_course_hours) * 100
        df['預計配分'] = df['原始配分'].apply(lambda x: round(x, 1)) # 保留一位小數比較好看

        # 6. 微調總分至 100 (針對整數)
        # 這裡做一個簡單的處理：最後一項補差額，確保加起來是 100
        current_sum = df['預計配分'].sum()
        diff = 100 - current_sum
        if diff != 0:
            df.iloc[-1, df.columns.get_loc('預計配分')] += diff

        return df
    except Exception as e:
        st.error(f"配分計算錯誤: {e}")
        return df

# --- 4. Excel 下載 (支援小數點顯示) ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 準備匯出資料，移除計算用的暫存欄位
        export_df = df.copy()
        # 為了讓老師看懂，我們把「單元總節數」放在前面
        cols = ['單元名稱', '單元總節數', '學習目標', '目標分配節數', '預計配分']
        export_df = export_df[cols]
        export_df.rename(columns={'目標分配節數': '此目標佔用節數'}, inplace=True)
        
        export_df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        workbook = writer.book
        worksheet = writer.sheets['學習目標審核表']
        
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        num_fmt = workbook.add_format({'num_format': '0.0', 'border': 1, 'align': 'center'}) # 支援小數點
        
        worksheet.set_column('A:A', 15, cell_fmt) 
        worksheet.set_column('B:B', 10, num_fmt) 
        worksheet.set_column('C:C', 60, cell_fmt) 
        worksheet.set_column('D:D', 12, num_fmt)
        worksheet.set_column('E:E', 12, num_fmt)
        
        for col_num, value in enumerate(export_df.columns.values):
            worksheet.write(0, col_num, value, header_fmt)
            
    return output.getvalue()

# --- 5. 模型選擇 (不變) ---
def get_available_flash_model(api_key):
    try:
        genai.configure(api_key=api_key)
        valid_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for m in valid_models:
             if 'flash' in m.lower(): return m
        return "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

# --- 6. Prompt 大改：強制逐條列出 + 抓單元總時數 ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請分析以下教材，提取「單元名稱」、「學習目標」與「單元總授課節數」。

**輸出規則 (請嚴格執行)：**
1. **格式**：僅輸出 Markdown 表格，欄位：| 單元名稱 | 學習目標 | 授課節數 |
2. **學習目標拆解 (最重要)**：
   - 仔細閱讀教材中的條列式重點 (如 1., 2., 3... 或 A, B, C)。
   - **每一條重點必須獨立拆成 Excel 的一列 (Row)**。
   - **嚴禁合併**：如果有 10 點，表格就要有 10 列。
   - 範例：如果單元 4-1 有 10 點，請輸出 10 列「單元 4-1」，每列對應一點目標。
3. **授課節數 (單元總量)**：
   - 請找出該「單元」建議的總節數 (例如單元 4-1 建議 5 節)。
   - **請在該單元的每一列都填入這個「總節數」** (不用你去平分，後續程式會算)。
   - 如果找不到建議節數，請依內容份量推估 (例如內容很多的單元填 5，少的填 2)。

教材內容：
{content}
"""

# --- 7. 主程式 ---
st.set_page_config(page_title="內湖國小出題系統 (Pro)", layout="wide")

st.markdown("""<div style="background:#1E293B;padding:15px;text-align:center;color:white;border-radius:10px;">
<h2>內湖國小 AI 命題系統 (細目拆解版)</h2></div>""", unsafe_allow_html=True)

if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

with st.sidebar:
    st.header("設定")
    api_key = st.text_input("API Key", type="password")
    if st.button("重置"): 
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()

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
                    
                    # 解析
                    lines = [l.strip() for l in res.text.split('\n') if "|" in l and "---" not in l]
                    data = []
                    for l in lines:
                        row = [c.strip() for c in l.split('|') if c.strip()]
                        if len(row) >= 3: data.append(row[:3])
                    
                    if data:
                        df = pd.DataFrame(data[1:], columns=["單元名稱", "學習目標", "授課節數"])
                        # 這裡把 '授課節數' 改名為 '單元總節數' 以符合新邏輯
                        df.rename(columns={"授課節數": "單元總節數"}, inplace=True)
                        
                        df_cal = calculate_scores(df)
                        st.session_state.extracted_data = df_cal
                        st.session_state.step = 2
                        st.rerun()
                except Exception as e: st.error(str(e))

elif st.session_state.step == 2:
    st.info("💡 邏輯更新：請修改「單元總節數」。系統會自動將該單元的節數，平均分配給底下的所有學習目標。")
    
    df_curr = st.session_state.extracted_data
    
    # 編輯器：讓老師改單元總節數
    edited_df = st.data_editor(
        df_curr,
        column_config={
            "單元名稱": st.column_config.TextColumn(disabled=True),
            "學習目標": st.column_config.TextColumn(width="large"),
            "單元總節數": st.column_config.NumberColumn("單元總節數", help="例如 4-1 總共 5 節，請在此輸入 5 (每一列都填 5)"),
            "目標分配節數": st.column_config.NumberColumn("此目標佔用 (節)", disabled=True, format="%.2f", help="自動計算：總節數 / 目標數量"),
            "預計配分": st.column_config.NumberColumn("預計配分 (%)", disabled=True)
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # 即時重算
    if not edited_df.equals(df_curr):
        st.session_state.extracted_data = calculate_scores(edited_df)
        st.rerun()

    st.download_button("下載 Excel", df_to_excel(edited_df), "細目審核表.xlsx")
    if st.button("重新上傳"): st.session_state.step=1; st.rerun()
