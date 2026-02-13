import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image
import io

# ==========================================
# 1. 檔案處理工具 (File Processors)
# ==========================================
def read_pdf(file):
    try:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return f"\n[PDF讀取錯誤: {file.name}]\n"

def read_docx(file):
    try:
        doc = Document(file)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    except Exception as e:
        return f"\n[Word讀取錯誤: {file.name}]\n"

def read_pptx(file):
    try:
        prs = Presentation(file)
        text = ""
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text += shape.text + "\n"
        return text
    except Exception as e:
        return f"\n[PPT讀取錯誤: {file.name}]\n"

def read_doc_dirty(file):
    """
    暴力讀取舊版 .doc 檔
    原理：直接讀取二進位檔，過濾出可讀的中英文字元。
    缺點：可能會包含一些亂碼或格式符號，但 AI 通常看得懂。
    """
    try:
        content = file.read()
        # 嘗試用不同的編碼解碼，或直接過濾
        text = ""
        # 簡單過濾：只保留常見的中英文與標點符號範圍
        # 這是非常基礎的過濾，主要為了讓 AI 能抓到關鍵字
        try:
            # 嘗試解碼 (Big5 是台灣舊版 Word 常見編碼)
            text = content.decode('big5', errors='ignore')
        except:
            # 如果失敗，嘗試 utf-8
            text = content.decode('utf-8', errors='ignore')
            
        return f"\n=== 檔案: {file.name} (舊版Word) ===\n{text}\n"
    except Exception as e:
        return f"\n[舊版 .doc 讀取失敗: {file.name} - 建議轉存 .docx]\n"

# ==========================================
# 2. 系統設定 (System Prompt)
# ==========================================
SYSTEM_PROMPT = """
**Role:**
你是「國小專業定期評量命題 AI」，精通 1-6 年級全科（國/數/社/自/英）教材教法。
你具備將教材轉化為 **[適中]**、**[困難]**、**[素養]** 三種不同層次試卷的能力。

**Core Principle:**
嚴格遵守「兩段式輸出」：
1. **Phase 1**：僅輸出【試題審核表】。
2. **Phase 2**：使用者確認後，才輸出【試題】。

### 1. 核心參數：試卷模式
* **🟢 模式 A：適中** (60% 記憶 + 40% 應用)
* **🔴 模式 B：困難** (30% 應用 + 70% 分析評鑑)
* **🌟 模式 C：素養** (PISA/TIMSS/PIRLS 國際標準，情境導向)

### 2. 題型與配分硬約束
* 總分 100 分。
* 題型權限：依使用者限制調整。
* 單格配分上限 3 分。

### 3. ✅ 視覺化與圖表生成
* 數據表格：生成 Markdown 表格。
* 圖像標記：插入 ``。

### 4. ✅ 選項品質與科目保險絲
* 嚴格執行 OptionClass 檢查與科目專屬規範。

### 5. 輸出格式
(一) 【試題審核表】：含基本檢查、圖表清單、目標覆蓋。
(二) 【試題】：含題組情境、Markdown 表格、題目。

### 6. 自動修正
若總分不為 100 或出現以上皆是，自動修正。
"""

# ==========================================
# 3. 網頁介面設定 (Frontend UI)
# ==========================================
st.set_page_config(page_title="QuestWiz 出題助手", page_icon="📝", layout="wide")

st.title("📝 QuestWiz 國小命題引擎")
st.markdown("支援 **PDF / Word(.docx/.doc) / PPT / 圖片** 多檔分析")

# --- 側邊欄：API Key 設定 ---
with st.sidebar:
    st.header("🔑 設定")
    api_key = st.text_input("輸入 Google Gemini API Key", type="password")
    st.markdown("[取得免費 API Key](https://aistudio.google.com/app/apikey)")
    st.divider()
    st.info("💡 提示：您可以一次拖曳多個檔案上傳！")

# --- 主畫面 ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None

# 如果還沒有開始對話，顯示設定表單
if not st.session_state.chat_history:
    with st.container(border=True):
        st.subheader("🛠️ 命題參數設定")
        
        col1, col2 = st.columns(2)
        with col1:
            grade = st.selectbox("年級", ["一年級", "二年級", "三年級", "四年級", "五年級", "六年級"], index=4)
            subject = st.selectbox("科目", ["依教材推定", "國語", "數學", "自然", "社會", "英語"], index=2)
        
        with col2:
            mode = st.radio("試卷模式", ["🟢 適中 (標準)", "🔴 困難 (資優)", "🌟 素養 (PISA/TIMSS)"], index=2)

        st.markdown("---")
        
        # --- 檔案上傳區 (修正重點：accept_multiple_files=True) ---
        uploaded_files = st.file_uploader(
            "上傳教材 (支援直接拖曳多個檔案)", 
            type=["pdf", "docx", "doc", "pptx", "txt", "jpg", "png", "jpeg"],
            accept_multiple_files=True  # <--- 關鍵修正：允許上傳多個檔案
        )
        
        # 題型開關
        with st.expander("進階設定 (題型開關/學習目標)"):
            c1, c2, c3, c4 = st.columns(4)
            allow_single = c1.checkbox("單選題", value=True)
            allow_multi = c2.checkbox("多選題", value=True)
            allow_match = c3.checkbox("配合題", value=True)
            allow_short = c4.checkbox("簡答題", value=True)
            learning_goals = st.text_area("學習目標 (選填)", placeholder="例如：能分辨酸性與鹼性水溶液...", height=68)

        start_btn = st.button("🚀 開始生成試卷審核表", type="primary", use_container_width=True)

    if start_btn and api_key and uploaded_files:
        
        all_extracted_text = ""
        images_list = []
        
        # 顯示讀取進度條
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_files = len(uploaded_files)
        
        for i, file in enumerate(uploaded_files):
            status_text.text(f"正在讀取檔案 ({i+1}/{total_files}): {file.name} ...")
            file_type = file.name.split('.')[-1].lower()
            
            # 依格式讀取
            if file_type == 'pdf':
                text = read_pdf(file)
                all_extracted_text += f"\n=== 檔案: {file.name} ===\n{text}\n"
            
            elif file_type == 'docx':
                text = read_docx(file)
                all_extracted_text += f"\n=== 檔案: {file.name} ===\n{text}\n"
            
            elif file_type == 'doc': # 處理舊版 doc
                text = read_doc_dirty(file)
                all_extracted_text += text
            
            elif file_type == 'pptx':
                text = read_pptx(file)
                all_extracted_text += f"\n=== 檔案: {file.name} ===\n{text}\n"
            
            elif file_type == 'txt':
                text = file.read().decode("utf-8")
                all_extracted_text += f"\n=== 檔案: {file.name} ===\n{text}\n"
            
            elif file_type in ['jpg', 'jpeg', 'png']:
                img = Image.open(file)
                images_list.append(img)
                all_extracted_text += f"\n[已上傳圖片: {file.name}]\n"

            progress_bar.progress((i + 1) / total_files)
            
        status_text.text("檔案讀取完成，正在傳送給 AI ...")

        # --- 組合 Prompt ---
        restrictions = []
        if not allow_single: restrictions.append("禁止單選題")
        if not allow_multi: restrictions.append("禁止多選題")
        if not allow_match: restrictions.append("禁止配合題")
        if not allow_short: restrictions.append("禁止簡答題")
        restriction_text = "、".join(restrictions) if restrictions else "無限制 (皆可)"

        user_text_prompt = f"""
        【使用者下單參數】
        科目：{subject}
        年級：{grade}
        模式：{mode}
        學習目標：{learning_goals if learning_goals else "依教材擷取"}
        限制條件：{restriction_text}

        【教材內容 (彙整)】
        {all_extracted_text}
        """

        # 初始化模型
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash", 
            system_instruction=SYSTEM_PROMPT
        )
        chat = model.start_chat(history=[])
        
        # 發送訊息 (文字 + 圖片列表)
        message_parts = [user_text_prompt]
        if images_list:
            message_parts.extend(images_list)

        with st.spinner("AI 正在分析所有教材並設計審核表..."):
            try:
                response = chat.send_message(message_parts)
                st.session_state.chat_session = chat
                st.session_state.chat_history.append({"role": "user", "content": f"*(已傳送 {len(uploaded_files)} 份教材資料)*"})
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
            except Exception as e:
                st.error(f"發生錯誤：{str(e)}")

# --- 對話模式 ---
else:
    for message in st.session_state.chat_history:
        role = "ai" if message["role"] == "model" else "user"
        avatar = "🤖" if role == "ai" else "🧑‍🏫"
        with st.chat_message(role, avatar=avatar):
            st.markdown(message["content"])

    if user_input := st.chat_input("請輸入「確認出題」或提出修改建議..."):
        chat = st.session_state.chat_session
        
        with st.chat_message("user", avatar="🧑‍🏫"):
            st.markdown(user_input)
        
        with st.spinner("AI 正在思考中..."):
            try:
                response = chat.send_message(user_input)
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "model", "content": response.text})
                st.rerun()
            except Exception as e:
                st.error(f"連線錯誤：{str(e)}")

    if st.button("🔄 重新設定"):
        st.session_state.chat_history = []
        st.session_state.chat_session = None
        st.rerun()