# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class LaundryConsumptionReport(models.Model):
    """What every branch used, out of which zone, on which order."""
    _name = 'laundry.consumption.report'
    _description = 'Material Consumption Analysis'
    _auto = False
    _order = 'date desc'
    _rec_name = 'product_id'

    date = fields.Datetime(string='Date', readonly=True)
    branch_id = fields.Many2one('laundry.branch', string='Branch', readonly=True)
    product_id = fields.Many2one('product.product', string='Material', readonly=True)
    categ_id = fields.Many2one('product.category', string='Category', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit', readonly=True)
    purpose = fields.Selection([
        ('production', 'Production'),
        ('maintenance', 'Machine Maintenance'),
        ('housekeeping', 'Housekeeping'),
        ('damage', 'Damage / Loss'),
        ('other', 'Other'),
    ], string='Purpose', readonly=True)
    operation_type = fields.Selection([
        ('issue', 'Issue to Operations'),
        ('return', 'Return to Store'),
    ], string='Operation', readonly=True)
    machine_id = fields.Many2one('laundry.machine', string='Machine', readonly=True)
    laundry_order_id = fields.Many2one(
        'laundry.order', string='Laundry Order', readonly=True)
    issue_id = fields.Many2one(
        'laundry.stock.issue', string='Document', readonly=True)
    user_id = fields.Many2one('res.users', string='Issued By', readonly=True)
    qty = fields.Float(string='Quantity', readonly=True)
    cost = fields.Float(string='Cost', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    l.id                                      AS id,
                    i.date                                    AS date,
                    i.branch_id                               AS branch_id,
                    i.purpose                                 AS purpose,
                    i.operation_type                          AS operation_type,
                    i.machine_id                              AS machine_id,
                    i.laundry_order_id                        AS laundry_order_id,
                    i.user_id                                 AS user_id,
                    i.id                                      AS issue_id,
                    i.company_id                              AS company_id,
                    l.product_id                              AS product_id,
                    pt.categ_id                               AS categ_id,
                    pt.uom_id                                 AS product_uom_id,
                    CASE WHEN i.operation_type = 'return'
                         THEN -1 ELSE 1 END
                        * (l.product_uom_qty / NULLIF(lu.factor, 0) * pu.factor)
                                                              AS qty,
                    CASE WHEN i.operation_type = 'return'
                         THEN -1 ELSE 1 END * l.subtotal       AS cost
                  FROM laundry_stock_issue_line l
                  JOIN laundry_stock_issue i   ON i.id = l.issue_id
                  JOIN product_product pp      ON pp.id = l.product_id
                  JOIN product_template pt     ON pt.id = pp.product_tmpl_id
                  JOIN uom_uom lu              ON lu.id = l.product_uom_id
                  JOIN uom_uom pu              ON pu.id = pt.uom_id
                 WHERE i.state = 'done'
            )
        """ % self._table)
