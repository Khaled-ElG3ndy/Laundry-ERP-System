{
    'name': 'Fair Price Custom Receipt',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Custom receipt with SNAP/EBT breakdown',
    'depends': ['point_of_sale', 'fps_pos_snap'],
    'assets': {
        'point_of_sale._assets_pos': [
            'fps_receipt/static/src/xml/receipt.xml',
            'fps_receipt/static/src/js/receipt.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
