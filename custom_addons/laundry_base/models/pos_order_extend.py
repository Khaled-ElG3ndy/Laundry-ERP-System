# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    laundry_order_id = fields.Many2one(
        'laundry.order',
        string='Laundry Order',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
    )

    @api.model
    def create_from_ui(self, orders, draft=False):
        order_ids = super().create_from_ui(orders, draft=draft)
        for order_data in orders:
            ui_order = order_data.get('data', {})
            laundry_data = ui_order.get('laundry_data', {})
            if not laundry_data:
                continue
            pos_ref = ui_order.get('name')
            pos_order = self.search(
                [('pos_reference', '=', pos_ref)], limit=1
            )
            if not pos_order:
                _logger.warning(
                    'laundry_base: pos.order %s not found for laundry link',
                    pos_ref,
                )
                continue
            if pos_order.laundry_order_id:
                continue
            try:
                laundry_order = self.env['laundry.order']._create_from_pos_order(
                    pos_order, laundry_data
                )
                pos_order.write({'laundry_order_id': laundry_order.id})
            except Exception as e:
                _logger.error(
                    'laundry_base: Failed to create laundry.order for %s: %s',
                    pos_order.name, str(e),
                )
        return order_ids


class PosConfig(models.Model):
    _inherit = 'pos.config'

    laundry_mode = fields.Boolean(
        string='Laundry Mode',
        default=False,
        help='Enable Laundry POS screens for this terminal.',
    )
    laundry_branch_id = fields.Many2one(
        'laundry.branch',
        string='Laundry Branch',
    )
    laundry_default_promise_hours = fields.Float(
        string='Default Promise Hours',
        default=24.0,
    )
    laundry_require_customer = fields.Boolean(
        string='Require Customer',
        default=True,
    )
