from odoo import SUPERUSER_ID, api


def post_init_hook(env):
    """Create durable labels for orders that predate this feature."""
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    orders = env["pos.order"].search([])
    orders._ensure_laundry_labels()
    orders.filtered("x_laundry_intake_id")._ensure_laundry_sla_deadline_snapshot()
    env["pos.order.laundry.status.history"]._backfill_durations()
