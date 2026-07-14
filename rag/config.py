"""Primal: The Awakening RAG 助手 - 全域設定。

參照 multimodal-rag-review 的設定風格：集中管理路徑與模型設定，可由 .env 覆寫。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

# --- 路徑 ---
BOOKS_DIR = ROOT.parent                  # 專案根目錄
RULEBOOKS_DIR = BOOKS_DIR / "規則書"      # 官方規則書＋FAQ PDF
AIDS_DIR = BOOKS_DIR / "玩家輔助"         # 角色表、Player Aid 等輔助 PDF
CARDS_DIR = BOOKS_DIR / "卡表"            # primal_database.xlsm、cards_extra.json
ZH_DIR = BOOKS_DIR / "中文翻譯"           # 繁中譯文 (.zh-TW.md)
DATA_DIR = ROOT / "data"
IMG_DIR = DATA_DIR / "page_images"       # 原書頁面渲染圖（多模態用）
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"

for _d in (DATA_DIR, IMG_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key, default)
    return v if v and v.strip() else default


# --- LLM / VLM 端點（OpenAI 相容；預設 LM Studio）---
LLM_BASE_URL = _env("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_API_KEY = _env("LLM_API_KEY", "lm-studio")
LLM_MODEL = _env("LLM_MODEL", "")          # 留空 = 自動取端點上第一個模型
LLM_TIMEOUT = int(_env("LLM_TIMEOUT", "300"))
MAX_TOKENS = int(_env("MAX_TOKENS", "2048"))
TEMPERATURE = float(_env("TEMPERATURE", "0.2"))

# --- 檢索參數 ---
TOP_K = int(_env("TOP_K", "8"))
LOW_SCORE = float(_env("LOW_SCORE", "17"))  # 首位檢索分數低於此值時，提示模型「可能查無資料」

# --- 多模態（附掛原書頁面圖）---
SEND_IMAGES = _env("SEND_IMAGES", "auto")   # auto / on / off
MAX_IMAGES = int(_env("MAX_IMAGES", "3"))
RENDER_DPI = int(_env("RENDER_DPI", "110"))
