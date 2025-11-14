# application/bookbot.py
# pyright: reportAttributeAccessIssue=false, reportUnknownMemberType=false

import os, json, re, difflib, unicodedata
from typing import Any, Dict, Optional

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
