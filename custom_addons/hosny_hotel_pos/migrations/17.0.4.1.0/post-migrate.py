# -*- coding: utf-8 -*-
"""Charge VAT on top of hotel contract prices instead of inside them.

The agreed price sheet quotes every price before VAT, but the catalogue was
created with the retail catalogue's VAT-inclusive tax, so a 2.90 sheet price
was billed as 2.90 *including* VAT. This moves the sheet's products onto the
price-exclusive sale tax, so 2.90 is billed as 2.90 + 0.44 VAT = 3.34.

* Only the sheet's own products (``default_code`` from the price book), and only
  while every tax they carry is still price-inclusive -- a product somebody has
  already retaxed by hand is left alone.
* Pricelist rules are not touched: the prices stay exactly as imported.
* Orders already taken, paid or parked, keep the taxes stored on their lines.
"""

import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.hosny_hotel_pos.data import price_book

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    vat = env['hotel.pricing.setup']._hotel_taxes()
    if not vat:
        _logger.warning('Hotel pricing: no price-exclusive sale tax found, so '
                        'hotel products keep their VAT-inclusive tax')
        return

    codes = [product[0] for product in price_book.PRODUCTS]
    templates = env['product.template'].with_context(active_test=False).search(
        [('default_code', 'in', codes)])
    inclusive = templates.filtered(
        lambda template: template.taxes_id
        and all(template.taxes_id.mapped('price_include')))
    inclusive.write({'taxes_id': [(6, 0, vat.ids)]})

    _logger.info('Hotel pricing: %d hotel products now charge %s on top of the '
                 'contract price; %d left as they were',
                 len(inclusive), vat.name, len(templates) - len(inclusive))
