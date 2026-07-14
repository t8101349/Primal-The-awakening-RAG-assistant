"""RAG + MoA（Mixture-of-Agents）規則裁定管線。

流程：
    1. BM25 檢索規則書段落（與 ask.py 共用同一套檢索器）
    2. 層 1「提案者」×3：同一份證據、不同角色，平行各自推理
    3. 層 2「聚合者」：批判性綜合三份草稿，裁決矛盾，輸出最終答案＋依據

用法：
    python moa.py "支付體力費用時可以故意多棄牌嗎？"
    python moa.py --show-drafts "..."   # 連三份草稿一起印出
    python moa.py --no-rag "..."        # 不檢索，純 MoA（一般問題）
    python moa.py --top-k 8 "..."

後端：讀 config.py（.env 可切 LM Studio / Z.ai / HF 等 OpenAI 相容端點）。
思考模型（GLM-4.6V Flash 等）的 <think> 區塊會自動剝除，只留答案。
"""
from __future__ import annotations

import argparse
import re
import sys
from operator import itemgetter

import requests
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel
from langchain_openai import ChatOpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LOW_SCORE
from retriever import BM25Retriever

PERSONAS = {
    "rules_lawyer": (
        "你是嚴謹的桌遊規則分析師。只根據提供的規則書段落逐條推理，"
        "引用時標明《書名》與頁碼；段落沒寫的就說「依目前資料無法確認」，不可腦補。"
    ),
    "veteran": (
        "你是這款遊戲的資深玩家。用實戰情境解釋規則會怎麼運作，舉具體例子，"
        "但結論仍必須以提供的段落為準，並標明依據頁碼。"
    ),
    "skeptic": (
        "你是專門找碴的裁判。先檢查：有沒有例外情況？FAQ 或勘誤是否推翻了規則書原文？"
        "常見誤判是什麼？把這些疑點逐一釐清後再下結論，標明依據頁碼。"
    ),
}

AGGREGATOR_SYSTEM = (
    "你是聚合者（aggregator），也是最終裁判。以下有三位助手對同一問題的草稿，"
    "它們可能有錯誤或互相矛盾。請對照「規則書段落」逐一查證：\n"
    "1. 只保留段落能支持的內容；剔除臆測。\n"
    "2. 草稿互相矛盾時，以官方 FAQ／勘誤 優先於規則書原文，再以論證較強的一方為準。\n"
    "3. 用繁體中文輸出，格式：\n"
    "- **結論**：一句話直接回答。\n"
    "- **說明**：簡短解釋，含相關例外。\n"
    "- **依據**：《書名》第 X 頁 條列。\n"
    "- **不確定性**：資料不足之處；沒有就寫「無」。"
)

# 思考模型的 <think>…</think>（含未閉合的殘塊）一律剝除
_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.S)


def strip_think(text: str) -> str:
    out = _THINK.sub("", text).strip()
    return out if out else "（此提案者無有效輸出）"


def pick_model() -> str:
    if LLM_MODEL:
        return LLM_MODEL
    r = requests.get(f"{LLM_BASE_URL}/models",
                     headers={"Authorization": f"Bearer {LLM_API_KEY}"}, timeout=10)
    r.raise_for_status()
    models = [m["id"] for m in r.json()["data"]]
    if not models:
        raise RuntimeError("端點上沒有已載入的模型")
    return models[0]


def format_context(chunks: list[dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        book = c["book"].replace("Primal The Awakening - ", "")
        lang = "中譯" if c["lang"] == "zh" else "英文原文"
        parts.append(f"--- 段落 {i}《{book}》第 {c['page']} 頁（{lang}）---\n{c['text']}")
    return "\n\n".join(parts)


def make_proposer(model: str, persona: str):
    llm = ChatOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
                     model=model, temperature=0.7)
    prompt = ChatPromptTemplate.from_messages([
        ("system", persona),
        ("human", "規則書段落：\n{context}\n\n問題：{question}"),
    ])
    return prompt | llm | StrOutputParser() | RunnableLambda(strip_think)


def build_moa(model: str):
    layer1 = RunnableParallel(
        question=itemgetter("question"),
        context=itemgetter("context"),
        **{name: make_proposer(model, persona) for name, persona in PERSONAS.items()},
    )
    agg_llm = ChatOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
                         model=model, temperature=0.2)
    agg_prompt = ChatPromptTemplate.from_messages([
        ("system", AGGREGATOR_SYSTEM),
        ("human",
         "規則書段落：\n{context}\n\n問題：{question}\n\n"
         "【草稿一・規則分析師】\n{rules_lawyer}\n\n"
         "【草稿二・資深玩家】\n{veteran}\n\n"
         "【草稿三・找碴裁判】\n{skeptic}"),
    ])
    aggregate = agg_prompt | agg_llm | StrOutputParser() | RunnableLambda(strip_think)
    return layer1, aggregate


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG + MoA 規則裁定")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--top-k", type=int, default=6)
    ap.add_argument("--no-rag", action="store_true", help="不檢索，純 MoA")
    ap.add_argument("--show-drafts", action="store_true", help="印出三份草稿")
    args = ap.parse_args()
    question = " ".join(args.question)

    if args.no_rag:
        context = "（本次未提供規則書段落，請依一般知識回答並明說沒有出處。）"
    else:
        chunks = BM25Retriever().search(question, k=args.top_k)
        if not chunks:
            print("找不到相關段落。")
            sys.exit(1)
        context = format_context(chunks)
        if chunks[0]["score"] < LOW_SCORE:
            print(f"[提示] 檢索相關性偏低（最高分 {chunks[0]['score']:.1f}），"
                  "此問題可能超出資料庫範圍。\n")
            context = ("【注意】檢索相關性偏低，以下段落可能與問題無關——若確實無關，"
                       "請直接說「資料庫中找不到相關內容」，不要硬湊答案。\n\n" + context)

    model = pick_model()
    print(f"[模型] {model}｜提案者 ×{len(PERSONAS)} 平行 → 聚合者\n")

    layer1, aggregate = build_moa(model)
    drafts = layer1.invoke({"question": question, "context": context})

    if args.show_drafts:
        for name in PERSONAS:
            print(f"===== 草稿：{name} =====\n{drafts[name]}\n")

    print(aggregate.invoke(drafts))

    if not args.no_rag:
        print("\n" + "─" * 40)
        print("檢索依據：")
        for c in chunks:
            book = c["book"].replace("Primal The Awakening - ", "")
            lang = "中譯" if c["lang"] == "zh" else "原文"
            print(f"  · 《{book}》第 {c['page']} 頁（{lang}）")


if __name__ == "__main__":
    main()
