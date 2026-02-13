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
import re # 新增：用於文字清洗

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
                with open("temp.doc", "wb") as f: f.write(file.getbuffer())
                result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
                if result.returncode == 0:
                    file_text = result.stdout
                if os.path.exists("temp.doc"): os.remove("temp.doc")
            
            # --- 文字清洗區 ---
            # 1. 移除連續多餘的空行，縮減 Token
            file_text = re.sub(r'\n\s*\n', '\n\n', file_text)
            text_content += f"\n\n=== 檔案: {file.name} ===\n{file_text}"
            
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name} - {str(e)}]"
            
    return text_content

# --- 3. 核心 Gem 命題鐵律 (Phase 1 專用：審核表生成) ---
# 這裡稍微修改，教導 AI 如何「分配分數」
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

# --- 4. 智能模型選擇與重試機制 ---
def get_best_model(api_key, mode="fast"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None, "找不到可用模型"
        target_model = None
        # 優先選擇 flash 模型以求快速與長文本處理能力
        if mode == "fast":
            for m in models:
                if 'flash' in m.lower(): target_model = m; break
            if not target_model: target_model = models[0]
        # 這裡保留 smart 邏輯給第二階段用
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
                wait_time = (i + 1) * 3
                st.toast(f"⏳ 伺服器忙碌，休息 {wait_time} 秒後再試...", icon="☕")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("連線逾時，請檢查 API Key 或網路狀態。")

# --- 5. 網頁介面配置 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

# (保留原本的 CSS 樣式)
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

# 狀態管理
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
                    # 1. 準備 API
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="fast")
                    
                    if error_msg:
                        st.error(f"❌ API 連線錯誤：{error_msg}")
                    else:
                        # 2. 讀取並清洗檔案
                        content = extract_text_from_files(uploaded_files)
                        
                        try:
                            st.toast(f"⚡ 啟動 AI 引擎 ({model_name}) 分析中...", icon="🤖")
                            
                            # 3. 設定 Phase 1 專用模型
                            model_fast = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=GEM_INSTRUCTIONS_PHASE1, 
                                generation_config={"temperature": 0.0} # 溫度 0 確保格式最穩定
                            )
                            
                            chat = model_fast.start_chat(history=[])
                            
                            with st.chat_message("ai"):
                                message_placeholder = st.empty()
                                full_response = ""
                                t_str = "、".join(selected_types)
                                
                                # 4. 構建精準 Prompt
                                prompt_content = f"""
                                任務：分析以下教材並產出審核表。
                                
                                【參數設定】
                                年級：{grade}
                                科目：{subject}
                                可用題型：{t_str}
                                
                                【教材內容】
                                {content}
                                
                                【執行步驟】
                                1. 識別教材中的單元結構。
                                2. 提取具體的學習目標（Key Learning Points）。
                                3. 根據內容長度，計算該單元應佔總分 100 分中的多少比例。
                                4. 僅輸出 Markdown 表格。
                                """
                                st.session_state.last_prompt_content = prompt_content
                                
                                # 5. 串流輸出
                                response = generate_with_retry(chat, prompt_content, stream=True)
                                
                                for chunk in response:
                                    if chunk.text:
                                        full_response += chunk.text
                                        message_placeholder.markdown(full_response + "▌")
                                message_placeholder.markdown(full_response)
                            
                            # 6. 狀態保存與換頁
                            # 簡單防呆：確保有產出表格
                            if "|" in full_response and "單元" in full_response:
                                st.session_state.chat_history.append({"role": "model", "content": full_response})
                                st.session_state.phase = 2
                                time.sleep(1) # 稍微緩衝讓使用者看清結果
                                st.rerun()
                            else:
                                st.error("❌ AI 產出格式異常，未偵測到表格，請檢查教材檔案是否清晰。")
                                
                        except Exception as e: 
                            st.error(f"連線失敗：{e} (請檢查 API Key 或稍後重試)")

# --- Phase 2: 這裡先留白或顯示簡單訊息，等待你下一步指令 ---
elif st.session_state.phase == 2:
    st.info("✅ 第一階段完成！審核表已生成 (Phase 2 待續...)")
    current_md = st.session_state.chat_history[0]["content"]
    st.markdown(current_md)
    
    if st.button("⬅️ 返回重來"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.rerun()

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
