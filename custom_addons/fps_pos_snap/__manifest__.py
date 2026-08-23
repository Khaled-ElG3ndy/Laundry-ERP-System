{
    "name": "Fair Price POS SNAP/EBT",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "EBT/SNAP payment handling with split tender support",
    "author": "Fair Price Supermarket",
    "website": "https://pos.telnovapos.com",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "fps_grocery_core"],
    "data": [
        "data/pos_payment_method_data.xml",
        "views/pos_payment_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "fps_pos_snap/static/src/js/snap_payment.js",
            "fps_pos_snap/static/src/xml/snap_templates.xml",
            "fps_pos_snap/static/src/css/snap_styles.css",
        ]
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
