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

# --- 1. 定義學科與題型映射 ---
SUBJECT_Q_TYPES = {
    "國語": ["國字注音", "造句", "單選題", "閱讀素養題", "句型變換", "簡答題"],
    "數學": ["應用計算題", "圖表分析題", "填充題", "單選題", "是非題"],
    "自然科學": ["實驗判讀題", "圖表分析題", "單選題", "是非題", "填充題", "配合題"],
    "社會": ["地圖判讀題", "情境案例分析", "單選題", "是非題", "配合題", "簡答題"],
    "英語": ["英語會話選擇", "詞彙搭配", "文意選填", "單選題", "閱讀理解"],
    "": ["單選題", "是非題", "填充題", "簡答題"]
}

# --- 2. 檔案讀取工具 ---
def read_pdf(file):
    pdf_reader = PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_doc(file):
    with open("temp.doc", "wb") as f: f.write(file.getbuffer())
    try:
        result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else "[讀取失敗]"
    except: return "[組件未就緒]"
    finally:
        if os.path.exists("temp.doc"): os.remove("temp.doc")

# --- 3. Excel 下載工具 ---
def md_to_excel(md_text):
    try:
        lines = [l for l in md_text.strip().split('\n') if l.startswith('|')]
        if len(lines) < 3: return None
        headers = [c.strip() for c in lines[0].split('|') if c.strip()]
        data = [[c.strip() for c in l.split('|') if c.strip()] for l in lines[2:]]
        df = pd.DataFrame(data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        return output.getvalue()
    except: return None

# --- 4. 核心 Gem 命題鐵律 ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
1. **科目守門員**：若教材與科目明顯不符，僅回覆：『ERROR_SUBJECT_MISMATCH』。
2. **目標對應**：學習目標必須原文採自教材。每一條目標在整份試卷中至少出現一次。
3. **分階段輸出**：Phase 1 審核表，Phase 2 試卷與答案。
"""

# --- 5. 智能模型選擇器 ---
def get_best_model(api_key, mode="fast"):
    genai.configure(api_key=api_key)
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        if not models: return None, "找不到可用模型"
        target_model = None
        if mode == "fast":
            for m in models:
                if 'flash' in m.lower(): target_model = m; break
            if not target_model:
                for m in models:
                    if 'gemini-pro' in m.lower() and 'vision' not in m.lower(): target_model = m; break
        elif mode == "smart":
            for m in models:
                if 'pro' in m.lower() and '1.5' in m.lower(): target_model = m; break
            if not target_model:
                for m in models:
                    if 'pro' in m.lower(): target_model = m; break
        if not target_model: target_model = models[0]
        return target_model, None
    except Exception as e: return None, str(e)

# --- 6. 網頁介面視覺設計 ---
st.set_page_config(page_title="內湖國小 AI 輔助出題系統", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0F172A; }
    .block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 5rem; }
    
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 30px; border-radius: 20px; text-align: center; margin-bottom: 30px; 
        border: 1px solid #475569;
    }
    .school-name { font-size: 28px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 16px; color: #94A3B8; margin-top: 8px; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #E2E8F0 !important; }
    
    .step-box {
        background-color: #1E293B; padding: 12px; border-radius: 10px; 
        margin-bottom: 12px; border-left: 5px solid #3B82F6; font-size: 13px;
        color: #CBD5E1;
    }
    .step-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    .step-box a:hover { text-decoration: underline; }
    
    /* 按鈕樣式調整 */
    [data-testid="stSidebar"] .stButton > button { 
        display: block; margin: 0 auto !important; 
        width: 100%; border-radius: 8px;
    }
    
    .footer { position: fixed; left: 0; bottom: 0; width: 100%; background-color: #0F172A; color: #475569; text-align: center; padding: 15px; font-size: 11px; border-top: 1px solid #1E293B; z-index: 100; }
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

# --- Sidebar: 詳細引導 ---
with st.sidebar:
    st.markdown("### 🖥️ 快速開始指南")
    # 修正登入說明：建議使用個人帳號
    st.markdown("""
    <div class="step-box">
        <b>Step 1. 前往官網</b><br>
        🔗 <a href="https://aistudio.google.com/" target="_blank">Google AI Studio (點我)</a>
    </div>
    <div class="step-box">
        <b>Step 2. 登入帳號</b><br>
        👤 <b>建議使用個人 Google 帳號</b><br>(教育帳號權限可能受限)
    </div>
    <div class="step-box">
        <b>Step 3. 取得金鑰</b><br>
        🆕 點擊 <b>"Get API key"</b> 並複製
    </div>
    <div class="step-box">
        <b>Step 4. 啟用系統</b><br>
        📋 貼到下方框內即可開始
    </div>
    """, unsafe_allow_html=True)
    
    api_input = st.text_area("在此輸入 API Key", height=70, placeholder="必填欄位")
    st.divider()
    
    # --- 重置按鈕上移至此 ---
    if st.button("🔄 重置系統進度"):
        st.session_state.phase = 1
        st.session_state.chat_history = []
        st.session_state.last_prompt_content = ""
        st.rerun()
        
    st.divider()
    
    st.markdown("### 📂 資源快速連結")
    st.markdown("""
    <div class="step-box">
        <b>📖 教材資源下載</b><br>
        - <a href="https://webetextbook.knsh.com.tw/" target="_blank">康軒電子書</a><br>
        - <a href="https://edisc3.hle.com.tw/" target="_blank">翰林行動大師</a><br>
        - <a href="https://reader.nani.com.tw/" target="_blank">南一 OneBox</a>
    </div>
    <div class="step-box">
        <b>🏛️ 官方參考資料</b><br>
        - <a href="https://cirn.moe.edu.tw/Syllabus/index.aspx?sid=1108" target="_blank">108 課綱資源網 (CIRN)</a><br>
        - <a href="https://www.nhps.hc.edu.tw/" target="_blank">內湖國小校網</a>
    </div>
    """, unsafe_allow_html=True)

# --- Phase 1: 規劃審核表 (使用快速模型) ---
if st.session_state.phase == 1:
    with st.container(border=True):
        st.markdown("### 📍 第一階段：參數設定與學習目標規劃")
        
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
        uploaded_files = st.file_uploader("5. 上傳教材檔案", type=["pdf", "docx", "doc"], accept_multiple_files=True)
        
        if st.button("🚀 產出學習目標審核表", type="primary", use_container_width=True):
            if not api_input:
                st.error("❌ 動作中止：尚未輸入 API Key。")
            elif not grade or not subject or not uploaded_files or not selected_types:
                st.warning("⚠️ 動作中止：請確認年級、科目、題型與教材已備妥。")
            else:
                # 動畫效果：顯示 Spinner
                with st.spinner("⚡ 正在極速掃描教材內容，請稍候..."):
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="fast")
                    
                    if error_msg:
                        st.error(f"❌ API 連線錯誤：{error_msg}")
                    else:
                        content = ""
                        for f in uploaded_files:
                            ext = f.name.split('.')[-1].lower()
                            if ext == 'pdf': content += read_pdf(f)
                            elif ext == 'docx': content += read_docx(f)
                            elif ext == 'doc': content += read_doc(f)
                        
                        try:
                            # 顯示 Toast 通知
                            st.toast(f"⚡ 啟動 AI 引擎 ({model_name}) 分析中...", icon="🤖")
                            
                            model_fast = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=GEM_INSTRUCTIONS, 
                                generation_config={"temperature": 0.0}
                            )
                            
                            chat = model_fast.start_chat(history=[])
                            
                            with st.chat_message("ai"):
                                message_placeholder = st.empty()
                                full_response = ""
                                t_str = "、".join(selected_types)
                                prompt_content = f"年級：{grade}, 科目：{subject}\n題型：{t_str}\n教材內容：\n{content}"
                                st.session_state.last_prompt_content = prompt_content
                                
                                response = chat.send_message(prompt_content, stream=True)
                                
                                for chunk in response:
                                    full_response += chunk.text
                                    message_placeholder.markdown(full_response + "▌")
                                message_placeholder.markdown(full_response)
                            
                            if "ERROR_SUBJECT_MISMATCH" in full_response:
                                st.error(f"❌ 防呆啟動：教材內容與『{subject}』不符，請重新確認檔案。")
                            else:
                                st.session_state.chat_history.append({"role": "model", "content": full_response})
                                st.session_state.phase = 2
                                st.rerun()
                        except Exception as e: st.error(f"連線失敗：{e}")

# --- Phase 2: 正式出題 (使用強力模型) ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    
    with st.container(border=True):
        st.markdown("### 📥 第二階段：下載審核表")
        with st.chat_message("ai"): st.markdown(current_md)
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button(label="📥 匯出此審核表 (Excel)", data=excel_data, file_name=f"內湖國小_{subject}_審核表.xlsx", use_container_width=True)

    st.divider()
    with st.container(border=True):
        st.markdown("### 📝 第三階段：試卷正式生成")
        
        cb1, cb2 = st.columns(2)
        with cb1:
            if st.button("✅ 審核表確認無誤，開始出題", type="primary", use_container_width=True):
                # 動畫效果：Phase 2 載入動畫
                with st.spinner("🧠 正在進行深度推理命題，請稍候..."):
                    keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                    target_key = random.choice(keys)
                    model_name, error_msg = get_best_model(target_key, mode="smart")
                    
                    if error_msg:
                         st.error(f"❌ 無法啟動高階模型：{error_msg}")
                    else:
                        st.toast(f"🧠 切換至深度思考模式 ({model_name})...", icon="💡")
                        
                        try:
                            model_smart = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=GEM_INSTRUCTIONS,
                                generation_config={"temperature": 0.2}
                            )
                            
                            with st.chat_message("ai"):
                                message_placeholder = st.empty()
                                full_response = ""
                                final_prompt = f"""
                                {st.session_state.last_prompt_content}
                                ---
                                審核表參考：
                                {current_md}
                                
                                請正式產出【試題】與【參考答案卷】。
                                """
                                response = model_smart.generate_content(final_prompt, stream=True)
                                for chunk in response:
                                    full_response += chunk.text
                                    message_placeholder.markdown(full_response + "▌")
                                message_placeholder.markdown(full_response)
                            
                            st.session_state.chat_history.append({"role": "model", "content": full_response})
                        except Exception as e: st.error(f"命題失敗：{e}")

        with cb2:
            if st.button("⬅️ 返回修改參數", use_container_width=True):
                st.session_state.phase = 1
                st.session_state.chat_history = []
                st.rerun()
    
    # 顯示出題歷史
    if len(st.session_state.chat_history) > 1:
        # Phase 2 已經在上方顯示，這邊主要處理後續微調
        pass 

    # 微調對話框
    if len(st.session_state.chat_history) > 0:
        if prompt := st.chat_input("對題目不滿意？請輸入指令微調 (如：第3題太難請換一題)"):
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.spinner("🔧 AI 正在修改試題..."):
                keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                genai.configure(api_key=random.choice(keys))
                model_pro = genai.GenerativeModel("gemini-1.5-pro", system_instruction=GEM_INSTRUCTIONS)
                
                # 建立臨時對話歷史
                history_for_chat = []
                history_for_chat.append({"role": "user", "parts": [st.session_state.last_prompt_content]})
                history_for_chat.append({"role": "model", "parts": [current_md]})
                if len(st.session_state.chat_history) > 1:
                     history_for_chat.append({"role": "model", "parts": [st.session_state.chat_history[-1]["content"]]})
                
                chat_pro = model_pro.start_chat(history=history_for_chat)
                
                with st.chat_message("ai"):
                    message_placeholder = st.empty()
                    full_response = ""
                    response = chat_pro.send_message(prompt, stream=True)
                    for chunk in response:
                        full_response += chunk.text
                        message_placeholder.markdown(full_response + "▌")
                    message_placeholder.markdown(full_response)
                
                st.session_state.chat_history.append({"role": "model", "content": full_response})

st.markdown('<div class="footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
