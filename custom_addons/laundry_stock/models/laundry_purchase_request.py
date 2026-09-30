# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LaundryPurchaseRequest(models.Model):
    """What a branch asks to buy, before anybody talks to a vendor.

    The request is the internal document: the branch writes what it needs, a
    manager approves it, and only then does it become one request for
    quotation per vendor, delivered to the branch that asked.
    """
    _name = 'laundry.purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_request desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        index=True,
        tracking=True,
        default=lambda self: self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)], limit=1),
    )
    user_id = fields.Many2one(
        'res.users',
        string='Requested By',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    date_request = fields.Date(
        string='Request Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_required = fields.Date(string='Needed By', tracking=True)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Urgent'),
    ], string='Priority', default='0')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('purchased', 'Purchased'),
        ('rejected', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    approver_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        copy=False,
    )
    approval_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    reason = fields.Text(string='Reason', help='Why the request was rejected.')
    note = fields.Text(string='Notes')

    line_ids = fields.One2many(
        'laundry.purchase.request.line',
        'request_id',
        string='Products',
        copy=True,
    )
    estimated_total = fields.Monetary(
        string='Estimated Total',
        compute='_compute_estimated_total',
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

    purchase_order_ids = fields.One2many(
        'purchase.order',
        'laundry_request_id',
        string='Purchase Orders',
    )
    purchase_count = fields.Integer(compute='_compute_purchase_count')

    # ── COMPUTES ────────────────────────────────────────────

    @api.depends('line_ids.price_subtotal')
    def _compute_estimated_total(self):
        for request in self:
            request.estimated_total = sum(
                request.line_ids.mapped('price_subtotal')
            )

    @api.depends('purchase_order_ids')
    def _compute_purchase_count(self):
        for request in self:
            request.purchase_count = len(request.purchase_order_ids)

    # ── CRUD ────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'laundry.purchase.request') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(request.state not in ('draft', 'cancel', 'rejected')
               for request in self):
            raise UserError(_(
                'Only a draft, cancelled or rejected request can be deleted.'
            ))
        return super().unlink()

    # ── WORKFLOW ────────────────────────────────────────────

    def action_submit(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_('Add at least one product to request.'))
            request.state = 'to_approve'
        return True

    def action_approve(self):
        may_approve = (
            self.env.su
            or self.env.user.has_group('laundry_stock.group_laundry_purchaser')
            or self.env.user.has_group('laundry_base.group_laundry_manager')
        )
        if not may_approve:
            raise UserError(_(
                'Only a branch manager or a purchasing officer can approve a '
                'request.'
            ))
        self.write({
            'state': 'approved',
            'approver_id': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })
        return True

    def action_reject(self):
        for request in self:
            if not request.reason:
                raise UserError(_(
                    'Write the reason of the rejection before rejecting the '
                    'request.'
                ))
            request.state = 'rejected'
        return True

    def action_cancel(self):
        for request in self:
            if request.purchase_order_ids.filtered(
                    lambda po: po.state not in ('cancel',)):
                raise UserError(_(
                    'Cancel the purchase orders of this request first.'
                ))
            request.state = 'cancel'
        return True

    def action_draft(self):
        self.write({
            'state': 'draft',
            'approver_id': False,
            'approval_date': False,
        })
        return True

    # ── RFQ ─────────────────────────────────────────────────

    def action_create_rfq(self):
        """One request for quotation per vendor, delivered to the branch."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_(
                'The request has to be approved before asking a vendor.'
            ))
        self.branch_id._require_warehouse()
        picking_type = self.branch_id.warehouse_id.in_type_id
        if not picking_type:
            raise UserError(_(
                'The warehouse of branch "%s" has no receipt operation type.',
                self.branch_id.display_name
            ))

        without_vendor = self.line_ids.filtered(lambda l: not l.partner_id)
        if without_vendor:
            raise UserError(_(
                'These lines have no vendor yet:\n%s\n\nSet a vendor on the '
                'line, or add one on the product, and try again.',
                '\n'.join('- %s' % line.product_id.display_name
                          for line in without_vendor)
            ))

        orders = self.env['purchase.order']
        by_vendor = {}
        for line in self.line_ids:
            by_vendor.setdefault(line.partner_id, self.env[
                'laundry.purchase.request.line'])
            by_vendor[line.partner_id] |= line

        for vendor, lines in by_vendor.items():
            order = self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'company_id': self.company_id.id,
                'picking_type_id': picking_type.id,
                'origin': self.name,
                'branch_id': self.branch_id.id,
                'laundry_request_id': self.id,
                'date_order': fields.Datetime.now(),
                'order_line': [
                    fields.Command.create(line._prepare_purchase_line())
                    for line in lines
                ],
            })
            orders |= order

        self.state = 'purchased'
        self._message_log(body=_(
            '%s request(s) for quotation created: %s',
            len(orders), ', '.join(orders.mapped('name'))
        ))
        return self.action_view_purchase_orders()

    def action_view_purchase_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'purchase.purchase_rfq'
        )
        action['domain'] = [('laundry_request_id', '=', self.id)]
        action['context'] = {'default_laundry_request_id': self.id}
        if len(self.purchase_order_ids) == 1:
            action['view_mode'] = 'form'
            action['views'] = [
                (self.env.ref('purchase.purchase_order_form').id, 'form')
            ]
            action['res_id'] = self.purchase_order_ids.id
        return action


class LaundryPurchaseRequestLine(models.Model):
    _name = 'laundry.purchase.request.line'
    _description = 'Purchase Request Line'
    _order = 'request_id, sequence, id'

    request_id = fields.Many2one(
        'laundry.purchase.request',
        string='Request',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        index=True,
        domain=[('purchase_ok', '=', True)],
    )
    description = fields.Char(string='Description')
    product_qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit',
        required=True,
        compute='_compute_from_product',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        compute='_compute_from_product',
        store=True,
        readonly=False,
        precompute=True,
        domain=[('supplier_rank', '>', 0)],
    )
    price_unit = fields.Float(
        string='Estimated Price',
        digits='Product Price',
        compute='_compute_price_unit',
        store=True,
        readonly=False,
    )
    price_subtotal = fields.Monetary(
        string='Subtotal',
        compute='_compute_price_subtotal',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        related='request_id.currency_id',
        readonly=True,
    )
    qty_available = fields.Float(
        string='On Hand',
        compute='_compute_qty_available',
        digits='Product Unit of Measure',
    )
    state = fields.Selection(related='request_id.state', store=True)

    @api.depends('product_id')
    def _compute_from_product(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_po_id or line.product_id.uom_id
            seller = line.product_id.seller_ids[:1]
            line.partner_id = seller.partner_id or line.partner_id

    @api.depends('product_id', 'product_qty', 'product_uom_id', 'partner_id')
    def _compute_price_unit(self):
        for line in self:
            if not line.product_id:
                line.price_unit = 0.0
                continue
            product = line.product_id.with_company(line.request_id.company_id)
            seller = product._select_seller(
                partner_id=line.partner_id,
                quantity=line.product_qty,
                uom_id=line.product_uom_id,
            )
            if seller:
                line.price_unit = seller.price
            else:
                line.price_unit = product.uom_id._compute_price(
                    product.standard_price, line.product_uom_id
                ) if line.product_uom_id else product.standard_price

    @api.depends('product_qty', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.product_qty * line.price_unit

    @api.depends('product_id', 'product_uom_id', 'request_id.branch_id')
    def _compute_qty_available(self):
        for line in self:
            location = line.request_id.branch_id.store_location_id
            if not line.product_id or not location:
                line.qty_available = 0.0
                continue
            product = line.product_id.sudo().with_context(location=location.id)
            qty = product.qty_available
            if line.product_uom_id:
                qty = product.uom_id._compute_quantity(qty, line.product_uom_id)
            line.qty_available = qty

    @api.constrains('product_qty')
    def _check_qty(self):
        for line in self:
            if line.product_qty <= 0:
                raise ValidationError(
                    _('Quantity must be above zero for "%s".',
                      line.product_id.display_name)
                )

    def _prepare_purchase_line(self):
        self.ensure_one()
        values = {
            'product_id': self.product_id.id,
            'product_qty': self.product_qty,
            'product_uom': self.product_uom_id.id,
        }
        if self.description:
            values['name'] = '%s\n%s' % (
                self.product_id.display_name, self.description
            )
        if self.request_id.date_required:
            values['date_planned'] = fields.Datetime.to_datetime(
                self.request_id.date_required
            )
        return values
