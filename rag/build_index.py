"""建立語料索引與頁面圖。

做三件事：
1. 從 中文翻譯/*.zh-TW.md 切塊（依【原書第 N 頁】標記與標題），lang=zh
2. 用 PyMuPDF 直接抽取全部 14 本 PDF 的每頁英文原文，lang=en
   （主規則書沒有中譯，靠這份英文原文回答；中譯有缺漏處也能比對原文）
3. 把每本 PDF 的每一頁渲染成 JPEG，供回答時附圖（多模態）

輸出：
    data/chunks.jsonl                  一行一塊 {id, book, page, section, lang, text}
    data/page_images/<book>/page_NNN.jpg
"""
from __future__ import annotations

import json
import re
import sys

import fitz  # PyMuPDF

from config import (
    AIDS_DIR, BOOKS_DIR, CARDS_DIR, CHUNKS_PATH, IMG_DIR,
    RENDER_DPI, RULEBOOKS_DIR, ZH_DIR,
)

PAGE_MARK = re.compile(r"^>\s*【原書第\s*(\d+)\s*頁】")
HEADER = re.compile(r"^(#{1,3})\s+(.*)")
MAX_CHUNK = 1600  # 字元


def normalize_book(stem: str) -> str:
    """統一書名（去掉檔名裡多餘的 .pdf 與 .zh-TW 後綴）。"""
    stem = re.sub(r"\.zh-TW$", "", stem)
    stem = re.sub(r"\.pdf$", "", stem, flags=re.I)
    return stem.strip()


def split_long(text: str) -> list[str]:
    """段落優先切分，避免超過 MAX_CHUNK。"""
    if len(text) <= MAX_CHUNK:
        return [text]
    parts, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) > MAX_CHUNK:
            parts.append(buf.strip())
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        parts.append(buf.strip())
    return parts


def chunk_zh_markdown(path) -> list[dict]:
    """依頁標記與標題切塊，記錄 (book, page, section)。"""
    book = normalize_book(path.stem)
    page, section = 1, ""
    blocks: list[dict] = []
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        buf.clear()
        if len(text) < 30:  # 太短的雜訊塊不收
            return
        for piece in split_long(text):
            blocks.append(
                {"book": book, "page": page, "section": section, "lang": "zh", "text": piece}
            )

    for line in path.read_text(encoding="utf-8").splitlines():
        m = PAGE_MARK.match(line.strip())
        if m:
            flush()
            page = int(m.group(1))
            continue
        h = HEADER.match(line)
        if h:
            # 只在大標題（#、##）切塊；小標題（###+）不切，避免魔物設置段被切碎
            if len(h.group(1)) <= 2:
                flush()
            section = h.group(2).strip()
        buf.append(line)
    flush()
    return blocks


def chunk_pdf_english(path) -> list[dict]:
    """PyMuPDF 逐頁抽英文原文，一頁一塊（過長再切）。"""
    book = normalize_book(path.stem)
    blocks: list[dict] = []
    with fitz.open(path) as doc:
        for i, pg in enumerate(doc, start=1):
            text = pg.get_text("text").strip()
            if len(text) < 40:
                continue
            text = re.sub(r"[ \t]+", " ", text)
            for piece in split_long(text):
                blocks.append(
                    {"book": book, "page": i, "section": "", "lang": "en", "text": piece}
                )
    return blocks


CARD_DISPLAY = [  # (cards_hunters.json 欄位, 顯示標籤)
    ("card_type", "類型"), ("subtype", "子類型"), ("stamina_cost", "體力費用"),
    ("card_id", "卡號"), ("trait", "特性"), ("text", "效果"),
    ("level", "等級"), ("health", "生命"), ("element", "元素"),
    ("cost", "費用"), ("damage", "傷害"), ("deck_composition", "牌組構成"),
    ("faq", "FAQ"),
]


def _card_records_to_blocks(cards: list[dict]) -> list[dict]:
    """卡片紀錄 -> 檢索塊：每卡一塊（卡名進 section 吃標題加權）＋
    每獵人×卡號系列一個牌組清單塊。xlsm 與 JSON 兩種來源共用。"""
    book = "primal_database（卡表）"
    blocks: list[dict] = []
    decks: dict[str, dict[str, list[str]]] = {}  # hunter -> 卡號 -> [卡名]

    for i, c in enumerate(cards, start=1):
        name = c.get("name", "")
        if not name:
            continue
        category, hunter = c.get("category", ""), c.get("hunter", "")
        head = f"【卡牌】{name}"
        owner = f"{category}／{hunter}" if hunter else category
        lines = [f"{head}（{owner}）" if owner else head]
        for key, label in CARD_DISPLAY:
            v = c.get(key)
            if v:
                lines.append(f"{label}：{v}")
        blocks.append({
            "book": book, "page": i,
            "section": f"{name}（{hunter or category}）",
            "lang": "en", "text": "\n".join(lines),
        })
        if hunter:
            tier = str(c.get("card_id") or c.get("level") or "?")
            decks.setdefault(hunter, {}).setdefault(tier, []).append(name)

    # 每個獵人×每個卡號系列一塊（避免一人一大塊被 BM25 長度懲罰壓低）：
    # S = 起始牌組；字母開頭卡號（A1、B2…）依字母歸入專精系列；其餘依原值
    for hunter, tiers in decks.items():
        groups: dict[str, list[str]] = {}
        for tier, names in tiers.items():
            if tier == "S":
                key = "起始牌組（Starter deck，卡號 S）"
            elif tier[:1].isalpha() and len(tier) <= 3:
                key = f"專精 {tier[0]} 系列（Mastery {tier[0]}）"
            else:
                key = f"卡號/等級 {tier}"
            groups.setdefault(key, []).extend(f"{n}（{tier}）" for n in names)
        for key, names in groups.items():
            blocks.append({
                "book": book, "page": 0,
                "section": f"{hunter} {key} 牌組清單（deck list）",
                "lang": "en",
                "text": f"【牌組清單】獵人 {hunter}・{key}，共 {len(names)} 張：\n"
                        + "、".join(names),
            })
    return blocks


def chunk_cards_xlsm(path) -> list[dict]:
    """解析 primal_database.xlsm 的 Cards 表（Hunters/Campaign sheet 為玩家存檔，不收錄）。"""
    from export_cards import parse_xlsm
    return _card_records_to_blocks(parse_xlsm(path))


def chunk_cards_json(path) -> list[dict]:
    """解析 cards_hunters.json（export_cards.py 自 xlsm 匯出；無 xlsm 時的替代來源）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _card_records_to_blocks(data.get("cards", []))


def chunk_cards_extra(path) -> list[dict]:
    """解析 cards_extra.json（擴充獵人卡補充，如 Heart of the Wild 的 Drusk/Zaraya）。

    來源是規則書牌組列表：卡名（英＋中）與牌組分佈完整，效果全文僅在實體卡上，
    使用者可自行在 JSON 的 text 欄補上後重建索引。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    book = "cards_extra（擴充卡表補充）"
    tier_label = {"S": "起始牌組", "1": "等級 1", "2": "等級 2", "3": "等級 3"}
    blocks: list[dict] = []
    decks: dict[str, dict[str, list[str]]] = {}

    for i, c in enumerate(data.get("cards", []), start=1):
        name, zh, hunter = c["name"], c.get("name_zh", ""), c["hunter"]
        text = c.get("text") or "未收錄——效果全文僅見實體卡，可在 cards_extra.json 補上"
        blocks.append({
            "book": book, "page": i,
            "section": f"{name}（{hunter}）",
            "lang": "en",
            # 牌組分佈用緊湊代號（S/1/2/3），避免每張卡都帶「等級/起始牌組」
            # 關鍵詞、在牌組清單類問題上蓋過清單塊
            "text": f"【卡牌】{name}（{zh}）（Hunter／{hunter}）\n"
                    f"Decks: {'/'.join(c.get('decks', []))}\n效果：{text}",
        })
        for t in c.get("decks", []):
            label = f"{name}（{zh}）" if zh else name
            decks.setdefault(hunter, {}).setdefault(t, []).append(label)

    # 每個獵人×每個等級一個清單塊：段落標題與「Drusk 等級 2 牌組」這類問法直接對上，
    # 避免合併成大塊後被 BM25 長度懲罰壓過單卡條目
    mechanics = data.get("hunter_mechanics", {})
    for hunter, tiers in decks.items():
        for t in sorted(tiers):
            label = tier_label.get(t, t)
            lines = [f"【牌組清單】獵人 {hunter} {label} 牌組（deck list），共 {len(tiers[t])} 張："]
            if hunter in mechanics:
                lines.append(f"機制定位：{mechanics[hunter]}")
            lines.append("、".join(tiers[t]))
            blocks.append({
                "book": book, "page": 0,
                "section": f"{hunter} {label} 牌組清單（deck list）",
                "lang": "en", "text": "\n".join(lines),
            })
    return blocks


def chunk_monsters(path) -> list[dict]:
    """解析 monsters.json（魔物總表，彙整自規則書）。

    每隻魔物一個 chunk（名字進 section 吃標題加權），
    另依元素分組產生「XX屬魔物」總覽 chunk。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    book = "monsters（魔物總表）"
    blocks: list[dict] = []
    by_element: dict[str, list[str]] = {}

    for i, m in enumerate(data.get("monsters", []), start=1):
        name, zh = m["name"], m.get("name_zh", "")
        # 每隻魔物拆成「魔物資料」與「遠征設置」兩塊：
        # 塊太長會被 BM25 長度懲罰壓低，拆開後各自的問法能直接命中
        lines = [f"【魔物】{name}（{zh}）",
                 f"元素屬性：{m.get('element', '未知')}",
                 f"所屬產品：{m.get('expansion', '未知')}",
                 f"自創劇本地形限制：{m.get('terrain', '未收錄')}"]
        for rule in m.get("special_rules", []):
            lines.append(f"特殊規則：{rule}")
        nv = m.get("nightmare_variant")
        if nv not in (None, "", "未知"):
            lines.append(f"夢魘變體：{'有' if nv is True or nv == 'true' else nv}")
        for q in m.get("faq", []):
            lines.append(f"FAQ：{q}")
        if m.get("sources"):
            lines.append("出處：" + "；".join(m["sources"]))
        blocks.append({
            "book": book, "page": i,
            "section": f"{name}（{zh}）魔物資料",
            "lang": "zh", "text": "\n".join(lines),
        })
        setups = m.get("expedition_setup", [])
        if setups:
            s_lines = [f"【魔物遠征設置】{name}（{zh}）遠征模式／場地設置：",
                       f"地形限制：{m.get('terrain', '未收錄')}"]
            s_lines += [f"設置：{s}" for s in setups]
            blocks.append({
                "book": book, "page": i,
                "section": f"{name}（{zh}）遠征模式設置",
                "lang": "zh", "text": "\n".join(s_lines),
            })
        elem = (m.get("element") or "未知").split("（")[0]
        by_element.setdefault(elem, []).append(f"{name}（{zh}）")

    for elem, names in by_element.items():
        blocks.append({
            "book": book, "page": 0,
            "section": f"{elem}屬魔物總覽（element roster）",
            "lang": "zh",
            "text": f"【魔物總覽】{elem}屬性的魔物共 {len(names)} 隻：" + "、".join(names),
        })
    return blocks


def render_pages(path) -> int:
    book = normalize_book(path.stem)
    out_dir = IMG_DIR / book
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    zoom = RENDER_DPI / 72
    with fitz.open(path) as doc:
        for i, pg in enumerate(doc, start=1):
            out = out_dir / f"page_{i:03d}.jpg"
            if out.exists():
                n += 1
                continue
            pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            pix.save(out, jpg_quality=80)
            n += 1
    return n


def main() -> None:
    chunks: list[dict] = []

    zh_files = sorted(ZH_DIR.glob("*.zh-TW.md"))
    for p in zh_files:
        chunks.extend(chunk_zh_markdown(p))
    print(f"[zh] {len(zh_files)} 份譯文 -> {len(chunks)} 塊")

    # 規則書＋玩家輔助＋（容錯）根目錄殘留的 PDF
    pdfs = sorted(
        {p for d in (RULEBOOKS_DIR, AIDS_DIR, BOOKS_DIR) if d.exists()
         for p in d.glob("*.pdf")}
    )
    n_en = 0
    for p in pdfs:
        blocks = chunk_pdf_english(p)
        chunks.extend(blocks)
        n_en += len(blocks)
    print(f"[en] {len(pdfs)} 本 PDF -> {n_en} 塊")

    cards_path = CARDS_DIR / "primal_database.xlsm"
    cards_json = CARDS_DIR / "cards_hunters.json"
    if cards_path.exists():
        card_blocks = chunk_cards_xlsm(cards_path)
        chunks.extend(card_blocks)
        print(f"[卡表] {cards_path.name} -> {len(card_blocks)} 塊")
    elif cards_json.exists():
        card_blocks = chunk_cards_json(cards_json)
        chunks.extend(card_blocks)
        print(f"[卡表] {cards_json.name}（JSON 匯出）-> {len(card_blocks)} 塊")

    extra_path = CARDS_DIR / "cards_extra.json"
    if extra_path.exists():
        extra_blocks = chunk_cards_extra(extra_path)
        chunks.extend(extra_blocks)
        print(f"[卡表補充] {extra_path.name} -> {len(extra_blocks)} 塊")

    monsters_path = CARDS_DIR / "monsters.json"
    if monsters_path.exists():
        monster_blocks = chunk_monsters(monsters_path)
        chunks.extend(monster_blocks)
        print(f"[魔物總表] {monsters_path.name} -> {len(monster_blocks)} 塊")

    variants_dir = BOOKS_DIR / "variants"
    if variants_dir.exists():
        n_var = 0
        for p in sorted(variants_dir.glob("*.md")):
            blocks = chunk_zh_markdown(p)
            for b in blocks:  # 標明非官方，避免與官方規則混淆
                b["book"] = f"{normalize_book(p.stem)}（自製變體，非官方）"
            chunks.extend(blocks)
            n_var += len(blocks)
        if n_var:
            print(f"[變體規則] variants/ -> {n_var} 塊")

    for i, c in enumerate(chunks):
        c["id"] = i
    with CHUNKS_PATH.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"索引寫入 {CHUNKS_PATH}（共 {len(chunks)} 塊）")

    if "--no-images" in sys.argv:
        print("略過頁面圖渲染（--no-images）")
        return
    total = 0
    for p in pdfs:
        total += render_pages(p)
        print(f"[img] {p.name} 渲染完成")
    print(f"頁面圖共 {total} 張 -> {IMG_DIR}")


if __name__ == "__main__":
    main()
