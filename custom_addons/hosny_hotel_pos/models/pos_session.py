# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _hotel_partner_domain(self):
        """Extra domain restricting which customers this session may use.

        Empty for the retail POS, so it keeps loading its usual customers.
        For the hotel POS it is a plain field domain rather than a fixed list
        of names, which means marking a new partner as a hotel customer makes
        them available at the till with no code change.
        """
        self.ensure_one()
        if self.config_id.is_hotel_pos:
            return [('is_hotel_customer', '=', True)]
        return []

    def _loader_params_product_pricelist(self):
        """Tell the client which pricelists are real contracts.

        The POS blocks selling when the order is not on a contract pricelist,
        and it needs to be able to ask that directly rather than inferring it
        from which pricelist happens to be the config default.
        """
        params = super()._loader_params_product_pricelist()
        fields = params['search_params'].setdefault('fields', [])
        if 'is_hotel_contract' not in fields:
            fields.append('is_hotel_contract')
        return params

    def _get_pos_ui_res_partner(self, params):
        """Restrict the partners preloaded into the client.

        The base implementation throws away the loader domain and substitutes
        the 100 most-used partners from ``get_limited_partners_loading``, so
        filtering has to be reapplied here rather than in the loader params.
        The hotel customer list is small, so it is loaded whole -- the cashier
        never has to search for a contract customer.
        """
        partners = super()._get_pos_ui_res_partner(params)
        domain = self._hotel_partner_domain()
        if not domain:
            return partners

        allowed = self.env['res.partner'].search(domain)
        loaded_ids = set(allowed.ids)
        partners = [p for p in partners if p['id'] in loaded_ids]

        missing = loaded_ids - {p['id'] for p in partners}
        if missing:
            search_params = dict(params['search_params'],
                                 domain=[('id', 'in', list(missing))])
            partners += self.env['res.partner'].search_read(**search_params)
        return partners

    def get_pos_ui_res_partner_by_params(self, custom_search_params):
        """Keep customer *search* inside the same restriction as the preload.

        The client passes its own domain here, and the base method lets it win,
        so without this a cashier could surface a retail customer by typing
        their name into the hotel POS. Deliberately not ``@api.model`` -- the
        base method is a record method, and the client calls it with the
        session id, so ``self`` is the session.
        """
        domain = self._hotel_partner_domain()
        if domain:
            custom_search_params = dict(custom_search_params)
            custom_search_params['domain'] = (
                list(custom_search_params.get('domain') or []) + domain)
        return super().get_pos_ui_res_partner_by_params(custom_search_params)
