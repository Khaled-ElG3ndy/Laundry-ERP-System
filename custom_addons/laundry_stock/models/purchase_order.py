# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        index=True,
        ondelete='restrict',
        help='Branch the goods are bought for. It drives the warehouse the '
             'receipt lands in.',
    )
    laundry_request_id = fields.Many2one(
        'laundry.purchase.request',
        string='Purchase Request',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
    )

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        for order in self:
            warehouse = order.branch_id.warehouse_id
            if warehouse and warehouse.in_type_id:
                order.picking_type_id = warehouse.in_type_id

    @api.onchange('picking_type_id')
    def _onchange_picking_type_branch(self):
        for order in self:
            if order.branch_id or not order.picking_type_id.warehouse_id:
                continue
            branch = order.picking_type_id.warehouse_id.laundry_branch_ids[:1]
            if branch:
                order.branch_id = branch

    def action_view_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Request'),
            'res_model': 'laundry.purchase.request',
            'res_id': self.laundry_request_id.id,
            'view_mode': 'form',
        }
