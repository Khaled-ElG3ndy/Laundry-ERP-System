# -*- coding: utf-8 -*-
from odoo import fields, models


class LaundryStage(models.Model):
    _name = 'laundry.stage'
    _description = 'Laundry Order Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    name_ar = fields.Char(string='الاسم بالعربي')
    sequence = fields.Integer(default=10, index=True)

    state_key = fields.Selection([
        ('draft', 'Draft'),
        ('received', 'Received'),
        ('tagged', 'Tagged'),
        ('sorted', 'Sorted'),
        ('washing', 'Washing'),
        ('drying', 'Drying'),
        ('ironing', 'Ironing'),
        ('packing', 'Packing'),
        ('ready', 'Ready'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('picked_up', 'Picked Up'),
        ('cancelled', 'Cancelled'),
        ('issue', 'Issue'),
        ('rewash', 'Rewash'),
    ], required=True)

    fold = fields.Boolean(default=False)
    color = fields.Integer(default=0)
    is_terminal = fields.Boolean(default=False)
    is_blocking = fields.Boolean(default=False)
    production_visible = fields.Boolean(default=True)
    counter_visible = fields.Boolean(default=True)

    def name_get(self):
        return [(s.id, s.name_ar or s.name) for s in self]
