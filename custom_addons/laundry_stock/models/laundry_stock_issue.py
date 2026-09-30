# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_is_zero


class LaundryStockIssue(models.Model):
    """Materials leaving the branch store: what the laundry actually used.

    Confirming an issue posts a real stock transfer, so on-hand quantities and
    the consumption report always agree with each other.
    """
    _name = 'laundry.stock.issue'
    _description = 'Material Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    operation_type = fields.Selection([
        ('issue', 'Issue to Operations'),
        ('return', 'Return to Store'),
    ], string='Operation', required=True, default='issue', tracking=True,
        help='An issue takes materials out of the store. A return puts back '
             'what was drawn and not used.')
    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        index=True,
        tracking=True,
        default=lambda self: self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)], limit=1),
    )
    date = fields.Datetime(
        string='Date',
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    purpose = fields.Selection([
        ('production', 'Production'),
        ('maintenance', 'Machine Maintenance'),
        ('housekeeping', 'Housekeeping'),
        ('damage', 'Damage / Loss'),
        ('other', 'Other'),
    ], string='Purpose', required=True, default='production', tracking=True)

    source = fields.Selection([
        ('manual', 'Written by Hand'),
        ('order', 'From a Laundry Order'),
        ('pos', 'From Counter Sales'),
    ], string='Source', default='manual', required=True, readonly=True)
    pos_date_from = fields.Date(string='Sales From', readonly=True)
    pos_date_to = fields.Date(string='Sales To', readonly=True)

    laundry_order_id = fields.Many2one(
        'laundry.order',
        string='Laundry Order',
        index=True,
        ondelete='set null',
        help='Fill it in to charge the materials to one order.',
    )
    machine_id = fields.Many2one(
        'laundry.machine',
        string='Machine',
        index=True,
        ondelete='set null',
        domain="[('branch_id', '=', branch_id)]",
    )
    user_id = fields.Many2one(
        'res.users',
        string='Issued By',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )

    location_id = fields.Many2one(
        'stock.location',
        string='From',
        required=True,
        compute='_compute_locations',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('usage', 'in', ('internal', 'production'))]",
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        string='To',
        required=True,
        compute='_compute_locations',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('usage', 'in', ('internal', 'production'))]",
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string='Transfer',
        readonly=True,
        copy=False,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Issued'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many(
        'laundry.stock.issue.line',
        'issue_id',
        string='Materials',
        copy=True,
    )
    total_cost = fields.Monetary(
        string='Total Cost',
        compute='_compute_total_cost',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    note = fields.Text(string='Notes')

    # ── COMPUTES ────────────────────────────────────────────

    @api.depends('branch_id', 'operation_type')
    def _compute_locations(self):
        for issue in self:
            store = issue.branch_id.store_location_id
            consumption = issue.branch_id.consumption_location_id
            if issue.operation_type == 'return':
                issue.location_id = consumption
                issue.location_dest_id = store
            else:
                issue.location_id = store
                issue.location_dest_id = consumption

    @api.depends('line_ids.subtotal')
    def _compute_total_cost(self):
        for issue in self:
            issue.total_cost = sum(issue.line_ids.mapped('subtotal'))

    @api.onchange('purpose')
    def _onchange_purpose(self):
        if self.purpose != 'maintenance':
            self.machine_id = False

    # ── CRUD ────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'laundry.stock.issue') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(issue.state == 'done' for issue in self):
            raise UserError(_(
                'An issued document cannot be deleted. Cancel it instead, or '
                'register a return.'
            ))
        return super().unlink()

    # ── ACTIONS ─────────────────────────────────────────────

    def action_fill_from_norms(self):
        """Propose the materials the linked order is expected to consume."""
        self.ensure_one()
        if not self.laundry_order_id:
            raise UserError(_('Pick a laundry order first.'))
        needs = self.env['laundry.consumption.norm']._quantities_for_order(
            self.laundry_order_id
        )
        if not needs:
            raise UserError(_(
                'No consumption norm matches this order. Define the norms '
                'under Laundry > Configuration > Consumption Norms.'
            ))
        commands = [fields.Command.clear()]
        skipped = []
        for product, (qty, uom) in needs.items():
            # Stock quantities carry two decimals: a dose that rounds to zero
            # cannot be moved, and would block the transfer.
            if float_is_zero(qty, precision_rounding=uom.rounding):
                skipped.append(product.display_name)
                continue
            commands.append(fields.Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
                'product_uom_id': uom.id,
            }))
        self.line_ids = commands
        if skipped and len(commands) == 1:
            raise UserError(_(
                'The norms give a quantity too small to move for: %s.\n'
                'Issue those over several orders, or set the norm per order.',
                ', '.join(skipped)
            ))
        return True

    def action_confirm(self):
        for issue in self:
            if issue.state != 'draft':
                raise UserError(_('Only a draft document can be issued.'))
            if not issue.line_ids:
                raise UserError(_('Add at least one material.'))
            issue.branch_id._require_warehouse()
            if not issue.branch_id.consumption_location_id:
                raise UserError(_(
                    'Branch "%s" has no consumption location yet. Run "Set Up '
                    'Warehouse" on the branch.', issue.branch_id.display_name
                ))
            zero_lines = issue.line_ids.filtered(
                lambda line: float_is_zero(
                    line.product_uom_qty,
                    precision_rounding=line.product_uom_id.rounding,
                )
            )
            if zero_lines:
                raise UserError(_(
                    'These lines carry no quantity to move: %s',
                    ', '.join(zero_lines.mapped('product_id.display_name'))
                ))
            issue.line_ids._snapshot_cost()
            picking = issue._create_picking()
            issue.write({'picking_id': picking.id, 'state': 'done'})
            issue._message_log(body=_(
                'Materials issued through transfer %s.', picking.name
            ))
        return True

    def _create_picking(self):
        self.ensure_one()
        picking_type = self.branch_id.issue_picking_type_id
        if not picking_type:
            raise UserError(_(
                'Branch "%s" has no material issue operation type. Run "Set Up '
                'Warehouse" on the branch.', self.branch_id.display_name
            ))
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': self.location_id.id,
            'location_dest_id': self.location_dest_id.id,
            'origin': self.name,
            'scheduled_date': self.date,
            'company_id': self.company_id.id,
            'move_ids': [
                fields.Command.create({
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': self.location_id.id,
                    'location_dest_id': self.location_dest_id.id,
                    'company_id': self.company_id.id,
                })
                for line in self.line_ids
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            # Consumption is not negotiable: what was written down leaves the
            # store, even if the reservation could not cover all of it.
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True).button_validate()
        return picking

    def action_cancel(self):
        for issue in self:
            if issue.state == 'done':
                raise UserError(_(
                    'This document is already issued. Register a return to put '
                    'the materials back into the store.'
                ))
            issue.state = 'cancel'
        return True

    def action_draft(self):
        for issue in self:
            if issue.state == 'done':
                raise UserError(_('An issued document cannot go back to draft.'))
            issue.state = 'draft'
        return True

    def action_view_picking(self):
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_('No transfer is attached to this document yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }


class LaundryStockIssueLine(models.Model):
    _name = 'laundry.stock.issue.line'
    _description = 'Material Issue Line'
    _order = 'issue_id, sequence, id'

    issue_id = fields.Many2one(
        'laundry.stock.issue',
        string='Issue',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product',
        string='Material',
        required=True,
        index=True,
        domain=[('is_laundry_supply', '=', True), ('type', '=', 'product')],
    )
    product_uom_qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit',
        required=True,
        compute='_compute_product_uom_id',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    available_qty = fields.Float(
        string='On Hand',
        compute='_compute_available_qty',
        digits='Product Unit of Measure',
        help='Quantity currently in the source location, in the unit of this '
             'line.',
    )
    unit_cost = fields.Float(
        string='Unit Cost',
        digits='Product Price',
        compute='_compute_unit_cost',
        store=True,
        readonly=False,
    )
    subtotal = fields.Monetary(
        string='Cost',
        compute='_compute_subtotal',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='issue_id.currency_id',
        readonly=True,
    )
    state = fields.Selection(related='issue_id.state', store=True)
    note = fields.Char(string='Note')

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends('product_id', 'product_uom_id', 'issue_id.company_id')
    def _compute_unit_cost(self):
        for line in self:
            product = line.product_id.with_company(
                line.issue_id.company_id or self.env.company
            )
            cost = product.standard_price
            if line.product_uom_id and product:
                cost = product.uom_id._compute_price(cost, line.product_uom_id)
            line.unit_cost = cost

    @api.depends('product_uom_qty', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.product_uom_qty * line.unit_cost

    @api.depends('product_id', 'product_uom_id', 'issue_id.location_id')
    def _compute_available_qty(self):
        for line in self:
            location = line.issue_id.location_id
            if not line.product_id or not location:
                line.available_qty = 0.0
                continue
            product = line.product_id.sudo().with_context(location=location.id)
            qty = product.qty_available
            if line.product_uom_id:
                qty = product.uom_id._compute_quantity(qty, line.product_uom_id)
            line.available_qty = qty

    @api.constrains('product_uom_qty')
    def _check_qty(self):
        for line in self:
            if line.product_uom_qty <= 0:
                raise ValidationError(
                    _('Quantity must be above zero for "%s".',
                      line.product_id.display_name)
                )

    def _snapshot_cost(self):
        """Freeze the cost of the day on the line."""
        for line in self:
            if not line.unit_cost:
                line._compute_unit_cost()
        return True
