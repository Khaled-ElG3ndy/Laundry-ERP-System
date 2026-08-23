# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError


class LaundryIssue(models.Model):
    _name = 'laundry.issue'
    _description = 'Laundry Issue / Claim'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        required=True, copy=False, readonly=True,
        default=lambda self: _('New'),
    )
    order_id = fields.Many2one(
        'laundry.order',
        required=True,
        index=True,
        ondelete='cascade',
        tracking=True,
    )
    order_line_id = fields.Many2one(
        'laundry.order.line',
        string='Affected Line',
        domain="[('order_id','=',order_id)]",
    )
    partner_id = fields.Many2one(
        related='order_id.partner_id', store=True,
    )
    branch_id = fields.Many2one(
        related='order_id.branch_id', store=True, index=True,
    )
    issue_type = fields.Selection([
        ('damage', 'Damage / تلف'),
        ('missing', 'Missing Item / قطعة مفقودة'),
        ('rewash', 'Rewash / إعادة غسيل'),
        ('complaint', 'Complaint / شكوى'),
        ('delay', 'Delay / تأخير'),
        ('other', 'Other / أخرى'),
    ], required=True, tracking=True)

    state = fields.Selection([
        ('open', 'Open / مفتوح'),
        ('in_review', 'In Review / قيد المراجعة'),
        ('resolved', 'Resolved / تم الحل'),
        ('compensated', 'Compensated / تعويض'),
        ('closed', 'Closed / مغلق'),
    ], default='open', required=True, tracking=True)

    reported_by = fields.Many2one(
        'res.users', default=lambda self: self.env.user, readonly=True,
    )
    reported_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    resolved_by = fields.Many2one('res.users', readonly=True)
    resolved_date = fields.Datetime(readonly=True)

    description = fields.Text(required=True)
    root_cause = fields.Text()
    resolution_notes = fields.Text()

    compensation_amount = fields.Monetary(currency_field='currency_id')
    compensation_approved_by = fields.Many2one('res.users', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    rewash_order_id = fields.Many2one('laundry.order', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('laundry.issue')
                    or _('New')
                )
        issues = super().create(vals_list)
        for issue in issues:
            if issue.order_id.state not in ('cancelled', 'delivered', 'picked_up'):
                issue.order_id.sudo().write({'state': 'issue'})
        return issues

    def action_resolve(self, resolution_notes=''):
        if not self.env.user.has_group('laundry_base.group_laundry_supervisor'):
            raise AccessError(_('Supervisor permission required.'))
        self.write({
            'state': 'resolved',
            'resolved_by': self.env.uid,
            'resolved_date': fields.Datetime.now(),
            'resolution_notes': resolution_notes,
        })

    def action_create_rewash_order(self):
        self.ensure_one()
        if self.rewash_order_id:
            raise AccessError(_('Rewash order already exists.'))
        rewash = self.env['laundry.order'].create({
            'partner_id': self.order_id.partner_id.id,
            'branch_id': self.order_id.branch_id.id,
            'company_id': self.order_id.company_id.id,
            'state': 'received',
            'priority': 'urgent',
            'payment_state': 'paid',
            'promise_date': fields.Datetime.now(),
            'intake_notes': 'Rewash for %s' % self.name,
            'order_line_ids': [(0, 0, {
                'item_category_id': l.item_category_id.id,
                'service_type_id': l.service_type_id.id,
                'qty': l.qty,
                'unit_price': 0.0,
                'line_notes': 'Rewash: %s' % self.description,
            }) for l in self.order_id.order_line_ids
              if not self.order_line_id or l == self.order_line_id],
        })
        self.write({'rewash_order_id': rewash.id, 'state': 'in_review'})
        return rewash
