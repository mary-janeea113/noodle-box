"""Beta seed catalogue. Prices and stock are placeholders for launch testing."""

SEED_PRODUCTS = [
    ("IND-MG", "Indomie", "Mi Goreng", "noodle", 299, 30),
    ("MAG-2M", "Maggi", "2-Minute Noodles", "noodle", 279, 30),
    ("SAM-BUL", "Samyang", "Buldak Fire Noodles", "noodle", 449, 20),
    ("NOG-SHIN", "Nongshim", "Shin Ramyun", "noodle", 399, 20),
    ("NIS-CUP", "Nissin", "Nissin Cup Noodles", "noodle", 349, 20),
    ("MAR-CUP", "Maruchan", "Maruchan Ramen", "noodle", 349, 20),
    ("FAN-ORI", "Fantastic Noodles", "Original Chicken", "noodle", 299, 25),
    ("MAM-TOM", "Mama", "Tom Yum Noodles", "noodle", 299, 25),
    ("YUM-ORI", "Yum Yum", "Original Noodles", "noodle", 279, 25),
    ("KOK-CUR", "Koka", "Curry Noodles", "noodle", 299, 20),
    ("DRK-WAT", "Noodle Box", "Still Water", "drink", 150, 50),
    ("DRK-ORG", "Noodle Box", "Orange Fizz", "drink", 200, 50),
    ("PASS-5D", "Noodle Box", "5-Day Noodle Pass", "pass", 1500, 100),
]


def seed_products(connection):
    connection.executemany(
        """INSERT OR IGNORE INTO products
           (sku, brand, name, category, price_cents, stock, active, beta_seed, redemptions_total)
           VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)""",
        [(*row, 5 if row[3] == "pass" else 0) for row in SEED_PRODUCTS],
    )
