from odoo import models, fields, api

class ProductDepartment(models.Model):
    _name = 'fps.product.department'
    _description = 'Product Department'
    _order = 'sequence, name'

    name = fields.Char(string='Department Name', required=True)
    code = fields.Char(string='Code', required=True, size=4)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    is_fresh = fields.Boolean(string='Fresh Department', help='Meat, Produce, Bakery, Deli')
    is_weighted = fields.Boolean(string='Weighted Items', help='Items sold by weight')
    default_snap_eligible = fields.Boolean(string='SNAP Eligible by Default', default=True)
    color = fields.Integer(string='Color Index')
    product_count = fields.Integer(compute='_compute_product_count')

    @api.depends()
    def _compute_product_count(self):
        for dept in self:
            dept.product_count = self.env['product.template'].search_count([
                ('fps_department_id', '=', dept.id)
            ])
