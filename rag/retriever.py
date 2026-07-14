"""中英雙語 BM25 檢索器（純 Python，零外部依賴）。

- 英文：小寫單詞
- 中文：單字 + 相鄰雙字（bigram）
- 查詢擴充：內建術語表把中文術語補上英文對應詞，
  讓中文問題也能命中英文原文頁（跨語言檢索的簡易解法）。
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter

from config import CHUNKS_PATH

_EN = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[一-鿿]")

# 中文術語 -> 英文檢索詞（與譯文固定譯法一致）
GLOSSARY: dict[str, str] = {
    "獵人": "hunter", "魔物": "monster", "怪物": "monster",
    "體力": "stamina", "消耗階段": "attrition phase", "消耗傷害": "attrition damage",
    "行為卡": "behavior card", "架勢": "stance", "釋放": "unleash",
    "戰役": "campaign", "自由狩獵": "free hunt", "聚落": "settlement",
    "裝備": "gear", "戰利品": "trophy", "傷口": "wound", "指示物": "token",
    "設置": "setup", "地形": "terrain", "侵略等級": "aggression level",
    "難度": "aggression level difficulty", "專精": "mastery", "危局卡": "peril card",
    "反射": "reflex", "閃避": "dodge", "攻擊卡": "offensive card",
    "防禦": "defense", "高地": "plateau", "沼澤": "swamp", "水域": "water",
    "岩石": "rock", "冰地": "ice", "劇本": "scenario", "遠征": "expedition",
    "生態域": "biome", "任務": "quest", "血之幻象": "blood vision",
    "到期": "expiration", "獎勵": "reward", "牌組": "deck", "卡牌": "card",
    "等級": "level", "回合": "round turn", "階段": "phase", "圖板": "board",
    "覺醒者": "awakened", "弩砲": "ballista", "毒": "venom poison",
    "夢魘": "nightmare", "麻痺孢子": "paralyzing spore", "戰舞": "war dance",
    "穿刺": "pierce", "節奏": "rhythm", "共鳴": "resonance",
    "刷新": "refresh", "整備": "upkeep", "掙扎": "struggle",
    "倒地": "ko knocked out", "釋放大招": "unleash",
}

# 問題含這些詞時才視為在問自製變體，否則變體條目降權（防止蓋過官方規則）
_VARIANT_MARKERS = ("變體", "自製", "狂龍", "狂暴化", "極限化", "斷末魔", "house rule")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    tokens = _EN.findall(text)
    chars = _CJK.findall(text)
    tokens.extend(chars)
    tokens.extend(a + b for a, b in zip(chars, chars[1:]))
    return tokens


def expand_query(q: str) -> str:
    extra = [en for zh, en in GLOSSARY.items() if zh in q]
    return q + " " + " ".join(extra)


# 術語表裡的英文通用詞不算專有名詞（不參與書名／段落標題加權）
_GLOSSARY_WORDS = {w for v in GLOSSARY.values() for w in v.split()}


def _is_toc(chunk: dict) -> bool:
    sec = (chunk.get("section") or "").lower()
    return "目錄" in sec or "table of contents" in sec or "contents" == sec


class BM25Retriever:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.chunks: list[dict] = []
        with CHUNKS_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                self.chunks.append(json.loads(line))
        self.book_tokens = [set(tokenize(c["book"])) for c in self.chunks]
        self.section_tokens = [set(tokenize(c.get("section") or "")) for c in self.chunks]
        # 段落標題參與索引（標題常含魔物名等關鍵訊號）
        self.doc_tokens = [
            Counter(tokenize(f"{c.get('section', '')} {c['text']}")) for c in self.chunks
        ]
        self.doc_len = [sum(t.values()) for t in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / max(1, len(self.doc_len))
        self.df: Counter = Counter()
        for t in self.doc_tokens:
            self.df.update(t.keys())
        self.n = len(self.chunks)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 8, include_toc: bool = False) -> list[dict]:
        """主檢索 + 專有名詞輔助檢索。

        通用規則詞（設置、遠征模式…）常讓總覽頁蓋過真正的條目頁，
        因此若問題含專有名詞（魔物／獵人名），額外以名詞單獨檢索，
        保留最多 3 個名額給這些精準命中的段落。
        """
        main = self._search_once(query, k, include_toc)
        proper = {
            t for t in tokenize(query)
            if len(t) >= 4 and _EN.fullmatch(t) and t not in _GLOSSARY_WORDS
        }
        if not proper:
            return main
        seen = {re.sub(r"[\s\W]+", "", c["text"])[:80] for c in main}
        extra: list[dict] = []
        for noun in sorted(proper):
            for c in self._search_once(noun, 3, include_toc):
                key = re.sub(r"[\s\W]+", "", c["text"])[:80]
                if key not in seen:
                    seen.add(key)
                    extra.append(c)
        extra = extra[:4]
        if not extra:
            return main
        return main[: max(k - len(extra), 1)] + extra

    def _search_once(self, query: str, k: int, include_toc: bool = False) -> list[dict]:
        q_terms = tokenize(expand_query(query))
        # 專有名詞（原始問題中 ≥4 字母的英文詞，如魔物名、獵人名）命中書名／段落標題時加權
        proper = {
            t for t in tokenize(query)
            if len(t) >= 4 and _EN.fullmatch(t) and t not in _GLOSSARY_WORDS
        }
        # 原始問題的中文雙字組（用於段落標題命中加權）
        chars = _CJK.findall(query)
        q_cjk_bi = {a + b for a, b in zip(chars, chars[1:])}
        scores = [0.0] * self.n
        for term in set(q_terms):
            idf = self._idf(term)
            if idf <= 0:
                continue
            for i, tokens in enumerate(self.doc_tokens):
                tf = tokens.get(term, 0)
                if not tf:
                    continue
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avg_len)
                scores[i] += idf * tf * (self.k1 + 1) / denom
        asking_variant = any(m in query for m in _VARIANT_MARKERS)
        for i in range(self.n):
            if not scores[i]:
                continue
            if not include_toc and _is_toc(self.chunks[i]):
                scores[i] *= 0.2  # 目錄頁降權（參照 multimodal-rag-review 的 TOC 過濾）
            if not asking_variant and "自製變體" in self.chunks[i]["book"]:
                scores[i] *= 0.35  # 非變體問題時，自製規則降權以免蓋過官方規則
            hits = len(proper & self.book_tokens[i])
            if hits:
                scores[i] *= 1.0 + 0.35 * min(hits, 3)  # 書名命中加權
            sec_hits = len(proper & self.section_tokens[i])
            if sec_hits:
                scores[i] *= 1.0 + 0.8 * min(sec_hits, 2)  # 段落標題命中加權（魔物／獵人名）
            cjk_hits = len(q_cjk_bi & self.section_tokens[i])
            if cjk_hits:
                # 中文標題命中加權（如「起始牌組」「等級 2」）；上限壓低，
                # 避免「遠征模式」這類高頻通用標題蓋過具體條目
                scores[i] *= 1.0 + 0.15 * min(cjk_hits, 2)
        ranked = sorted(range(self.n), key=lambda i: scores[i], reverse=True)[: k * 4]
        # 跨書去重：多本擴充有幾乎相同的通用段落（如「生態域使用方式」），只留分數最高的一份
        seen: set[str] = set()
        out: list[dict] = []
        for i in sorted(ranked, key=lambda i: (scores[i], self.chunks[i]["lang"] == "zh"), reverse=True):
            c = self.chunks[i]
            key = re.sub(r"[\s\W]+", "", c["text"])[:80]
            if key in seen or scores[i] <= 0:
                continue
            seen.add(key)
            out.append({**c, "score": round(scores[i], 3)})
            if len(out) >= k:
                break
        return out
