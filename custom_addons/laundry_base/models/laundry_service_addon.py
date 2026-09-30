# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .laundry_naming import display_name_for


class LaundryServiceAddon(models.Model):
    _name = 'laundry.service.addon'
    _description = 'Laundry Service Add-on'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    name_ar = fields.Char(string='Arabic Name', required=True)
    price = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    applicable_service_ids = fields.Many2many(
        'laundry.service.type',
        'laundry_service_addon_rel',
        'addon_id',
        'service_id',
        string='Applicable Services',
    )

    @api.depends('name', 'name_ar')
    def _compute_display_name(self):
        for addon in self:
            addon.display_name = display_name_for(addon)
