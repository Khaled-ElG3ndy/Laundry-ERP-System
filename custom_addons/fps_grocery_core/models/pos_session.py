from odoo import models

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        fields = result['search_params']['fields']
        if 'snap_eligible' not in fields:
            fields.append('snap_eligible')
        return result
