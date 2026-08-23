# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    is_hotel_pos = fields.Boolean(
        string='Hotel & Company POS',
        help="Marks the dedicated hotel/company point of sale. The import keys "
             "on this flag, so renaming the POS never creates a second one.",
        default=False,
        copy=False,
        index=True,
    )
