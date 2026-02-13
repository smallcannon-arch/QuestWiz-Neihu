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

# --- 2. 檔案讀取工具 (加入快取優化 🚀) ---
# 透過 @st.cache_data，讓程式記住讀過的檔案，不用每次都重讀
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
                # .doc 處理較複雜，通常不快取或需特殊處理，這裡維持原樣
                with open("temp.doc", "wb") as f: f.write(file.getbuffer())
                result = subprocess.run(['antiword', 'temp.doc'], capture_output=True, text=True)
                if result.returncode == 0:
                    text_content += result.stdout
                if os.path.exists("temp.doc"): os.remove("temp.doc")
        except Exception as e:
            text_content += f"\n[讀取錯誤: {file.name}]"
    return text_content

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

# --- 4. 核心 Gem 命題鐵律 (優化指令：減少廢話) ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。
1. **科目守門員**：若教材與科目明顯不符，僅回覆：『ERROR_SUBJECT_MISMATCH』。
2. **目標對應**：學習目標必須原文採自教材。每一條目標在整份試卷中至少出現一次。
3. **直接輸出**：請直接產出表格或試題，不要有任何開場白（如「好的，這是...」）或結尾語，以節省生成時間。
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
    .block-container { max-width: 1200px; padding-top: 1rem; padding-bottom: 5rem; }
    
    .school-header {
        background: linear-gradient(90deg, #1E293B 0%, #334155 100%);
        padding: 25px; border-radius: 18px; text-align: center; margin-bottom: 25px; 
        border: 1px solid #475569;
    }
    .school-name { font-size: 26px; font-weight: 700; color: #F1F5F9; letter-spacing: 3px; }
    .app-title { font-size: 15px; color: #94A3B8; margin-top: 6px; }
    h1, h2, h3, p, span, label, .stMarkdown { color: #E2E8F0 !important; }
    
    /* 舒適型卡片 (間距拉寬優化) */
    .comfort-box {
        background-color: #1E293B; 
        padding: 15px;               /* 增加內距 */
        border-radius: 10px; 
        margin-bottom: 15px;         /* 增加卡片間距 */
        border-left: 5px solid #3B82F6; 
        font-size: 14px;             /* 字體稍微加大 */
        color: #CBD5E1; 
        line-height: 1.8;            /* 行高增加，閱讀不擁擠 */
    }
    .comfort-box b { color: #fff; }
    .comfort-box a { color: #60A5FA !important; text-decoration: none; font-weight: bold; }
    .comfort-box a:hover { text-decoration: underline; }
    .comfort-box ul { margin: 0; padding-left: 1.2rem; }
    .comfort-box li { margin-bottom: 5px; } /* 列表項目間距 */

    /* 側邊欄元件舒適化 */
    [data-testid="stSidebar"] .stMarkdown { margin-bottom: 10px; } 
    .stTextArea textarea { min-height: 80px; } /* 輸入框拉高 */
    .stTextArea { margin-bottom: 15px !important; }
    [data-testid="stSidebar"] .stButton > button { 
        display: block; margin: 15px auto !important; /* 按鈕上下留白 */
        width: 100%; border-radius: 8px; height: 42px; /* 按鈕加大 */
        background-color: #334155; border: 1px solid #475569;
        font-size: 15px;
    }
    
    .footer { position: fixed; left: 0; bottom: 0; width: 100%; background-color: #0F172A; color: #475569; text-align: center; padding: 12px; font-size: 11px; border-top: 1px solid #1E293B; z-index: 100; }
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

# --- Sidebar: 舒適版 (間距拉寬) ---
with st.sidebar:
    st.markdown("### 🚀 快速指南")
    
    st.markdown("""
    <div class="comfort-box">
        <ol style="margin:0; padding-left:1.2rem;">
            <li>前往 <a href="https://aistudio.google.com/" target="_blank">Google AI Studio (點我)</a></li>
            <li>登入<b>個人 Google 帳號</b> (避開教育版)</li>
            <li>點擊 <b>Get API key</b> 並複製</li>
            <li>貼入下方欄位</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)
    
    api_input = st.text_area("在此輸入 API Key", height=80, placeholder="請貼上金鑰...")
    
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
        • <a href="https://reader.nani.com.tw/" target="_blank">南一 OneBox</a><br>
        <br>
        <b>參考資料：</b><br>
        • <a href="https://cirn.moe.edu.tw/Syllabus/index.aspx?sid=1108" target="_blank">108課綱資源網 (CIRN)</a><br>
        • <a href="https://www.nhps.hc.edu.tw/" target="_blank">內湖國小校網</a>
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
                        # 使用快取函數讀取檔案 (效能優化關鍵 🚀)
                        content = extract_text_from_files(uploaded_files)
                        
                        try:
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

# --- Phase 2: 正式出題 ---
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
    
    # 微調對話框
    if len(st.session_state.chat_history) > 1:
        if prompt := st.chat_input("對題目不滿意？請輸入指令微調"):
            with st.chat_message("user"): st.markdown(prompt)
            
            with st.spinner("🔧 AI 正在修改試題..."):
                keys = [k.strip() for k in api_input.replace('\n', ',').split(',') if k.strip()]
                genai.configure(api_key=random.choice(keys))
                model_pro = genai.GenerativeModel("gemini-1.5-pro", system_instruction=GEM_INSTRUCTIONS)
                
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
