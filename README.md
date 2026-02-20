# Integrated ODOO Electronic Shelf Label

A custom Odoo 19 addon module that integrates with the **SUNLUX ESL (Electronic Shelf Label)** system via the SUNLUX REST API v1.4. Automatically syncs product names, prices, barcodes, and discount information to physical ESL tags displayed on store shelves.

---

## Features

- **Auto-sync on save** — When a product with ESL sync enabled is saved, changes are pushed to the ESL tags in the background automatically
- **Manual sync button** — "Sync to ESL Now" button on each product form for immediate sync
- **Bulk sync** — Sync multiple products at once from the product list view via the Action menu
- **Discount price support** — Set an original/retail price to show a strikethrough price on the ESL tag (e.g. ~~€12.99~~ → **€9.99**)
- **Scheduled auto-sync** — Cron job runs periodically to keep all ESL-enabled products in sync
- **API call logging** — Every API call is logged with request/response data, status, duration, and product name
- **Token caching** — Bearer token is cached in system parameters and auto-refreshed before expiry
- **Real-time browser notifications** — Auto-sync triggers a subtle info notification in the Odoo UI

---

## Requirements

- Odoo 19.0
- Python packages: `requests`
- SUNLUX ESL account with API credentials (Base URL, UID, SID, Key)
- Depends on Odoo modules: `point_of_sale`, `product`

---

## Installation

1. Copy the `sunlux_esl` folder into your Odoo `custom-addons` directory
2. Add the path to `addons_path` in your `odoo.conf`
3. Restart Odoo with module update:
   ```bash
   python odoo-bin -c odoo.conf -u sunlux_esl
   ```
4. Install the module from **Settings > Apps**

---

## Configuration

Go to **Settings > Point of Sale > SUNLUX ESL Configuration** and enter:

| Field | Description |
|---|---|
| SUNLUX API Base URL | e.g. `https://tagdisplay.com` |
| Merchant UID | Your merchant user ID |
| Platform SID | Your platform store ID |
| Secret Key | Your API secret key |

Click **Test Connection** to verify credentials. A Bearer token will be fetched and cached automatically.

---

## Usage

### Enable ESL sync on a product

1. Open any product → **General Information** tab
2. Scroll down to the **SUNLUX ESL** section
3. Check **"Sync to ESL"**
4. *(Optional)* Set **"Original Price (ESL)"** to show a strikethrough discount price on the tag
5. Save — the product will auto-sync to the ESL system

### Price display logic

| `Original Price (ESL)` | ESL Tag shows |
|---|---|
| 0 or not set | `retailPrice = salePrice = Sales Price` |
| Set and > Sales Price | `retailPrice = Original Price` (strikethrough), `salePrice = Sales Price` |

### Bulk sync

From the **Products list view**, select multiple products → **Action > Sync to SUNLUX ESL**

---

## Module Structure

```
sunlux_esl/
├── __init__.py
├── __manifest__.py
├── data/
│   └── ir_cron.xml                  # Scheduled sync cron job
├── models/
│   ├── __init__.py
│   ├── product_template.py          # ESL fields, write() override, sync logic
│   ├── res_config_settings.py       # API credentials in Settings
│   ├── sunlux_esl_api.py            # SUNLUX REST API client (auth + data)
│   └── sunlux_esl_log.py            # API call log model
├── security/
│   └── ir.model.access.csv          # Access control rules
└── views/
    ├── product_template_views.xml   # ESL fields on product form
    ├── res_config_settings_views.xml # Settings panel
    └── sunlux_esl_log_views.xml     # Log list/form views
```

---

## API Endpoints Used

| Operation | Endpoint |
|---|---|
| Authenticate | `POST /epts-api/v2/sys/api/tToken` |
| Full product sync | `POST /epts-api/goods/goods/batch/edit?light=0` |
| Price-only sync | `POST /epts-api/goods/goods/batchPrice` |

Authentication uses **MD5 signature**: `md5(sid={sid}&key={key}&uid={uid}&timestamp={ts})`

---

## License

LGPL-3.0
