{
    "name": "Fair Price Grocery Core",
    "version": "17.0.1.0.0",
    "category": "Point of Sale",
    "summary": "Core grocery retail features for Fair Price Supermarket",
    "author": "Fair Price Supermarket",
    "website": "https://pos.telnovapos.com",
    "license": "LGPL-3",
    "depends": ["base", "product", "point_of_sale", "stock", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "data/product_department_data.xml",
        "views/product_views.xml",
        "views/pos_config_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "fps_grocery_core/static/src/js/models.js",
            "fps_grocery_core/static/src/xml/grocery_templates.xml",
        ]
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
