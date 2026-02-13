import streamlit as st
import google.generativeai as genai
import io
import pandas as pd
import math
import tempfile
import os
import time

# 嘗試匯入 Python 文檔處理套件
try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

try:
    from pptx import Presentation
    HAS_PPTX = True
except ImportError:
    HAS_PPTX = False

# --- 1. 核心邏輯：檔案處理 (暴力讀取版) ---
def process_file_for_ai(uploaded_file, api_key):
    """
    策略：
    1. PDF -> 走 Google AI File API (視覺讀取，最強，可讀掃描檔)。
    2. DOCX/PPTX -> 走 Python 轉譯 (輔助，補上結構符號)。
    """
    genai.configure(api_key=api_key)
    filename = uploaded_file.name.lower()
    
    # === 策略 A: PDF 直讀模式 (視覺分析) ===
    if filename.endswith(".pdf"):
        # 建立暫存檔 (因為 Gemini 需要實體路徑)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        try:
            st.toast(f"正在將 {filename} 傳送至 AI 視覺中樞...", icon="👁️")
            gemini_file = genai.upload_file(path=tmp_path, mime_type="application/pdf")
            
            # 等待 Google 處理檔案
            while gemini_file.state.name == "PROCESSING":
                time.sleep(1)
                gemini_file = genai.get_file(gemini_file.name)
            
            if gemini_file.state.name == "FAILED":
                return "error", "Google AI 無法讀取此 PDF (可能是加密或損壞)。"
            
            return "file_mode", gemini_file
            
        except Exception as e:
            return "error", str(e)
        finally:
            if os.path.exists(tmp_path): os.remove(tmp_path)

    # === 策略 B: Word/PPT 結構化文字模式 ===
    else:
        st.toast(f"正在解析 {filename} 文字結構...", icon="📝")
        text_content = ""
        header = f"\n\n=== 檔案：{uploaded_file.name} ===\n"

        try:
            if filename.endswith('.docx') and HAS_DOCX:
                doc = Document(uploaded_file)
                # 技巧：強制在每個段落前加符號，防止 AI 忽略列表
                paragraphs = []
                for p in doc.paragraphs:
                    text = p.text.strip()
                    if text:
                        # 如果是短句 (疑似標題或目標)，加 bullet
                        prefix = "● " if len(text) < 80 else ""
                        paragraphs.append(f"{prefix}{text}")
                text_content = "\n".join(paragraphs)
            
            elif filename.endswith('.pptx') and HAS_PPTX:
                prs = Presentation(uploaded_file)
                for slide_idx, slide in enumerate(prs.slides):
                    slide_text = []
                    for shape in slide.shapes:
                        if hasattr(shape, "text") and shape.text.strip():
                            slide_text.append(f"● {shape.text}")
                    if slide_text:
                        text_content += f"\n[Slide {slide_idx+1}]\n" + "\n".join(slide_text) + "\n"
            
            elif filename.endswith('.txt'):
                text_content = str(uploaded_file.read(), "utf-8")
            
            else:
                return "error", "不支援的格式。請上傳 PDF (最佳), DOCX, PPTX 或 TXT。"

            return "text_mode", header + text_content

        except Exception as e:
            return "error", f"讀取失敗: {str(e)}"

# --- 2. 算分核心 (總分 100 鎖定) ---
def calculate_scores(df):
    """
    邏輯：
    1. 找出每個單元的「單元總節數」(Unit Total Hours)。
    2. 計算該單元有幾個目標 (Objective Count)。
    3. 每個目標分到的時數 = 單元總節數 / 目標數。
    4. 總權重 = 所有目標分到的時數總和 (= 課程總時數)。
    5. 配分 = (目標時數 / 總權重) * 100。
    """
    if df is None or df.empty: return df

    # 初始化
    if '預計配分' not in df.columns: df['預計配分'] = 0.0

    try:
        # 1. 欄位防呆
        if '授課節數' in df.columns: df.rename(columns={'授課節數': '單元總節數'}, inplace=True)
        
        # 2. 強制轉數值 (處理文字干擾)
        df['單元總節數'] = pd.to_numeric(df['單元總節數'], errors='coerce').fillna(1)
        
        # 3. 演算法：單元時數分配
        # 先算每個單元有幾條 (分母)
        unit_counts = df['單元名稱'].value_counts()
        
        def get_objective_weight(row):
            unit = row['單元名稱']
            total_hours = row['單元總節數']
            count = unit_counts.get(unit, 1)
            if count == 0: count = 1
            return total_hours / count

        # 算出每一列 (每一個目標) 實際佔用的「時數份額」
        df['目標權重(時數)'] = df.apply(get_objective_weight, axis=1)

        # 4. 計算整份考卷總時數
        # 這裡用去重複的方式算總時數，比較精準
        unique_units = df[['單元名稱', '單元總節數']].drop_duplicates()
        total_course_hours = unique_units['單元總節數'].sum()
        if total_course_hours == 0: total_course_hours = 1

        # 5. 算出百分比配分
        df['原始配分'] = (df['目標權重(時數)'] / total_course_hours) * 100
        df['預計配分'] = df['原始配分'].apply(lambda x: round(x, 1))

        # 6. 100分校正 (補差額給最後一項)
        current_sum = df['預計配分'].sum()
        diff = 100 - current_sum
        if abs(diff) > 0.01:
            df.iloc[-1, df.columns.get_loc('預計配分')] += diff

        return df
    except Exception as e:
        st.error(f"算分邏輯錯誤: {e}")
        return df

# --- 3. Excel 下載器 ---
def df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        export_df = df.copy()
        
        # 整理欄位顯示順序
        cols = ['單元名稱', '單元總節數', '學習目標', '目標權重(時數)', '預計配分']
        final_cols = [c for c in cols if c in export_df.columns]
        export_df = export_df[final_cols]
        export_df.rename(columns={'目標權重(時數)': '此目標佔用節數'}, inplace=True)
        
        export_df.to_excel(writer, index=False, sheet_name='審核表')
        
        # 美化格式
        workbook = writer.book
        worksheet = writer.sheets['審核表']
        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#DCE6F1', 'border': 1})
        text_fmt = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        num_fmt = workbook.add_format({'num_format': '0.0', 'border': 1, 'align': 'center'})
        
        worksheet.set_column('A:A', 15, text_fmt)
        worksheet.set_column('B:B', 12, num_fmt)
        worksheet.set_column('C:C', 60, text_fmt) # 目標欄位加寬
        worksheet.set_column('D:E', 12, num_fmt)
        
        for i, col in enumerate(export_df.columns):
            worksheet.write(0, i, col, header_fmt)
            
    return output.getvalue()

# --- 4. Prompt: 強制拆解與抓時數 ---
GEM_EXTRACT_PROMPT = """
你是一個精準的教材分析師。請閱讀提供的教材，提取「單元名稱」、「學習目標」與「單元總授課節數」。

**任務 1：抓取授課節數 (Teaching Hours)**
- 請在文中搜尋代表時間的關鍵字，如「5節」、「六堂課」、「40分鐘 x 3」等。
- 將該單元的**總節數**填入表格。
- 若找不到，請根據單元內容份量推估 (填入 1~5 的數字)。

**任務 2：拆解學習目標 (Explode Rows)**
- 看到編號 (1. 2. 3...) 或列表符號 (●, -)，**必須將每一個目標拆成獨立的一列 (Row)**。
- 範例：若單元有 3 個重點，請輸出 3 列，這 3 列的「單元名稱」與「授課節數」都相同。
- **嚴禁合併**。

**輸出格式 (Markdown 表格)**
欄位：| 單元名稱 | 學習目標 | 授課節數 |
"""

# --- 5. 主程式 ---
st.set_page_config(page_title="內湖國小 AI 命題系統 (Hard Read)", layout="wide")

st.markdown("""<div style="background:#1E293B;padding:15px;text-align:center;color:white;border-radius:10px;">
<h2>內湖國小 AI 命題系統 (Hard Read 版)</h2></div>""", unsafe_allow_html=True)

if "extracted_data" not in st.session_state: st.session_state.extracted_data = None
if "step" not in st.session_state: st.session_state.step = 1

with st.sidebar:
    st.header("設定")
    api_key = st.text_input("Google API Key", type="password")
    
    # 支援度檢查
    st.divider()
    if HAS_DOCX: st.caption("✅ DOCX 模組正常")
    else: st.error("❌ 缺 python-docx (無法讀 Word)")
    
    if st.button("🔄 重置"): 
        st.session_state.extracted_data = None
        st.session_state.step = 1
        st.rerun()

# Step 1: 上傳
if st.session_state.step == 1:
    st.info("💡 支援 PDF (最強，可讀掃描檔)、Word、PPT。請直接上傳，AI 會想辦法硬讀。")
    uploaded_files = st.file_uploader("選擇教材檔案", type=["pdf", "docx", "pptx", "txt"], accept_multiple_files=True)
    
    if st.button("🚀 開始分析 & 自動配分", type="primary", use_container_width=True):
        if api_key and uploaded_files:
            with st.spinner("AI 正在暴力讀取與拆解資料..."):
                all_data = []
                # 處理多個檔案
                for file in uploaded_files:
                    try:
                        # 1. 決定讀取策略
                        mode, payload = process_file_for_ai(file, api_key)
                        
                        if mode == "error":
                            st.warning(f"跳過檔案 {file.name}: {payload}")
                            continue

                        # 2. 呼叫 Gemini (使用 Flash 模型省錢又快)
                        model = genai.GenerativeModel("models/gemini-1.5-flash")
                        
                        if mode == "file_mode":
                            # 視覺模式 (PDF)
                            response = model.generate_content([GEM_EXTRACT_PROMPT, payload])
                        else:
                            # 文字模式 (DOCX/PPTX)
                            response = model.generate_content(GEM_EXTRACT_PROMPT + f"\n\n教材內容：\n{payload}")

                        # 3. 解析回應
                        lines = [l.strip() for l in response.text.split('\n') if "|" in l and "---" not in l]
                        for l in lines:
                            row = [c.strip() for c in l.split('|') if c.strip()]
                            if len(row) >= 3: all_data.append(row[:3])
                            
                    except Exception as e:
                        st.error(f"處理 {file.name} 時發生錯誤: {e}")

                if all_data:
                    # 轉成 DataFrame
                    df = pd.DataFrame(all_data[1:], columns=["單元名稱", "學習目標", "授課節數"]) # 假設第一筆是標題，若不是會被濾掉，這裡簡單處理
                    # 如果第一筆真的是標題 (含有 '單元' 字樣)，則移除
                    if "單元" in df.iloc[0,0]: 
                        df = df.iloc[1:].reset_index(drop=True)
                    
                    df.rename(columns={"授課節數": "單元總節數"}, inplace=True)
                    
                    # 進入算分
                    df_cal = calculate_scores(df)
                    st.session_state.extracted_data = df_cal
                    st.session_state.step = 2
                    st.rerun()
                else:
                    st.error("AI 讀不到任何表格資料。請確認檔案內容。")

# Step 2: 結果確認
elif st.session_state.step == 2:
    st.success("✅ 資料提取成功！配分已自動計算。")
    st.markdown("請檢查 **「單元總節數」** 是否正確。若 AI 抓錯 (例如抓成 1)，請手動修改，配分會立刻重算。")
    
    df_curr = st.session_state.extracted_data
    
    # 編輯器
    edited_df = st.data_editor(
        df_curr,
        column_config={
            "單元名稱": st.column_config.TextColumn(disabled=True),
            "學習目標": st.column_config.TextColumn(width="large"),
            "單元總節數": st.column_config.NumberColumn("單元總節數", min_value=1, max_value=50, help="修改此處，配分自動更新"),
            "目標權重(時數)": st.column_config.NumberColumn("此目標佔用", disabled=True, format="%.2f"),
            "預計配分": st.column_config.NumberColumn("配分 (%)", disabled=True)
        },
        use_container_width=True,
        num_rows="dynamic"
    )
    
    # 即時重算
    if not edited_df.equals(df_curr):
        st.session_state.extracted_data = calculate_scores(edited_df)
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 下載審核表 (Excel)", df_to_excel(edited_df), "審核表.xlsx", use_container_width=True)
    with col2:
        if st.button("⬅️ 重新上傳", use_container_width=True): 
            st.session_state.step=1
            st.rerun()
