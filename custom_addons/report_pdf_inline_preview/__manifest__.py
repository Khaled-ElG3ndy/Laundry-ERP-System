{
    'name': 'PDF Report Inline Preview',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': 'Open QWeb PDF reports inline in the browser',
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'report_pdf_inline_preview/static/src/js/report_pdf_inline_handler.js',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
