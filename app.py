"""Noodle Box beta POS and investor dashboard."""

import hmac
import json
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from build_poster import render_poster
from config import settings
from models import db_session, init_db
from pos_logic import POSProblem, checkout, purchase_for_friend, purchase_pass, redeem_code
from qr_code import qr_svg


app = FastAPI(title="Noodle Box POS", version="1.0.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic(auto_error=False)


@app.on_event("startup")
def startup():
    init_db()


def _location(value: str | None) -> str:
    candidate = (value or settings.default_location_code).strip().upper()
    if not candidate or len(candidate) > 40:
        raise HTTPException(status_code=400, detail="Invalid location code")
    return candidate


def _admin(credentials: HTTPBasicCredentials | None = Depends(security)):
    expected = settings.admin_password
    valid = bool(expected and credentials and credentials.username == "admin" and hmac.compare_digest(credentials.password, expected))
    if not valid:
        if not expected:
            raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in the environment to enable the dashboard.")
        raise HTTPException(status_code=401, detail="Admin login required", headers={"WWW-Authenticate": "Basic"})
    return True


def _render(request, template, context, status_code=200):
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def _pos_data():
    with db_session() as connection:
        products = [dict(row) for row in connection.execute("SELECT * FROM products WHERE active = 1 ORDER BY category, brand, name")]
    return {
        "noodles": [product for product in products if product["category"] == "noodle"],
        "drinks": [product for product in products if product["category"] == "drink"],
        "passes": [product for product in products if product["category"] == "pass"],
    }


@app.get("/", response_class=HTMLResponse)
def pos_page(request: Request, location: str | None = None, error: str | None = None):
    data = _pos_data()
    return _render(request, "pos.html", {**data, "location": _location(location), "locations": settings.location_codes, "error": error})


@app.post("/checkout", response_class=HTMLResponse)
async def pos_checkout(request: Request):
    form = await request.form()
    location = _location(str(form.get("location_code") or ""))
    ids, quantities = [], []
    for raw_id, raw_quantity in zip(form.getlist("product_ids"), form.getlist("quantities")):
        if not str(raw_id).strip() or not str(raw_quantity).strip() or str(raw_quantity).strip() == "0":
            continue
        ids.append(raw_id)
        quantities.append(raw_quantity)
    try:
        sale = checkout(ids, quantities, location)
    except POSProblem as error:
        return pos_page(request, location, str(error))
    return RedirectResponse(f"/receipt/{sale['order_code']}", status_code=303)


@app.post("/friend", response_class=HTMLResponse)
async def buy_friend(request: Request):
    form = await request.form()
    location = _location(str(form.get("location_code") or ""))
    try:
        purchase = purchase_for_friend(form.get("order_id"), form.get("friend_name"), location, form.get("product_id") or None)
    except (POSProblem, ValueError) as error:
        return pos_page(request, location, str(error))
    return RedirectResponse(f"/receipt/{purchase['order_code']}", status_code=303)


@app.post("/pass", response_class=HTMLResponse)
async def buy_pass(request: Request):
    form = await request.form()
    location = _location(str(form.get("location_code") or ""))
    try:
        purchase = purchase_pass(form.get("product_id"), location)
    except (POSProblem, ValueError) as error:
        return pos_page(request, location, str(error))
    return RedirectResponse(f"/receipt/{purchase['order_code']}", status_code=303)


@app.get("/receipt/{order_code}", response_class=HTMLResponse)
def receipt(request: Request, order_code: str):
    with db_session() as connection:
        transaction = connection.execute("SELECT * FROM transactions WHERE order_code = ?", (order_code,)).fetchone()
        if not transaction:
            raise HTTPException(status_code=404, detail="Receipt not found")
        items = [dict(row) for row in connection.execute("SELECT * FROM transaction_items WHERE transaction_id = ?", (transaction["id"],))]
        voucher = connection.execute("SELECT * FROM vouchers WHERE transaction_id = ?", (transaction["id"],)).fetchone()
    return _render(request, "receipt.html", {"transaction": dict(transaction), "items": items, "voucher": dict(voucher) if voucher else None,
                                                 "location": transaction["location_code"]})


@app.get("/redeem", response_class=HTMLResponse)
def redeem_page(request: Request, location: str | None = None, error: str | None = None, result: str | None = None):
    return _render(request, "redeem.html", {"location": _location(location), "locations": settings.location_codes, "error": error, "result": result})


@app.post("/redeem", response_class=HTMLResponse)
async def redeem_submit(request: Request):
    form = await request.form()
    location = _location(str(form.get("location_code") or ""))
    try:
        redemption = redeem_code(form.get("code"), location)
    except POSProblem as error:
        return redeem_page(request, location, str(error))
    return RedirectResponse(f"/receipt/{redemption['order_code']}", status_code=303)


@app.get("/scan")
def scan(location: str | None = None):
    code = _location(location)
    with db_session() as connection:
        payload = json.dumps({"destination": settings.questionnaire_url})
        connection.execute("INSERT INTO events (event_type, location_code, metadata) VALUES ('poster_qr_hit', ?, ?)", (code, payload))
        connection.execute("INSERT INTO events (event_type, location_code, metadata) VALUES ('questionnaire_click', ?, ?)", (code, payload))
    return RedirectResponse(settings.questionnaire_url, status_code=307)


@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request, location: str | None = None, thanks: bool = False):
    return _render(request, "feedback.html", {"location": _location(location), "locations": settings.location_codes, "thanks": thanks, "error": None})


@app.post("/feedback", response_class=HTMLResponse)
async def feedback_submit(request: Request):
    form = await request.form()
    location = _location(str(form.get("location_code") or ""))
    try:
        rating = int(form.get("rating", ""))
        if not 1 <= rating <= 5:
            raise ValueError
    except (TypeError, ValueError):
        return _render(request, "feedback.html", {"location": location, "locations": settings.location_codes, "thanks": False,
                                                   "error": "Choose a rating from 1 to 5."}, 400)
    comment = str(form.get("comment", "")).strip()[:1000]
    with db_session() as connection:
        connection.execute("INSERT INTO feedback (rating, comment, location_code) VALUES (?, ?, ?)", (rating, comment, location))
        connection.execute("INSERT INTO events (event_type, location_code, metadata) VALUES ('feedback_submitted', ?, ?)",
                           (location, json.dumps({"rating": rating})))
    return RedirectResponse(f"/feedback?{urlencode({'location': location, 'thanks': 'true'})}", status_code=303)


@app.get("/poster", response_class=HTMLResponse)
def poster():
    # Fresh runtime poster respects PUBLIC_BASE_URL and DEFAULT_LOCATION_CODE.
    return HTMLResponse(render_poster())


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, location: str | None = None, _=Depends(_admin)):
    selected = "ALL" if (location or "").strip().upper() == "ALL" else _location(location)
    with db_session() as connection:
        known_locations = sorted(set(settings.location_codes + [row[0] for row in connection.execute(
            "SELECT location_code FROM transactions UNION SELECT location_code FROM feedback UNION SELECT location_code FROM events")]))
        known_locations.insert(0, "ALL")
        transaction_filter = "WHERE location_code = ?" if selected else ""
        args = (selected,) if selected else ()
        sales = connection.execute(
            f"SELECT COUNT(*) count, COALESCE(SUM(amount_cents), 0) revenue FROM transactions {transaction_filter} AND transaction_type IN ('sale','friend_purchase','pass_purchase')" if transaction_filter else
            "SELECT COUNT(*) count, COALESCE(SUM(amount_cents), 0) revenue FROM transactions WHERE transaction_type IN ('sale','friend_purchase','pass_purchase')",
            args,
        ).fetchone()
        if selected != "ALL":
            brand_rows = connection.execute(
                """SELECT brand, SUM(quantity) cups FROM transaction_items i JOIN transactions t ON t.id=i.transaction_id
                   WHERE i.category='noodle' AND t.location_code=? GROUP BY brand ORDER BY cups DESC, brand""", (selected,)
            ).fetchall()
            voucher_rows = connection.execute(
                """SELECT v.code,v.voucher_type,v.friend_name,v.redemptions_total,v.redemptions_remaining,t.location_code
                   FROM vouchers v JOIN transactions t ON t.id=v.transaction_id WHERE t.location_code=? ORDER BY v.created_at DESC""", (selected,)
            ).fetchall()
            deals = connection.execute("SELECT deal_type,COUNT(*) total FROM transactions WHERE location_code=? GROUP BY deal_type ORDER BY total DESC,deal_type", (selected,)).fetchall()
            event_rows = connection.execute("SELECT event_type,COUNT(*) total FROM events WHERE location_code=? GROUP BY event_type ORDER BY event_type", (selected,)).fetchall()
            transaction_rows = connection.execute("SELECT * FROM transactions WHERE location_code=? ORDER BY id DESC LIMIT 20", (selected,)).fetchall()
            feedback = connection.execute("SELECT COUNT(*) total, AVG(rating) average FROM feedback WHERE location_code=?", (selected,)).fetchone()
            products = connection.execute("SELECT * FROM products ORDER BY category,brand,name").fetchall()
        else:
            brand_rows = connection.execute("SELECT brand,SUM(quantity) cups FROM transaction_items WHERE category='noodle' GROUP BY brand ORDER BY cups DESC,brand").fetchall()
            voucher_rows = connection.execute("SELECT v.code,v.voucher_type,v.friend_name,v.redemptions_total,v.redemptions_remaining,t.location_code FROM vouchers v JOIN transactions t ON t.id=v.transaction_id ORDER BY v.created_at DESC").fetchall()
            deals = connection.execute("SELECT deal_type,COUNT(*) total FROM transactions GROUP BY deal_type ORDER BY total DESC,deal_type").fetchall()
            event_rows = connection.execute("SELECT event_type,COUNT(*) total FROM events GROUP BY event_type ORDER BY event_type").fetchall()
            transaction_rows = connection.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 20").fetchall()
            feedback = connection.execute("SELECT COUNT(*) total, AVG(rating) average FROM feedback").fetchone()
            products = connection.execute("SELECT * FROM products ORDER BY category,brand,name").fetchall()
        active_deal = deals[0] if deals else None
        return _render(request, "admin.html", {
            "selected": selected, "locations": known_locations, "sales_count": sales["count"], "revenue_cents": sales["revenue"],
            "brand_rows": [dict(row) for row in brand_rows], "voucher_rows": [dict(row) for row in voucher_rows],
            "deals": [dict(row) for row in deals], "popular_deal": active_deal["deal_type"] if active_deal else "—",
            "event_rows": [dict(row) for row in event_rows], "transactions": [dict(row) for row in transaction_rows],
            "feedback_count": feedback["total"], "feedback_average": feedback["average"],
            "products": [dict(row) for row in products], "error": request.query_params.get("error"),
        })


@app.post("/admin/products", response_class=HTMLResponse)
async def admin_product_save(request: Request, _=Depends(_admin)):
    form = await request.form()
    try:
        product_id = str(form.get("product_id", "")).strip()
        sku = str(form.get("sku", "")).strip().upper()[:30]
        brand = str(form.get("brand", "")).strip()[:80]
        name = str(form.get("name", "")).strip()[:100]
        category = str(form.get("category", "")).strip()
        price_cents = round(float(form.get("price", "0")) * 100)
        stock = int(form.get("stock", "0"))
        active = 1 if form.get("active") == "on" else 0
        if not sku or not brand or not name or category not in {"noodle", "drink", "pass"} or price_cents < 0 or stock < 0:
            raise ValueError
        with db_session() as connection:
            if product_id:
                connection.execute("UPDATE products SET sku=?,brand=?,name=?,category=?,price_cents=?,stock=?,active=? WHERE id=?",
                                   (sku, brand, name, category, price_cents, stock, active, int(product_id)))
            else:
                total = 5 if category == "pass" else 0
                connection.execute("INSERT INTO products (sku,brand,name,category,price_cents,stock,active,beta_seed,redemptions_total) VALUES (?,?,?,?,?,?,?,0,?)",
                                   (sku, brand, name, category, price_cents, stock, active, total))
    except Exception:
        return RedirectResponse("/admin?error=Check+SKU%2C+category%2C+price%2C+and+stock+values", status_code=303)
    return RedirectResponse("/admin", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}
