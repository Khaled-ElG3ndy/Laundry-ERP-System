# -*- coding: utf-8 -*-
from odoo import fields, models


class LaundryItemCategory(models.Model):
    _inherit = 'laundry.item.category'

    avg_weight_kg = fields.Float(
        string='Average Weight (kg)',
        digits=(6, 3),
        default=0.5,
        help='Typical weight of one piece. Chemical doses expressed per '
             'kilogram are converted with it.',
    )
