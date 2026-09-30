# -*- coding: utf-8 -*-
{
    'name': 'Laundry Inventory & Purchasing',
    'version': '17.0.1.6.4',
    'category': 'Inventory/Inventory',
    'summary': 'Branch warehouses, laundry supplies, material issues and purchasing',
    'description': """
Laundry Inventory & Purchasing
==============================

Gives every laundry branch a real warehouse with a proper zone layout, tracks
the supplies the branch consumes (chemicals, packaging, hangers, spare parts)
and covers the buying side end to end:

* one warehouse per branch, with storage zones and put-away rules per supply
  category;
* material issues from the branch store to operations, maintenance or
  housekeeping, posted as real stock moves so on-hand quantities stay true;
* consumption norms per service / item category, so an order can be costed and
  its materials issued in one click;
* internal purchase requests with an approval step that turn into vendor RFQs
  delivered straight to the requesting branch;
* reordering rules and a consumption analysis report.

Every label follows the user's own language (Arabic or English).
""",
    'author': 'TelNova Solutions',
    'website': 'https://telnovasolution.com',
    'license': 'LGPL-3',
    'depends': [
        'laundry_base',
        'stock',
        'stock_account',
        'purchase_stock',
    ],
    'data': [
        'security/laundry_stock_groups.xml',
        'security/ir.model.access.csv',
        'security/laundry_stock_rules.xml',
        'data/laundry_stock_sequence.xml',
        'data/product_category_data.xml',
        'data/laundry_supply_product_data.xml',
        'views/laundry_branch_views.xml',
        'views/product_views.xml',
        'views/laundry_machine_views.xml',
        'views/laundry_consumption_norm_views.xml',
        'views/laundry_stock_issue_views.xml',
        'wizard/laundry_pos_consumption_views.xml',
        'wizard/laundry_opening_stock_views.xml',
        'views/laundry_purchase_request_views.xml',
        'views/purchase_order_views.xml',
        'views/laundry_order_views.xml',
        'views/stock_views.xml',
        'report/laundry_consumption_report_views.xml',
        'views/laundry_stock_dashboard_views.xml',
        'views/laundry_stock_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'laundry_stock/static/src/css/laundry_stock_dashboard.css',
            'laundry_stock/static/src/xml/laundry_stock_icons.xml',
            'laundry_stock/static/src/xml/laundry_stock_dashboard.xml',
            'laundry_stock/static/src/js/laundry_stock_dashboard.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
