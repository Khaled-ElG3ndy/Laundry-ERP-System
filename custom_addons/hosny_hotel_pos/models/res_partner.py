# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_hotel_customer = fields.Boolean(
        string='Hotel / Company Customer',
        help="Makes this customer selectable in the Hotel & Company point of "
             "sale. The POS filters on this field, so marking a new customer "
             "here is all that is needed to make them available at the till.",
        default=False,
        copy=False,
        index=True,
    )

    hotel_excel_name = fields.Char(
        string='Name in Price Sheet',
        help="The customer's name exactly as spelled in the agreed price "
             "sheet, kept so a partner can always be traced back to its source "
             "row even after the display name is tidied up.",
        copy=False,
    )

    hotel_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Contract Pricelist',
        compute='_compute_hotel_contract',
        help="The contract pricelist this customer is on, when it is one of "
             "the hotel ones.",
    )
    hotel_price_rule_count = fields.Integer(compute='_compute_hotel_contract')
    hotel_pricelist_is_shared = fields.Boolean(compute='_compute_hotel_contract')
    hotel_pricelist_sharer_count = fields.Integer(compute='_compute_hotel_contract')

    @api.depends('property_product_pricelist')
    def _compute_hotel_contract(self):
        for partner in self:
            pricelist = partner.property_product_pricelist
            contract = pricelist if pricelist.is_hotel_contract else pricelist.browse()
            partner.hotel_pricelist_id = contract
            partner.hotel_price_rule_count = len(contract.item_ids)
            partner.hotel_pricelist_is_shared = contract.hotel_customer_count > 1
            partner.hotel_pricelist_sharer_count = max(
                contract.hotel_customer_count - 1, 0)

    def action_open_hotel_contract_prices(self):
        """Open the agreed prices for this customer."""
        self.ensure_one()
        if not self.hotel_pricelist_id:
            raise UserError(_(
                "%(partner)s has no hotel contract pricelist yet. Assign one in "
                "the Sales tab before reviewing agreed prices.",
                partner=self.display_name))
        action = self.hotel_pricelist_id.action_open_hotel_price_rules()
        action['name'] = _('Hotel Contract Prices - %(partner)s',
                           partner=self.display_name)
        action['context'] = dict(action.get('context', {}),
                                 hotel_partner_id=self.id)
        return action

    def action_open_hotel_pricelist(self):
        """Open the pricelist record itself, for structural changes."""
        self.ensure_one()
        if not self.hotel_pricelist_id:
            raise UserError(_(
                "%(partner)s has no hotel contract pricelist yet.",
                partner=self.display_name))
        return {
            'type': 'ir.actions.act_window',
            'name': self.hotel_pricelist_id.display_name,
            'res_model': 'product.pricelist',
            'res_id': self.hotel_pricelist_id.id,
            'view_mode': 'form',
        }

    def action_create_customer_specific_pricelist(self):
        """Move this customer off a shared tier onto a private copy of it."""
        self.ensure_one()
        pricelist = self.hotel_pricelist_id
        if not pricelist:
            raise UserError(_(
                "%(partner)s has no hotel contract pricelist to copy.",
                partner=self.display_name))
        if not pricelist.hotel_is_shared:
            raise UserError(_(
                "\"%(pricelist)s\" is already used by %(partner)s alone, so "
                "editing it affects nobody else. Copying it would only add a "
                "pricelist to maintain.",
                pricelist=pricelist.display_name, partner=self.display_name))

        copy = pricelist.copy_for_hotel_customer(self)
        return {
            'type': 'ir.actions.act_window',
            'name': copy.display_name,
            'res_model': 'product.pricelist',
            'res_id': copy.id,
            'view_mode': 'form',
        }
