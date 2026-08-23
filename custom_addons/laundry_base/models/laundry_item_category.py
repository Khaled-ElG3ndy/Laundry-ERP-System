# -*- coding: utf-8 -*-
from odoo import fields, models


class LaundryItemCategory(models.Model):
    _name = 'laundry.item.category'
    _description = 'Laundry Item Category'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    name_ar = fields.Char(string='الاسم بالعربي', required=True)
    code = fields.Char(size=20)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    image = fields.Binary(string='Icon', attachment=True)

    default_service_id = fields.Many2one(
        'laundry.service.type',
        string='Default Service',
    )
    special_handling_notes = fields.Text(
        string='Special Handling Notes',
        translate=True,
    )
    applicable_service_ids = fields.Many2many(
        'laundry.service.type',
        'laundry_item_cat_service_rel',
        'category_id',
        'service_id',
        string='Applicable Services',
    )

    def name_get(self):
        return [(c.id, c.name_ar or c.name) for c in self]
