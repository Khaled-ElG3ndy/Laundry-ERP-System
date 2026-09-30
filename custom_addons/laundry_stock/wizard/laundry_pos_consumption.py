# -*- coding: utf-8 -*-
from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

POS_DONE_STATES = ('paid', 'done', 'invoiced')


class LaundryPosConsumption(models.TransientModel):
    """Turn what the counter sold over a period into one material issue."""
    _name = 'laundry.pos.consumption'
    _description = 'Issue Materials from Sales'

    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        default=lambda self: self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)], limit=1),
    )
    date_from = fields.Date(
        string='From',
        required=True,
        default=fields.Date.context_today,
    )
    date_to = fields.Date(
        string='To',
        required=True,
        default=fields.Date.context_today,
    )
    pos_config_ids = fields.Many2many(
        'pos.config',
        string='Points of Sale',
        compute='_compute_pos_config_ids',
        store=True,
        readonly=False,
        help='Leave empty to read every point of sale.',
    )
    ignore_overlap = fields.Boolean(
        string='Issue Anyway',
        help='Tick it to issue a period that was already issued once.',
    )
    line_count = fields.Integer(
        string='Sold Lines',
        compute='_compute_preview',
    )
    piece_count = fields.Float(
        string='Pieces',
        compute='_compute_preview',
    )
    preview = fields.Text(
        string='Materials',
        compute='_compute_preview',
    )

    @api.depends('branch_id')
    def _compute_pos_config_ids(self):
        for wizard in self:
            wizard.pos_config_ids = wizard.branch_id.pos_config_id

    def _pos_lines(self):
        """The sold lines of the period, in the user's own time zone."""
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_('The end date comes before the start date.'))
        timezone = pytz.timezone(self.env.user.tz or 'UTC')
        start = timezone.localize(
            datetime.combine(self.date_from, time.min)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        end = timezone.localize(
            datetime.combine(self.date_to, time.max)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        domain = [
            ('order_id.date_order', '>=', start),
            ('order_id.date_order', '<=', end),
            ('order_id.state', 'in', POS_DONE_STATES),
            ('qty', '>', 0),
        ]
        if self.pos_config_ids:
            domain.append(('order_id.config_id', 'in', self.pos_config_ids.ids))
        return self.env['pos.order.line'].search(domain)

    @api.depends('branch_id', 'date_from', 'date_to', 'pos_config_ids')
    def _compute_preview(self):
        norm_model = self.env['laundry.consumption.norm']
        for wizard in self:
            wizard.line_count = 0
            wizard.piece_count = 0.0
            wizard.preview = ''
            if not wizard.date_from or not wizard.date_to:
                continue
            try:
                lines = wizard._pos_lines()
            except UserError:
                continue
            needs, missing = norm_model._quantities_for_pos_lines(
                lines, branch=wizard.branch_id)
            wizard.line_count = len(lines)
            wizard.piece_count = sum(lines.mapped('qty'))
            rows = [
                '• %s: %s %s' % (product.display_name, round(qty, 4), uom.name)
                for product, (qty, uom) in needs.items()
            ]
            if missing:
                rows.append('')
                rows.append(_(
                    'No weight on: %s — their per-kilogram norms were skipped.',
                    ', '.join(missing)
                ))
            wizard.preview = '\n'.join(rows) or _(
                'No consumption norm matches what was sold in this period.'
            )

    def action_create_issue(self):
        self.ensure_one()
        self.branch_id._require_warehouse()
        lines = self._pos_lines()
        if not lines:
            raise UserError(_('Nothing was sold in this period.'))

        if not self.ignore_overlap:
            overlapping = self.env['laundry.stock.issue'].search([
                ('branch_id', '=', self.branch_id.id),
                ('source', '=', 'pos'),
                ('state', '!=', 'cancel'),
                ('pos_date_from', '<=', self.date_to),
                ('pos_date_to', '>=', self.date_from),
            ], limit=3)
            if overlapping:
                raise UserError(_(
                    'This period was already issued: %s.\n'
                    'Tick "Issue Anyway" to do it again.',
                    ', '.join(overlapping.mapped('name'))
                ))

        needs, missing = self.env['laundry.consumption.norm'] \
            ._quantities_for_pos_lines(lines, branch=self.branch_id)
        if not needs:
            raise UserError(_(
                'No consumption norm matches what was sold in this period. '
                'Set the norms first, under Laundry > Inventory > '
                'Configuration > Consumption Norms.'
            ))

        note = _('From %s sold line(s), %s piece(s), between %s and %s.',
                 len(lines), round(sum(lines.mapped('qty')), 2),
                 self.date_from, self.date_to)
        if missing:
            note += '\n' + _('No weight on: %s.', ', '.join(missing))

        issue = self.env['laundry.stock.issue'].create({
            'branch_id': self.branch_id.id,
            'purpose': 'production',
            'source': 'pos',
            'pos_date_from': self.date_from,
            'pos_date_to': self.date_to,
            'note': note,
            'line_ids': [
                fields.Command.create({
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom_id': uom.id,
                })
                for product, (qty, uom) in needs.items()
                if qty > 0
            ],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Material Issue'),
            'res_model': 'laundry.stock.issue',
            'res_id': issue.id,
            'view_mode': 'form',
        }
