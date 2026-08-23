from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    laundry_require_ten_digit_phone = fields.Boolean(
        string="Enable 10-Digit Phone Validation",
        config_parameter="pos_laundry_receipt.require_ten_digit_phone",
    )
    pos_laundry_sla_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Laundry SLA Calendar",
        related="pos_config_id.laundry_sla_calendar_id",
        readonly=False,
    )
