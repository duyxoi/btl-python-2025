# application/bookbot.py
# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false

import os, json, re, difflib, unicodedata
from typing import Any, Dict, Optional, List

from flask import Blueprint, request, jsonify, render_template, current_app
from sqlalchemy import or_, func, desc, cast, Integer
import google.generativeai as genai

from application.database import db
from application.models import Product, Category

bookbot_bp = Blueprint("bookbot", __name__, template_folder="../templates")
genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))

SYSTEM_INSTRUCTION = (
    "Bạn là BookBot tư vấn sách bằng tiếng Việt. "
    "Trả lời ngắn gọn, lịch sự. Nếu không có dữ liệu trong kho thì nói thẳng là chưa có."
)

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
    # tách theo . ! ? … và xuống dòng
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

def _summarize_text_bullets(src_text: str, max_bullets: int = 5) -> List[str]:
    """Ưu tiên LLM (Gemini) để tóm tắt an toàn từ mô tả; lỗi -> fallback."""
    if not src_text:
        return []
    source = src_text.strip()
    # tránh prompt quá dài
    if len(source) > 4000:
        source = source[:4000] + "…"
    # Nếu thiếu API key, fallback luôn
    if not os.getenv("GEMINI_API_KEY"):
        return _fallback_bullets(source, max_bullets)
    try:
        model_name = current_app.config.get("GEMINI_MODEL", "models/gemini-2.5-flash")
        model = genai.GenerativeModel(
            model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
                "top_p": 0.8,
                "max_output_tokens": 384,
            },
        )
        prompt = f"""
Bạn là BookBot. Nhiệm vụ: TÓM TẮT NỘI DUNG SÁCH BẰNG TIẾNG VIỆT, KHÔNG SPOILER.
Chỉ sử dụng đúng đoạn Nguồn bên dưới, cấm suy diễn/bổ sung ngoài Nguồn.
Đầu ra: 3–5 gạch đầu dòng ngắn gọn, súc tích.

Nguồn:
\"\"\"{source}\"\"\"

Trả JSON:
{{ "bullets": ["...", "..."] }}
"""
        resp = model.generate_content(prompt)
        js = _extract_json((resp.text or "").strip()) or {}
        bullets = js.get("bullets") if isinstance(js, dict) else None
        if isinstance(bullets, list) and bullets:
            # lọc rỗng và giới hạn số lượng
            bullets = [str(x).strip() for x in bullets if str(x).strip()]
            return bullets[:max_bullets]
    except Exception:
        current_app.logger.exception("Gemini summarize error")
    return _fallback_bullets(source, max_bullets)

def _search_books_for_summary(user_text: str, limit: int = 5) -> List[Product]:
    if not user_text:
        return []
    # Tách token từ bản gốc (giữ dấu), lọc bằng dạng _norm để bỏ từ nhiễu
    raw_words = re.split(r"\s+", user_text.strip())
    stop_norm = {
        "tom", "tat", "tom tat", "tong", "tong tat",
        "noi", "dung", "noi dung",
        "gioi", "thieu", "gioi thieu",
        "cuon", "quyen", "sach", "ve",
        "plot", "summary"
    }
    tokens: List[str] = []
    for w in raw_words:
        if not w:
            continue
        wn = _norm(w)
        if wn in stop_norm:
            continue
        # bỏ token quá ngắn
        if len(w.strip()) <= 1:
            continue
        tokens.append(w.strip())
    # fallback: nếu lọc hết thì dùng lại câu gốc
    if not tokens:
        tokens = [user_text.strip()]
    P: Any = Product
    q = Product.query
    # Mỗi token: phải xuất hiện ở ít nhất một trong các cột -> filter nối tiếp (AND)
    for tok in tokens:
        like = f"%{tok}%"
        per_tok = []
        if hasattr(P, "name"):        per_tok.append(P.name.ilike(like))
        if hasattr(P, "author"):      per_tok.append(P.author.ilike(like))
        if hasattr(P, "description"): per_tok.append(P.description.ilike(like))
        if hasattr(P, "category"):    per_tok.append(P.category.ilike(like))
        if per_tok:
            q = q.filter(or_(*per_tok))
    return q.limit(limit).all()

def _handle_summary_intent(user_text: str) -> Optional[Dict]:
    """Intent: tóm tắt nội dung sách theo từ khóa người dùng."""
    t = _norm(user_text)
    # từ khóa kích hoạt
    trigger = any(k in t for k in ["tom tat", "tong tat", "noi dung", "gioi thieu", "plot", "summary"])
    if not trigger:
        return None
    books = _search_books_for_summary(user_text, limit=5)
    if not books:
        return {"answer": "Mình chưa tìm thấy tựa sách phù hợp để tóm tắt trong kho."}
    # Chọn kết quả tốt nhất theo độ giống name với truy vấn đã bỏ từ khóa
    t_clean = re.sub(r"\b(tom tat|tong tat|noi dung|gioi thieu|plot|summary)\b", " ", t).strip()
    best = None
    best_score = -1.0
    for b in books:
        name = _norm(getattr(b, "name", "") or "")
        score = difflib.SequenceMatcher(None, t_clean, name).ratio() if name else 0.0
        if score > best_score:
            best = b; best_score = score
    # Nếu score quá thấp nhưng chỉ có 1 cuốn, vẫn tóm tắt; nếu >1 mà score thấp, liệt kê để người dùng chọn
    if len(books) > 1 and best_score < 0.35:
        opts = [{
            "title": getattr(x, "name", "N/A"),
            "author": getattr(x, "author", None) or "N/A",
            "qty": int(getattr(x, "quantity", 0) or 0)
        } for x in books[:5]]
        return {
            "answer": "Mình tìm thấy vài tựa sách có thể trùng. Bạn muốn tóm tắt cuốn nào?",
            "books": opts
        }
    # Tóm tắt từ mô tả
    desc = (getattr(best, "description", None) or "").strip()
    title = getattr(best, "name", "N/A")
    author = getattr(best, "author", None) or "N/A"
    qty = int(getattr(best, "quantity", 0) or 0)
    if not desc:
        return {"answer": f"Chưa có dữ liệu mô tả để tóm tắt cho “{title}”."}
    bullets = _summarize_text_bullets(desc, max_bullets=5)
    if not bullets:
        return {"answer": f"Mình chưa thể tóm tắt “{title}” lúc này. Bạn thử lại sau nhé."}
    return {
        "summary": {
            "title": title,
            "author": author,
            "bullets": bullets,
            "in_stock": qty > 0,
            "qty": qty
        }
    }

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
    if hasattr(P, "name"):        conds.append(P.name.ilike(like))
    if hasattr(P, "author"):      conds.append(P.author.ilike(like))
    if hasattr(P, "description"): conds.append(P.description.ilike(like))
    if hasattr(P, "category"):    conds.append(P.category.ilike(like))  # nếu category là string

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
        # nếu dùng quan hệ Category
        cat = ""
        if hasattr(b, "category_id") and "Category" in globals():
            c = Category.query.get(getattr(b, "category_id"))
            cat = getattr(c, "name", "") if c else ""
        elif hasattr(b, "category"):  # string
            cat = getattr(b, "category", "") or ""
        lines.append(f"- {name} — {author} — {cat}")
    return "\n".join(lines)

def _extract_json(text: str) -> Optional[Dict]:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        s = s[i:j+1]
    try:
        return json.loads(s)
    except Exception:
        return None

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
    summary_res = _handle_summary_intent(user_text)
    if summary_res:
        return summary_res
    # 1) Đếm đầu sách, bản còn hàng
    if any(k in t for k in ["bao nhieu", "so luong", "tong", "co bao nhieu"]) and ("sach" in t or "dau sach" in t):
        total_titles = db.session.query(Product.id).count()
        instock_titles = db.session.query(Product.id).filter(_qty_col() > 0).count()
        total_copies = db.session.query(func.coalesce(func.sum(_qty_col()), 0)).select_from(Product).scalar() or 0
        ans = f"Thư viện có {int(total_titles)} đầu sách; {int(instock_titles)} đầu đang còn hàng (tổng số bản: {int(total_copies)})."
        return {"answer": ans, "data": {
            "total_titles": int(total_titles),
            "in_stock_titles": int(instock_titles),
            "total_copies": int(total_copies),
        }}

    # 2) Hỏi theo MỘT thể loại cụ thể (vd: văn học, thiếu nhi…)
    cat = _find_category(user_text)
    if cat:
        qs = (Product.query
              .filter_by(category_id=cat.id)
              .filter(_qty_col() > 0)
              .order_by(desc(_qty_col()))
              .limit(12)
              .all())
        if not qs:
            return {"answer": f"Thể loại {cat.name} hiện chưa có sách còn hàng."}
        books = [{
            "title": getattr(b, "name", "N/A"),
            "author": getattr(b, "author", None) or "N/A",
            "qty": int(getattr(b, "quantity", 0) or 0)
        } for b in qs]
        return {"answer": f"Sách thuộc thể loại {cat.name} đang có:", "books": books}

    # 3) Liệt kê CÁC thể loại (chỉ khi KHÔNG khớp 1 thể loại cụ thể)
    if ("the loai" in t) or ("danh muc" in t) or ("loai sach" in t) or (("loai" in t) and ("sach" in t)):
        rows = (
            db.session.query(Category.name, func.count(Product.id))
            .outerjoin(Product, Product.category_id == Category.id)
            .group_by(Category.id, Category.name)
            .order_by(Category.name.asc())
            .all()
        )
        if rows:
            cats = [{"category": n, "count": int(c)} for (n, c) in rows]
            ans = "Các thể loại hiện có: " + ", ".join([f"{x['category']} ({x['count']})" for x in cats])
            return {"answer": ans, "data": {"by_category": cats}}
        return {"answer": "Hệ thống chưa có dữ liệu thể loại."}

    # 4) “đang có / còn hàng / trong thư viện”
    if any(k in t for k in ["dang co", "con hang", "trong thu vien", "co san"]):
        qs = (Product.query
              .filter(_qty_col() > 0)
              .order_by(desc(_qty_col()))
              .limit(10)
              .all())
        if not qs:
            return {"answer": "Kho hiện chưa có sách nào còn hàng."}
        books = [{
            "title": getattr(b, "name", "N/A"),
            "author": getattr(b, "author", None) or "N/A",
            "qty": int(getattr(b, "quantity", 0) or 0)
        } for b in qs]
        return {"answer": f"Top {len(books)} sách đang còn hàng nhiều nhất:", "books": books}

    return None

# --------------- API ---------------
@bookbot_bp.post("/api/bookbot")
def api_bookbot():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify(error="missing message"), 400

    # 1) DB-first: nếu bắt được intent thì trả lời trực tiếp từ DB
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
