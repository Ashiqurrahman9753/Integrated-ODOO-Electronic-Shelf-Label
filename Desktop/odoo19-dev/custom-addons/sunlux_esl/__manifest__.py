# -*- coding: utf-8 -*-
{
    'name': 'Tag Display (SUNLUX ESL Integration)',
    'version': '19.0.1.2.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Sync Odoo products to SUNLUX Electronic Shelf Label (ESL) hardware',
    'description': """
Tag Display — SUNLUX ESL Integration
======================================
Connects Odoo 19 products to SUNLUX Electronic Shelf Label (ESL) hardware
via the SUNLUX REST API v1.5.

Key Features
------------
- Auto-syncs product name, price, stock, barcode to physical ESL tags
- Smart tag binding: assigns the first available tag of the preferred screen size
- Conflict resolution wizard: reassign a tag when all sizes are occupied
- Price discount support: set an original price to show a strikethrough on the tag
- Auto-refresh: Odoo Price Tags list updates live after each background sync
- Bulk sync and barcode generation from the product list view
- Full API audit log for every request/response
- Daily scheduled sync (disabled by default)

Configuration
-------------
Point of Sale → Settings → Tag Display section:
  - Base URL, UID, SID, Secret Key from your SUNLUX merchant portal
  - Test Connection button to verify credentials
  - Fetch Tags button to import physical tags from SUNLUX

Developer Notes
---------------
- Odoo 19 / Python 3.12 / PostgreSQL 15+
- Background sync uses a separate DB cursor with READ COMMITTED isolation
  and up to 4 retries on concurrency errors (LockNotAvailable, DeadlockDetected,
  SerializationFailure)
- Tag binding uses SELECT ... FOR UPDATE SKIP LOCKED to prevent race conditions
  when multiple products sync simultaneously
- Bus messages sent to all internal user partner channels trigger JS auto-refresh
  on the sunlux.esl.tag list view
    """,
    'author': 'Ashiqur Rahman',
    'depends': ['point_of_sale', 'product'],
    'assets': {
        'web.assets_backend': [
            'sunlux_esl/static/src/tag_list_auto_refresh.js',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/api_log_views.xml',
        'views/tag_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/tag_reassign_wizard_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
