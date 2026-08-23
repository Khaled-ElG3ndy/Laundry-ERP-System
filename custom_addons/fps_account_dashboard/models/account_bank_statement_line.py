# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    """Expose the counterpart account so a transaction can be booked in one step.

    ``account.bank.statement.line.create`` already understands a ``counterpart_account_id``
    key, but no field carries it, so it is unreachable from a form. Without it every
    transaction lands in the suspense account and needs a second reconciliation step -
    and journals with no suspense account cannot record anything at all.
    """
    _inherit = 'account.bank.statement.line'

    fps_counterpart_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Counterpart Account",
        compute='_compute_fps_counterpart_account_id',
        inverse='_inverse_fps_counterpart_account_id',
        store=False,
        readonly=False,
        check_company=True,
        domain="[('deprecated', '=', False), ('account_type', '!=', 'off_balance')]",
        help="Account holding the other side of this transaction. Leave it on the "
             "journal's suspense account to reconcile the transaction later.",
    )

    @api.depends('move_id.line_ids.account_id')
    def _compute_fps_counterpart_account_id(self):
        for st_line in self:
            _liquidity, suspense, other = st_line._seek_for_lines()
            counterpart = suspense + other
            st_line.fps_counterpart_account_id = counterpart.account_id if len(counterpart) == 1 else False

    def _inverse_fps_counterpart_account_id(self):
        for st_line in self:
            account = st_line.fps_counterpart_account_id
            if not account:
                continue
            _liquidity, suspense, other = st_line._seek_for_lines()
            counterpart = suspense + other
            if len(counterpart) != 1:
                raise UserError(_(
                    "The transaction %s is split over several journal items, so its "
                    "counterpart account cannot be changed from here. Use Reconcile "
                    "instead, or open the journal entry.",
                    st_line.display_name,
                ))
            if counterpart.account_id != account:
                # `account.move.line.write` refuses the change on a reconciled line,
                # which is the guard we want.
                counterpart.account_id = account.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Hand the value over to the key core's `create` already supports, so the
            # counterpart line is created with the right account instead of being
            # created on the suspense account and rewritten right after.
            account_id = vals.pop('fps_counterpart_account_id', None)
            if account_id and not vals.get('counterpart_account_id'):
                vals['counterpart_account_id'] = account_id
            elif not vals.get('counterpart_account_id') and vals.get('journal_id'):
                # Say what to do about it rather than letting core report the missing
                # suspense account, which offers no way out.
                journal = self.env['account.journal'].browse(vals['journal_id'])
                if not journal.suspense_account_id:
                    raise UserError(_(
                        "Choose a counterpart account for this transaction.\n\n"
                        "The journal %s has no suspense account, so the transaction "
                        "cannot be parked for a later reconciliation. Either pick a "
                        "counterpart account here, or set a suspense account in the "
                        "journal configuration.",
                        journal.display_name,
                    ))
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_fps_reconcile(self):
        """Open the reconciliation wizard on the selected transaction."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("Only posted transactions can be reconciled."))
        if self.is_reconciled:
            raise UserError(_(
                "The transaction %s is already fully reconciled. Use \"Undo "
                "Reconciliation\" first if you need to change it.",
                self.display_name,
            ))
        wizard = self.env['account.bank.statement.line.reconcile'].create({
            'st_line_id': self.id,
            'partner_id': self.partner_id.id,
        })
        wizard.action_load_open_items()
        return {
            'name': _("Reconcile Transaction"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line.reconcile',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_fps_undo_reconciliation(self):
        """Reset the selected transactions to their unreconciled state."""
        for st_line in self:
            if st_line.state != 'posted':
                raise UserError(_("Only posted transactions can be unreconciled."))
            st_line.journal_id._fps_check_suspense_account()
        self.action_undo_reconciliation()
        return True

    def action_fps_open_move(self):
        """Open the journal entry behind the transaction."""
        self.ensure_one()
        return {
            'name': _("Journal Entry"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('account.view_move_form').id, 'form')],
        }
