# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LaundryOrder(models.Model):
    _inherit = 'laundry.order'

    stock_issue_ids = fields.One2many(
        'laundry.stock.issue',
        'laundry_order_id',
        string='Material Issues',
    )
    issue_material_count = fields.Integer(compute='_compute_issue_material_count')
    material_cost = fields.Monetary(
        string='Material Cost',
        compute='_compute_material_figures',
        store=True,
        currency_field='currency_id',
        help='What the materials actually issued for this order cost.',
    )
    estimated_material_cost = fields.Monetary(
        string='Expected Material Cost',
        compute='_compute_estimated_material_cost',
        currency_field='currency_id',
        help='What the consumption norms say this order should use.',
    )
    materials_issued = fields.Boolean(
        string='Materials Issued',
        compute='_compute_material_figures',
        store=True,
    )

    @api.depends('stock_issue_ids')
    def _compute_issue_material_count(self):
        for order in self:
            order.issue_material_count = len(order.stock_issue_ids)

    @api.depends('stock_issue_ids.state', 'stock_issue_ids.total_cost',
                 'stock_issue_ids.operation_type')
    def _compute_material_figures(self):
        for order in self:
            done = order.stock_issue_ids.filtered(lambda i: i.state == 'done')
            cost = 0.0
            for issue in done:
                cost += (
                    -issue.total_cost if issue.operation_type == 'return'
                    else issue.total_cost
                )
            order.material_cost = cost
            order.materials_issued = bool(
                done.filtered(lambda i: i.operation_type == 'issue')
            )

    def _compute_estimated_material_cost(self):
        norm_model = self.env['laundry.consumption.norm']
        for order in self:
            total = 0.0
            for product, (qty, uom) in norm_model._quantities_for_order(order).items():
                cost = product.with_company(order.company_id).standard_price
                total += uom._compute_quantity(qty, product.uom_id) * cost
            order.estimated_material_cost = total

    # ── ACTIONS ─────────────────────────────────────────────

    def action_issue_materials(self):
        """Open a draft issue for this order, pre-filled from the norms."""
        self.ensure_one()
        if not self.branch_id:
            raise UserError(_('This order has no branch.'))
        self.branch_id._require_warehouse()
        issue = self.env['laundry.stock.issue'].create({
            'branch_id': self.branch_id.id,
            'laundry_order_id': self.id,
            'purpose': 'production',
            'source': 'order',
            'company_id': self.company_id.id,
        })
        try:
            issue.action_fill_from_norms()
        except UserError:
            # No norm matches yet: the user fills the lines by hand.
            pass
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Issue'),
            'res_model': 'laundry.stock.issue',
            'res_id': issue.id,
            'view_mode': 'form',
        }

    def action_view_material_issues(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_issue'
        )
        action['domain'] = [('laundry_order_id', '=', self.id)]
        action['context'] = {
            'default_laundry_order_id': self.id,
            'default_branch_id': self.branch_id.id,
        }
        return action

    # ── AUTOMATIC ISSUE ─────────────────────────────────────

    def write(self, vals):
        result = super().write(vals)
        if vals.get('state'):
            self._auto_issue_materials(vals['state'])
        return result

    def _auto_issue_materials(self, state):
        """Issue the materials of an order when its branch asks for it.

        Stock must never hold up the shop floor: a problem here is logged and
        posted on the order, and the order keeps moving.
        """
        for order in self:
            branch = order.branch_id
            if not branch.auto_consume or branch.auto_consume_state != state:
                continue
            if order.materials_issued or not order.order_line_ids:
                continue
            if not branch.warehouse_id or not branch.consumption_location_id:
                continue
            if not self.env['laundry.consumption.norm']._quantities_for_order(order):
                continue
            try:
                # A savepoint keeps a stock problem from poisoning the
                # transaction that is moving the order forward.
                with self.env.cr.savepoint():
                    issue = self.env['laundry.stock.issue'].create({
                        'branch_id': branch.id,
                        'laundry_order_id': order.id,
                        'purpose': 'production',
                        'source': 'order',
                        'company_id': order.company_id.id,
                    })
                    issue.action_fill_from_norms()
                    issue.action_confirm()
            except Exception as error:  # noqa: BLE001 - never block the floor
                _logger.warning(
                    'Automatic material issue failed for laundry order %s: %s',
                    order.name, error,
                )
                order._message_log(body=_(
                    'The materials of this order could not be issued '
                    'automatically: %s', error
                ))
