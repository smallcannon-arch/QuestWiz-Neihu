import subprocess
import sys
import os
import re

# --- 0. 自動安裝依賴套件 (Auto-Install) ---
# 這段程式碼會自動檢查並安裝缺少的套件，防止執行失敗
def install_package(package):
    try:
        __import__(package)
    except ImportError:
        print(f"📦 正在自動安裝 {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# 檢查清單
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

# --- 1. 定義學科與題型映射 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 2. 檔案讀取工具 (強化版：分頁+清洗) ---
@st.cache_data
def extract_text_from_files(files):
    text_content = ""
    for file in files:
        try:
            file_text = ""
            ext = file.name.split('.')[-1].lower()
            
            if ext == 'pdf':
                pdf_reader = PdfReader(file)
                # 加上頁碼標記，幫助 AI 區分單元邊界
                for i, page in enumerate(pdf_reader.pages):
                    content = page.extract_text() or ""
                    file_text += f"\n--- Page {i+1} ---\n{content}"
            elif ext == 'docx':
                doc = Document(file)
                # 保留段落結構
                file_text = "\n".join([p.text for p in doc.paragraphs])
            elif ext == 'doc':
                # 嘗試處理舊版 Word，若失敗則忽略
                try:
                    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
                    result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
                    if result.returncode == 0:
                        file_text = result.stdout
                    if os.path.exists("temp.doc"): os.remove("temp.doc")
                except:
                    file_text = "[舊版 .doc 讀取失敗，請轉存為 .docx]"
            
            # --- 文字清洗區 ---
            # 移除連續多餘的空行，節省 Token
            file_text = re.sub(r'\n\s*\n', '\n\n', file_text)
            text_content += f"\n\n=== 檔案: {file.name} ===\n{file_text}"
            
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name} - {str(e)}]"
            
    return text_content

# --- 3. Excel 下載工具 (含：抗沾黏 + 分數自動校正 + 美化) ---
def md_to_excel(md_text):
    try:
        # Step 1: 預處理 - 修復 AI 可能的格式錯誤
        cleaned_text = md_text.replace("||", "|\n|")
        
        lines = cleaned_text.strip().split('\n')
        table_lines = []
        is_table_started = False
        
        # Step 2: 抓取表格內容
        for line in lines:
            if ("單元" in line or "目標" in line or "配分" in line) and "|" in line:
                is_table_started = True
                table_lines.append(line)
                continue
            
            if is_table_started:
                if "---" in line: continue
                if "|" in line:
                    table_lines.append(line)
                
        if not table_lines: return None

        # Step 3: 資料解析
        data = []
        for line in table_lines:
            row = [cell.strip() for cell in line.strip('|').split('|')]
            data.append(row)

        if len(data) < 2: return None

        headers = data[0]
        rows = data[1:]
        
        # Step 4: 強力補齊與切削
        max_cols = len(headers)
        cleaned_rows = []
        for r in rows:
            if len(r) == max_cols:
                cleaned_rows.append(r)
            elif len(r) < max_cols:
                cleaned_rows.append(r + [''] * (max_cols - len(r)))
            else:
                cleaned_rows.append(r[:max_cols])

        df = pd.DataFrame(cleaned_rows, columns=headers)
        
        # --- 🔥 分數自動校正 (Normalization) ---
        score_col = None
        for col in df.columns:
            if "配分" in col:
                score_col = col
                break
        
        if score_col:
            try:
                # 提取數字
                scores = []
                for x in df[score_col]:
                    nums = re.findall(r'\d+', str(x))
                    scores.append(float(nums[0]) if nums else 0.0)
                
                current_total = sum(scores)
                
                # 如果總分不是 100，且大於 0，進行校正
                if current_total > 0 and current_total != 100:
                    st.toast(f"⚖️ 系統自動校正：將原始總分 {int(current_total)} 分依比例調整為 100 分。", icon="✅")
                    
                    new_scores = [(s / current_total) * 100 for s in scores]
                    rounded_scores = [round(s) for s in new_scores]
                    
                    # 處理四捨五入誤差，將差額補在分數最高的那項
                    diff = 100 - sum(rounded_scores)
                    if diff != 0:
                        max_idx = rounded_scores.index(max(rounded_scores))
                        rounded_scores[max_idx] += diff
                    
                    df[score_col] = rounded_scores
            except:
                pass # 若校正失敗則維持原樣
        # ------------------------------------

        # Step 5: 使用 XlsxWriter 引擎進行美化
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='學習目標審核表')
            workbook = writer.book
            worksheet = writer.sheets['學習目標審核表']
            
            wrap_format = workbook.add_format({'text_wrap': True, 'valign': 'vcenter'})
            header_format = workbook.add_format({
                'bold': True, 'text_wrap': True, 'valign': 'vcenter', 
                'fg_color': '#D7E4BC', 'border': 1
            })

            # 設定標題列格式
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # 設定欄寬
            worksheet.set_column(0, 0, 15, wrap_format) # 單元
            worksheet.set_column(1, 1, 55, wrap_format) # 學習目標 (最寬)
            worksheet.set_column(2, 2, 20, wrap_format) # 題型
            worksheet.set_column(3, 3, 10, wrap_format) # 配分
                
        return output.getvalue()
    except Exception as e:
        print(f"Excel 轉換失敗: {e}")
        return None

# --- 4. 核心 Gem 命題鐵律 (Phase 1 專用) ---
GEM_INSTRUCTIONS_PHASE1 = """
你是「國小專業定期評量命題 AI」。

### ⚠️ Phase 1 任務目標：
請閱讀使用者提供的教材內容，整理出一份【學習目標審核表】。

### 絕對規則 (違反將導致系統崩潰)：
1. **配分邏輯**：請根據各單元內容的「篇幅長度」與「重要性」，將總分分配為 **剛好 100 分**。
2. **禁止廢話**：**嚴禁** 撰寫前言 (如 "好的，這是我整理的...") 或結語。
3. **禁止出題**：現在還不是出題階段，**嚴禁** 產出題目。
4. **格式要求**：
   - 僅輸出標準 Markdown 表格。
   - 欄位必須包含：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
   - **每一列資料必須強制換行**，不可接在同一行。
"""

# --- 5. 智能模型與工具 ---
def get_best_model(api_key, mode="fast"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None, "找不到可用模型"
        target_model = None
        if mode == "fast":
            for m in models:
                if 'flash' in m.lower(): target_model = m; break
            if not target_model: target_model = models[0]
        elif mode == "smart":
            for m in models:
                if 'pro' in m.lower() and '1.5' in m.lower(): target_model = m; break
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
            if "429" in str(e):
                time.sleep((i + 1) * 3)
            else:
                raise e
    raise Exception("連線逾時，請檢查 API Key 或網路狀態。")

# --- 6. 介面設定 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
    footer { display: none !important; visibility: hidden !important; }
    .stApp { background-color: #0F172A; }
    .block-container { max-width: 1200px; padding-top: 1.5rem !important; padding-bottom: 5rem; }
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 25px; border-radius: 18px; text-align: center; margin-bottom: 25px; 
        border: 1px solid #475569;
    }
    .school-name { font-size: 26px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 15px; color: #94A3B8; margin-top: 6px; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #E2E8F0 !important; }
    .comfort-box {
        background-color: #1E293B; padding: 15px; border-radius: 10px; 
        margin-bottom: 15px; border-left: 5px solid #3B82F6; 
        font-size: 14px; color: #CBD5E1; line-height: 1.8;
    }
    .comfort-box b { color: #fff; }
    .comfort-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    [data-testid="stSidebar"] .stMarkdown { margin-bottom: 10px; } 
    .stTextArea textarea { min-height: 80px; }
    .stTextArea { margin-bottom: 15px !important; }
    [data-testid="stSidebar"] .stButton > button { 
        display: block; margin: 15px auto !important; 
        width: 100%; border-radius: 8px; height: 42px;
        background-color: #334155; border: 1px solid #475569; font-size: 15px;
    }
    .custom-footer { 
        position: fixed; left: 0; bottom: 0; width: 100%; 
        background-color: #0F172A; color: #475569; 
        text-align: center; padding: 12px; font-size: 11px; 
        border-top: 1px solid #1E293B; z-index: 100; 
    }
    </style>
    <div class="school-header">
        <div class="school-name">新竹市香山區內湖國小</div>
        <div class="app-title">評量命題與學習目標自動化系統</div>
    </div>
    """, unsafe_allow_html=True)

if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_prompt_content" not in st.session_state: st.session_state.last_prompt_content = ""

# --- Sidebar ---
with st.sidebar:
    st.markdown("### 🚀 系統設定")
    api_input = st.text_area("在此輸入 API Key", height=80, placeholder="請貼上 Google AI Studio 金鑰...")
    
    if st.button("🔄 重置系統"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.session_state.last_prompt_content = ""
        st.rerun()

    st.markdown("### 📚 資源連結")
    st.markdown("""
    <div class="comfort-box">
        <b>教材下載：</b><br>
        • <a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒電子書</a><br>
        • <a href="https://edisc3.hle.com.tw/" target="_blank">翰林行動大師</a><br>
        • <a href="https://reader.nani.com.tw/" target="_blank">南一 OneBox</a>
    </div>
    """, unsafe_allow_html=True)

# --- Phase 1: 參數設定與教材上傳 ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與教材上傳")
        
        c1, c2, c3 = st.columns(3)
        with c1: grade = st.selectbox("1. 選擇年級", ["", "一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=0)
        with c2: subject = st.selectbox("2. 選擇科目", ["", "國語", "數學", "自然科學", "社會", "英語"], index=0)
        with c3: mode = st.selectbox("3. 命題模式", ["🟢 模式 A：適中", "🔴 模式 B：困難", "🌟 模式 C：素養"], index=0)
        
        st.divider()
        st.markdown("**4. 勾選欲產出的題型**")
        available_types = SUBJECT_Q_TYPES.get(subject, SUBJECT_Q_TYPES[""])
        cols = st.columns(min(len(available_types), 4))
        selected_types = []
        for i, t in enumerate(available_types):
            if cols[i % len(cols)].checkbox(t, value=True):
                selected_types.append(t)
        
        st.divider()
        uploaded_files = st.file_uploader("5. 上傳教材檔案 (Word/PDF)", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            if not api_input:
                st.error("❌ 動作中止：側邊欄尚未輸入 API Key。")
            elif not grade or not subject or not uploaded_files or not selected_types:
                st.warning("⚠️ 動作中止：請確認年級、科目、題型與教材已備妥。")
            else:
                with st.spinner("⚡ 正在極速掃描教材內容，請稍候..."):
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="fast")
                    
                    if error_msg:
                        st.error(f"❌ API 連線錯誤：{error_msg}")
                    else:
                        content = extract_text_from_files(uploaded_files)
                        try:
                            st.toast(f"⚡ 啟動 AI 引擎 ({model_name}) 分析中...", icon="🤖")
                            
                            model_fast = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=GEM_INSTRUCTIONS_PHASE1, 
                                generation_config={"temperature": 0.0}
                            )
                            
                            chat = model_fast.start_chat(history=[])
                            
                            with st.chat_message("ai"):
                                message_placeholder = st.empty()
                                full_response = ""
                                t_str = "、".join(selected_types)
                                
                                prompt_content = f"""
                                任務：分析以下教材並產出審核表。
                                【參數設定】年級：{grade}, 科目：{subject}, 可用題型：{t_str}
                                【教材內容】{content}
                                【執行步驟】
                                1. 識別教材中的單元結構。
                                2. 提取具體的學習目標。
                                3. 根據內容長度，計算該單元應佔總分 100 分中的多少比例。
                                4. 僅輸出 Markdown 表格。
                                """
                                st.session_state.last_prompt_content = prompt_content
                                response = generate_with_retry(chat, prompt_content, stream=True)
                                
                                for chunk in response:
                                    if chunk.text:
                                        full_response += chunk.text
                                        message_placeholder.markdown(full_response + "▌")
                                message_placeholder.markdown(full_response)
                            
                            # 簡單防呆
                            if "|" in full_response and "單元" in full_response:
                                st.session_state.chat_history.append({"role": "model", "content": full_response})
                                st.session_state.phase = 2
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ AI 產出格式異常，未偵測到表格，請重試。")
                                
                        except Exception as e: 
                            st.error(f"連線失敗：{e} (請檢查 API Key 或稍後重試)")

# --- Phase 2: 下載與確認 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    
    with st.container(border=True):
        st.markdown("### 📥 第二階段：下載審核表")
        st.info("請下載 Excel 表格，確認配分與學習目標是否正確。確認無誤後請點擊下方按鈕進入出題階段。")
        
        with st.expander("👁️ 預覽 AI 產出的表格內容", expanded=False):
            st.markdown(current_md)
        
        # Excel 轉換 (包含自動配分校正)
        excel_data = md_to_excel(current_md)
        
        c1, c2 = st.columns([1, 1])
        with c1:
            if excel_data:
                st.download_button(
                    label="📥 下載 Excel 審核表 (.xlsx)",
                    data=excel_data,
                    file_name=f"內湖國小_{st.session_state.get('subject', '科目')}_審核表.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.warning("⚠️ 表格轉換失敗")
        
        with c2:
             if st.button("⬅️ 返回重來 (清除資料)", use_container_width=True):
                st.session_state.phase = 1
                st.session_state.chat_history = []
                st.rerun()

    st.divider()
    
    if st.button("✅ 審核無誤，開始正式命題 (Phase 3)", type="primary", use_container_width=True):
        st.toast("🚀 進入 Phase 3... (功能開發中)", icon="🚧")
        # 未來功能：
        # st.session_state.phase = 3
        # st.rerun()

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
