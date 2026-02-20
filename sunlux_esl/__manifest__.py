# -*- coding: utf-8 -*-
{
    'name': 'SUNLUX ESL Integration',
    'version': '1.0.0',
    'category': 'Sales/Point of Sale',
    'summary': 'Sync Odoo products to SUNLUX Electronic Shelf Labels',
    'depends': ['point_of_sale', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'views/sunlux_esl_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
