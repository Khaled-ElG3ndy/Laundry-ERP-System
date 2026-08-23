from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _loader_params_res_company(self):
        result = super()._loader_params_res_company()
        fields = result.setdefault("search_params", {}).setdefault("fields", [])

        for field_name in ("street", "street2", "zip", "city", "mobile"):
            if field_name not in fields:
                fields.append(field_name)

        return result
