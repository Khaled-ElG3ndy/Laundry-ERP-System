# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class AccountMoveLine(models.Model):
    """Reconcile and unreconcile journal items straight from a list view.

    ``reconcile()`` and ``remove_move_reconcile()`` exist in Community but are only
    reachable programmatically, so there is no way to match two journal items from
    the interface.
    """
    _inherit = 'account.move.line'

    def action_fps_reconcile(self):
        if len(self) < 2:
            raise UserError(_(
                "Select at least two journal items to reconcile them together."
            ))
        self.reconcile()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_fps_unreconcile(self):
        reconciled = self.filtered(lambda line: line.matched_debit_ids or line.matched_credit_ids)
        if not reconciled:
            raise UserError(_("None of the selected journal items is reconciled."))
        reconciled.remove_move_reconcile()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
