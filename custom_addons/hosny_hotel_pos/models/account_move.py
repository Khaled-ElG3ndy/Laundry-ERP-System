# -*- coding: utf-8 -*-
"""Contract prices on customer invoices typed in Accounting.

Odoo 17 prices an invoice line from the product's own sales price and never
looks at the customer's pricelist. Hotel products carry 0.00 there -- their
price lives only in the contract pricelist -- so an invoice written by hand for
a hotel customer came out at 0.00 while the hotel POS charged the agreed price.

The line now asks the customer's pricelist first when it is a hotel contract,
exactly the way a sale order line does, and changing the customer re-prices the
lines that carry a contract price. Customers without a contract, vendor bills
and every line created with an explicit price (POS invoices, sale order
invoices, credit notes) behave exactly as in core.
"""

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.onchange('partner_id')
    def _onchange_partner_id_hotel_contract_prices(self):
        """Re-price contract lines when the customer changes.

        A line's price only follows its product, so a line added before the
        customer was chosen would otherwise keep the 0.00 it got then -- the
        same thing the POS avoids by re-pricing the order on ``set_partner``.
        Only lines whose product has a hotel contract rule are touched, so a
        price typed on any other line survives a customer change, as in core.
        """
        contracts = self.env['product.pricelist'].search(
            [('is_hotel_contract', '=', True)])
        if not contracts:
            return
        for move in self:
            if move.state != 'draft' or not move.is_sale_document(include_receipts=True):
                continue
            move.invoice_line_ids.filtered(
                lambda line: line._has_hotel_contract_rule(contracts)
            )._compute_price_unit()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            pricelist = line._get_hotel_contract_pricelist()
            if pricelist:
                line.price_unit = line._get_hotel_contract_price_unit(pricelist)

    def _get_hotel_contract_pricelist(self):
        """The customer's contract pricelist, or an empty recordset.

        Only a hotel contract counts. Every other partner resolves to some
        fallback pricelist too (the first one of the company), and applying
        that would change retail invoicing, which this module leaves alone.
        """
        self.ensure_one()
        Pricelist = self.env['product.pricelist']
        move = self.move_id
        if (self.display_type != 'product' or not self.product_id
                or not move.partner_id
                or not move.is_sale_document(include_receipts=True)):
            return Pricelist
        company = move.company_id or self.env.company
        pricelist = move.partner_id.with_company(company).property_product_pricelist
        return pricelist if pricelist.is_hotel_contract else Pricelist

    def _get_hotel_contract_price_unit(self, pricelist):
        """Price this line from ``pricelist``, as ``sale.order.line`` does.

        A fixed rule is stored in the pricelist's currency and the pricelist
        does not convert it, so the price is taken in that currency and
        converted to the invoice's at the end, the way core converts a
        product's own price.
        """
        self.ensure_one()
        move = self.move_id
        company = move.company_id or self.env.company
        currency = self.currency_id or move.currency_id or company.currency_id
        pricelist_currency = pricelist.currency_id
        price = pricelist.with_company(company)._get_product_price(
            self.product_id,
            self.quantity or 1.0,
            currency=pricelist_currency,
            uom=self.product_uom_id or None,
            date=self._get_hotel_contract_price_date(),
        )
        price = self.product_id._get_tax_included_unit_price_from_price(
            price,
            pricelist_currency,
            product_taxes=self.product_id.taxes_id._filter_taxes_by_company(company),
            fiscal_position=move.fiscal_position_id,
        )
        if pricelist_currency != currency:
            price = pricelist_currency._convert(
                price, currency, company,
                move.date or fields.Date.context_today(self), round=False)
        return price

    def _get_hotel_contract_price_date(self):
        move = self.move_id
        return move.invoice_date or move.date or fields.Date.context_today(self)

    def _has_hotel_contract_rule(self, contracts):
        """Whether any contract in ``contracts`` prices this line's product."""
        self.ensure_one()
        if self.display_type != 'product' or not self.product_id:
            return False
        return any(
            contract._get_product_rule(
                self.product_id,
                self.quantity or 1.0,
                uom=self.product_uom_id or None,
                date=self._get_hotel_contract_price_date(),
            )
            for contract in contracts
        )
