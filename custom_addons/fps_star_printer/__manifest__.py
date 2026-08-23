{
    'name': 'Fair Price Star TSP100 Printer',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Star TSP100 FuturePRNT Ethernet Printer Support',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'fps_star_printer/static/src/js/star_printer.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
