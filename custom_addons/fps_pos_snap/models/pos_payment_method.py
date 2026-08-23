from odoo import models, fields

class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    is_snap_ebt = fields.Boolean(string='Is SNAP/EBT', default=False)
    snap_restrict_to_eligible = fields.Boolean(
        string='Restrict SNAP to Eligible Products',
        default=True,
    )
