{
    "name": "POS Laundry Variant Popup",
    "version": "17.0.3.14.0",
    "summary": "Laundry service popup with stain removal, mirzam and starch add-ons",
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
        "point_of_sale.assets_qunit_tests": [
            "pos_laundry_variant_popup/static/tests/laundry_variant_utils_tests.js",
        ],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/laundry_addon_data.xml",
        "views/product_template_views.xml",
    ],
    "installable": True,
    "application": False,
}
