# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class LaundryHotelSession(models.Model):
    """Hotel pickup session — driver collects ready orders from hotel.
    Works for Farha Hotel and any generic hotel commercial account."""
    _name = 'laundry.hotel.session'
    _description = 'Hotel Pickup Session'
    _order = 'session_date desc, id desc'
    _rec_name = 'name'

    name            = fields.Char(string='Session Ref', readonly=True, copy=False)
    commercial_id   = fields.Many2one('laundry.commercial.account',
        string='Hotel Account', required=True,
        domain=[('state','=','active')])
    hotel_name      = fields.Char(related='commercial_id.name', readonly=True)
    driver_name     = fields.Char(string='Driver')
    vehicle_plate   = fields.Char(string='Vehicle Plate')
    session_date    = fields.Date(string='Pickup Date', default=fields.Date.today)
    state           = fields.Selection([
        ('draft',     'Draft'),
        ('dispatched','Dispatched'),
        ('delivered', 'Delivered'),
        ('returned',  'Returned'),
    ], default='draft', tracking=True)
    order_ids       = fields.Many2many(
        'laundry.order', string='Orders to Pickup',
        domain="[('commercial_account_id','=',commercial_id),"
               " ('state','=','ready')]")
    order_count     = fields.Integer(compute='_compute_order_count', string='Orders')
    total_amount    = fields.Monetary(compute='_compute_total', string='Total',
        currency_field='currency_id')
    currency_id     = fields.Many2one('res.currency',
        default=lambda self: self.env.company.currency_id)
    notes           = fields.Text(string='Notes')
    pickup_time     = fields.Datetime(string='Dispatched At')
    delivery_time   = fields.Datetime(string='Delivered At')
    branch_id       = fields.Many2one('laundry.branch', string='Branch')

    def _compute_order_count(self):
        for s in self:
            s.order_count = len(s.order_ids)

    def _compute_total(self):
        for s in self:
            s.total_amount = sum(s.order_ids.mapped('amount_total'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'laundry.hotel.session') or 'HS/0001'
        return super().create(vals_list)

    def action_dispatch(self):
        self.ensure_one()
        if not self.order_ids:
            raise UserError(_('Add orders before dispatching.'))
        if not self.driver_name:
            raise UserError(_('Enter driver name.'))
        self.write({
            'state':       'dispatched',
            'pickup_time': fields.Datetime.now(),
        })
        # Update orders to out_for_delivery
        self.order_ids.sudo().write({'state': 'out_for_delivery'})
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'message': _('✓ %s order(s) dispatched with driver %s',
                             len(self.order_ids), self.driver_name),
                'type': 'success',
            }
        }

    def action_mark_delivered(self):
        self.ensure_one()
        self.write({
            'state':         'delivered',
            'delivery_time': fields.Datetime.now(),
        })
        self.order_ids.sudo().write({
            'state':         'delivered',
            'payment_state': 'on_account',
        })
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'message': _('✓ Delivered to the hotel. It will be billed '
                             'on the account.'),
                'type': 'success',
            }
        }

    def action_load_ready_orders(self):
        """Auto-load all ready orders for this hotel account."""
        self.ensure_one()
        ready = self.env['laundry.order'].search([
            ('commercial_account_id', '=', self.commercial_id.id),
            ('state', '=', 'ready'),
        ])
        self.order_ids = ready
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'message': _('%s ready order(s) loaded', len(ready)),
                'type': 'info',
            }
        }

    def action_print_manifest(self):
        return self.env.ref(
            'laundry_base.action_report_hotel_manifest'
        ).report_action(self)
