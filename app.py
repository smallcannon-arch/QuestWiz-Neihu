這是一個非常具體的 `KeyError` 錯誤，同時也反映了 AI 在「摘要」與「逐字稿」之間的理解落差。

### 發生錯誤的原因 (KeyError)

您的截圖顯示 `KeyError: "['單元總節數'] not in index"`。
這是因為 AI 在產生表格時，有時候欄位名稱會寫成「授課時數」、「建議節數」或「節數」，導致程式碼中的 `.rename` 函數找不到「授課節數」這個字眼來修改，造成欄位名稱沒有成功改成系統預期的 `單元總節數`。當 Excel 匯出功能試圖抓取這個欄位時，就會因為找不到而崩潰。

### 邏輯修正 (針對 4-1 單元 10 個目標)

您提到單元 4-1 有 5 節課，但有 10 個目標。
先前的 AI 為了省事，把 10 點濃縮成了 3 點（如您截圖所示）。
我將修改 Prompt，**強制 AI 進行「逐字拆解」**，並且在程式碼中加入**「暴力欄位重新命名」**，不管 AI 給什麼標題，程式直接強制覆蓋為標準名稱，徹底解決 `KeyError`。

---

### 🛠️ 修正後的完整程式碼 (`app.py`)

請直接全選覆蓋。這次更新包含了：

1. **修復崩潰 (KeyError)**：使用 `df.columns = [...]` 強制統一欄位名稱。
2. **細節全抓**：Prompt 加入「逐字提取」、「禁止摘要」指令，確保 10 點目標會變成 10 列。
3. **自動均分演算法**：輸入 5 節，若有 10 個目標，每列自動配分 0.5 節。

```python
import streamlit as st
import google.generativeai as genai
import io
import pandas as pd
import math
from pypdf import PdfReader
from docx import Document
try:
    from pptx import Presentation
except ImportError:
    st.error("請安裝 python-pptx: pip install python-pptx")

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
                    text_content += file_header + "[警示] 此 PDF 似乎是掃描檔(圖片)，AI 無法讀取文字。請先轉檔為 Word 或使用 OCR 工具。\n"
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
                except Exception as e:
                    text_content += file_header + f"[PPTX Error] {str(e)}"

            elif filename.endswith('.txt'):
                text_content += file_header + str(file.read(), "utf-8")
            
            elif filename.endswith('.doc') or filename.endswith('.ppt'):
                text_content += file_header + "[系統提示] 舊版 Office 檔案無法直接讀取，請轉存為 .docx/.pptx 後再上傳。"

        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name}] {str(e)}\n"
            
    return text_content

# --- 3. 邏輯核心：單元時數均分演算法 ---
def calculate_scores(df):
    try:
        # 1. 確保欄位名稱正確 (防止 KeyError)
        # 如果欄位名稱跑掉，這裡先做基本檢查，但主要的強制命名在 Step 1
        if '單元總節數' not in df.columns and '授課節數' in df.columns:
            df.rename(columns={'授課節數': '單元總節數'}, inplace=True)

        # 轉為數值
        df['單元總節數'] = pd.to_numeric(df['單元總節數'], errors='coerce').fillna(1)
        
        # 2. 計算每個單元有多少條目標 (Row count)
        # 例如 4-1 有 10 條目標，count 就是 10
        unit_counts = df['單元名稱'].value_counts()
        
        # 3. 核心算法：將單元總節數平均分配給每一條目標
        # 4-1 總共 5 節 / 10 條目標 = 每條目標 0.5 節
        def distribute_hours(row):
            unit_name = row['單元名稱']
            total_unit_hours = row['單元總節數']
            count = unit_counts.get(unit_name, 1)
            if count == 0: return 0
            return total_unit_hours / count

        df['目標權重(節)'] = df.apply(distribute_hours, axis=1)

        # 4. 計算整份考卷的總時數 (所有不重複單元的節數總和)
        # 這裡利用 drop_duplicates 只算一次每個單元的節數
        unique_units = df[['單元名稱', '單元總節數']].drop_duplicates()
        total_course_hours = unique_units['單元總節數'].sum()
        
        if total_course_hours == 0: total_course_hours = 1

        # 5. 計算配分
        # (該目標分到的 0.5 節 / 總課程時數) * 100
        df['原始配分'] = (df['目標權重(節)'] / total_course_hours) * 100
        df['預計配分'] = df['原始配分'].apply(lambda x: round(x, 1))

        # 6. 微調總分至 100 (針對浮點數誤差)
        current_sum = df['預計配分'].sum()
        diff = 100 - current_sum
        # 將誤差加到第一列 (或分數最高的一列)
        if diff != 0:
             df.iloc[0, df.columns.get_loc('預計配分')] += diff
             # 再次確保小數點漂亮
             df.iloc[0, df.columns.get_loc('預計配分')] = round(df.iloc[0, df.columns.get_loc('預計配分')], 1)

        return df
    except Exception as e:
        st.error(f"配分計算錯誤: {e}")
        return df

# --- 4. Excel 下載 (修復 KeyError) ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df = df.copy()
        
        # 確保需要的欄位都存在，若無則補上預設值
        required_cols = ['單元名稱', '單元總節數', '學習目標', '目標權重(節)', '預計配分']
        for col in required_cols:
            if col not in export_df.columns:
                export_df[col] = "" # 防呆補空值

        # 選取並排序欄位
        export_df = export_df[required_cols]
        export_df.rename(columns={'目標權重(節)': '此列佔分比重(節)'}, inplace=True)
        
        # 加入空的題型欄位供填寫
        export_df["對應題型"] = ""
        
        export_df.to_excel(writer, index=False, sheet_name='學習目標細目表')
        workbook = writer.book
        worksheet = writer.sheets['學習目標細目表']
        
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        cell_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        num_fmt = workbook.add_format({'num_format': '0.0', 'border': 1, 'align': 'center'})
        
        worksheet.set_column('A:A', 15, cell_fmt) # 單元
        worksheet.set_column('B:B', 12, num_fmt) # 總節數
        worksheet.set_column('C:C', 60, cell_fmt) # 目標
        worksheet.set_column('D:D', 15, num_fmt) # 權重
        worksheet.set_column('E:E', 12, num_fmt) # 配分
        worksheet.set_column('F:F', 20, cell_fmt) # 題型
        
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

# --- 6. Prompt (強化版：逐字抓取，禁止縮減) ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請分析以下教材，提取「單元名稱」、「學習目標」與「單元總授課節數」。

**輸出規則 (嚴格執行)：**
1. 輸出 Markdown 表格，欄位順序必須是：| 單元名稱 | 學習目標 | 單元總節數 |
2. **學習目標提取 (關鍵)**：
   - 請找出教材中的條列式目標 (如 1. 2. 3. 或 A. B. C.)。
   - **必須逐字提取，禁止摘要、禁止縮減、禁止合併。**
   - **每一點目標必須獨立成一列 (One row per objective)。**
   - 例如：單元 4-1 有 10 點目標，請輸出 10 列，每一列的單元名稱都是「單元 4-1」。
3. **單元總節數 (Unit Total Hours)**：
   - 找出該單元的總節數 (例如單元 4-1 是 5 節)。
   - **請在該單元的每一列都填入相同的總數字** (例如這 10 列的節數欄位全部填 5)。
   - 不用你去算平均，直接填總數。

教材內容：
{content}
"""

# --- 7. 主程式 ---
st.set_page_config(page_title="內湖國小出題系統 (Pro)", layout="wide")

st.markdown("""<div style="background:#1E293B;padding:15px;text-align:center;color:white;border-radius:10px;">
<h2>內湖國小 AI 命題系統 (細目拆解修復版)</h2></div>""", unsafe_allow_html=True)

if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

with st.sidebar:
    st.header("設定")
    api_key = st.text_input("API Key", type="password")
    if st.button("重置系統"): 
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()

    st.divider()
    with st.expander("🛠️ 轉檔工具箱"):
        st.markdown("[Word 轉檔](https://cloudconvert.com/doc-to-docx)")
        st.markdown("[PPT 轉檔](https://cloudconvert.com/ppt-to-pptx)")
        st.markdown("[PDF 轉文字(OCR)](https://www.ilovepdf.com/zh-tw/pdf_to_word)")

# Step 1: 分析
if st.session_state.step == 1:
    col1, col2 = st.columns([1, 2])
    with col1:
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("科目", list(SUBJECT_Q_TYPES.keys()))
    with col2:
        uploaded_files = st.file_uploader("上傳教材 (PDF/DOCX/PPTX)", accept_multiple_files=True)

    if st.button("🚀 開始分析 (生成細目表)", type="primary", use_container_width=True):
        if api_key and uploaded_files:
            with st.spinner("AI 正在逐字拆解，確保 10 點目標不遺漏..."):
                try:
                    text = extract_text_from_files(uploaded_files)
                    model_name = get_available_flash_model(api_key)
                    model = genai.GenerativeModel(model_name)
                    res = model.generate_content(GEM_EXTRACT_PROMPT.format(content=text[:50000]))
                    
                    # 表格解析與暴力命名
                    lines = [l.strip() for l in res.text.split('\n') if "|" in l and "---" not in l]
                    data = []
                    for l in lines:
                        row = [c.strip() for c in l.split('|') if c.strip()]
                        if len(row) >= 3: 
                            # 只取前三欄，忽略 AI 可能多生成的雜訊
                            data.append(row[:3])
                    
                    if data:
                        # 暴力強制命名：不管 AI 輸出什麼標題，第一欄就是單元，第二欄就是目標，第三欄就是總節數
                        # 略過第一列 (通常是 AI 的標題列)
                        start_idx = 1 if "單元" in data[0][0] or "Unit" in data[0][0] else 0
                        df = pd.DataFrame(data[start_idx:], columns=["單元名稱", "學習目標", "單元總節數"])
                        
                        df_cal = calculate_scores(df)
                        st.session_state.extracted_data = df_cal
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("AI 讀取失敗，請確認檔案不是圖片掃描檔。")
                except Exception as e: st.error(str(e))
        else:
            st.warning("請輸入 API Key 並上傳檔案")

# Step 2: 編輯與下載
elif st.session_state.step == 2:
    st.info("💡 說明：每列代表一個目標。請確認「單元總節數」是否正確 (例如單元 4-1 總共 5 節)，系統會自動平分給該單元的所有目標。")
    
    df_curr = st.session_state.extracted_data
    
    edited_df = st.data_editor(
        df_curr,
        column_config={
            "單元名稱": st.column_config.TextColumn(disabled=True),
            "學習目標": st.column_config.TextColumn(width="large", help="AI 逐字提取的目標"),
            "單元總節數": st.column_config.NumberColumn("單元總節數", help="請輸入該單元的總時數 (例如 5)，同一單元的每一列都要填一樣"),
            "目標權重(節)": st.column_config.NumberColumn("此列權重", disabled=True, format="%.2f", help="自動計算：總節數 / 目標數"),
            "預計配分": st.column_config.NumberColumn("配分 (%)", disabled=True, format="%.1f")
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # 即時重算
    if not edited_df.equals(df_curr):
        st.session_state.extracted_data = calculate_scores(edited_df)
        st.rerun()

    st.caption(f"目前總分：{edited_df['預計配分'].sum():.1f} 分 (目標 100 分)")

    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 下載 Excel 細目表", df_to_excel(edited_df), "學習目標細目表.xlsx", use_container_width=True)
    with col2:
        if st.button("⬅️ 重新上傳", use_container_width=True): 
            st.session_state.step=1; st.rerun()

```
