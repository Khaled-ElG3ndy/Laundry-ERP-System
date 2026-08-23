from odoo import fields, models
from odoo.tools.misc import str2bool


LAUNDRY_PHONE_VALIDATION_PARAM = "pos_laundry_receipt.require_ten_digit_phone"


class PosConfig(models.Model):
    _inherit = "pos.config"

    name = fields.Char(
        string="Point of Sale",
        required=True,
        translate=True,
        help="An internal identification of the point of sale.",
    )

    laundry_require_ten_digit_phone = fields.Boolean(
        string="Require 10-Digit Phone Number",
        compute="_compute_laundry_require_ten_digit_phone",
        compute_sudo=True,
    )
    laundry_sla_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Laundry SLA Calendar",
        help=(
            "Working calendar used to calculate laundry SLA deadlines for this "
            "POS branch. Leave empty to use the company working calendar."
        ),
    )

    def _compute_laundry_require_ten_digit_phone(self):
        is_enabled = str2bool(
            self.env["ir.config_parameter"].sudo().get_param(
                LAUNDRY_PHONE_VALIDATION_PARAM,
                "False",
            )
        )
        for config in self:
            config.laundry_require_ten_digit_phone = is_enabled
