# --- 3. Excel 下載工具 (含：抗沾黏 + 自動配分校正) ---
def md_to_excel(md_text):
    try:
        # Step 1: 預處理
        cleaned_text = md_text.replace("||", "|\n|")
        lines = cleaned_text.strip().split('\n')
        table_lines = []
        is_table_started = False
        
        # Step 2: 抓取表格
        for line in lines:
            if ("單元" in line or "目標" in line or "配分" in line) and "|" in line:
                is_table_started = True
                table_lines.append(line)
                continue
            if is_table_started:
                if "---" in line: continue
                if "|" in line: table_lines.append(line)
                
        if not table_lines: return None

        # Step 3: 轉為 List
        data = []
        for line in table_lines:
            row = [cell.strip() for cell in line.strip('|').split('|')]
            data.append(row)

        if len(data) < 2: return None

        headers = data[0]
        rows = data[1:]
        
        # Step 4: 補齊欄位
        max_cols = len(headers)
        cleaned_rows = []
        for r in rows:
            if len(r) == max_cols: cleaned_rows.append(r)
            elif len(r) < max_cols: cleaned_rows.append(r + [''] * (max_cols - len(r)))
            else: cleaned_rows.append(r[:max_cols])

        df = pd.DataFrame(cleaned_rows, columns=headers)

        # --- 🔥 新增功能：分數自動校正 (Auto-Normalization) ---
        # 1. 找出「配分」是哪一欄 (通常是最後一欄，包含 '配分' 字眼)
        score_col = None
        for col in df.columns:
            if "配分" in col:
                score_col = col
                break
        
        if score_col:
            try:
                # 2. 清洗數據 (把 '10分', '約5%' 這種變成純數字)
                # 使用正則表達式只留下數字
                scores = []
                for x in df[score_col]:
                    nums = re.findall(r'\d+', str(x))
                    if nums:
                        scores.append(float(nums[0]))
                    else:
                        scores.append(0.0)
                
                # 3. 計算目前的總分 (例如 140)
                current_total = sum(scores)
                
                if current_total > 0 and current_total != 100:
                    st.toast(f"⚠️ 偵測到 AI 原始配分總和為 {int(current_total)} 分，系統已自動修正為 100 分。", icon="⚖️")
                    
                    # 4. 依比例重新分配
                    new_scores = []
                    for s in scores:
                        # 公式：(原始分數 / 原始總分) * 100
                        new_s = (s / current_total) * 100
                        new_scores.append(new_s)
                    
                    # 5. 取整數處理 (四雪五入)
                    rounded_scores = [round(s) for s in new_scores]
                    
                    # 6. 餘數分配 (處理 rounding error)
                    # 因為四捨五入後，總分可能是 99 或 101，要把差額補在分數最高的項目上
                    diff = 100 - sum(rounded_scores)
                    if diff != 0:
                        # 找到分數最高的索引
                        max_idx = rounded_scores.index(max(rounded_scores))
                        rounded_scores[max_idx] += diff
                    
                    # 7. 寫回 DataFrame
                    df[score_col] = rounded_scores
                    
            except Exception as e:
                print(f"分數校正失敗: {e}")
                # 失敗就算了，維持原狀
        # ----------------------------------------------------

        # Step 5: 寫入 Excel (XlsxWriter)
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

            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            worksheet.set_column(0, 0, 15, wrap_format)
            worksheet.set_column(1, 1, 55, wrap_format) 
            worksheet.set_column(2, 2, 20, wrap_format)
            worksheet.set_column(3, 3, 10, wrap_format)
                
        return output.getvalue()
    except Exception as e:
        print(f"Excel 轉換失敗: {e}")
        return None
