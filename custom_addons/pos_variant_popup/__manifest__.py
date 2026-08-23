{
    'name': 'POS Variant Popup',
    'version': '17.0.2.0.0',
    'category': 'Point of Sale',
    'summary': 'Show product variants as a popup in POS',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'pos_variant_popup/static/src/css/variant_popup.css',
            'pos_variant_popup/static/src/xml/variant_popup.xml',
            'pos_variant_popup/static/src/js/variant_popup.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
