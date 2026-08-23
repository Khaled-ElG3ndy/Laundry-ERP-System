# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    laundry_service_group_id = fields.Many2one(
        "laundry.service.group",
        string="Laundry Service Group",
        index=True,
        ondelete="set null",
    )
    laundry_pos_display_name = fields.Char(
        string="Laundry POS Display Name",
        translate=True,
        help="Short label shown inside the POS service card.",
    )
