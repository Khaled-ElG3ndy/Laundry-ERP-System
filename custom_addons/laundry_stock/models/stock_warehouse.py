# -*- coding: utf-8 -*-
from odoo import fields, models

from .product_category import ZONE_SELECTION


class StockLocation(models.Model):
    _inherit = 'stock.location'

    laundry_zone_code = fields.Selection(
        ZONE_SELECTION,
        string='Laundry Storage Zone',
        help='Set on the sub-locations a branch store is split into.',
    )
    laundry_branch_id = fields.Many2one(
        'laundry.branch',
        string='Laundry Branch',
        ondelete='set null',
        index=True,
        help='Branch this location belongs to.',
    )


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    laundry_branch_ids = fields.One2many(
        'laundry.branch',
        'warehouse_id',
        string='Laundry Branch',
    )
