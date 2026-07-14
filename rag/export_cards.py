"""把 primal_database.xlsm 的 Cards 表匯出成 卡表/cards_hunters.json。

用途：xlsm 是社群維護的原始卡表（含巨集、體積大、被 .gitignore 排除），
匯出成 JSON 後可版本控管、跨機器攜帶。build_index.py 找不到 xlsm 時
會自動改用此 JSON 建索引；xlsm 更新後重跑本腳本同步。

用法：
    python export_cards.py
"""
from __future__ import annotations

import json

from config import CARDS_DIR

# xlsm 欄位標題 -> JSON 鍵
COLMAP = {
    "Card": "category", "Hunter": "hunter", "Card name": "name",
    "Card type": "card_type", "Subtype": "subtype",
    "Stamina cost": "stamina_cost", "Stamina icons": "stamina_icons",
    "Card ID": "card_id", "Card trait": "trait", "Card text": "text",
    "Level": "level", "Health": "health", "Element": "element",
    "Cost": "cost", "Damage": "damage",
    "Deck composition": "deck_composition", "FAQ": "faq",
}


def parse_xlsm(path) -> list[dict]:
    """讀取 Cards 表 -> 卡片 dict 列表（只保留非空欄位）。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Cards"]
    idx: dict[str, int] = {}
    cards: list[dict] = []
    for r in ws.iter_rows(values_only=True):
        vals = ["" if v is None else str(v).strip() for v in r]
        if not idx:
            if any(v.startswith("Card name") for v in vals):
                idx = {v.split("\n")[0]: i for i, v in enumerate(vals) if v}
            continue

        def get(col: str) -> str:
            i = idx.get(col, 999)
            return vals[i] if i < len(vals) else ""

        if not get("Card name"):
            continue
        card = {key: get(col) for col, key in COLMAP.items() if get(col)}
        cards.append(card)
    wb.close()
    return cards


def main() -> None:
    src = CARDS_DIR / "primal_database.xlsm"
    out = CARDS_DIR / "cards_hunters.json"
    cards = parse_xlsm(src)
    data = {
        "_note": "自 primal_database.xlsm 的 Cards 表匯出（export_cards.py）。"
                 "xlsm 更新後請重跑匯出。含 6 位獵人（Daeron/Thoerg/Ljonar/Mirah/"
                 "Karah/Heleren）與通用/裝備卡的完整效果文字；"
                 "Drusk/Zaraya 另見 cards_extra.json。",
        "cards": cards,
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    from collections import Counter
    hunters = Counter(c.get("hunter", "（無）") for c in cards)
    cats = Counter(c.get("category", "（無）") for c in cards)
    print(f"匯出 {len(cards)} 張卡 -> {out}")
    print("獵人分佈:", dict(hunters.most_common()))
    print("分類分佈:", dict(cats.most_common()))


if __name__ == "__main__":
    main()
