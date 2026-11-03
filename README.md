# Noodle Box beta POS

A server-rendered FastAPI POS for the Noodle Box university beta. It includes simulated payments, friend vouchers, a five-redemption prepaid pass, the 2-cup drink deal, feedback capture, scan analytics, an admin dashboard and a print-ready A5 poster.

**Payments are in TEST MODE. No payment provider is connected and no card is charged.** Catalogue prices and starting stock are beta placeholders. The seeded noodle brands are a test list, not verified sales rankings.

## Run locally

Python 3.11 or newer is recommended.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` before sharing the app. Set a private `ADMIN_PASSWORD` and replace `QUESTIONNAIRE_URL` with the questionnaire URL. The local default sends `/scan` to the app's feedback page. Start the app with:

```sh
uvicorn app:app --reload
```

Open <http://localhost:8000>. SQLite is created at `data/noodlebox.db`; the database and beta catalogue are initialized on first start. The admin page is at <http://localhost:8000/admin> and uses HTTP Basic login with username `admin` and the password from `ADMIN_PASSWORD`.

To create a standalone poster file using the current `.env` settings:

```sh
python build_poster.py
```

The app's `/poster` page always renders a current poster using `PUBLIC_BASE_URL` and `DEFAULT_LOCATION_CODE`. Print that page at 100% / actual size (A5). Its QR is an inline SVG made locally; there is no QR service or network dependency. Print width is 40 mm, above the 25 mm minimum.

## Cloud deploy: Render

The included `render.yaml` is a Render Blueprint for a Docker web service. It uses a 1 GB persistent disk mounted at `/var/data` for SQLite.

1. Push this project to a GitHub repository that Render can access.
2. In Render, select **New → Blueprint**, connect the repository, and apply `render.yaml`.
3. Enter the actual `QUESTIONNAIRE_URL` and set `PUBLIC_BASE_URL` after Render gives the service its public `https://…onrender.com` address. `ADMIN_PASSWORD` is generated as a secret by the Blueprint; set or rotate it in the service's Environment page if needed.
4. Wait for `/health` to report healthy. Open the assigned public URL, then `/admin` and sign in as `admin` with the configured password.
5. Open `/poster` at the deployed public address, print the poster, and scan its QR. It points to the deployed `/scan` route; that route logs the hit and redirects to `QUESTIONNAIRE_URL`.

Render currently allows persistent disks on paid web services; free web services cannot attach a disk. This Blueprint therefore selects the low-cost `starter` plan so the SQLite file survives restarts and deploys. The free tier can be used for a disposable preview, but its local filesystem is ephemeral and isn't suitable for retaining beta transactions. See [Render persistent disks](https://render.com/docs/disks) and [Render free service limits](https://render.com/docs/free).

The deployment can create a public URL, but it must be launched from a Render account connected to a Git repository. No hosting account or repository connection was provided with this workspace, so this kit is deployable but is not already running at a public URL.

## Configuration

| Variable | Purpose |
| --- | --- |
| `QUESTIONNAIRE_URL` | Destination for `/scan` redirects; change without reprinting only if existing QR URLs already point to this app's `/scan`. |
| `PUBLIC_BASE_URL` | Public app origin used to create the poster QR, for example `https://your-service.onrender.com`. |
| `ADMIN_PASSWORD` | Password for `/admin`; username is `admin`. Keep this in the host's secret settings. |
| `LOCATION_CODES` | Comma-separated locations available in POS forms and dashboard filters. |
| `DEFAULT_LOCATION_CODE` | Location selected by default and encoded into the poster QR. |
| `DATABASE_PATH` | SQLite file path. Set to `/var/data/noodlebox.db` when the Render disk is mounted. |

To swap the questionnaire later, update `QUESTIONNAIRE_URL` in Render and redeploy. The existing poster QR remains valid because it targets `/scan`. To change the public app domain, update `PUBLIC_BASE_URL` and print/download `/poster` again so its QR points at the new domain. To rotate the admin password, update `ADMIN_PASSWORD` in the Render service environment and redeploy.

## Products and locations

The first boot inserts a beta seed list of 10 noodle brands with editable placeholder prices and stock, two drinks for the date-night offer, and a five-redemption pass. In `/admin`, use the product editor to adjust SKU, brand, name, category, price, stock and active status; the form can also add products. Deactivate products by unchecking Active. Keep noodle products in the `noodle` category so sales and redemptions appear in cups-by-brand analytics. Stock is reduced for purchases and redemptions.

Set `LOCATION_CODES` to add locations (for example `LOC-UNI-01,LOC-APT-02,LOC-OFF-03`). POS, redemption, feedback and QR routes record the selected location. `/admin` filters the dashboard by one location or `ALL`.

## Features

- **Sell a cup:** select products and quantities, then take a simulated payment. Each order gets a receipt code.
- **Buy for a friend:** from a sale receipt, buy one additional cup for a named friend. It creates a paid `FRIEND-XXXXXX` voucher with one free redemption.
- **5-Day Pass:** purchase a pass to receive a unique `PASS-XXXXXX` code. Each redemption subtracts one; the app rejects a code at zero.
- **Date Night:** exactly two noodle cups plus any drink automatically discounts one lowest-priced drink to zero.
- **Admin dashboard:** sales count, revenue, cups by brand, popular deal type, voucher/pass usage, scan and feedback event counts, average rating, live transaction feed, location filter and editable catalogue.
- **Questionnaire analytics:** `/scan` logs a poster hit and questionnaire click before redirecting to `QUESTIONNAIRE_URL`.
- **Feedback:** `/feedback` records a 1–5 rating and free-text note in SQLite.

## Investor demo script

1. Open `/poster` and scan its QR. Show the redirect to the configured questionnaire; the dashboard records the poster hit and questionnaire click.
2. Open `/`, select `LOC-UNI-01`, add two noodle cups and an Orange Fizz, then submit **Take test payment**. Show the free drink and receipt code.
3. On the receipt, enter a friend's name and select **Buy a friend cup**. Show the printable `FRIEND-…` code.
4. Return to the POS, buy a 5-Day Pass, and redeem its `PASS-…` code five times at `/redeem`. Show that a sixth redemption is rejected.
5. Submit a rating at `/feedback`.
6. Open `/admin`, filter `LOC-UNI-01`, and show sales, revenue, cup brands, deal count, voucher/pass redemptions, scan and feedback events, rating and live feed.

## Data and limits

SQLite is appropriate for this single-instance beta. The attached Render disk supports one service instance; do not scale this deployment horizontally. Payments are simulated, and the public feedback form is unauthenticated. Treat product data and analytics as beta signals until real-world test operations confirm them.
