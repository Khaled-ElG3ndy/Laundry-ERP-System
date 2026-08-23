{
    "name": "Web Scroll Fix",
    "version": "17.0.1.0.0",
    "summary": "Fix scroll issue in Odoo web client",
    "category": "Tools",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["web"],
    "assets": {
        "web.assets_backend": [
            "web_scroll_fix/static/src/scss/scroll_fix.scss",
        ],
    },
    "installable": True,
    "application": False,
}
