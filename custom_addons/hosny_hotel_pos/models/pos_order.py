# -*- coding: utf-8 -*-
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _process_order(self, order, draft, existing_order):
        """Refuse to settle a hotel order without a contract customer.

        Enforced server-side because this is the single point every payment
        passes through, including orders replayed after an offline spell. A
        browser-only check would be bypassed by a stale client.

        ``draft`` orders are parked, not paid, so they are left alone; the
        check applies at the moment money is taken.
        """
        if not draft:
            self._check_hotel_contract_customer(order.get('data', order))
        return super()._process_order(order, draft, existing_order)

    @api.model
    def _check_hotel_contract_customer(self, order_data):
        session = self.env['pos.session'].browse(
            order_data.get('pos_session_id')).exists()
        if not session or not session.config_id.is_hotel_pos:
            return

        partner = self.env['res.partner'].browse(
            order_data.get('partner_id') or 0).exists()
        if not partner:
            raise UserError(_(
                "Select a hotel or company customer before taking payment. "
                "This point of sale applies agreed contract prices, so an "
                "order without a customer cannot be settled here."))

        if not partner.is_hotel_customer:
            raise UserError(_(
                "\"%(name)s\" is not a hotel or company customer. Only contract "
                "customers can be served from this point of sale.",
                name=partner.display_name))

        pricelist = partner.property_product_pricelist
        if not pricelist.is_hotel_contract:
            raise UserError(_(
                "\"%(name)s\" has no agreed contract pricelist, so this order "
                "cannot be priced correctly. Assign that customer a hotel "
                "contract pricelist first.",
                name=partner.display_name))

        # The order must have been priced with the customer's own pricelist. A
        # mismatch means the client priced the lines before the customer was
        # chosen, which is exactly the silent mispricing this guards against.
        order_pricelist_id = order_data.get('pricelist_id')
        if order_pricelist_id and order_pricelist_id != pricelist.id:
            raise UserError(_(
                "This order was priced with a different pricelist than "
                "\"%(name)s\" is contracted on. Re-select the customer so the "
                "lines are recalculated, then take payment again.",
                name=partner.display_name))
