{
    "name": "POS Foam Modern UI",
    "version": "17.0.1.0.0",
    "summary": "Modern POS UI for laundry business",
    "description": """
Modern POS theme for laundry / foam business.
Improves product cards, left panel, buttons, categories, search, and payment area.
""",
    "category": "Point of Sale",
    "author": "Custom",
    "website": "",
    "license": "LGPL-3",
    "depends": ["point_of_sale"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_foam_modern_ui/static/src/css/pos_foam_modern_ui.css",
            "pos_foam_modern_ui/static/src/xml/pos_foam_modern_ui.xml",
            "pos_foam_modern_ui/static/src/js/smooth_closing.js",
            
        ],
    },
    "installable": True,
    "application": False,
}
