# Primal: The Awakening — 中文規則 RAG 助手

《Primal: The Awakening》桌遊的本機中文規則問答系統：用自然語言（繁體中文）詢問規則判定、關卡設置、獵人卡組、魔物機制，系統檢索規則書段落後由 LLM 生成附出處的回答。

## 特色

- **中英雙語檢索**：純 Python BM25（零重依賴），中文問題可同時命中繁中譯文與英文原文（內建術語對照擴充查詢）
- **多模態**：回答時自動附上命中頁的原書掃描圖，視覺模型可直接讀表格與圖示（補足文字抽取的佚失）
- **四種問答模式**：規則問答（附依據頁碼）／關卡設置（魔物卡牌、場地、特殊機制、注意事項）／獵人玩法與卡組建議／劇情推進
- **MoA 疑難裁定**：三個角色（規則分析師、資深玩家、找碴裁判）平行推理，聚合者裁決矛盾（FAQ／勘誤優先）
- **結構化資料**：595 張卡牌條目（xlsm 卡表）＋擴充獵人牌組表＋23 條魔物總表（元素、地形、特殊規則、遠征設置，皆附出處）
- **誠實性防線**：低相關性檢索自動示警、資料庫外內容明確聲明、「未收錄／依版面推測」標記如實轉述

## 資料夾結構

```
├── 規則書/       官方規則書+戰役書＋擴充＋FAQ PDF（不隨儲存庫散布，請自備）
├── 玩家輔助/     角色表、Player Aid 等 PDF（同上）
├── 中文翻譯/     規則書繁中譯文 .zh-TW.md（同上）
├── variants/     自製變體規則（隨庫提供；索引時標記「非官方」與官方規則分流）
├── 卡表/         primal_database.xlsm（社群卡表，請自備）
│                 cards_hunters.json（rag/export_cards.py 自 xlsm 匯出，595 張卡
│                 　　含 6 位獵人完整效果文字；無 xlsm 時索引自動改用此檔）
│                 cards_extra.json、monsters.json（本專案彙整，隨庫提供）
└── rag/          程式本體（詳見 rag/README.md）
    └── data/     索引與頁面圖（執行 build_index.py 自動生成）
```

> **版權說明**：官方規則書 PDF、譯文與社群卡表受著作權保護，不包含在本儲存庫中。
> 請將自有檔案放入對應資料夾後重建索引。缺少部分資料時系統仍可運作（涵蓋範圍縮小）。

## 快速開始

```bash
# 1. 安裝依賴（Python 3.10+）
pip install -r rag/requirements.txt

# 2. 放入資料（見上方資料夾結構），然後建立索引與頁面圖
cd rag
python build_index.py            # 加 --no-images 可跳過頁面圖渲染

# 3. 準備一個 OpenAI 相容端點（擇一）
#    - LM Studio（預設）：載入模型（建議視覺模型）→ Developer 頁籤啟動伺服器（localhost:1234）
#    - 雲端 API：複製 .env.example 為 .env，填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL

# 4. 提問
python ask.py "Attrition damage 和一般傷害有什麼不同？"
python ask.py "在 Niz-Maraga 生態域打 Pazis 遠征模式怎麼設置？"
python moa.py "支付體力費用時可以故意多棄幾張牌嗎？"   # 疑難裁定（4 次推理呼叫）
python ask.py --context "..."                          # 只看檢索結果（離線可用）
```

詳細選項、MoA 說明與架構圖見 [rag/README.md](rag/README.md)。

## 已知限制

- 譯文由 PDF 文字層轉出，佚失圖示以〔圖示〕標注、版面推測處附譯註，回答會如實轉述這些保留
- 回答品質取決於所接的模型；本機小模型建議搭配 `moa.py` 交叉驗證重要裁定，並以「依據」頁碼回查原書
