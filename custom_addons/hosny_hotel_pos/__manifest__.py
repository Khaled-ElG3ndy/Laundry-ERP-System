# -*- coding: utf-8 -*-
{
    'name': 'Hotel Contract Pricing - Farha Laundry',
    'version': '17.0.4.0.0',
    'category': 'Point of Sale',
    'summary': 'A dedicated POS for hotel and company customers, priced from their agreed contracts',
    'description': """
Hotel & Company Sales
=====================
A point of sale of its own for contract customers, where the cashier picks the
customer and Odoo applies that customer's agreed prices. The retail POS is left
completely alone.

* one shared catalogue of hotel linen services, no per-customer duplicates
* one pricelist per agreed price tier, plus customer-specific copies on demand
* customers are ordinary partners, filtered into the POS by a field
* the manual pricelist selector is hidden -- choosing a customer is the whole
  workflow
* selling is blocked until a contract customer is chosen, server-side as well
  as in the till
* prices are ordinary pricelist rules, editable in the backend; the price sheet
  is imported only when somebody explicitly asks for it
    """,
    'author': 'Farha Laundry',
    'website': '',
    'depends': [
        'point_of_sale',
        'product',
    ],
    'i18n': [
        'i18n/ar_001.po',
        'i18n/ar.po',
    ],
    'data': [
        'security/hotel_security.xml',
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/product_pricelist_views.xml',
        'views/pos_config_views.xml',
        'wizard/hotel_price_import_views.xml',
        'views/hotel_menus.xml',
        # Structure only -- runs on install and every upgrade, never writes a
        # price. Importing the price sheet is an explicit action.
        'data/hotel_setup.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'hosny_hotel_pos/static/src/js/hotel_pos.js',
            'hosny_hotel_pos/static/src/scss/pos_order_summary.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
