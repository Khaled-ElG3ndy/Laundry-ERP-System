from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    fps_enable_grocery = fields.Boolean(string='Enable Grocery Features')
    fps_enable_snap = fields.Boolean(string='Enable SNAP/EBT')
    fps_enable_weighted_barcodes = fields.Boolean(string='Enable Weighted Barcodes')
    fps_default_department_id = fields.Many2one(
        'fps.product.department',
        string='Default Department',
    )
