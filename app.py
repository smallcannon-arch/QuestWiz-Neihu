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
            if 'flash' in m.lower() and '1.5' in m.lower(): return m
        for m in valid_models:
            if 'flash' in m.lower(): return m
        for m in valid_models:
            if 'pro' in m.lower(): return m
            
        return "models/gemini-1.5-flash" # 最後嘗試
    except Exception:
        return "models/gemini-1.5-flash"

# --- 6. AI 提示詞 (極簡化：只做摘取) ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請分析以下教材內容，並提取「單元名稱」、「學習目標」與「授課節數」。

**輸出規則 (嚴格遵守)：**
1. 僅輸出一個 Markdown 表格。
2. 欄位必須包含：| 單元名稱 | 學習目標 | 授課節數 |
3. 「授課節數」欄位**只能填入數字** (例如: 4, 3, 5)。若教材未提及，請根據內容長度推估一個整數 (1~5)。
4. 學習目標請精簡摘錄重點 (不要超過 50 字)。
5. **不要**計算分數，**不要**輸出其他廢話。

教材內容：
{content}
"""

# --- 7. 主程式介面 ---
st.set_page_config(page_title="內湖國小出題系統 (Pro)", layout="wide")

st.markdown("""
    <style>
    .school-header { background: linear-gradient(90deg, #1E293B 0%, #334155 100%); padding: 20px; border-radius: 12px; text-align: center; color: white; margin-bottom: 20px; }
    </style>
    <div class="school-header">
        <h2 style="margin:0;">內湖國小 AI 命題與審核系統</h2>
        <p style="opacity:0.8; margin-top:5px;">學習目標自動摘取 • 智慧配分 • 雙向細目表生成</p>
    </div>
""", unsafe_allow_html=True)

# 狀態初始化
if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

# --- 側邊欄：設定與工具 ---
with st.sidebar:
    st.header("⚙️ 設定與金鑰")
    api_key = st.text_input("Google API Key", type="password", placeholder="在此貼上您的 Key")
    
    if st.button("🔄 重置系統"):
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()

    st.divider()
    st.markdown("### 🛠️ 萬用轉檔工具箱")
    st.info("遇到舊版檔案 (.doc, .ppt) 或 圖片型 PDF 讀不到字？請先用下方工具轉檔。")
    
    with st.expander("📂 舊檔救星 (轉成 .docx/.pptx)"):
        st.markdown("""
        您的檔案是 2003 年以前的舊格式嗎？
        1. **Word 轉檔**：[CloudConvert (Doc to Docx)](https://cloudconvert.com/doc-to-docx)
        2. **PPT 轉檔**：[CloudConvert (Ppt to Pptx)](https://cloudconvert.com/ppt-to-pptx)
        """)

    with st.expander("📸 圖片/掃描檔救星 (OCR)"):
        st.markdown("""
        您的 PDF 是掃描的圖片嗎？AI 讀不到字？
        1. **PDF 轉 Word (含 OCR)**：[iLovePDF](https://www.ilovepdf.com/zh-tw/pdf_to_word)
        2. **圖片 轉 文字**：[Google Drive](https://drive.google.com)  
           *(小撇步：上傳圖片 -> 右鍵 -> 選擇「Google 文件」開啟)*
        """)

# --- Step 1: 上傳與參數 ---
if st.session_state.step == 1:
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("1. 參數設定")
        grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"])
        subject = st.selectbox("科目", list(SUBJECT_Q_TYPES.keys()))
    with col2:
        st.subheader("2. 上傳教材")
        st.markdown("支援格式：**PDF, DOCX, PPTX** (建議) / TXT")
        uploaded_files = st.file_uploader("請選擇檔案", type=["pdf", "docx", "pptx", "txt", "doc", "ppt"], accept_multiple_files=True)

    if st.button("🚀 開始分析教材 (生成審核表)", type="primary", use_container_width=True):
        if not api_key:
            st.error("❌ 請在左側輸入 Google API Key")
        elif not uploaded_files:
            st.warning("⚠️ 請上傳至少一個教材檔案")
        else:
            with st.spinner("🤖 AI 正在閱讀教材並摘取結構 (使用 Flash 模型)..."):
                try:
                    # 1. 讀檔
                    text_content = extract_text_from_files(uploaded_files)
                    
                    # 2. 自動選模型
                    best_model_name = get_available_flash_model(api_key)
                    st.toast(f"已啟用省錢模式：{best_model_name}", icon="✅")
                    
                    model = genai.GenerativeModel(best_model_name)
                    
                    # 3. 發送請求
                    response = model.generate_content(GEM_EXTRACT_PROMPT.format(content=text_content[:40000]))
                    raw_text = response.text
                    
                    # 4. 解析表格
                    lines = [line.strip() for line in raw_text.split('\n') if "|" in line and "---" not in line]
                    data = []
                    for line in lines:
                        row = [cell.strip() for cell in line.split('|') if cell.strip()]
                        if len(row) >= 3:
                            data.append(row[:3])
                    
                    if len(data) > 0:
                        # 處理標題列
                        headers = ["單元名稱", "學習目標", "授課節數"]
                        start_idx = 1 if "單元" in data[0][0] else 0
                        
                        df = pd.DataFrame(data[start_idx:], columns=headers)
                        
                        # 5. 呼叫 Python 進行配分計算
                        df_calculated = calculate_scores(df)
                        
                        st.session_state.extracted_data = df_calculated
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error("❌ AI 無法識別教材結構，請確認檔案內容是否清晰，或使用側邊欄轉檔工具。")
                        with st.expander("查看 AI 原始回應"):
                            st.text(raw_text)
                            
                except Exception as e:
                    st.error(f"發生錯誤: {e}")

# --- Step 2: 確認與下載 ---
elif st.session_state.step == 2:
    st.subheader("✅ 學習目標審核表 (自動配分完畢)")
    
    st.info("💡 您可以直接修改「授課節數」，右側的「預計配分」會自動重新計算，保持總分 100。")
    
    # 使用 data_editor 讓使用者修改
    df_current = st.session_state.extracted_data
    
    edited_df = st.data_editor(
        df_current,
        column_config={
            "預計配分": st.column_config.NumberColumn("預計配分 (%)", help="由系統依節數比例自動計算", disabled=True), # 設為唯讀，強制由節數驅動
            "授課節數": st.column_config.NumberColumn("授課節數", help="可修改，修改後自動更新配分", min_value=1, max_value=50)
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # 即時重算：如果使用者修改了節數，立刻重新計算配分並刷新介面
    # 注意：這裡利用 session_state 比較來觸發重算
    if not edited_df.equals(df_current):
         recalculated_df = calculate_scores(edited_df)
         st.session_state.extracted_data = recalculated_df
         st.rerun()

    # 顯示總分狀態
    current_total = edited_df['預計配分'].sum()
    st.caption(f"目前總分：{current_total} 分")

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        # 下載 Excel
        excel_data = df_to_excel(edited_df)
        st.download_button(
            label="📥 下載 Excel 審核表",
            data=excel_data,
            file_name="學習目標審核表.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with col_d2:
        if st.button("⬅️ 重新上傳教材", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
