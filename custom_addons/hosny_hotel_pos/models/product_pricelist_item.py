# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    hotel_import_tracked = fields.Boolean(
        string='Set by the Price Sheet',
        copy=True,
        help="This rule came from the agreed price sheet, so the importer "
             "watches it. Rules created by hand are never touched by an import.",
    )

    hotel_imported_price = fields.Float(
        string='Price as Imported',
        digits='Product Price',
        copy=True,
        help="What the price sheet last set this rule to. Comparing it with "
             "the current price is how the importer knows a price was edited "
             "by hand, so it can leave it alone. A separate flag records that "
             "an import happened at all, because a genuine imported price of "
             "0.00 must not read as 'never imported'.",
    )

    hotel_price_edited = fields.Boolean(
        string='Edited Since Import',
        compute='_compute_hotel_price_edited',
        store=True,
        help="Set once someone changes the price away from the imported value.",
    )

    @api.depends('fixed_price', 'hotel_imported_price', 'hotel_import_tracked',
                 'compute_price', 'pricelist_id.is_hotel_contract')
    def _compute_hotel_price_edited(self):
        for item in self:
            if not item.hotel_import_tracked or not item.pricelist_id.is_hotel_contract:
                item.hotel_price_edited = False
                continue
            currency = item.currency_id or item.pricelist_id.currency_id
            if currency:
                item.hotel_price_edited = currency.compare_amounts(
                    item.fixed_price, item.hotel_imported_price) != 0
            else:
                item.hotel_price_edited = item.fixed_price != item.hotel_imported_price
