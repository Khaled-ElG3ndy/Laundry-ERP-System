# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError


class LaundryStatusLog(models.Model):
    _name = 'laundry.status.log'
    _description = 'Laundry Order Status Log'
    _order = 'timestamp desc, id desc'

    order_id = fields.Many2one(
        'laundry.order',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    timestamp = fields.Datetime(
        required=True,
        readonly=True,
        index=True,
        default=fields.Datetime.now,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Changed By',
        required=True,
        readonly=True,
    )
    from_state = fields.Char(readonly=True)
    to_state = fields.Char(readonly=True, index=True)
    note = fields.Text(readonly=True)

    def write(self, vals):
        raise AccessError(_('Status log entries are immutable.'))

    def unlink(self):
        raise AccessError(_('Status log entries cannot be deleted.'))
