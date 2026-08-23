# -*- coding: utf-8 -*-
{
    'name': 'Laundry Theme & Dashboard',
    'name_ar': 'واجهة المغسلة الاحترافية',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Premium Arabic-first laundry dashboard and UI',
    'author': 'TelNova Solutions',
    'license': 'LGPL-3',
    'icon': 'static/description/icon.png',
    'depends': ['laundry_base', 'web'],
    'data': [
        'views/laundry_dashboard_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'laundry_theme/static/src/css/laundry_theme.css',
            'laundry_theme/static/src/xml/laundry_dashboard.xml',
            'laundry_theme/static/src/js/laundry_dashboard.js',
            'laundry_theme/static/src/xml/laundry_new_order.xml',
            'laundry_theme/static/src/js/laundry_new_order.js',
            'laundry_theme/static/src/xml/widgets/order_line_picker.xml',
            'laundry_theme/static/src/js/widgets/order_line_picker.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
