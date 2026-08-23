# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import UserError


class AccountJournal(models.Model):
    """Make every accounting dashboard card an entry point instead of a read-only tile.

    Odoo 17 Community keeps the bank/cash transaction and reconciliation UI in the
    Enterprise ``account_accountant`` module, which leaves the dashboard cards with
    buttons that lead to un-creatable lists. This adds the missing actions and the
    counters the cards need to render them.
    """
    _inherit = 'account.journal'

    # -------------------------------------------------------------------------
    # DASHBOARD DATA
    # -------------------------------------------------------------------------

    def _get_journal_dashboard_data_batched(self):
        dashboard_data = super()._get_journal_dashboard_data_batched()
        self._fps_fill_dashboard_data(dashboard_data)
        return dashboard_data

    def _fps_fill_dashboard_data(self, dashboard_data):
        """Add the counters the extra dashboard buttons rely on.

        Both counts use the very same domain as the action behind the Reconcile
        button, so the badge never disagrees with the list it opens.
        """
        liquidity_journals = self.filtered(lambda journal: journal.type in ('bank', 'cash'))
        other_journals = self - liquidity_journals

        transactions_to_reconcile = {}
        if liquidity_journals:
            transactions_to_reconcile = {
                journal.id: count
                for journal, count in self.env['account.bank.statement.line']._read_group(
                    domain=[
                        *self.env['account.bank.statement.line']._check_company_domain(self.env.companies),
                        ('journal_id', 'in', liquidity_journals.ids),
                    ] + self._fps_transactions_to_reconcile_domain(),
                    groupby=['journal_id'],
                    aggregates=['__count'],
                )
            }

        items_to_reconcile = {}
        if other_journals:
            items_to_reconcile = {
                journal.id: count
                for journal, count in self.env['account.move.line']._read_group(
                    domain=[
                        *self.env['account.move.line']._check_company_domain(self.env.companies),
                        ('journal_id', 'in', other_journals.ids),
                    ] + self._fps_items_to_reconcile_domain(),
                    groupby=['journal_id'],
                    aggregates=['__count'],
                )
            }

        for journal in self:
            data = dashboard_data[journal.id]
            if journal.type in ('bank', 'cash'):
                # Warn on the card when a transaction cannot be booked yet: without a
                # suspense account `_prepare_move_line_default_vals` refuses to create
                # the counterpart line.
                data['fps_has_suspense_account'] = bool(journal.suspense_account_id)
                data['fps_number_to_reconcile'] = transactions_to_reconcile.get(journal.id, 0)
            else:
                data['fps_has_suspense_account'] = True
                data['fps_number_to_reconcile'] = items_to_reconcile.get(journal.id, 0)

    @api.model
    def _fps_transactions_to_reconcile_domain(self):
        """Bank/cash transactions still sitting on the suspense account."""
        return [
            ('is_reconciled', '=', False),
            ('state', '=', 'posted'),
        ]

    @api.model
    def _fps_items_to_reconcile_domain(self):
        """Journal items of a non-liquidity journal that are still open."""
        return [
            ('parent_state', '=', 'posted'),
            ('account_id.reconcile', '=', True),
            ('reconciled', '=', False),
            ('display_type', 'not in', ('line_section', 'line_note')),
        ]

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _fps_check_liquidity_journal(self):
        self.ensure_one()
        if self.type not in ('bank', 'cash'):
            raise UserError(_(
                "%s is not a bank or cash journal, so it cannot hold transactions.",
                self.display_name,
            ))

    def _fps_check_suspense_account(self):
        """Bank/cash transactions need a suspense account to hold their counterpart."""
        self.ensure_one()
        if not self.suspense_account_id:
            raise UserError(_(
                "The journal %s has no suspense account, so a transaction cannot be "
                "recorded on it yet.\n\n"
                "Open the journal configuration and set the \"Suspense Account\" field, "
                "or pick a counterpart account directly on the transaction.",
                self.display_name,
            ))

    # -------------------------------------------------------------------------
    # BANK & CASH ACTIONS
    # -------------------------------------------------------------------------

    def action_fps_new_transaction(self):
        """Open a form to record one bank/cash transaction.

        Core's ``action_new_transaction`` opens the statement list, which is declared
        ``create="false"`` in Community and is therefore a dead end.
        """
        self.ensure_one()
        self._fps_check_liquidity_journal()
        return {
            'name': _("New Transaction"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line',
            'view_mode': 'form',
            'views': [(self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_form').id, 'form')],
            'target': 'new',
            'context': {
                'default_journal_id': self.id,
                'journal_type': self.type,
                'fps_dashboard_journal_id': self.id,
            },
        }

    def action_fps_open_transactions(self):
        """List every transaction of the journal, editable in place."""
        self.ensure_one()
        self._fps_check_liquidity_journal()
        return {
            'name': _("Transactions - %s", self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_tree').id, 'tree'),
                (self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_form').id, 'form'),
            ],
            'search_view_id': self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_search').id,
            'domain': [('journal_id', '=', self.id)],
            'context': {
                'default_journal_id': self.id,
                'journal_type': self.type,
            },
        }

    def action_fps_new_statement(self):
        """Open a statement form. ``account.bank.statement`` has no form view in Community."""
        self.ensure_one()
        self._fps_check_liquidity_journal()
        return {
            'name': _("New Statement"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'view_mode': 'form',
            'views': [(self.env.ref('fps_account_dashboard.view_fps_bank_statement_form').id, 'form')],
            'context': {
                'default_journal_id': self.id,
                'journal_type': self.type,
            },
        }

    def action_fps_open_statements(self):
        self.ensure_one()
        self._fps_check_liquidity_journal()
        return {
            'name': _("Statements - %s", self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('account.view_bank_statement_tree').id, 'tree'),
                (self.env.ref('fps_account_dashboard.view_fps_bank_statement_form').id, 'form'),
            ],
            'domain': [('journal_id', '=', self.id)],
            'context': {
                'default_journal_id': self.id,
                'journal_type': self.type,
            },
        }

    # -------------------------------------------------------------------------
    # PAYMENT ACTIONS
    # -------------------------------------------------------------------------

    def action_fps_customer_payment(self):
        self.ensure_one()
        action = self.open_payments_action('inbound', mode='form')
        action['name'] = _("Customer Payment")
        return action

    def action_fps_vendor_payment(self):
        self.ensure_one()
        action = self.open_payments_action('outbound', mode='form')
        action['name'] = _("Vendor Payment")
        return action

    def action_fps_internal_transfer(self):
        self.ensure_one()
        self._fps_check_liquidity_journal()
        action = self.open_payments_action('transfer', mode='form')
        action['name'] = _("Internal Transfer")
        return action

    # -------------------------------------------------------------------------
    # JOURNAL ENTRY ACTIONS
    # -------------------------------------------------------------------------

    def action_fps_new_entry(self):
        """Create a free-form journal entry in this journal, whatever its type."""
        self.ensure_one()
        return {
            'name': _("New Journal Entry"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'views': [(self.env.ref('account.view_move_form').id, 'form')],
            'context': {
                'default_journal_id': self.id,
                'default_move_type': 'entry',
                'view_no_maturity': True,
            },
        }

    # -------------------------------------------------------------------------
    # RECONCILIATION ACTIONS
    # -------------------------------------------------------------------------

    def action_fps_reconcile(self):
        """Open what has to be reconciled for this journal.

        Bank and cash journals reconcile transactions (their counterpart sits in the
        suspense account); every other journal reconciles journal items.
        """
        self.ensure_one()
        if self.type in ('bank', 'cash'):
            return self._fps_action_reconcile_transactions()
        return self._fps_action_reconcile_items()

    def _fps_action_reconcile_transactions(self):
        self.ensure_one()
        return {
            'name': _("Reconcile - %s", self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement.line',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_tree').id, 'tree'),
                (self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_form').id, 'form'),
            ],
            'search_view_id': self.env.ref('fps_account_dashboard.view_fps_bank_statement_line_search').id,
            'domain': [('journal_id', '=', self.id)] + self._fps_transactions_to_reconcile_domain(),
            'context': {
                'default_journal_id': self.id,
                'journal_type': self.type,
                'search_default_unreconciled': 1,
            },
            'help': """
                <p class="o_view_nocontent_smiling_face">%s</p>
                <p>%s</p>
            """ % (
                _("Nothing left to reconcile"),
                _("Every transaction of this journal has been matched with a "
                  "journal item. New transactions will show up here."),
            ),
        }

    def _fps_action_reconcile_items(self):
        """Unreconciled journal items of this journal, ready for a manual match."""
        self.ensure_one()
        return {
            'name': _("Reconcile - %s", self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'tree,form',
            'views': [
                (self.env.ref('fps_account_dashboard.view_fps_move_line_reconcile_tree').id, 'tree'),
                (self.env.ref('account.view_move_line_form').id, 'form'),
            ],
            'domain': [('journal_id', '=', self.id)] + self._fps_items_to_reconcile_domain(),
            'context': {
                'default_journal_id': self.id,
                'search_default_group_by_partner': 1,
                'expand': 1,
            },
            'help': """
                <p class="o_view_nocontent_smiling_face">%s</p>
                <p>%s</p>
            """ % (
                _("Nothing left to reconcile"),
                _("Select journal items sharing the same account and partner, then "
                  "press Reconcile to match them together."),
            ),
        }
