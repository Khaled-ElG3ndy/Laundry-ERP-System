{
    'name': 'Custom POS Receipt',
    'version': '17.0.1.2.8',
    'depends': ['point_of_sale', 'l10n_sa_pos', 'pos_laundry_receipt'],
    'assets': {
        'point_of_sale._assets_pos': [
            'custom_pos_receipt/static/src/js/order_receipt.js',
            'custom_pos_receipt/static/src/css/receipt.css',
            'custom_pos_receipt/static/src/xml/receipt.xml',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
}
