# Main
# application/bookbot.py
# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false

import os, json, re, difflib, unicodedata
from typing import Any, Dict, Optional, List, Tuple

from flask import Blueprint, request, jsonify, render_template, current_app
from sqlalchemy import or_, func, desc, cast, Integer
import google.generativeai as genai

from application.database import db
from application.models import Product, Category

bookbot_bp = Blueprint("bookbot", __name__, template_folder="../templates")

# Lấy key một lần
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "Bạn là BookBot tư vấn sách bằng tiếng Việt. "
    "Trả lời ngắn gọn, lịch sự. Nếu không có dữ liệu trong kho thì nói thẳng là chưa có."
)

# Cột giá có thể có nhiều tên, liệt kê vài cái phổ biến
PRICE_ATTR_CANDIDATES = [
    "price", "gia", "giaban", "gia_ban", "gia_ban_ra",
    "price_sell", "sell_price", "unit_price",
    "price_sale", "gia_khuyen_mai",
]


# ----------------- Helpers -----------------
def _norm(s: str) -> str:
    """Hạ chữ thường + bỏ dấu tiếng Việt + gom khoảng trắng để so khớp intent ổn định."""
    if not s:
        return ""
    s = str(s).lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")  # bỏ dấu
    s = re.sub(r"[^a-z0-9\s]", " ", s)  # bỏ ký tự lạ
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _sent_split_vi(text: str) -> List[str]:
    """Tách câu đơn giản cho tiếng Việt."""
    if not text:
        return []
    parts = re.split(r"(?<=[\.\!\?…])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p and len(p.strip()) > 1]


def _fallback_bullets(text: str, max_bullets: int = 5, max_words: int = 28) -> List[str]:
    """Tóm tắt dự phòng: lấy 3–5 câu đầu, rút ngắn mỗi câu ~28 từ."""
    sents = _sent_split_vi(text)
    if not sents:
        return []
    bullets: List[str] = []
    for s in sents[:max_bullets]:
        ws = s.split()
        if len(ws) > max_words:
            s = " ".join(ws[:max_words]) + "…"
        bullets.append(s)
    return bullets


# Bọc Json vào câu trả lời của Gemini
def _extract_json(text: str) -> Optional[Dict]:
    """Bóc JSON từ chuỗi (kể cả khi Gemini trả kèm ```json ... ```)."""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    try:
        return json.loads(s)
    except Exception:
        return None


# ---------- TÓM TẮT DỰA TRÊN MÔ TẢ TRONG DB ----------
def _summarize_text_bullets(src_text: str, max_bullets: int = 7) -> List[str]:
    """
    TÓM TẮT nội dung sách dựa trên đoạn mô tả trong DB (an toàn, bám kho).
    Nếu lỗi hoặc thiếu API key thì fallback bằng cách cắt gọn mô tả.
    """
    if not src_text:
        return []
    source = src_text.strip()
    if len(source) > 4000:
        source = source[:4000] + "…"

    if not GEMINI_API_KEY:
        return _fallback_bullets(source, max_bullets)

    try:
        model_name = current_app.config.get("GEMINI_MODEL", "models/gemini-2.5-flash")
        model = genai.GenerativeModel(
            model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.3,
                "top_p": 0.9,
                "max_output_tokens": 896,  # cho phép trả lời dài hơn
            },
        )
        prompt = f"""
Bạn là BookBot. Nhiệm vụ: TÓM TẮT NỘI DUNG SÁCH BẰNG TIẾNG VIỆT, HẠN CHẾ SPOILER.
Chỉ sử dụng đúng đoạn Nguồn bên dưới, nhưng được phép diễn giải, tách ý, nối câu
sao cho dễ hiểu hơn, KHÔNG thêm sự kiện mới không có trong Nguồn.

Yêu cầu:
- Viết 4–8 gạch đầu dòng.
- Mỗi gạch dài khoảng 1–3 câu, mô tả rõ một ý/chương/bài học quan trọng.
- Văn phong tự nhiên, dễ hiểu.

Nguồn:
\"\"\"{source}\"\"\""

Trả JSON:
{{ "bullets": ["...", "..."] }}
"""
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        js = _extract_json(raw) or {}
        bullets = js.get("bullets") if isinstance(js, dict) else None
        if isinstance(bullets, list) and bullets:
            bullets = [str(x).strip() for x in bullets if str(x).strip()]
            return bullets[:max_bullets]
    except Exception:
        current_app.logger.exception("Gemini summarize error")

    # lỗi Gemini -> fallback
    return _fallback_bullets(source, max_bullets)


# ---------- TÓM TẮT OPEN-WORLD (DÙNG TÊN SÁCH + TÁC GIẢ, CÓ THỂ SPOIL) ----------
def _summarize_book_open_world(
    title: str,
    author: str,
    desc_hint: str = "",
    max_bullets: int = 7,
) -> List[str]:
    """
    Tóm tắt tương đối CHI TIẾT dựa trên tên sách + tác giả.
    Dùng khi description trong DB quá ngắn (chỉ vài chữ).
    Cho phép Gemini dùng kiến thức của nó về cuốn sách.
    """
    if not GEMINI_API_KEY:
        text = desc_hint or title
        if not text:
            return []
        return _fallback_bullets(text, max_bullets)

    try:
        model_name = current_app.config.get("GEMINI_MODEL", "models/gemini-2.5-flash")
        model = genai.GenerativeModel(
            model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.4,
                "top_p": 0.9,
                "max_output_tokens": 1024,
            },
        )
        prompt = f"""
Bạn là BookBot. Hãy tóm tắt tương đối chi tiết nội dung cuốn sách "{title}" của {author} bằng tiếng Việt.

Nếu bạn biết về cuốn sách này:
- Hãy dựa trên kiến thức của mình để mô tả các phần, ý tưởng, chương/bài học quan trọng.
Nếu bạn không chắc chắn:
- Hãy dựa trên gợi ý sau (nếu có): {desc_hint or "(không có gợi ý trong kho)"}.

Yêu cầu:
- Viết 4–8 gạch đầu dòng.
- Mỗi gạch dài khoảng 1–3 câu, giúp người đọc hiểu được sách nói về điều gì, học được điều gì.
- Hạn chế tiết lộ toàn bộ kết thúc, nhưng có thể nói khái quát những bài học/chủ đề chính.

Trả JSON:
{{ "bullets": ["...", "..."] }}
"""
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        js = _extract_json(raw) or {}
        bullets = js.get("bullets") if isinstance(js, dict) else None
        if isinstance(bullets, list) and bullets:
            bullets = [str(x).strip() for x in bullets if str(x).strip()]
            return bullets[:max_bullets]
    except Exception:
        current_app.logger.exception("Gemini open-world summarize error")

    text = desc_hint or title
    if not text:
        return []
    return _fallback_bullets(text, max_bullets)


# ---------- HỖ TRỢ TÌM SÁCH ĐỂ TÓM TẮT ----------
def _search_books_for_summary(user_text: str, limit: int = 5) -> List[Product]:
    """
    Tìm sách phù hợp để tóm tắt dựa trên câu người dùng.
    Dùng OR giữa các token để không quá khắt khe,
    bỏ bớt các từ vô nghĩa như 'cho', 'toi', 'cua'...
    """
    if not user_text:
        return []

    raw_words = re.split(r"\s+", user_text.strip())
    # stop words sau khi đã _norm (bỏ dấu, thường hóa)
    stop_norm = {
        "tom", "tat", "tom tat", "tong", "tong tat",
        "noi", "dung", "noi dung",
        "gioi", "thieu", "gioi thieu",
        "cuon", "quyen", "sach", "ve",
        "plot", "summary",
        # thêm mấy từ nói cho vui nhưng không giúp tìm sách
        "cho", "toi", "ban", "minh", "nha", "nhe", "giup", "cua", "xin", "hay",
    }

    tokens: List[tuple[str, str]] = []
    for w in raw_words:
        if not w:
            continue
        wn = _norm(w)
        if not wn:
            continue
        if wn in stop_norm:
            continue
        if len(wn) <= 1:
            continue
        tokens.append((w.strip(), wn))

    # Nếu lọc hết thì dùng cả câu gốc
    if not tokens:
        tokens = [(user_text.strip(), _norm(user_text))]

    P: Any = Product
    q = Product.query

    # Dùng OR giữa các token thay vì AND
    conds = []
    for orig, _ in tokens:
        like = f"%{orig}%"
        per_tok = []
        if hasattr(P, "name"):
            per_tok.append(P.name.ilike(like))
        if hasattr(P, "author"):
            per_tok.append(P.author.ilike(like))
        if hasattr(P, "description"):
            per_tok.append(P.description.ilike(like))
        if hasattr(P, "category"):
            per_tok.append(P.category.ilike(like))
        if per_tok:
            conds.append(or_(*per_tok))

    if conds:
        q = q.filter(or_(*conds))

    return q.limit(limit).all()


def _handle_summary_intent(user_text: str) -> Optional[Dict]:
    """
    Intent: người dùng muốn TÓM TẮT NỘI DUNG SÁCH.
    Ví dụ: "tóm tắt sách X", "cho mình plot cuốn Y", "nội dung Nhà giả kim"...
    """
    t = _norm(user_text)
    trigger = any(
        k in t
        for k in ["tom tat", "tong tat", "noi dung", "gioi thieu", "plot", "summary"]
    )
    if not trigger:
        return None

    books = _search_books_for_summary(user_text, limit=5)
    if not books:
        return {"answer": "Mình chưa tìm thấy tựa sách phù hợp để tóm tắt trong kho."}

    # làm sạch câu truy vấn đã bỏ từ khóa 'tóm tắt', 'nội dung', ...
    t_clean = re.sub(
        r"\b(tom tat|tong tat|noi dung|gioi thieu|plot|summary)\b", " ", t
    ).strip()

    best = None
    best_score = -1.0
    for b in books:
        name = _norm(getattr(b, "name", "") or "")
        score = difflib.SequenceMatcher(None, t_clean, name).ratio() if name else 0.0
        if score > best_score:
            best = b
            best_score = score

    # nếu nhiều kết quả mà độ giống quá thấp -> trả danh sách cho user chọn
    if len(books) > 1 and best_score < 0.35:
        opts = [
            {
                "title": getattr(x, "name", "N/A"),
                "author": getattr(x, "author", None) or "N/A",
                "qty": int(getattr(x, "quantity", 0) or 0),
            }
            for x in books[:5]
        ]
        return {
            "answer": "Mình tìm thấy vài tựa sách có thể trùng. Bạn muốn tóm tắt cuốn nào?",
            "books": opts,
        }

    if not best:
        return {"answer": "Mình chưa xác định được cuốn sách bạn muốn tóm tắt."}

    # Tóm tắt sách đã chọn
    desc = (getattr(best, "description", None) or "").strip()
    title = getattr(best, "name", "N/A")
    author = getattr(best, "author", None) or "N/A"
    qty = int(getattr(best, "quantity", 0) or 0)

    # Nếu description đủ dài -> tóm dựa trên description (bám kho)
    # Nếu quá ngắn -> cho phép Gemini tóm dựa trên tên sách + tác giả
    if desc and len(desc.split()) >= 25:
        bullets = _summarize_text_bullets(desc, max_bullets=7)
    else:
        bullets = _summarize_book_open_world(
            title, author, desc_hint=desc, max_bullets=7
        )

    if not bullets:
        if not desc:
            return {"answer": f"Chưa có dữ liệu để tóm tắt cho “{title}”."}
        return {
            "answer": f"Mình chưa thể tóm tắt “{title}” lúc này. Bạn thử lại sau nhé."
        }

    bullets_text = "\n- " + "\n- ".join(bullets)
    ans = f"Tóm tắt nhanh cho “{title}” của {author}:{bullets_text}"
    if qty > 0:
        ans += f"\nHiện trong kho còn khoảng {qty} bản."
    else:
        ans += "\nHiện sách này đang hết hàng hoặc chưa có thông tin số lượng."

    return {
        "answer": ans,  # để frontend cũ vẫn hiển thị được
        "summary": {
            "title": title,
            "author": author,
            "bullets": bullets,
            "in_stock": qty > 0,
            "qty": qty,
        },
    }


# ---------- HỖ TRỢ GIÁ ----------
def _price_expr_and_attr() -> Tuple[Optional[Any], Optional[str]]:
    """Tìm cột giá trong Product và trả (biểu thức, tên_attr)."""
    P: Any = Product
    for attr in PRICE_ATTR_CANDIDATES:
        if hasattr(P, attr):
            col = getattr(P, attr)
            # cast sang Integer cho an toàn (kể cả nếu là DECIMAL / VARCHAR)
            return func.coalesce(cast(col, Integer), 0), attr
    return None, None


def _get_price_value(prod: Product) -> Optional[int]:
    """Đọc giá từ đối tượng Product, thử nhiều tên field khác nhau."""
    for attr in PRICE_ATTR_CANDIDATES:
        if hasattr(Product, attr):
            val = getattr(prod, attr, None)
            if val is None:
                continue
            try:
                return int(val)
            except Exception:
                # nếu là chuỗi kiểu "120.000" thì bóc số
                s = re.sub(r"[^\d]", "", str(val))
                if s.isdigit():
                    return int(s)
    return None


def _format_vnd(v: Optional[int]) -> str:
    if v is None:
        return "N/A"
    try:
        v_int = int(v)
    except Exception:
        return str(v)
    return f"{v_int:,}".replace(",", ".") + "đ"


def _parse_budget_vnd(norm_text: str) -> Optional[int]:
    """
    Parse ngân sách từ text đã _norm (không dấu).
    Hỗ trợ: 100k, 150 nghin, 1tr, 1 trieu, 200000, ...
    """
    if not any(ch.isdigit() for ch in norm_text):
        return None

    pattern = re.compile(r"(\d+)\s*(k|nghin|ngan|trieu|tr|m)?")
    matches = pattern.findall(norm_text)
    if not matches:
        return None

    budgets: List[int] = []
    for num_str, unit in matches:
        try:
            n = int(num_str)
        except Exception:
            continue
        unit = (unit or "").lower()
        if unit in {"k", "nghin", "ngan"}:
            n *= 1000
        elif unit in {"trieu", "tr", "m"}:
            n *= 1_000_000
        budgets.append(n)

    if not budgets:
        return None
    # lấy số lớn nhất (ví dụ: "50k-100k" -> 100k)
    return max(budgets)


def _is_price_question(norm_text: str) -> bool:
    """Nhận diện câu hỏi liên quan đến GIÁ / NGÂN SÁCH."""
    kws = [
        "gia", "tien", "tai chinh", "ngan sach",
        "tiet kiem", "re", "dat", "khoang", "tam",
        "duoi", "tren", "bao nhieu tien",
    ]
    return any(k in norm_text for k in kws) and any(ch.isdigit() for ch in norm_text)


def _handle_price_intent(user_text: str, norm_text: str, budget: int) -> Dict:
    """
    Gợi ý sách theo NGÂN SÁCH (vd: 'tài chính tầm 100k gợi ý vài cuốn sách').
    Nếu user có nhắc đến thể loại thì lọc thêm theo thể loại.
    """
    price_expr, price_attr = _price_expr_and_attr()
    if price_expr is None:
        return {
            "answer": "Hệ thống chưa lưu thông tin giá sách nên mình chưa gợi ý theo tầm giá được.",
        }

    q = Product.query.filter(_qty_col() > 0).filter(price_expr <= budget)

    # Nếu có thể loại trong câu hỏi -> lọc thêm
    cat = _find_category(user_text)
    if cat:
        q = q.filter_by(category_id=cat.id)

    # Lấy tối đa 10 cuốn rẻ nhất trong tầm giá
    qs = q.order_by(price_expr.asc()).limit(10).all()
    fmt_budget = _format_vnd(budget)

    if not qs:
        if cat:
            return {
                "answer": (
                    f"Với ngân sách khoảng {fmt_budget}, hiện chưa có sách "
                    f"thuộc thể loại {cat.name} phù hợp (theo dữ liệu giá)."
                )
            }
        return {
            "answer": (
                f"Với ngân sách khoảng {fmt_budget}, mình chưa tìm được cuốn nào phù hợp "
                "trong kho (theo dữ liệu giá hiện tại)."
            )
        }

    books: List[Dict[str, Any]] = []
    for b in qs:
        title = getattr(b, "name", "N/A")
        author = getattr(b, "author", None) or "N/A"
        qty = int(getattr(b, "quantity", 0) or 0)
        price_val = _get_price_value(b)
        books.append(
            {
                "title": title,
                "author": author,
                "qty": qty,
                "price": price_val,
                "price_display": _format_vnd(price_val),
            }
        )

    # Câu trả lời text cho chatbot
    lines = [
        f"- {x['title']} — {x['author']} (~{x['price_display']})"
        for x in books
    ]
    if cat:
        heading = (
            f"Với ngân sách khoảng {fmt_budget}, sách thể loại {cat.name} trong kho "
            f"phù hợp nhất là:"
        )
    else:
        heading = (
            f"Với ngân sách khoảng {fmt_budget}, bạn có thể tham khảo một số sách sau:"
        )

    ans = heading + "\n" + "\n".join(lines)

    return {
        "answer": ans,
        "books": books,
        "budget": budget,
        "budget_display": fmt_budget,
        "filter": "price_lte",
    }


# ---------- SỐ LƯỢNG & THỂ LOẠI ----------
def _qty_col():
    """Cột số lượng an toàn kiểu số nguyên, tránh NULL/chuỗi."""
    if hasattr(Product, "quantity"):
        return func.coalesce(cast(Product.quantity, Integer), 0)
    return func.coalesce(cast(0, Integer), 0)


def _pick_catalog_slice(user_text: str, limit: int = 16) -> str:
    """Trích một lát danh mục từ kho để neo LLM (chỉ tên - tác giả - thể loại)."""
    like = f"%{user_text}%"
    P: Any = Product
    conds = []
    if hasattr(P, "name"):
        conds.append(P.name.ilike(like))
    if hasattr(P, "author"):
        conds.append(P.author.ilike(like))
    if hasattr(P, "description"):
        conds.append(P.description.ilike(like))
    if hasattr(P, "category"):
        conds.append(P.category.ilike(like))  # nếu category là string

    q = Product.query
    if conds:
        q = q.filter(or_(*conds))
    items = q.limit(limit).all()
    if not items:
        return ""

    lines = []
    for b in items:
        name = getattr(b, "name", "N/A")
        author = getattr(b, "author", None) or "N/A"
        cat = ""
        if hasattr(b, "category_id") and "Category" in globals():
            c = Category.query.get(getattr(b, "category_id"))
            cat = getattr(c, "name", "") if c else ""
        elif hasattr(b, "category"):
            cat = getattr(b, "category", "") or ""
        lines.append(f"- {name} — {author} — {cat}")
    return "\n".join(lines)


def _find_category(user_text: str) -> Optional[Category]:
    """Tìm thể loại khớp nhất trong DB dựa trên tên/synonyms đơn giản (đã bỏ dấu)."""
    txt = _norm(user_text)
    cats = Category.query.all()
    if not cats:
        return None

    # khớp trực tiếp theo substring
    for c in cats:
        cn = _norm(c.name)
        if cn and cn in txt:
            return c

    # fuzzy match
    names_norm = [_norm(c.name) for c in cats if c.name]
    cand = difflib.get_close_matches(txt, names_norm, n=1, cutoff=0.66)
    if cand:
        return next((c for c in cats if _norm(c.name) == cand[0]), None)

    # synonyms mở rộng (không dấu)
    SYN = {
        "thieu nhi": ["tre em", "nhi dong", "thieu nien", "mau giao", "hoat hinh"],
        "truyen tranh": ["comic", "manga", "cartoon"],
        "van hoc": ["tieu thuyet", "novel"],
        "khoa hoc vien tuong": ["sci fi", "science fiction"],
        "kinh te": ["business", "lam giau", "quan tri"],
        "tam ly": ["tam li", "tam ly", "psychology"],
    }
    for cat in cats:
        norm_name = _norm(cat.name)
        for k, arr in SYN.items():
            if norm_name == k and any(a in txt for a in arr):
                return cat
    return None


# --------------- DB-first intents ---------------
def _handle_inventory_intents(user_text: str) -> Optional[Dict]:
    t = _norm(user_text)

    # 0) Intent TÓM TẮT SÁCH (dùng Gemini)
    summary_res = _handle_summary_intent(user_text)
    if summary_res:
        return summary_res

    # 0.5) Intent GIÁ / NGÂN SÁCH
    budget = _parse_budget_vnd(t)
    if budget is not None and _is_price_question(t):
        return _handle_price_intent(user_text, t, budget)

    # 1) Đếm đầu sách, bản còn hàng
    if any(k in t for k in ["bao nhieu", "so luong", "tong", "co bao nhieu"]) and (
        "sach" in t or "dau sach" in t
    ):
        total_titles = db.session.query(Product.id).count()
        instock_titles = (
            db.session.query(Product.id).filter(_qty_col() > 0).count()
        )
        total_copies = (
            db.session.query(func.coalesce(func.sum(_qty_col()), 0))
            .select_from(Product)
            .scalar()
            or 0
        )
        ans = (
            f"Thư viện có {int(total_titles)} đầu sách; "
            f"{int(instock_titles)} đầu đang còn hàng (tổng số bản: {int(total_copies)})."
        )
        return {
            "answer": ans,
            "data": {
                "total_titles": int(total_titles),
                "in_stock_titles": int(instock_titles),
                "total_copies": int(total_copies),
            },
        }

    # 2) Hỏi theo MỘT thể loại cụ thể
    cat = _find_category(user_text)
    if cat:
        qs = (
            Product.query.filter_by(category_id=cat.id)
            .filter(_qty_col() > 0)
            .order_by(desc(_qty_col()))
            .limit(12)
            .all()
        )
        if not qs:
            return {"answer": f"Thể loại {cat.name} hiện chưa có sách còn hàng."}
        books = [
            {
                "title": getattr(b, "name", "N/A"),
                "author": getattr(b, "author", None) or "N/A",
                "qty": int(getattr(b, "quantity", 0) or 0),
            }
            for b in qs
        ]
        return {
            "answer": f"Sách thuộc thể loại {cat.name} đang có:",
            "books": books,
        }

    # 3) Liệt kê CÁC thể loại
    if ("the loai" in t) or ("danh muc" in t) or ("loai sach" in t) or (
        ("loai" in t) and ("sach" in t)
    ):
        rows = (
            db.session.query(Category.name, func.count(Product.id))
            .outerjoin(Product, Product.category_id == Category.id)
            .group_by(Category.id, Category.name)
            .order_by(Category.name.asc())
            .all()
        )
        if rows:
            cats = [{"category": n, "count": int(c)} for (n, c) in rows]
            ans = "Các thể loại hiện có: " + ", ".join(
                [f"{x['category']} ({x['count']})" for x in cats]
            )
            return {"answer": ans, "data": {"by_category": cats}}
        return {"answer": "Hệ thống chưa có dữ liệu thể loại."}

    # 4) “đang có / còn hàng / trong thư viện”
    if any(k in t for k in ["dang co", "con hang", "trong thu vien", "co san"]):
        qs = (
            Product.query.filter(_qty_col() > 0)
            .order_by(desc(_qty_col()))
            .limit(10)
            .all()
        )
        if not qs:
            return {"answer": "Kho hiện chưa có sách nào còn hàng."}
        books = [
            {
                "title": getattr(b, "name", "N/A"),
                "author": getattr(b, "author", None) or "N/A",
                "qty": int(getattr(b, "quantity", 0) or 0),
            }
            for b in qs
        ]
        return {
            "answer": f"Top {len(books)} sách đang còn hàng nhiều nhất:",
            "books": books,
        }

    return None


# --------------- API ---------------
@bookbot_bp.post("/api/bookbot")
def api_bookbot():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify(error="missing message"), 400

    # 1) DB-first: nếu bắt được intent thì trả lời trực tiếp từ DB/Gemini + DB
    grounded = _handle_inventory_intents(user_msg)
    if grounded:
        return jsonify(grounded), 200

    # 2) Tư vấn: dùng LLM nhưng buộc bám vào lát dữ liệu kho
    catalog = _pick_catalog_slice(user_msg)
    strict_rules = (
        "Quy tắc nghiêm ngặt:\n"
        "• Chỉ được đề xuất từ 'Danh mục kho' cung cấp bên dưới.\n"
        "• Nếu danh mục trống: recommendations = [] và trả về follow_up để hỏi thêm.\n"
        "• Cấm bịa tên sách không có trong danh mục.\n"
        "• Trả lời ngắn gọn: 1 câu tóm tắt + nhiều nhất 3 gợi ý.\n"
    )
    style = (
        "Phong cách: Nói thẳng trọng tâm, dùng gạch đầu dòng, "
        "ưu tiên sách trong kho."
    )
    prompt = f"""
{SYSTEM_INSTRUCTION}

{strict_rules}
{style}

Danh mục kho (top liên quan):
{catalog or "(trống)"}

Người dùng: {user_msg}

Trả JSON:
{{
  "recommendations": [
    {{"title": "...", "author": "...", "reason": "...", "in_stock": true}}
  ],
  "follow_up": "Câu hỏi ngắn để hiểu rõ hơn (nếu cần)"
}}
"""
    model_name = current_app.config.get("GEMINI_MODEL", "models/gemini-2.5-flash")
    model = genai.GenerativeModel(
        model_name,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "top_p": 0.8,
            "max_output_tokens": 512,
        },
    )
    resp = model.generate_content(prompt)
    text = (resp.text or "").strip()
    payload = _extract_json(text) or {"raw": text}
    return jsonify(payload), 200


@bookbot_bp.get("/chatbot")
def chatbot_page():
    return render_template("chatbot.html")
