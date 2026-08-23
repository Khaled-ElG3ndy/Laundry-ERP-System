{
    "name": "POS Laundry Variant Popup",
    "version": "17.0.2.0.1",
    "summary": "Laundry variant popup with multi-language support",
    "category": "Point of Sale",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "pos_laundry_receipt"],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_laundry_variant_popup/static/src/js/pos_laundry_variant_popup.js",
            "pos_laundry_variant_popup/static/src/xml/pos_laundry_variant_popup.xml",
            "pos_laundry_variant_popup/static/src/scss/pos_laundry_variant_popup.scss",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/product_template_views.xml",
    ],
    "i18n": [
        "i18n/pos_laundry_variant_popup.pot",
        "i18n/ar.po",
        "i18n/ar_001.po",
    ],
    "installable": True,
    "application": False,
}
