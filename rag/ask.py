"""Primal: The Awakening RAG 助手 - 查詢入口。

用法：
    python ask.py "Attrition damage 和一般傷害有什麼不同？"
    python ask.py --context "Vyraxen 侵略等級 3 怎麼設置"   # 只看檢索結果，不呼叫 LLM
    python ask.py --no-images "..."                        # 純文字模式（非視覺模型用）

流程：BM25 檢索（中英雙語）→ 附掛命中頁的原書截圖 → OpenAI 相容端點生成繁中回答。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys

import requests

from config import (
    IMG_DIR, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT, LOW_SCORE,
    MAX_TOKENS, TEMPERATURE, TOP_K, SEND_IMAGES, MAX_IMAGES,
)
from prompts import SYSTEM_PROMPT, build_user_text
from retriever import BM25Retriever


def pick_model(base_url: str, api_key: str) -> str:
    if LLM_MODEL:
        return LLM_MODEL
    r = requests.get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    r.raise_for_status()
    models = r.json().get("data", [])
    if not models:
        raise RuntimeError("端點上沒有已載入的模型")
    return models[0]["id"]


def page_image(book: str, page: int):
    p = IMG_DIR / book / f"page_{page:03d}.jpg"
    return p if p.exists() else None


def collect_images(contexts: list[dict], limit: int) -> list[dict]:
    payloads, seen = [], set()
    for c in contexts:
        key = (c["book"], c["page"])
        if key in seen:
            continue
        seen.add(key)
        p = page_image(c["book"], c["page"])
        if not p:
            continue
        b64 = base64.b64encode(p.read_bytes()).decode()
        payloads.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"},
        })
        if len(payloads) >= limit:
            break
    return payloads


def main() -> None:
    ap = argparse.ArgumentParser(description="Primal: The Awakening 規則助手")
    ap.add_argument("question", nargs="+", help="你的問題（繁中或中英混合皆可）")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--context", action="store_true", help="只顯示檢索結果，不呼叫 LLM")
    ap.add_argument("--no-images", action="store_true", help="不附頁面截圖")
    args = ap.parse_args()
    question = " ".join(args.question)

    retriever = BM25Retriever()
    contexts = retriever.search(question, k=args.top_k)
    if not contexts:
        print("找不到相關段落。")
        sys.exit(1)
    low_relevance = contexts[0]["score"] < LOW_SCORE
    if low_relevance:
        print(f"[提示] 檢索相關性偏低（最高分 {contexts[0]['score']:.1f}），"
              "此問題可能超出資料庫範圍，回答僅供參考。\n")

    if args.context:
        for c in contexts:
            print(f"\n=== 《{c['book']}》第 {c['page']} 頁"
                  f"（{c['lang']}, score={c['score']}）{c.get('section','')} ===")
            print(c["text"][:800])
        return

    use_images = SEND_IMAGES != "off" and not args.no_images
    image_payloads = collect_images(contexts, MAX_IMAGES) if use_images else []

    user_content: list[dict] = [
        {"type": "text", "text": build_user_text(question, contexts, bool(image_payloads),
                                                 low_relevance=low_relevance)}
    ]
    user_content.extend(image_payloads)

    try:
        model = pick_model(LLM_BASE_URL, LLM_API_KEY)
    except Exception as e:
        print(f"[錯誤] 無法連線 LLM 端點 {LLM_BASE_URL}：{e}\n"
              f"請先啟動 LM Studio 並載入模型（建議視覺模型如 qwen2.5-vl），\n"
              f"或在 rag/.env 設定 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。\n"
              f"（可先用 --context 檢視檢索結果）")
        sys.exit(2)

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    r = requests.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}",
                 "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=LLM_TIMEOUT,
    )
    if r.status_code != 200 and image_payloads:
        # 非視覺模型收到圖片會報錯 -> 自動改純文字重試
        body["messages"][1]["content"] = user_content[:1]
        r = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}",
                     "Content-Type": "application/json"},
            data=json.dumps(body),
            timeout=LLM_TIMEOUT,
        )
    r.raise_for_status()
    answer = r.json()["choices"][0]["message"]["content"]

    print(answer)
    print("\n" + "─" * 40)
    print("檢索依據：")
    for c in contexts:
        lang = "中譯" if c["lang"] == "zh" else "原文"
        print(f"  · 《{c['book']}》第 {c['page']} 頁（{lang}）")
    if image_payloads:
        print(f"（已附 {len(image_payloads)} 張原書頁面截圖給模型比對）")


if __name__ == "__main__":
    main()
