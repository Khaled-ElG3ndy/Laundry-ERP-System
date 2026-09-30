# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .laundry_naming import display_name_for


class LaundryOrderLine(models.Model):
    _name = 'laundry.order.line'
    _description = 'Laundry Order Line'
    _order = 'sequence, id'

    order_id = fields.Many2one(
        'laundry.order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)

    item_category_id = fields.Many2one(
        'laundry.item.category',
        string='Item Category',
        required=True,
        index=True,
    )
    service_type_id = fields.Many2one(
        'laundry.service.type',
        string='Service',
        required=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='service_type_id.product_id',
        store=True,
        readonly=True,
    )
    description = fields.Char(
        string='Description',
        compute='_compute_description',
        store=True,
        readonly=False,
    )

    @api.depends('item_category_id', 'service_type_id')
    def _compute_description(self):
        for line in self:
            cat = (display_name_for(line.item_category_id)
                   if line.item_category_id else '')
            svc = (display_name_for(line.service_type_id)
                   if line.service_type_id else '')
            line.description = (
                '%s — %s' % (cat, svc) if cat and svc else (cat or svc)
            )

    qty = fields.Float(string='Qty', required=True, default=1.0, digits=(10, 2))
    unit_price = fields.Monetary(
        string='Unit Price',
        currency_field='currency_id',
        required=True,
    )
    price_overridden = fields.Boolean(default=False, readonly=True)

    urgent_surcharge = fields.Monetary(
        string='Urgent Surcharge',
        currency_field='currency_id',
        compute='_compute_surcharge',
        store=True,
    )

    @api.depends('order_id.is_urgent', 'service_type_id', 'unit_price')
    def _compute_surcharge(self):
        for line in self:
            if line.order_id.is_urgent and line.service_type_id:
                svc = line.service_type_id
                if svc.urgent_surcharge_type == 'percent':
                    line.urgent_surcharge = (
                        line.unit_price * (svc.urgent_surcharge_pct / 100.0)
                    )
                else:
                    line.urgent_surcharge = svc.urgent_surcharge_fixed
            else:
                line.urgent_surcharge = 0.0

    addon_ids = fields.Many2many(
        'laundry.service.addon',
        'laundry_order_line_addon_rel',
        'line_id',
        'addon_id',
        string='Add-ons',
    )
    addon_amount = fields.Monetary(
        string='Add-ons Total',
        currency_field='currency_id',
        compute='_compute_addon_amount',
        store=True,
    )

    @api.depends('addon_ids.price')
    def _compute_addon_amount(self):
        for line in self:
            line.addon_amount = sum(line.addon_ids.mapped('price'))

    addon_display = fields.Text(
        string='Services & Options',
        compute='_compute_addon_display',
        store=True,
    )

    @api.depends('addon_ids.name', 'addon_ids.name_ar', 'addon_ids.price')
    def _compute_addon_display(self):
        for line in self:
            if line.addon_ids:
                addons_text = '\n'.join([
                    f"  • {display_name_for(addon)} ({addon.price} SAR)"
                    for addon in line.addon_ids
                ])
                line.addon_display = addons_text
            else:
                line.addon_display = ''

    discount_pct = fields.Float(string='Discount %', digits=(5, 2), default=0.0)

    price_subtotal = fields.Monetary(
        string='Subtotal',
        currency_field='currency_id',
        compute='_compute_subtotal',
        store=True,
    )

    @api.depends('qty', 'unit_price', 'urgent_surcharge',
                 'addon_amount', 'discount_pct')
    def _compute_subtotal(self):
        for line in self:
            gross = (
                (line.unit_price + line.urgent_surcharge + line.addon_amount)
                * line.qty
            )
            line.price_subtotal = gross * (1.0 - (line.discount_pct / 100.0))

    currency_id = fields.Many2one(
        related='order_id.currency_id', store=True,
    )

    line_state = fields.Selection([
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('ready', 'Ready'),
        ('issue', 'Issue'),
    ], default='pending', string='Item State', index=True)

    line_notes = fields.Text(string='Item Notes')
    damage_note = fields.Text(string='Damage / Stain Note')

    is_piece_tracked = fields.Boolean(default=False)
    piece_barcode = fields.Char(string='Piece Barcode')

    pos_order_line_id = fields.Many2one(
        'pos.order.line',
        string='POS Order Line',
        readonly=True,
        copy=False,
        ondelete='set null',
    )
