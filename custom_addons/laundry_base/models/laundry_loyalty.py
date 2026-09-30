# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)


class LaundryLoyaltyProgram(models.Model):
    _name = 'laundry.loyalty.program'
    _description = 'Laundry Loyalty Program'

    name           = fields.Char(required=True, default='Loyalty Program')
    active         = fields.Boolean(default=True)
    points_per_sar = fields.Float(string='Points per SAR', default=1.0)
    sar_per_point  = fields.Float(string='SAR per Point', default=0.1)
    min_redeem     = fields.Integer(string='Min Points to Redeem', default=100)
    max_redeem_pct = fields.Float(string='Max Redeem % of Order', default=30.0)
    expiry_months  = fields.Integer(string='Points Expiry (months)', default=12)
    welcome_points = fields.Integer(string='Welcome Points', default=50)

    @api.model
    def get_active(self):
        return self.search([('active', '=', True)], limit=1)


class LaundryLoyaltyCard(models.Model):
    _name = 'laundry.loyalty.card'
    _description = 'Customer Loyalty Card'
    _rec_name = 'card_number'

    partner_id     = fields.Many2one('res.partner', required=True,
        string='Customer', ondelete='cascade', index=True)
    card_number    = fields.Char(string='Card Number', readonly=True, copy=False)
    points         = fields.Float(string='Current Points', default=0.0)
    total_earned   = fields.Float(string='Total Earned', default=0.0, readonly=True)
    total_redeemed = fields.Float(string='Total Redeemed', default=0.0, readonly=True)
    tier           = fields.Selection([
        ('silver', '🥈 Silver'),
        ('gold',   '🥇 Gold'),
        ('vip',    '💎 VIP'),
    ], string='Tier', compute='_compute_tier', store=True)
    active         = fields.Boolean(default=True)
    log_ids        = fields.One2many('laundry.loyalty.log', 'card_id', string='History')
    order_count    = fields.Integer(string='Total Orders', compute='_compute_order_count')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('card_number'):
                vals['card_number'] = self.env['ir.sequence'].next_by_code(
                    'laundry.loyalty.card') or 'LC/0001'
        return super().create(vals_list)

    @api.depends('total_earned')
    def _compute_tier(self):
        for card in self:
            if card.total_earned >= 5000:
                card.tier = 'vip'
            elif card.total_earned >= 2000:
                card.tier = 'gold'
            else:
                card.tier = 'silver'

    def _compute_order_count(self):
        for card in self:
            card.order_count = self.env['laundry.order'].search_count([
                ('partner_id', '=', card.partner_id.id)
            ])

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Orders',
            'res_model': 'laundry.order',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.partner_id.id)],
            'context': {'default_partner_id': self.partner_id.id},
        }

    def award_points(self, amount_sar, order_id=None, reason='purchase'):
        self.ensure_one()
        program = self.env['laundry.loyalty.program'].get_active()
        if not program:
            return 0
        pts = round(amount_sar * program.points_per_sar, 2)
        if pts <= 0:
            return 0
        self.write({
            'points':       self.points + pts,
            'total_earned': self.total_earned + pts,
        })
        self.env['laundry.loyalty.log'].create({
            'card_id':  self.id,
            'order_id': order_id,
            'type':     'earn',
            'points':   pts,
            'balance':  self.points,
            'reason':   reason,
        })
        return pts

    def redeem_points(self, points_to_use, order_id=None):
        self.ensure_one()
        program = self.env['laundry.loyalty.program'].get_active()
        if not program:
            raise UserError(_('No active loyalty program.'))
        if points_to_use > self.points:
            raise UserError(_(
                'Not enough points. Current balance: %.0f point(s)'
            ) % self.points)
        if points_to_use < program.min_redeem:
            raise UserError(_(
                'Minimum to redeem: %d point(s)'
            ) % program.min_redeem)
        sar_discount = round(points_to_use * program.sar_per_point, 2)
        self.write({
            'points':          self.points - points_to_use,
            'total_redeemed':  self.total_redeemed + points_to_use,
        })
        self.env['laundry.loyalty.log'].create({
            'card_id':  self.id,
            'order_id': order_id,
            'type':     'redeem',
            'points':   -points_to_use,
            'balance':  self.points,
            'reason':   'Redeemed for SAR %.2f discount' % sar_discount,
        })
        return sar_discount

    @api.model
    def get_or_create_for_partner(self, partner_id):
        card = self.search([
            ('partner_id', '=', partner_id),
            ('active', '=', True)
        ], limit=1)
        if not card:
            card = self.create({'partner_id': partner_id})
            program = self.env['laundry.loyalty.program'].get_active()
            if program and program.welcome_points > 0:
                card.write({
                    'points':       program.welcome_points,
                    'total_earned': program.welcome_points,
                })
                self.env['laundry.loyalty.log'].create({
                    'card_id': card.id,
                    'type':    'earn',
                    'points':  program.welcome_points,
                    'balance': program.welcome_points,
                    'reason':  'Welcome points',
                })
        return card


class LaundryLoyaltyLog(models.Model):
    _name = 'laundry.loyalty.log'
    _description = 'Loyalty Points Log'
    _order = 'create_date desc'

    card_id  = fields.Many2one('laundry.loyalty.card', required=True, ondelete='cascade')
    order_id = fields.Many2one('laundry.order', string='Order')
    type     = fields.Selection([
        ('earn',   'Earned'),
        ('redeem', 'Redeemed'),
        ('adjust', 'Adjusted'),
    ], required=True)
    points  = fields.Float(string='Points Change')
    balance = fields.Float(string='Balance After')
    reason  = fields.Char(string='Reason')
    date    = fields.Datetime(default=fields.Datetime.now, readonly=True)
