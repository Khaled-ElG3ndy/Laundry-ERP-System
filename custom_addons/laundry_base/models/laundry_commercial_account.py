# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LaundryCommercialAccount(models.Model):
    """
    Commercial / wholesale account stub.
    Full billing logic lives in laundry_commercial module (Phase 2).
    This stub allows laundry.order to reference it safely.
    """
    _name = 'laundry.commercial.account'
    _description = 'Laundry Commercial Account'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char(required=True, size=30)
    active = fields.Boolean(default=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Billing Contact',
        required=True,
    )
    state = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('closed', 'Closed'),
    ], default='active', required=True)

    credit_limit = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    billing_cycle = fields.Selection([
        ('weekly', 'Weekly'),
        ('biweekly', 'Bi-weekly'),
        ('monthly', 'Monthly'),
        ('custom', 'Custom'),
    ], default='monthly')

    payment_terms_id = fields.Many2one('account.payment.term')
    account_manager_id = fields.Many2one(
        'res.users',
        domain=[('share', '=', False)],
    )
    contract_notes = fields.Text()

    order_ids = fields.One2many(
        'laundry.order',
        'commercial_account_id',
        string='Orders',
    )

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for account in self:
            account.display_name = '[%s] %s' % (account.code, account.name)

    def action_run_billing(self):
        """Open billing wizard pre-filled for this account."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Run Billing',
            'res_model': 'laundry.billing.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_account_id': self.id,
            },
        }
