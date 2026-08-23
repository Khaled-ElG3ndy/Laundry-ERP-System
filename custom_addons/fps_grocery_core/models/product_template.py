from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fps_department_id = fields.Many2one('fps.product.department', string='Department')
    snap_eligible = fields.Boolean(string='SNAP Eligible', default=True)
    is_weighted = fields.Boolean(string='Sold by Weight')
    plu_code = fields.Char(string='PLU Code', size=5)
    scale_label_format = fields.Selection(
        [
            ('standard', 'Standard'),
            ('upc_a', 'UPC-A'),
            ('ean13', 'EAN-13'),
        ],
        string='Scale Label Format',
        default='standard',
    )
    is_perishable = fields.Boolean(string='Perishable')
    shelf_life_days = fields.Integer(string='Shelf Life (Days)')
    requires_refrigeration = fields.Boolean(string='Requires Refrigeration')
    is_fresh_prep = fields.Boolean(string='Fresh Prepared')
