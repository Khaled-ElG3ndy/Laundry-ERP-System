# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Names the service attribute is known by in an existing database.
SERVICE_ATTRIBUTE_NAMES = ('Service Type', 'نوع الخدمة')


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    is_laundry_service = fields.Boolean(
        string='Laundry Service Attribute',
        help='Tick the attribute that says which service a garment is sold '
             'with — ironing, wash & iron, deep clean. Consumption norms can '
             'then be set per service.',
    )

    @api.model
    def _laundry_service_attribute(self):
        """The attribute holding the service, flagged or found by its name."""
        flagged = self.search([('is_laundry_service', '=', True)], limit=1)
        if flagged:
            return flagged
        for name in SERVICE_ATTRIBUTE_NAMES:
            found = self.search([('name', '=', name)], limit=1)
            if found:
                found.is_laundry_service = True
                return found
        return self.browse()
