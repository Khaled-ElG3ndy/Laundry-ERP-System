# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

SUPPLY_TYPES = [
    ('detergent', 'Detergent'),
    ('softener', 'Softener & Starch'),
    ('bleach', 'Bleach & Disinfectant'),
    ('solvent', 'Dry-clean Solvent'),
    ('spotting', 'Spotting Chemical'),
    ('packaging', 'Packaging & Covers'),
    ('hanger', 'Hangers & Clips'),
    ('tag', 'Tags & Labels'),
    ('spare', 'Spare Part'),
    ('linen', 'Linen & Uniform'),
    ('housekeeping', 'Housekeeping & Office'),
    ('other', 'Other Supply'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_laundry_supply = fields.Boolean(
        string='Laundry Supply',
        help='Consumable bought and stocked by the laundry: chemicals, '
             'packaging, hangers, spare parts. It is not sold to customers.',
    )
    laundry_supply_type = fields.Selection(
        SUPPLY_TYPES,
        string='Supply Type',
    )
    laundry_min_qty = fields.Float(
        string='Min Qty per Branch',
        digits='Product Unit of Measure',
        help='Quantity that should always be on hand in each branch store. '
             'Used to generate reordering rules.',
    )
    laundry_max_qty = fields.Float(
        string='Max Qty per Branch',
        digits='Product Unit of Measure',
        help='Quantity a replenishment brings the branch store back up to.',
    )

    @api.onchange('is_laundry_supply')
    def _onchange_is_laundry_supply(self):
        for tmpl in self:
            if tmpl.is_laundry_supply:
                # A supply is bought and stocked, never sold at the counter.
                tmpl.detailed_type = 'product'
                tmpl.purchase_ok = True
                tmpl.sale_ok = False
                tmpl.available_in_pos = False

    def action_generate_orderpoints(self):
        """Create/refresh a reordering rule per branch store for these supplies."""
        orderpoint = self.env['stock.warehouse.orderpoint']
        branches = self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)]
        )
        if not branches:
            raise UserError(_(
                'No branch has a warehouse yet. Set the branch warehouses up '
                'first, from Laundry > Configuration > Branches.'
            ))
        created = 0
        for tmpl in self:
            if not tmpl.is_laundry_supply or tmpl.type != 'product':
                continue
            if not tmpl.laundry_max_qty and not tmpl.laundry_min_qty:
                continue
            for product in tmpl.product_variant_ids:
                for branch in branches:
                    location = branch.store_location_id
                    if not location:
                        continue
                    existing = orderpoint.search([
                        ('product_id', '=', product.id),
                        ('location_id', '=', location.id),
                    ], limit=1)
                    values = {
                        'product_min_qty': tmpl.laundry_min_qty,
                        'product_max_qty': (
                            tmpl.laundry_max_qty or tmpl.laundry_min_qty
                        ),
                    }
                    if existing:
                        existing.write(values)
                    else:
                        orderpoint.create(dict(
                            values,
                            product_id=product.id,
                            location_id=location.id,
                            warehouse_id=branch.warehouse_id.id,
                            company_id=branch.warehouse_id.company_id.id,
                        ))
                        created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _('%s reordering rule(s) created, the rest updated.',
                             created),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_generate_orderpoints(self):
        return self.product_tmpl_id.action_generate_orderpoints()
