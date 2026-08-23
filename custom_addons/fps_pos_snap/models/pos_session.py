from odoo import models

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        fields = result['search_params']['fields']
        if 'is_snap_ebt' not in fields:
            fields.append('is_snap_ebt')
        if 'snap_restrict_to_eligible' not in fields:
            fields.append('snap_restrict_to_eligible')
        return result
