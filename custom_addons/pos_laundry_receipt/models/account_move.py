from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    pos_order_ids = fields.One2many(
        'pos.order',
        'account_move',
        string='POS Orders',
        readonly=True,
    )
    pos_order_count = fields.Integer(
        string='POS Orders',
        compute='_compute_pos_order_count',
        readonly=True,
    )

    @api.depends('pos_order_ids')
    def _compute_pos_order_count(self):
        for move in self:
            move.pos_order_count = len(move.pos_order_ids)

    def action_view_pos_orders(self):
        self.ensure_one()
        action = self.env.ref('point_of_sale.action_pos_pos_form').read()[0]
        action['domain'] = [('id', 'in', self.pos_order_ids.ids)]
        if len(self.pos_order_ids) == 1:
            action['views'] = [
                (self.env.ref('point_of_sale.view_pos_pos_form').id, 'form'),
            ]
            action['res_id'] = self.pos_order_ids.id
        else:
            action['views'] = [
                (self.env.ref('point_of_sale.view_pos_order_tree').id, 'tree'),
                (self.env.ref('point_of_sale.view_pos_pos_form').id, 'form'),
            ]
            action['res_id'] = False
        action['context'] = {}
        return action
