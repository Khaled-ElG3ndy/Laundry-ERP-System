# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError


class LaundryAuditLog(models.Model):
    _name = 'laundry.audit.log'
    _description = 'Laundry Audit Log'
    _order = 'timestamp desc, id desc'

    order_id = fields.Many2one(
        'laundry.order', index=True, ondelete='set null', readonly=True,
    )
    user_id = fields.Many2one(
        'res.users', required=True, readonly=True,
    )
    action = fields.Selection([
        ('discount', 'Discount Applied'),
        ('price_override', 'Price Overridden'),
        ('cancel', 'Order Cancelled'),
        ('refund', 'Refund Issued'),
        ('handover', 'Order Handed Over'),
        ('compensation', 'Compensation Approved'),
        ('session_close', 'Session Closed'),
        ('other', 'Other'),
    ], required=True, readonly=True)
    details = fields.Text(readonly=True)
    timestamp = fields.Datetime(
        required=True, readonly=True, index=True,
        default=fields.Datetime.now,
    )
    branch_id = fields.Many2one(
        'laundry.branch',
        related='order_id.branch_id',
        store=True, index=True,
    )

    def write(self, vals):
        raise AccessError(_('Audit log entries are immutable.'))

    def unlink(self):
        raise AccessError(_('Audit log entries cannot be deleted.'))
