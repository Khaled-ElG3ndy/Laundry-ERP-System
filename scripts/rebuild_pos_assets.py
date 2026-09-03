"""Rebuild the Point of Sale asset bundles.

Run through `odoo-bin shell` right after a deploy, while the cashiers' tabs are
reconnected. Creating the bundle attachments is what makes pos_laundry_receipt
broadcast `pos_laundry_assets_changed`, and that is what makes an already open
Point of Sale reload itself once the cashier is idle. Without this step the
bundle is only rebuilt when somebody happens to open the POS, so an open till
could keep running the previous version.
"""
import logging

logging.disable(logging.CRITICAL)
built, failed = [], []
for bundle in ("point_of_sale._assets_pos", "web.assets_backend"):
    for rtl in (False, True):
        label = f"{bundle}{' (rtl)' if rtl else ''}"
        try:
            asset = env["ir.qweb"]._get_asset_bundle(bundle, rtl=rtl)
            asset.js()
            asset.css()
            built.append(label)
        except Exception as exc:  # noqa: BLE001 - report, never abort a deploy
            failed.append(f"{label}: {exc}")
env.cr.commit()
logging.disable(logging.NOTSET)

print("    rebuilt : " + ", ".join(built))
if failed:
    print("    FAILED  : " + "; ".join(failed))
