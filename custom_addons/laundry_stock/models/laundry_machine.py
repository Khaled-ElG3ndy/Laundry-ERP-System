# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LaundryMachine(models.Model):
    _name = 'laundry.machine'
    _description = 'Laundry Machine'
    _order = 'branch_id, sequence, name'

    name = fields.Char(string='Machine', required=True, translate=True)
    code = fields.Char(string='Code', required=True, size=16)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        required=True,
        index=True,
        ondelete='restrict',
    )
    machine_type = fields.Selection([
        ('washer', 'Washing Machine'),
        ('dryer', 'Dryer'),
        ('dry_clean', 'Dry-clean Machine'),
        ('ironer', 'Ironing / Flatwork'),
        ('press', 'Press'),
        ('folder', 'Folding Machine'),
        ('boiler', 'Boiler'),
        ('other', 'Other Equipment'),
    ], string='Type', required=True, default='washer')

    capacity_kg = fields.Float(string='Capacity (kg)', digits=(6, 2))
    serial_number = fields.Char(string='Serial Number')
    vendor_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        domain=[('supplier_rank', '>', 0)],
    )
    install_date = fields.Date(string='Installed On')
    warranty_end = fields.Date(string='Warranty Ends')
    note = fields.Text(string='Notes')

    issue_ids = fields.One2many(
        'laundry.stock.issue',
        'machine_id',
        string='Material Issues',
    )
    issue_count = fields.Integer(compute='_compute_issue_figures')
    maintenance_cost = fields.Monetary(
        string='Spare Parts Cost',
        compute='_compute_issue_figures',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    _sql_constraints = [
        ('code_branch_uniq', 'unique(code, branch_id)',
         'A machine with this code already exists in this branch.'),
    ]

    @api.depends('issue_ids.state', 'issue_ids.total_cost')
    def _compute_issue_figures(self):
        for machine in self:
            done = machine.issue_ids.filtered(lambda i: i.state == 'done')
            machine.issue_count = len(done)
            machine.maintenance_cost = sum(done.mapped('total_cost'))

    def action_view_issues(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_issue'
        )
        action['domain'] = [('machine_id', '=', self.id)]
        action['context'] = {
            'default_machine_id': self.id,
            'default_branch_id': self.branch_id.id,
            'default_purpose': 'maintenance',
        }
        return action

    def name_get(self):
        return [(m.id, '[%s] %s' % (m.code, m.name)) for m in self]
