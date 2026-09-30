# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LaundryOpeningStock(models.TransientModel):
    """Lay out a count sheet so the store keeper only has to type numbers."""
    _name = 'laundry.opening.stock'
    _description = 'Opening Stock Count'

    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        default=lambda self: self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)], limit=1),
    )
    categ_ids = fields.Many2many(
        'product.category',
        string='Categories',
        domain=[('laundry_zone_code', '!=', False)],
        help='Leave empty to lay out every supply category.',
    )
    include_all_supplies = fields.Boolean(
        string='Include Supplies with No Zone',
        default=True,
        help='Also lay out supplies whose category has no storage zone. They '
             'are counted in the main store.',
    )
    product_count = fields.Integer(
        string='Supplies',
        compute='_compute_product_count',
    )

    def _supplies(self):
        self.ensure_one()
        domain = [('is_laundry_supply', '=', True), ('type', '=', 'product')]
        if self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        elif not self.include_all_supplies:
            domain.append(('categ_id.laundry_zone_code', '!=', False))
        return self.env['product.product'].search(domain)

    @api.depends('categ_ids', 'include_all_supplies')
    def _compute_product_count(self):
        for wizard in self:
            wizard.product_count = len(wizard._supplies())

    def action_prepare_count(self):
        """One count line per supply, in the zone it belongs to."""
        self.ensure_one()
        self.branch_id._require_warehouse()
        store = self.branch_id.store_location_id
        zones = {
            zone.laundry_zone_code: zone
            for zone in self.branch_id.zone_location_ids
        }
        quant_model = self.env['stock.quant'].with_context(inventory_mode=True)
        created = 0
        for product in self._supplies():
            location = zones.get(product.categ_id.laundry_zone_code) or store
            existing = quant_model.search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ], limit=1)
            if existing:
                continue
            quant_model.create({
                'product_id': product.id,
                'location_id': location.id,
                'inventory_quantity': 0.0,
            })
            created += 1
        if not created:
            raise UserError(_(
                'Every supply already has a line in this branch. Open '
                '"Count Stock" and type the quantities.'
            ))

        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_count'
        )
        action['domain'] = [
            ('location_id', 'child_of',
             self.branch_id.warehouse_id.view_location_id.id),
            ('product_id.is_laundry_supply', '=', True),
        ]
        action['context'] = {
            'inventory_mode': True,
            'search_default_internal_loc': 1,
        }
        return action
