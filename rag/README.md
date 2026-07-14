# Primal: The Awakening — 中文規則 RAG 助手

參照 `multimodal-rag-review` 架構打造的桌遊規則助手：
**中英雙語 BM25 檢索**（純 Python，零外部依賴）＋**原書頁面截圖附掛**（多模態）＋
**OpenAI 相容端點生成**（預設 LM Studio）。一律以繁體中文回答。

## 檔案結構

```
Primal The Awakening-RAG assistant/
├── 規則書/       官方規則書＋擴充＋FAQ（15 本 PDF）
├── 玩家輔助/     角色表、Player Aid、延伸圖板等（5 份 PDF）
├── 卡表/         primal_database.xlsm（6 位獵人＋通用卡，含效果全文）
│                 cards_extra.json（Drusk/Zaraya 補充，可自行填入效果）
├── 中文翻譯/     13 份繁中譯文（.zh-TW.md，含【原書第 N 頁】標記）
└── rag/          本系統（程式＋data/ 索引與頁面圖，重建即生成）
```

## 資料涵蓋

- 核心規則書（英文原文，141 塊）＋ 12 本擴充規則書＋官方 FAQ v2.1（繁中譯文＋英文原文）
- 卡表：8 位獵人牌組（xlsm 6 位含效果全文；Drusk/Zaraya 僅卡名與牌組結構）
- 玩家輔助檔（文字部分＋頁面圖）
- **未涵蓋**：戰役書（Campaign Book）全文、魔物行為卡全文——助手會在答案中說明此限制

## 快速開始

```bash
# 1. 建立索引與頁面圖（只需跑一次；PDF 或譯文更新後重跑）
python build_index.py            # 加 --no-images 可跳過頁面圖渲染

# 2. 啟動 LM Studio -> 載入模型 -> Developer 頁籤啟動本機伺服器（預設 http://localhost:1234）
#    建議載入「視覺模型」（如 qwen2.5-vl-7b-instruct），才能讀取附掛的原書頁面截圖，
#    補足譯文中〔圖示〕佚失的資訊。純文字模型也可用（自動退回純文字模式）。

# 3. 提問
python ask.py "Attrition damage 和一般傷害有什麼不同？"
```

## 四種問法

| 類型 | 範例 | 回答內容 |
|---|---|---|
| 規則問題 | `python ask.py "體力費用可以多棄牌嗎？"` | 解答＋說明＋依據頁碼 |
| 關卡設置 | `python ask.py "在 Niz-Maraga 生態域打 Pazis 遠征模式怎麼設置？"` | 魔物卡牌選用／場地設置／特殊機制／注意事項 |
| 獵人玩法 | `python ask.py "獵人 Drusk 等級 2 的卡牌搭配建議"` | 玩法概述＋卡牌搭配＋注意事項 |
| 劇情推進 | `python ask.py "打完任務 36 之後下一場怎麼設置？"` | 設置步驟（控管劇透） |

## 常用選項

```bash
python ask.py --context "..."    # 只看檢索到的段落（不需要 LLM，離線可用）
python ask.py --no-images "..."  # 不附頁面截圖（純文字模型／省 token）
python ask.py --top-k 12 "..."   # 增加檢索段落數
```

## MoA 模式（moa.py）— 疑難裁定用

Mixture-of-Agents：三個角色（規則分析師／資深玩家／找碴裁判）拿同一份檢索證據
平行推理，聚合者比對草稿、裁決矛盾（FAQ／勘誤優先）後輸出最終答案。
適合本機小模型跑有爭議的規則題——代價是一題 4 次推理呼叫。

```bash
python moa.py "支付體力費用時可以故意多棄牌嗎？"
python moa.py --show-drafts "..."   # 連三份草稿一起印出
python moa.py --no-rag "..."        # 不檢索，純 MoA
```

需要 `pip install langchain-openai`。思考模型（GLM-4.6V Flash 等）的
`<think>` 區塊會自動剝除。日常快查用 `ask.py`（1 次呼叫、可附截圖），
疑難題用 `moa.py`。

## 設定

複製 `.env.example` 為 `.env` 修改。預設連 LM Studio（`http://localhost:1234/v1`）；
要改用雲端 API，設定 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 即可。

## 架構

```
問題（繁中）
  └→ retriever.py   BM25（中文 bigram＋英文詞）＋術語表查詢擴充（中→英，跨語言檢索）
                     ＋目錄頁降權＋書名/段落標題命中加權＋專有名詞輔助檢索
  └→ ask.py         組合命中段落＋對應原書頁面截圖（data/page_images/）
  └→ prompts.py     系統提示詞：四種回答模式、證據引用、FAQ 優先於規則書
  └→ LLM/VLM        OpenAI 相容 /chat/completions → 繁中回答＋依據清單
```

## 已知限制

- 譯文由 PDF 抽字翻譯而成，卡牌圖示（資源種類、觸發符號）部分佚失，
  已以〔圖示〕標注；附掛頁面截圖＋視覺模型可補足。
- 中譯的頁碼標記為 PDF 頁序（`【原書第 N 頁】`），與原書印刷頁碼可能不同，
  部分譯本已同時標注印刷頁碼。
- 戰役書不在資料庫內；劇情推進類問題只能提供擴充規則書內的任務設置資訊。
