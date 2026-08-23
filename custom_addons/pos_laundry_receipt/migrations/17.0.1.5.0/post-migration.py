def migrate(cr, version):
    """Backfill labels during upgrades from the tracking-only implementation."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    env["pos.order"].search([])._ensure_laundry_labels()
    env["pos.order.laundry.status.history"]._backfill_durations()
