{
    'name': 'Fair Price POS Shortcuts',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Quick action buttons for cashiers',
    'description': 'Adds shortcut buttons: Cash Drawer, Manual Item, Reprint, Reports, etc.',
    'author': 'Fair Price Supermarket',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'fps_pos_shortcuts/static/src/css/shortcuts.css',
            'fps_pos_shortcuts/static/src/xml/shortcuts.xml',
            'fps_pos_shortcuts/static/src/js/shortcuts.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
