# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    hotel_tier = fields.Char(
        string='Price Sheet Block',
        help="Which block of the agreed price sheet this pricelist was built "
             "from. Only the four shared tiers carry one; the Excel import "
             "matches on it, so a customer-specific copy (which has none) is "
             "never overwritten by a re-import.",
        copy=False,
        index=True,
    )

    is_hotel_contract = fields.Boolean(
        string='Hotel Contract Pricelist',
        help="Usable as a hotel/company contract pricelist. Covers the four "
             "shared tiers and every customer-specific copy made from them.",
        copy=False,
        index=True,
    )

    hotel_customer_ids = fields.Many2many(
        'res.partner',
        string='Customers on this Pricelist',
        compute='_compute_hotel_customer_ids',
    )
    hotel_customer_count = fields.Integer(compute='_compute_hotel_customer_ids')
    hotel_is_shared = fields.Boolean(compute='_compute_hotel_customer_ids')

    @api.depends_context('company')
    def _compute_hotel_customer_ids(self):
        """Resolve the partners pointing at each pricelist.

        ``res.partner.property_product_pricelist`` is a compute/inverse field
        backed by ``ir.property`` rather than a column, so it cannot be
        inverted with a One2many and cannot be searched. Reading the underlying
        properties is the only way to answer "who is on this tier?" -- which is
        exactly what someone about to edit a shared price needs to know.
        """
        by_pricelist = {}
        if self.ids:
            properties = self.env['ir.property'].sudo().search([
                ('name', '=', 'property_product_pricelist'),
                ('res_id', '!=', False),
                ('value_reference', 'in',
                 ['product.pricelist,%d' % pid for pid in self.ids]),
            ])
            for prop in properties:
                if not prop.value_reference or not prop.res_id:
                    continue
                pricelist_id = int(prop.value_reference.split(',')[1])
                partner_id = int(prop.res_id.split(',')[1])
                by_pricelist.setdefault(pricelist_id, []).append(partner_id)

        for pricelist in self:
            partners = self.env['res.partner'].browse(
                by_pricelist.get(pricelist.id, [])).exists()
            pricelist.hotel_customer_ids = partners
            pricelist.hotel_customer_count = len(partners)
            pricelist.hotel_is_shared = len(partners) > 1

    def action_open_hotel_price_rules(self):
        """Open this pricelist's rules for editing."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hotel Contract Prices - %s', self.display_name),
            'res_model': 'product.pricelist.item',
            'view_mode': 'tree,form',
            'domain': [('pricelist_id', '=', self.id)],
            'context': {
                'default_pricelist_id': self.id,
                'default_applied_on': '1_product',
                'default_compute_price': 'fixed',
            },
        }

    def copy_for_hotel_customer(self, partner):
        """Give one customer a private copy of this shared pricelist.

        Everything is duplicated up front -- rules included -- and only that
        partner is moved onto the copy, so the customers left behind keep the
        prices they had. The copy carries no ``hotel_tier``, which is what
        keeps a later Excel import from writing over the customer's own
        negotiated prices.
        """
        self.ensure_one()
        partner.ensure_one()

        if partner.property_product_pricelist != self:
            raise UserError(_(
                "%(partner)s is not on \"%(pricelist)s\", so a copy of it would "
                "not change what they are charged.",
                partner=partner.display_name, pricelist=self.display_name))

        copy = self.copy({
            'name': _('%(customer)s - Contract Prices', customer=partner.name),
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'hotel_tier': False,
            'is_hotel_contract': True,
            'active': True,
        })

        # copy() already duplicates item_ids. Guard against a second set rather
        # than assuming, so the copy can never end up with two rules per product.
        if not copy.item_ids:
            for item in self.item_ids:
                item.copy({'pricelist_id': copy.id})
        else:
            seen, duplicates = set(), self.env['product.pricelist.item']
            for item in copy.item_ids:
                key = (item.applied_on, item.product_tmpl_id.id,
                       item.product_id.id, item.categ_id.id, item.min_quantity)
                if key in seen:
                    duplicates |= item
                seen.add(key)
            duplicates.unlink()

        partner.property_product_pricelist = copy

        # The POS only loads pricelists the config lists, so the copy has to be
        # attached or the customer would silently fall back at the till.
        # Written as a single (6, 0, ids) union: pos.config.write inspects
        # vals['available_pricelist_ids'][0][2] to decide whether an open
        # session forbids the change, which raises on a link command. A union
        # also removes nothing, which is what keeps it allowed mid-session.
        for config in self.env['pos.config'].search([('is_hotel_pos', '=', True)]):
            if copy not in config.available_pricelist_ids:
                config.sudo().write({'available_pricelist_ids': [
                    (6, 0, (config.available_pricelist_ids | copy).ids)]})
        return copy
