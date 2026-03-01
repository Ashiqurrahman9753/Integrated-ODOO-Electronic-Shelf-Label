# SUNLUX ESL — Odoo 19 Integration

Custom Odoo 19 addon that syncs product data (name, price, barcode) to SUNLUX Electronic Shelf Label displays via their REST API.

---

## What's in this repo

```
custom-addons/sunlux_esl/   ← the only thing you need to touch
```

Odoo core, the virtualenv, config, and logs are **not committed** — you set those up yourself (see below).

---

## Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Odoo 19 source (clone separately from [odoo/odoo](https://github.com/odoo/odoo))
- `pip install requests`

---

## Setup

**1. Clone this repo**

```bash
git clone https://github.com/Ashiqurrahman9753/Portfolio-ashiqur-rahman.git
cd Portfolio-ashiqur-rahman
```

**2. Get Odoo 19**

```bash
git clone --depth=1 --branch 19.0 https://github.com/odoo/odoo.git
python -m venv odoo-venv
odoo-venv/Scripts/activate      # Windows
# or: source odoo-venv/bin/activate   # Linux/Mac
pip install -r odoo/requirements.txt
pip install requests
```

**3. Create the database**

A sanitized database dump is shared separately (ask the project owner).
Restore it:

```bash
createdb your-db-name
pg_restore -d your-db-name path/to/test-pos.dump
```

Or start fresh — Odoo will create the schema on first run.

**4. Configure Odoo**

Create `odoo.conf` in the project root:

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
odoo-venv/Scripts/python odoo/odoo-bin -c odoo.conf
```

Open `http://localhost:8069`, log in, go to **Apps → Update Apps List**, search for **SUNLUX ESL**, and install.

---

## SUNLUX API credentials

After install, go to **Settings → Point of Sale → Tag Display** and enter:

| Field | Description |
|---|---|
| Base URL | `https://your-sunlux-server` |
| Merchant UID | provided by SUNLUX |
| Platform SID | provided by SUNLUX |
| Secret Key | provided by SUNLUX |

Hit **Test Connection** — you should get a green notification.

---

## Database dump note

The shared dump (`test-pos.dump`) contains live product and tag data from the development setup.
Credentials stored in `ir_config_parameter` have been cleared before export — you'll need to re-enter them in Settings after restore.

---

## Module overview

| File | Purpose |
|---|---|
| `models/product_template.py` | ESL fields on products, auto-sync on price/name change |
| `models/api_client.py` | HTTP client for SUNLUX REST API |
| `models/tag.py` | Local mirror of physical ESL tags |
| `models/api_log.py` | API call log model |
| `models/res_config_settings.py` | Credentials UI in Settings |
| `models/tag_reassign_wizard.py` | Wizard for reassigning tags between products |
