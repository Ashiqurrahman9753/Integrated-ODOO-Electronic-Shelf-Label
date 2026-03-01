# SUNLUX ESL — Odoo 19 Integration

Odoo 19 addon that syncs product data to SUNLUX Electronic Shelf Label displays.

---

## What you need

- Python 3.10+
- PostgreSQL 14+
- Odoo 19 source

---

## Setup

**1. Clone this repo**

```bash
git clone https://github.com/Ashiqurrahman9753/Integrated-ODOO-Electronic-Shelf-Label.git
cd Integrated-ODOO-Electronic-Shelf-Label
```

**2. Get Odoo 19**

```bash
git clone --depth=1 --branch 19.0 https://github.com/odoo/odoo.git
python -m venv odoo-venv
source odoo-venv/bin/activate        # Linux/Mac
# odoo-venv\Scripts\activate         # Windows
pip install -r odoo/requirements.txt
pip install requests
```

**3. Create the database**

Start fresh — Odoo will set up the schema on first run.

```bash
createdb your-db-name
```

**4. Create odoo.conf**

```ini
[options]
db_host = localhost
db_port = 5432
db_user = postgres
db_password = yourpassword
db_name = your-db-name
addons_path = odoo/addons,custom-addons
http_port = 8069
```

**5. Run**

```bash
python odoo/odoo-bin -c odoo.conf
```

Go to `http://localhost:8069`, log in, then **Apps → Update Apps List → search SUNLUX ESL → Install**.

---

## SUNLUX credentials

Go to **Settings → Point of Sale → Tag Display** and fill in:

- Base URL
- Merchant UID
- Platform SID
- Secret Key

*(credentials shared separately by the project owner)*

Click **Test Connection** — should show a green success message.

---

## After setup

- Go to **Point of Sale → ESL Tags → Fetch Tags** to pull in physical tags from the SUNLUX base station
- On any product, enable **Sync to ESL** and hit **Sync Now**
- Price/name changes auto-sync in the background
