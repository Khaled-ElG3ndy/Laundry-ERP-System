# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
import logging
_logger = logging.getLogger(__name__)


class LaundryBillingWizard(models.TransientModel):
    _name = 'laundry.billing.wizard'
    _description = 'Laundry Commercial Billing Run'

    account_id = fields.Many2one(
        'laundry.commercial.account',
        string='Commercial Account',
        required=True,
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=fields.Date.today,
    )
    order_count = fields.Integer(string='Unbilled Orders', readonly=True)
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('previewed', 'Previewed'),
        ('done', 'Done'),
    ], default='draft', readonly=True)
    preview_line_ids = fields.One2many(
        'laundry.billing.wizard.line',
        'wizard_id',
        string='Orders to Invoice',
        readonly=True,
    )

    def action_preview(self):
        self.ensure_one()
        user = self.env.user
        if not (user.has_group('laundry_base.group_laundry_manager') or
                user.has_group('laundry_base.group_laundry_finance')):
            raise AccessError(_('Billing requires Manager or Finance permission.'))
        orders = self._get_billable_orders()
        self.order_count = len(orders)
        self.total_amount = sum(orders.mapped('amount_total'))
        self.preview_line_ids.unlink()
        lines = []
        for order in orders:
            lines.append((0, 0, {
                'order_id': order.id,
                'partner_name': order.partner_id.name,
                'date_order': order.date_order,
                'amount_total': order.amount_total,
                'line_count': order.line_count,
            }))
        self.preview_line_ids = lines
        self.state = 'previewed'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'previewed':
            raise UserError(_('Please preview before confirming.'))
        orders = self._get_billable_orders()
        if not orders:
            raise UserError(_('No unbilled orders found.'))
        invoice = self._create_invoice(orders)
        orders.write({'payment_state': 'invoiced'})
        for order in orders:
            order.invoice_ids = [(4, invoice.id)]
        self.env['laundry.audit.log'].sudo().create({
            'user_id': self.env.uid,
            'action': 'other',
            'details': (
                f'Billing: {self.account_id.name}, '
                f'{len(orders)} orders, {self.total_amount:.2f} SAR'
            ),
        })
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoice Created'),
            'res_model': 'account.move',
            'res_id': invoice.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def _get_billable_orders(self):
        return self.env['laundry.order'].search([
            ('commercial_account_id', '=', self.account_id.id),
            ('payment_state', '=', 'on_account'),
            ('state', 'not in', ['cancelled', 'draft']),
            ('date_order', '>=', fields.Datetime.to_datetime(self.date_from)),
            ('date_order', '<=', fields.Datetime.to_datetime(
                str(self.date_to) + ' 23:59:59'
            )),
        ], order='date_order asc')

    def _create_invoice(self, orders):
        invoice_lines = []
        for order in orders:
            for line in order.order_line_ids:
                if not line.product_id:
                    continue
                invoice_lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'name': '[%s] %s' % (
                        order.name,
                        line.description or line.product_id.name
                    ),
                    'quantity': line.qty,
                    'price_unit': line.unit_price + line.urgent_surcharge,
                    'discount': line.discount_pct,
                }))
        if not invoice_lines:
            raise UserError(_(
                'No invoiceable lines. Ensure order lines have linked products.'
            ))
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.account_id.partner_id.id,
            'invoice_date': fields.Date.today(),
            'payment_reference': 'Farha Laundry — %s — %s to %s' % (
                self.account_id.code, self.date_from, self.date_to
            ),
            'invoice_payment_term_id': (
                self.account_id.payment_terms_id.id
                if self.account_id.payment_terms_id else False
            ),
            'invoice_line_ids': invoice_lines,
            'narration': 'Laundry — %s\nPeriod: %s to %s\nOrders: %s' % (
                self.account_id.name,
                self.date_from,
                self.date_to,
                ', '.join(orders.mapped('name')),
            ),
        })


class LaundryBillingWizardLine(models.TransientModel):
    _name = 'laundry.billing.wizard.line'
    _description = 'Billing Wizard Preview Line'

    wizard_id = fields.Many2one('laundry.billing.wizard', ondelete='cascade')
    order_id = fields.Many2one('laundry.order', string='Order', readonly=True)
    partner_name = fields.Char(string='Customer', readonly=True)
    date_order = fields.Datetime(string='Date', readonly=True)
    amount_total = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        readonly=True,
    )
    line_count = fields.Integer(string='Items', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
    )
