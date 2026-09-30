# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .laundry_naming import display_name_for


class LaundryServiceType(models.Model):
    _name = 'laundry.service.type'
    _description = 'Laundry Service Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    name_ar = fields.Char(string='Arabic Name', required=True)
    code = fields.Char(size=20, required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    product_id = fields.Many2one(
        'product.product',
        string='Accounting Product',
        required=True,
        domain=[('type', '=', 'service')],
        help='Odoo service product for accounting. Must be type=service.',
    )
    base_price = fields.Monetary(
        string='Base Price (SAR)',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    urgent_surcharge_type = fields.Selection([
        ('percent', 'Percentage %'),
        ('fixed', 'Fixed SAR'),
    ], default='percent', required=True)
    urgent_surcharge_pct = fields.Float(
        string='Urgent Surcharge %',
        digits=(5, 2),
        default=25.0,
    )
    urgent_surcharge_fixed = fields.Monetary(
        string='Urgent Fixed Surcharge',
        currency_field='currency_id',
    )
    standard_duration_hours = fields.Float(
        string='Standard Duration (hrs)',
        default=24.0,
    )
    urgent_duration_hours = fields.Float(
        string='Urgent Duration (hrs)',
        default=4.0,
    )
    is_dry_clean = fields.Boolean(default=False)
    is_express = fields.Boolean(default=False)
    color = fields.Integer(default=0)

    applicable_category_ids = fields.Many2many(
        'laundry.item.category',
        'laundry_item_cat_service_rel',
        'service_id',
        'category_id',
        string='Applicable Item Categories',
    )
    addon_ids = fields.Many2many(
        'laundry.service.addon',
        'laundry_service_addon_rel',
        'service_id',
        'addon_id',
        string='Available Add-ons',
    )

    @api.constrains('product_id')
    def _check_product_is_service(self):
        for rec in self:
            if rec.product_id and rec.product_id.type != 'service':
                raise ValidationError(
                    _('Product "%s" must be of type Service.') % rec.product_id.name
                )

    def compute_price(self, is_urgent=False):
        self.ensure_one()
        price = self.base_price
        if is_urgent:
            if self.urgent_surcharge_type == 'percent':
                price += price * (self.urgent_surcharge_pct / 100.0)
            else:
                price += self.urgent_surcharge_fixed
        return price

    @api.depends('name', 'name_ar')
    def _compute_display_name(self):
        for service in self:
            service.display_name = display_name_for(service)
