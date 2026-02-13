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

# --- 2. 檔案讀取工具 (快取優化) ---
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
        # 過濾掉非表格行，只保留以 | 開頭的行
        lines = [l for l in md_text.strip().split('\n') if l.strip().startswith('|')]
        if len(lines) < 2: return None # 至少要有標題和分隔線
        
        # 移除 Markdown 分隔線 (例如 |---|---|)
        data_lines = [l for l in lines if '---' not in l]
        
        if len(data_lines) < 2: return None
        
        headers = [c.strip() for c in data_lines[0].split('|') if c.strip()]
        data = [[c.strip() for c in l.split('|') if c.strip()] for l in data_lines[1:]]
        
        # 確保資料欄位數與標題一致 (簡單防呆)
        cleaned_data = []
        for row in data:
            if len(row) == len(headers):
                cleaned_data.append(row)
            elif len(row) > len(headers):
                cleaned_data.append(row[:len(headers)]) # 截斷多餘
            else:
                cleaned_data.append(row + [''] * (len(headers) - len(row))) # 補空值
                
        df = pd.DataFrame(cleaned_data, columns=headers)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='學習目標審核表')
        return output.getvalue()
    except: return None

# --- 4. 核心 Gem 命題鐵律 (強化表格指令) ---
GEM_INSTRUCTIONS = """
你是「國小專業定期評量命題 AI」。

### ⚠️ 最高指導原則：
1. **Phase 1 (現在)**：
   - 僅產出【學習目標審核表】。
   - **必須使用標準 Markdown 表格格式**，確保每一列資料都獨立換行。
   - **絕對禁止**在此階段產出任何試題、題目或答案。
   - 表格欄位依序為：| 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
2. **Phase 2 (之後)**：才依照審核表產出試題。
3. **科目防呆**：若教材與科目不符，僅回覆『ERROR_SUBJECT_MISMATCH』。
"""

# --- 5. 智能模型選擇與重試機制 ---
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
            if not target_model:
                for m in models:
                    if 'pro' in m.lower(): target_model = m; break
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
                wait_time = (i + 1) * 5
                st.toast(f"⏳ 伺服器忙碌 (429)，{wait_time} 秒後自動重試 ({i+1}/{max_retries})...", icon="⚠️")
                time.sleep(wait_time)
            else:
                raise e
    raise Exception("重試次數過多，請稍後再試。")

# --- 6. 網頁介面視覺設計 ---
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

# 狀態管理
if "phase" not in st.session_state: st.session_state.phase = 1 
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "last_prompt_content" not in st.session_state: st.session_state.last_prompt_content = ""

# --- Sidebar ---
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
                                # 在 Prompt 中強制要求 Markdown 表格格式
                                prompt_content = f"""
                                任務：Phase 1 學習目標提取
                                年級：{grade}, 科目：{subject}
                                題型：{t_str}
                                教材內容：
                                {content}
                                ---
                                請產出【學習目標審核表】。
                                **請務必使用標準 Markdown 表格格式輸出，包含以下欄位：**
                                | 單元名稱 | 學習目標(原文) | 對應題型 | 預計配分 |
                                |---|---|---|---|
                                
                                注意：僅產出表格，嚴禁產出試題！不要有其他開場白或結尾文字。
                                """
                                st.session_state.last_prompt_content = prompt_content
                                
                                response = generate_with_retry(chat, prompt_content, stream=True)
                                
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
                        except Exception as e: 
                            st.error(f"連線失敗：{e} (請檢查 API Key 或稍後重試)")

# --- Phase 2: 正式出題 ---
elif st.session_state.phase == 2:
    current_md = st.session_state.chat_history[0]["content"]
    
    with st.container(border=True):
        st.markdown("### 📥 第二階段：下載審核表")
        with st.chat_message("ai"): st.markdown(current_md)
        excel_data = md_to_excel(current_md)
        if excel_data:
            st.download_button(label="📥 匯出此審核表 (Excel)", data=excel_data, file_name=f"內湖國小_{subject}_審核表.xlsx", use_container_width=True)
        else:
            # 若表格解析失敗，給予提示
            st.warning("⚠️ 偵測到表格格式可能不完整 (AI 輸出格式異常)，Excel 匯出功能暫時停用，但您仍可繼續出題。")

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
                                response = generate_with_retry(model_smart, final_prompt, stream=True)
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
    
    # 微調
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
                    response = generate_with_retry(chat_pro, prompt, stream=True)
                    for chunk in response:
                        full_response += chunk.text
                        message_placeholder.markdown(full_response + "▌")
                    message_placeholder.markdown(full_response)
                
                st.session_state.chat_history.append({"role": "model", "content": full_response})

st.markdown('<div class="custom-footer">© 2026 新竹市香山區內湖國小. All Rights Reserved.</div>', unsafe_allow_html=True)
