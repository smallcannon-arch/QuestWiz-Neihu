import streamlit as st
import google.generativeai as genai
import PyPDF2
from docx import Document
from pptx import Presentation
from PIL import Image
import pandas as pd
import io

# ==========================================
# 1. 增強型檔案處理工具 (加入 CSV 支援)
# ==========================================
def read_pdf(file):
    pdf_reader = PyPDF2.PdfReader(file)
    return "".join([p.extract_text() or "" for p in pdf_reader.pages])

def read_docx(file):
    doc = Document(file)
    return "\n".join([p.text for p in doc.paragraphs])

def read_csv(file):
    try:
        df = pd.read_csv(file)
        return df.to_string() # 將表格轉為純文字讓 AI 讀取
    except: return "[CSV讀取失敗]"

# ==========================================
# 2. 進化版 System Prompt (強調自動抓取節數)
# ==========================================
SYSTEM_PROMPT = """
你是「內湖國小專用命題與審核 AI」。
你的任務是根據教材內容自動產生「試題審核表」與「高品質試卷」。

### ⚡ 行政配分核心指令：
1. **自動偵測節數**：請掃描教材或上傳的審核表，尋找「X節」或「X堂課」的關鍵字。
   - 例如：看到「3-1 ... 4節」、「3-2 ... 7節」，則總節數為 11 節。
2. **比例配分公式**：
   - 子單元配分 = (該單元節數 / 總節數) * 100。
   - 請在【試題審核表】中精確顯示此計算結果。
3. **兩段式輸出**：先輸出審核表（含配分權重表），確認後才出題。
4. **素養導向**：符合 PISA/TIMSS 標準，使用生活化情境。

### 輸出格式：
(一) 【試題審核表】
- 包含：範圍、模式、總分、配分分解。
- **權重對照表**：單元名稱 | 偵測到節數 | 權重百分比 | 預計佔分。
- 學習目標覆蓋表。
"""

# ==========================================
# 3. 網頁介
