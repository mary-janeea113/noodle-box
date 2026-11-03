"""POS operations: checkout, friend vouchers, prepaid passes and redemption."""

import json
import secrets
import sqlite3
import string

from models import db_session


class POSProblem(ValueError):
    pass


def _event(connection, event_type, location_code, metadata=None):
    connection.execute(
        "INSERT INTO events (event_type, location_code, metadata) VALUES (?, ?, ?)",
        (event_type, location_code, json.dumps(metadata or {}, separators=(",", ":"))),
    )


def _code(connection, prefix, length=6):
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        value = f"{prefix}-{''.join(secrets.choice(alphabet) for _ in range(length))}"
        if not connection.execute("SELECT 1 FROM vouchers WHERE code = ?", (value,)).fetchone():
            return value
    raise RuntimeError("Unable to create a unique code")


def _order_code():
    return "NB-" + secrets.token_hex(4).upper()


def apply_date_night_discount(cart_items):
    """Apply one free, lowest-priced drink when a cart has exactly two noodle cups.

    ``cart_items`` uses the internal shape produced by ``checkout``: each row has
    ``id``, ``product`` (with ``category`` and ``price_cents``), and ``quantity``.
    The result identifies the one discounted product and total discount in cents.
    """
    cup_count = sum(item["quantity"] for item in cart_items if item["product"]["category"] == "noodle")
    drinks = [item for item in cart_items if item["product"]["category"] == "drink"]
    if cup_count != 2 or not drinks:
        return {"discount_cents": 0, "deal_type": "standard", "discounted_product_id": None}
    cheapest = min(drinks, key=lambda item: item["product"]["price_cents"])
    return {"discount_cents": cheapest["product"]["price_cents"],
            "deal_type": "date_night", "discounted_product_id": cheapest["id"]}


def _add_transaction(connection, location_code, transaction_type, amount_cents, discount_cents, deal_type):
    code = _order_code()
    cursor = connection.execute(
        """INSERT INTO transactions
           (order_code, location_code, transaction_type, amount_cents, discount_cents, deal_type)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (code, location_code, transaction_type, amount_cents, discount_cents, deal_type),
    )
    return cursor.lastrowid, code


def checkout(item_ids, quantities, location_code):
    """Charge in clearly labelled test mode and apply the 2-cup drink deal."""
    if not item_ids or len(item_ids) != len(quantities):
        raise POSProblem("Add at least one product to the cart.")
    items = []
    with db_session() as connection:
        for raw_id, raw_quantity in zip(item_ids, quantities):
            try:
                product_id, quantity = int(raw_id), int(raw_quantity)
            except (TypeError, ValueError):
                raise POSProblem("Choose valid products and quantities.")
            if quantity < 1 or quantity > 20:
                raise POSProblem("Quantity must be between 1 and 20.")
            product = connection.execute(
                "SELECT * FROM products WHERE id = ? AND active = 1 AND category IN ('noodle', 'drink')",
                (product_id,),
            ).fetchone()
            if not product:
                raise POSProblem("That product is not available for checkout.")
            if product["stock"] < quantity:
                raise POSProblem(f"Only {product['stock']} {product['name']} in stock.")
            existing = next((item for item in items if item["id"] == product_id), None)
            if existing:
                existing["quantity"] += quantity
                if existing["quantity"] > product["stock"]:
                    raise POSProblem(f"Only {product['stock']} {product['name']} in stock.")
            else:
                items.append({"id": product_id, "product": product, "quantity": quantity})

        deal = apply_date_night_discount(items)
        discount = deal["discount_cents"]
        deal_type = deal["deal_type"]

        subtotal = sum(item["product"]["price_cents"] * item["quantity"] for item in items)
        amount = subtotal - discount
        transaction_id, order_code = _add_transaction(
            connection, location_code, "sale", amount, discount, deal_type
        )
        discount_item_id = deal["discounted_product_id"]
        discount_written = False
        for item in items:
            product = item["product"]
            line_discount = 0
            if deal_type == "date_night" and item["id"] == discount_item_id and not discount_written:
                line_discount = discount
                discount_written = True
            connection.execute(
                """INSERT INTO transaction_items
                   (transaction_id, product_id, product_name, brand, category, quantity, unit_price_cents, discount_cents)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (transaction_id, product["id"], product["name"], product["brand"], product["category"], item["quantity"], product["price_cents"], line_discount),
            )
            connection.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (item["quantity"], product["id"]))
        _event(connection, "sale", location_code, {"order_code": order_code, "amount_cents": amount, "deal_type": deal_type})
        return {"id": transaction_id, "order_code": order_code, "amount_cents": amount,
                "discount_cents": discount, "deal_type": deal_type,
                "items": [{"name": item["product"]["name"], "quantity": item["quantity"]} for item in items]}


def purchase_for_friend(order_id, friend_name, location_code=None, product_id=None):
    """Create a paid, printable one-cup friend voucher linked to an earlier order."""
    friend_name = (friend_name or "").strip()[:80]
    if not friend_name:
        raise POSProblem("Enter your friend's name.")
    with db_session() as connection:
        parent = connection.execute(
            "SELECT * FROM transactions WHERE order_code = ? OR CAST(id AS TEXT) = ?",
            (str(order_id), str(order_id)),
        ).fetchone()
        if not parent:
            raise POSProblem("The original order was not found. Make a sale first.")
        location_code = location_code or parent["location_code"]
        if product_id:
            product = connection.execute("SELECT * FROM products WHERE id = ? AND active = 1 AND category = 'noodle'", (int(product_id),)).fetchone()
        else:
            product = connection.execute("SELECT * FROM products WHERE active = 1 AND category = 'noodle' ORDER BY price_cents LIMIT 1").fetchone()
        if not product or product["stock"] < 1:
            raise POSProblem("A noodle cup is not in stock for this voucher.")
        transaction_id, order_code = _add_transaction(
            connection, location_code, "friend_purchase", product["price_cents"], 0, "friend_voucher"
        )
        connection.execute(
            """INSERT INTO transaction_items
               (transaction_id, product_id, product_name, brand, category, quantity, unit_price_cents)
               VALUES (?, ?, ?, ?, 'noodle', 1, ?)""",
            (transaction_id, product["id"], product["name"], product["brand"], product["price_cents"]),
        )
        connection.execute("UPDATE products SET stock = stock - 1 WHERE id = ?", (product["id"],))
        voucher_code = _code(connection, "FRIEND")
        connection.execute(
            """INSERT INTO vouchers
               (code, voucher_type, transaction_id, product_id, friend_name, redemptions_total, redemptions_remaining)
               VALUES (?, 'friend', ?, ?, ?, 1, 1)""",
            (voucher_code, transaction_id, product["id"], friend_name),
        )
        _event(connection, "friend_voucher_created", location_code, {"code": voucher_code, "friend_name": friend_name, "order_code": order_code})
        _event(connection, "sale", location_code, {"order_code": order_code, "amount_cents": product["price_cents"], "deal_type": "friend_voucher"})
        return {"id": transaction_id, "order_code": order_code, "code": voucher_code,
                "friend_name": friend_name, "amount_cents": product["price_cents"]}


def purchase_pass(product_id, location_code):
    with db_session() as connection:
        product = connection.execute(
            "SELECT * FROM products WHERE id = ? AND active = 1 AND category = 'pass'", (int(product_id),)
        ).fetchone()
        if not product or product["stock"] < 1:
            raise POSProblem("The 5-Day Noodle Pass is not available right now.")
        transaction_id, order_code = _add_transaction(
            connection, location_code, "pass_purchase", product["price_cents"], 0, "5_day_pass"
        )
        connection.execute(
            """INSERT INTO transaction_items
               (transaction_id, product_id, product_name, brand, category, quantity, unit_price_cents)
               VALUES (?, ?, ?, ?, 'pass', 1, ?)""",
            (transaction_id, product["id"], product["name"], product["brand"], product["price_cents"]),
        )
        connection.execute("UPDATE products SET stock = stock - 1 WHERE id = ?", (product["id"],))
        code = _code(connection, "PASS")
        total = product["redemptions_total"] or 5
        connection.execute(
            """INSERT INTO vouchers
               (code, voucher_type, transaction_id, redemptions_total, redemptions_remaining)
               VALUES (?, 'pass', ?, ?, ?)""",
            (code, transaction_id, total, total),
        )
        _event(connection, "pass_purchased", location_code, {"code": code, "order_code": order_code, "redemptions_total": total})
        _event(connection, "sale", location_code, {"order_code": order_code, "amount_cents": product["price_cents"], "deal_type": "5_day_pass"})
        return {"id": transaction_id, "order_code": order_code, "code": code,
                "amount_cents": product["price_cents"], "remaining": total}


def redeem_code(code, location_code):
    code = (code or "").strip().upper()
    with db_session() as connection:
        voucher = connection.execute("SELECT * FROM vouchers WHERE code = ?", (code,)).fetchone()
        if not voucher:
            raise POSProblem("Voucher code not found.")
        if voucher["redemptions_remaining"] <= 0:
            raise POSProblem("This code has no redemptions remaining.")
        if voucher["voucher_type"] == "friend":
            product = connection.execute("SELECT * FROM products WHERE id = ? AND active = 1", (voucher["product_id"],)).fetchone()
        else:
            product = connection.execute("SELECT * FROM products WHERE active = 1 AND category = 'noodle' ORDER BY price_cents LIMIT 1").fetchone()
        if not product or product["category"] != "noodle" or product["stock"] < 1:
            raise POSProblem("No noodle cups are currently in stock for redemption.")
        transaction_id, order_code = _add_transaction(
            connection, location_code, "redemption", 0, product["price_cents"], f"{voucher['voucher_type']}_redemption"
        )
        connection.execute(
            """INSERT INTO transaction_items
               (transaction_id, product_id, product_name, brand, category, quantity, unit_price_cents, discount_cents)
               VALUES (?, ?, ?, ?, 'noodle', 1, ?, ?)""",
            (transaction_id, product["id"], product["name"], product["brand"], product["price_cents"], product["price_cents"]),
        )
        connection.execute("UPDATE products SET stock = stock - 1 WHERE id = ?", (product["id"],))
        connection.execute("UPDATE vouchers SET redemptions_remaining = redemptions_remaining - 1 WHERE id = ?", (voucher["id"],))
        event_type = "pass_redeemed" if voucher["voucher_type"] == "pass" else "friend_voucher_redeemed"
        _event(connection, event_type, location_code, {"code": code, "order_code": order_code, "remaining": voucher["redemptions_remaining"] - 1})
        return {"id": transaction_id, "order_code": order_code, "code": code,
                "product_name": product["name"], "voucher_type": voucher["voucher_type"],
                "remaining": voucher["redemptions_remaining"] - 1}
