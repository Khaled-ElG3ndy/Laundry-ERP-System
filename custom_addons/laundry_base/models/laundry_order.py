# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class LaundryOrder(models.Model):
    _name = 'laundry.order'
    _description = 'Laundry Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    # ── IDENTIFICATION ──────────────────────────────────────
    name = fields.Char(
        string='Order Ref',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
    )
    barcode = fields.Char(
        string='Barcode',
        copy=False,
        index=True,
    )

    # ── NATIVE ODOO LINKS ───────────────────────────────────
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        readonly=True,
        copy=False,
        index=True,
        ondelete='set null',
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'laundry_order_invoice_rel',
        'order_id',
        'invoice_id',
        string='Invoices',
        copy=False,
    )

    # ── CUSTOMER ────────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        index=True,
        tracking=True,
    )
    partner_phone = fields.Char(
        related='partner_id.phone',
        string='Phone',
        store=True,
    )
    commercial_account_id = fields.Many2one(
        'laundry.commercial.account',
        string='Commercial Account',
        index=True,
        tracking=True,
    )
    is_commercial = fields.Boolean(
        compute='_compute_is_commercial',
        store=True,
        index=True,
    )

    @api.depends('commercial_account_id')
    def _compute_is_commercial(self):
        for o in self:
            o.is_commercial = bool(o.commercial_account_id)

    # ── BRANCH ──────────────────────────────────────────────
    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    # ── STATE ───────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'Draft / مسودة'),
        ('received', 'Received / مستلم'),
        ('tagged', 'Tagged / مُصنّف'),
        ('sorted', 'Sorted / مُرتَّب'),
        ('washing', 'Washing / في الغسيل'),
        ('drying', 'Drying / في التجفيف'),
        ('ironing', 'Ironing / في الكوي'),
        ('packing', 'Packing / في التعبئة'),
        ('ready', 'Ready / جاهز'),
        ('out_for_delivery', 'Out for Delivery / في الطريق'),
        ('delivered', 'Delivered / تم التوصيل'),
        ('picked_up', 'Picked Up / تم الاستلام'),
        ('cancelled', 'Cancelled / ملغي'),
        ('issue', 'Issue / إشكالية'),
        ('rewash', 'Rewash / إعادة غسيل'),
    ],
        string='State',
        default='received',
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )

    stage_id = fields.Many2one(
        'laundry.stage',
        string='Stage',
        compute='_compute_stage_id',
        store=True,
    )

    @api.depends('state')
    def _compute_stage_id(self):
        stages = {s.state_key: s for s in self.env['laundry.stage'].search([])}
        for o in self:
            o.stage_id = stages.get(o.state, False)

    priority = fields.Selection([
        ('normal', 'Normal'),
        ('urgent', 'Urgent / عاجل'),
    ], default='normal', required=True, index=True, tracking=True)

    is_urgent = fields.Boolean(
        compute='_compute_is_urgent',
        store=True,
        index=True,
    )

    @api.depends('priority')
    def _compute_is_urgent(self):
        for o in self:
            o.is_urgent = (o.priority == 'urgent')

    # ── DATES ───────────────────────────────────────────────
    date_order = fields.Datetime(
        string='Order Date',
        required=True,
        default=fields.Datetime.now,
        copy=False,
        index=True,
    )
    promise_date = fields.Datetime(
        string='Promise Date / موعد التسليم',
        required=True,
        index=True,
        tracking=True,
    )
    actual_ready_date = fields.Datetime(
        string='Actual Ready Date',
        readonly=True,
        copy=False,
    )
    handover_date = fields.Datetime(
        string='Handover Date',
        readonly=True,
        copy=False,
    )
    delivery_requested = fields.Boolean(
        string='Delivery Requested',
        default=False,
    )
    pickup_date = fields.Datetime(
        string='Scheduled Pickup',
        help='[Phase 2] Driver pickup time.',
    )
    is_overdue = fields.Boolean(
        compute='_compute_is_overdue',
        store=True,
        index=True,
    )

    @api.depends('promise_date', 'state')
    def _compute_is_overdue(self):
        terminal = ('delivered', 'picked_up', 'cancelled')
        now = fields.Datetime.now()
        for o in self:
            if o.state in terminal:
                o.is_overdue = False
            elif o.promise_date and now > o.promise_date:
                o.is_overdue = True
            else:
                o.is_overdue = False

    # ── TRACKING ────────────────────────────────────────────
    bag_reference = fields.Char(string='Bag / Batch Ref', index=True)
    rack_location = fields.Char(string='Rack / Shelf')

    # ── STAFF ───────────────────────────────────────────────
    user_id = fields.Many2one(
        'res.users',
        string='Cashier',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
    )
    assigned_production_id = fields.Many2one(
        'res.users',
        string='Production Staff',
        domain=[('share', '=', False)],
    )

    # ── ORDER LINES ─────────────────────────────────────────
    order_line_ids = fields.One2many(
        'laundry.order.line',
        'order_id',
        string='Order Lines',
        copy=True,
    )
    line_count = fields.Integer(
        compute='_compute_line_count',
        string='Items',
    )

    @api.depends('order_line_ids')
    def _compute_line_count(self):
        for o in self:
            o.line_count = len(o.order_line_ids)

    # ── PAYMENT ─────────────────────────────────────────────
    payment_method = fields.Selection([
        ('cash',       'Cash / نقداً'),
        ('card',       'Card / بطاقة'),
        ('on_account', 'On Account / على الحساب'),
        ('split',      'Split / مقسّم'),
    ], string='Payment Method / طريقة الدفع',
       default='cash', tracking=True)

    loyalty_card_id = fields.Many2one('laundry.loyalty.card',
        string='Loyalty Card', compute='_compute_loyalty_card', store=True)
    loyalty_points_earned  = fields.Float(string='Points Earned', default=0.0, readonly=True)
    loyalty_points_used    = fields.Float(string='Points Redeemed', default=0.0, readonly=True)
    loyalty_discount       = fields.Monetary(string='Loyalty Discount',
        currency_field='currency_id', default=0.0)

    @api.depends('partner_id')
    def _compute_loyalty_card(self):
        for order in self:
            if order.partner_id:
                card = self.env['laundry.loyalty.card'].search(
                    [('partner_id','=',order.partner_id.id)], limit=1)
                order.loyalty_card_id = card
            else:
                order.loyalty_card_id = False

    cash_tendered = fields.Monetary(
        string='Cash Tendered / المبلغ المقدم',
        currency_field='currency_id',
        default=0.0,
    )

    change_amount = fields.Monetary(
        string='Change / الباقي',
        currency_field='currency_id',
        compute='_compute_change_amount',
        store=True,
    )

    @api.depends('cash_tendered', 'amount_total', 'payment_method')
    def _compute_change_amount(self):
        for order in self:
            if order.payment_method == 'cash' and order.cash_tendered > 0:
                order.change_amount = max(0, order.cash_tendered - order.amount_total)
            else:
                order.change_amount = 0.0

    payment_state = fields.Selection([
        ('unpaid', 'Unpaid / غير مدفوع'),
        ('partial', 'Partial / جزئي'),
        ('paid', 'Paid / مدفوع'),
        ('on_account', 'On Account / على الحساب'),
        ('invoiced', 'Invoiced / مُفوتر'),
    ],
        string='Payment State',
        default='unpaid',
        required=True,
        index=True,
        tracking=True,
        copy=False,
    )
    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    amount_paid = fields.Monetary(
        string='Paid',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    amount_due = fields.Monetary(
        string='Due',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends(
        'order_line_ids.price_subtotal',
        'pos_order_id.amount_paid',
        'payment_state',
    )
    def _compute_amounts(self):
        for o in self:
            total = sum(o.order_line_ids.mapped('price_subtotal'))
            o.amount_total = total
            if o.pos_order_id:
                o.amount_paid = o.pos_order_id.amount_paid
            elif o.payment_state == 'paid':
                o.amount_paid = total
            else:
                o.amount_paid = 0.0
            o.amount_due = max(0.0, total - o.amount_paid)

    # ── NOTES ───────────────────────────────────────────────
    intake_notes = fields.Text(string='Intake Notes')
    customer_notes = fields.Text(string='Customer Notes', translate=True)
    internal_notes = fields.Text(string='Internal Notes')
    pre_damage_notes = fields.Text(string='Pre-existing Damage / Stains')
    photo_required = fields.Boolean(string='Photo Required', default=False)

    # ── RELATED ─────────────────────────────────────────────
    status_log_ids = fields.One2many(
        'laundry.status.log', 'order_id', string='Status History',
    )
    issue_ids = fields.One2many(
        'laundry.issue', 'order_id', string='Issues',
    )
    issue_count = fields.Integer(compute='_compute_issue_count')

    @api.depends('issue_ids')
    def _compute_issue_count(self):
        for o in self:
            o.issue_count = len(o.issue_ids)

    # ── SQL CONSTRAINTS ─────────────────────────────────────
    _sql_constraints = [
        ('barcode_company_unique', 'UNIQUE(barcode, company_id)',
         'Order barcode must be unique per company.'),
    ]

    # ── LIFECYCLE ───────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('laundry.order')
                    or _('New')
                )
            if not vals.get('barcode'):
                import hashlib, time
                raw = '%s-%s' % (vals.get('name', ''), time.time())
                vals['barcode'] = hashlib.md5(
                    raw.encode()
                ).hexdigest()[:12].upper()
        orders = super().create(vals_list)
        for order in orders:
            order._log_status_change(None, order.state, 'Order created')
        return orders

    def write(self, vals):
        state_before = {o.id: o.state for o in self}
        if 'state' in vals:
            for order in self:
                order._check_state_transition_permission(
                    order.state, vals['state']
                )
        result = super().write(vals)
        if 'state' in vals:
            for order in self:
                old = state_before[order.id]
                new = vals['state']
                if old != new:
                    order._log_status_change(old, new)
                    order._set_state_timestamps(new)
        return result

    # ── PERMISSION CHECKS (SERVER-ENFORCED) ─────────────────
    def _check_state_transition_permission(self, from_state, to_state):
        # Skip permission check when running as superuser (uid=1)
        if self.env.uid == 1:
            return
        user = self.env.user
        if to_state == 'cancelled':
            if not user.has_group('laundry_base.group_laundry_supervisor'):
                raise AccessError(_(
                    'إلغاء الطلب يتطلب صلاحية المشرف.\n'
                    'Cancellation requires Supervisor permission.'
                ))
        if to_state == 'issue':
            has_prod = user.has_group('laundry_base.group_laundry_production')
            has_sup = user.has_group('laundry_base.group_laundry_supervisor')
            if not (has_prod or has_sup):
                raise AccessError(_(
                    'تسجيل إشكالية يتطلب صلاحية الإنتاج.\n'
                    'Logging an issue requires Production permission.'
                ))

    def action_apply_discount(self, line_id, discount_pct):
        self.ensure_one()
        user = self.env.user
        if not (0 <= discount_pct <= 100):
            raise ValidationError(_('Discount must be between 0 and 100.'))
        if discount_pct >= 10:
            if not user.has_group('laundry_base.group_laundry_supervisor'):
                raise AccessError(_(
                    'خصم 10% وما فوق يتطلب موافقة المشرف.\n'
                    'Discounts ≥10%% require Supervisor approval.'
                ))
        line = self.env['laundry.order.line'].browse(line_id)
        if line.order_id != self:
            raise UserError(_('Invalid order line.'))
        self.env['laundry.audit.log'].sudo().create({
            'order_id': self.id,
            'user_id': self.env.uid,
            'action': 'discount',
            'details': 'Discount %.1f%% on line %d' % (discount_pct, line_id),
        })
        line.sudo().write({'discount_pct': discount_pct})
        return True

    def action_override_price(self, line_id, new_price):
        self.ensure_one()
        if not self.env.user.has_group('laundry_base.group_laundry_supervisor'):
            raise AccessError(_(
                'تعديل السعر يتطلب صلاحية المشرف.\n'
                'Price override requires Supervisor permission.'
            ))
        line = self.env['laundry.order.line'].browse(line_id)
        if line.order_id != self:
            raise UserError(_('Invalid order line.'))
        self.env['laundry.audit.log'].sudo().create({
            'order_id': self.id,
            'user_id': self.env.uid,
            'action': 'price_override',
            'details': 'Price %s → %s on line %d' % (
                line.unit_price, new_price, line_id
            ),
        })
        line.sudo().write({'unit_price': new_price, 'price_overridden': True})
        return True

    def action_cancel(self, reason=''):
        self.ensure_one()
        self._check_state_transition_permission(self.state, 'cancelled')
        self.env['laundry.audit.log'].sudo().create({
            'order_id': self.id,
            'user_id': self.env.uid,
            'action': 'cancel',
            'details': reason or 'No reason provided',
        })
        self.write({
            'state': 'cancelled',
            'internal_notes': (
                (self.internal_notes or '') +
                '\n[Cancelled] %s' % reason
            ).strip(),
        })
        return True

    def _check_customer_phone(self):
        """Phone is mandatory before pickup/handover."""
        self.ensure_one()
        partner = self.partner_id
        if not (partner.phone or partner.mobile):
            raise ValidationError(_(
                'رقم الجوال مطلوب لاستلام الملابس!\n'
                'Phone number is required for clothes pickup!\n'
                'Customer: %s — Please update contact details first.'
            ) % partner.name)

    def action_award_loyalty_points(self):
        """Award loyalty points when order is paid."""
        self.ensure_one()
        if self.payment_state not in ('paid',) or self.loyalty_points_earned > 0:
            return
        card = self.env['laundry.loyalty.card'].get_or_create_for_partner(
            self.partner_id.id)
        pts = card.award_points(
            self.amount_total - self.loyalty_discount,
            order_id=self.id,
            reason=f'شراء طلب {self.name}',
        )
        self.write({'loyalty_points_earned': pts, 'loyalty_card_id': card.id})
        return pts

    def action_confirm_handover(self):
        self.ensure_one()
        self._check_customer_phone()
        if self.state != 'ready':
            raise UserError(_(
                'Only Ready orders can be handed over.'
            ))
        self.env['laundry.audit.log'].sudo().create({
            'order_id': self.id,
            'user_id': self.env.uid,
            'action': 'handover',
            'details': 'Handed over at counter',
        })
        self.write({'state': 'picked_up'})
        return True

    def action_print_label(self):
        return self.env.ref(
            'laundry_base.action_report_laundry_label'
        ).report_action(self)

    def action_print_receipt(self):
        return self.env.ref(
            'laundry_base.action_report_laundry_receipt'
        ).report_action(self)

    # ── INTERNAL HELPERS ────────────────────────────────────
    def _log_status_change(self, from_state, to_state, note=''):
        self.env['laundry.status.log'].sudo().create({
            'order_id': self.id,
            'from_state': from_state or '',
            'to_state': to_state,
            'user_id': self.env.uid,
            'note': note,
        })

    def _set_state_timestamps(self, new_state):
        if new_state == 'ready' and not self.actual_ready_date:
            self.actual_ready_date = fields.Datetime.now()
        elif new_state in ('delivered', 'picked_up') and not self.handover_date:
            self.handover_date = fields.Datetime.now()

    @api.model
    def _create_from_pos_order(self, pos_order, laundry_data):
        branch_id = laundry_data.get('branch_id')
        if not branch_id:
            branch = self.env['laundry.branch'].search(
                [('pos_config_id', '=', pos_order.config_id.id)], limit=1
            )
            branch_id = branch.id if branch else False

        paid = pos_order.amount_due == 0
        order_vals = {
            'pos_order_id': pos_order.id,
            'partner_id': pos_order.partner_id.id,
            'branch_id': branch_id,
            'company_id': pos_order.company_id.id,
            'state': 'received',
            'priority': laundry_data.get('priority', 'normal'),
            'payment_state': 'paid' if paid else 'partial',
            'promise_date': laundry_data.get('promise_date'),
            'bag_reference': laundry_data.get('bag_reference', ''),
            'intake_notes': laundry_data.get('intake_notes', ''),
            'customer_notes': laundry_data.get('customer_notes', ''),
            'pre_damage_notes': laundry_data.get('pre_damage_notes', ''),
            'delivery_requested': laundry_data.get('delivery_requested', False),
            'user_id': pos_order.user_id.id or self.env.uid,
        }
        laundry_order = self.create(order_vals)

        for line_data in laundry_data.get('lines', []):
            self.env['laundry.order.line'].create({
                'order_id': laundry_order.id,
                **line_data,
            })

        _logger.info(
            'Created laundry.order %s for pos.order %s',
            laundry_order.name, pos_order.name,
        )
        return laundry_order

    def action_move_to_tagged(self):
        self.ensure_one()
        self.write({'state': 'tagged'})

    def action_move_to_sorted(self):
        self.ensure_one()
        self.write({'state': 'sorted'})

    def action_move_to_washing(self):
        self.ensure_one()
        self.write({'state': 'washing'})

    def action_move_to_drying(self):
        self.ensure_one()
        self.write({'state': 'drying'})

    def action_move_to_ironing(self):
        self.ensure_one()
        self.write({'state': 'ironing'})

    def action_move_to_packing(self):
        self.ensure_one()
        self.write({'state': 'packing'})

    def action_move_to_ready(self):
        self.ensure_one()
        self.write({'state': 'ready'})

    def _get_qr_code_src(self):
        """Generate QR code as base64 image for reports."""
        self.ensure_one()
        try:
            import qrcode
            import base64
            from io import BytesIO
            qr_data = f"{self.name}|{self.barcode}|{self.partner_id.name}|{self.amount_total}"
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode()
        except Exception:
            return False
