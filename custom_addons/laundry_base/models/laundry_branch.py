# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .laundry_naming import display_name_for


class LaundryBranch(models.Model):
    _name = 'laundry.branch'
    _description = 'Laundry Branch'
    _order = 'sequence, name'

    name = fields.Char(string='Branch Name', required=True, translate=True)
    name_ar = fields.Char(string='Arabic Name')
    code = fields.Char(string='Code', required=True, size=10)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    pos_config_id = fields.Many2one(
        'pos.config',
        string='POS Configuration',
        ondelete='set null',
    )
    manager_id = fields.Many2one(
        'res.users',
        string='Branch Manager',
        domain=[('share', '=', False)],
    )
    phone = fields.Char()
    street = fields.Char()
    city = fields.Char()

    order_count = fields.Integer(
        compute='_compute_order_count',
        string='Total Orders',
        store=False,
    )
    open_order_count = fields.Integer(
        compute='_compute_order_count',
        string='Open Orders',
        store=False,
    )

    def _compute_order_count(self):
        for branch in self:
            if not branch.id:
                branch.order_count = 0
                branch.open_order_count = 0
                continue
            orders = self.env['laundry.order'].search(
                [('branch_id', '=', branch.id)]
            )
            branch.order_count = len(orders)
            branch.open_order_count = len(orders.filtered(
                lambda o: o.state not in ('delivered', 'picked_up', 'cancelled')
            ))

    @api.constrains('code')
    def _check_code_unique(self):
        for rec in self:
            if self.search_count([
                ('code', '=', rec.code),
                ('id', '!=', rec.id)
            ]):
                raise ValidationError(
                    _('Branch code must be unique: %s') % rec.code
                )

    @api.depends('name', 'name_ar', 'code')
    def _compute_display_name(self):
        for branch in self:
            branch.display_name = '[%s] %s' % (
                branch.code, display_name_for(branch))
