# -*- coding: utf-8 -*-
from odoo import fields, models

# The zones a branch store is split into. The code ties a product category, a
# physical sub-location and a put-away rule together. The second element is the
# translated label; the third is the physical location name, which Odoo does not
# translate, so it carries both languages.
SUPPLY_ZONES = [
    ('CHEM', 'Chemicals & Detergents', 'Chemicals & Detergents / كيماويات ومنظفات'),
    ('PACK', 'Packaging & Covers', 'Packaging & Covers / تغليف وأغطية'),
    ('HANG', 'Hangers & Tags', 'Hangers & Tags / شماعات وبطاقات'),
    ('SPARE', 'Spare Parts & Maintenance', 'Spare Parts & Maintenance / قطع غيار وصيانة'),
    ('LINEN', 'Linen & Uniforms', 'Linen & Uniforms / بياضات ويونيفورم'),
    ('HKPG', 'Housekeeping & Office', 'Housekeeping & Office / نظافة ومستلزمات مكتبية'),
]

ZONE_SELECTION = [(code, label) for code, label, _location_name in SUPPLY_ZONES]


class ProductCategory(models.Model):
    _inherit = 'product.category'

    laundry_zone_code = fields.Selection(
        ZONE_SELECTION,
        string='Laundry Storage Zone',
        help='Products of this category are stored in — and automatically put '
             'away to — this zone of every branch store.',
    )
