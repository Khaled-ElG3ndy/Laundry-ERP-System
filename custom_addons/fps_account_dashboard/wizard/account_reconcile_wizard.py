# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

# Cap the pre-loaded suggestions so a journal with a long history stays usable.
MAX_SUGGESTIONS = 100


def residual_sign(aml):
    """+1 when the journal item is an open debit, -1 when it is an open credit."""
    residual = aml.amount_residual_currency or aml.amount_residual
    return -1 if residual < 0 else 1


class AccountBankStatementLineReconcile(models.TransientModel):
    """Match a bank/cash transaction with open journal items.

    Replaces the Enterprise ``account_accountant`` reconciliation widget: it moves the
    transaction's counterpart out of the suspense account onto the accounts of the
    journal items it settles, then reconciles the two sides.
    """
    _name = 'account.bank.statement.line.reconcile'
    _description = "Reconcile Bank/Cash Transaction"

    st_line_id = fields.Many2one(
        comodel_name='account.bank.statement.line',
        string="Transaction",
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    journal_id = fields.Many2one(related='st_line_id.journal_id', string="Journal")
    company_id = fields.Many2one(related='st_line_id.company_id', string="Company")
    currency_id = fields.Many2one(related='st_line_id.currency_id', string="Currency")
    company_currency_id = fields.Many2one(
        related='st_line_id.company_id.currency_id',
        string="Company Currency",
    )
    date = fields.Date(related='st_line_id.date', string="Date")
    payment_ref = fields.Char(related='st_line_id.payment_ref', string="Label")
    amount = fields.Monetary(
        related='st_line_id.amount',
        string="Transaction Amount",
        currency_field='currency_id',
    )
    amount_open = fields.Monetary(
        string="Open Amount",
        compute='_compute_amount_open',
        currency_field='currency_id',
        help="Part of the transaction still sitting on the suspense account. It is "
             "smaller than the transaction amount once a first reconciliation has "
             "been made.",
    )

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string="Partner",
        help="Restrict the suggested journal items to this partner.",
    )
    line_ids = fields.One2many(
        comodel_name='account.bank.statement.line.reconcile.line',
        inverse_name='wizard_id',
        string="Open Items",
    )
    aml_domain = fields.Char(
        compute='_compute_aml_domain',
        string="Selectable Journal Items",
        help="Domain restricting what can be picked in the list below.",
    )

    amount_allocated = fields.Monetary(
        string="Allocated",
        compute='_compute_amounts',
        currency_field='currency_id',
    )
    amount_remaining = fields.Monetary(
        string="Remaining",
        compute='_compute_amounts',
        currency_field='currency_id',
    )

    counterpart_account_id = fields.Many2one(
        comodel_name='account.account',
        string="Post Remaining To",
        check_company=True,
        domain="[('deprecated', '=', False), ('account_type', '!=', 'off_balance')]",
        help="Account receiving whatever is left after the allocations below. "
             "Leave it empty to keep the remainder open for a later reconciliation.",
    )
    writeoff_label = fields.Char(
        string="Remaining Label",
        help="Label of the journal item created for the remaining amount.",
    )

    # -------------------------------------------------------------------------
    # COMPUTE
    # -------------------------------------------------------------------------

    @api.depends('st_line_id.amount_residual')
    def _compute_amount_open(self):
        # `amount_residual` mirrors the suspense line, which is signed the opposite way
        # from the transaction: a 500 inbound transaction parks a -500 counterpart.
        for wizard in self:
            wizard.amount_open = -wizard.st_line_id.amount_residual

    @api.depends('st_line_id', 'partner_id')
    def _compute_aml_domain(self):
        """Drive the picker from a domain rather than a list of ids.

        The pre-loaded suggestions are capped, but the user must still be able to
        reach an older item that the cap left out.
        """
        for wizard in self:
            wizard.aml_domain = str(wizard._open_items_domain())

    @api.depends('line_ids.amount_applied', 'line_ids.aml_id', 'amount_open')
    def _compute_amounts(self):
        for wizard in self:
            currency = wizard.currency_id or wizard.company_currency_id
            allocated = sum(line._applied_in_transaction_currency() for line in wizard.line_ids)
            wizard.amount_allocated = allocated
            remaining = abs(wizard.amount_open) - allocated
            wizard.amount_remaining = currency.round(remaining) if currency else remaining

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _open_items_domain(self):
        """Journal items this transaction may settle."""
        self.ensure_one()
        if not self.st_line_id:
            return [('id', '=', False)]
        domain = self.st_line_id._get_default_amls_matching_domain()
        if self.partner_id:
            domain = domain + [('partner_id', '=', self.partner_id.id)]
        return domain

    def _search_open_items(self, limit=MAX_SUGGESTIONS):
        """Oldest open items first, which is the order they get settled in."""
        self.ensure_one()
        return self.env['account.move.line'].search(
            self._open_items_domain(), limit=limit, order='date asc, id asc',
        )

    def _expected_sign(self):
        """Sign of the journal items a transaction of this direction settles.

        Money coming in settles open debits (customer invoices), money going out
        settles open credits (vendor bills).
        """
        self.ensure_one()
        return 1 if self.amount_open >= 0 else -1

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------

    def action_load_open_items(self):
        """Fill the list with candidates and pre-allocate the ones we are sure about.

        With a partner set the oldest open items are settled first, the way a payment
        on account is normally applied. Without one the list can mix unrelated
        partners, so only an item matching the transaction amount exactly is
        pre-allocated and everything else is left to the user.
        """
        self.ensure_one()
        amls = self._search_open_items()
        expected_sign = self._expected_sign()
        currency = self.currency_id or self.company_currency_id
        remaining = abs(self.amount_open)

        candidates = amls.filtered(lambda aml: residual_sign(aml) == expected_sign)
        if self.partner_id:
            to_allocate = candidates
        else:
            exact = candidates.filtered(lambda aml: currency.is_zero(
                abs(aml.amount_residual_currency or aml.amount_residual) - remaining
            ))
            to_allocate = exact[:1]

        commands = [Command.clear()]
        for aml in amls:
            applied = 0.0
            if aml in to_allocate and not float_is_zero(remaining, precision_rounding=currency.rounding):
                applied = min(abs(aml.amount_residual_currency or aml.amount_residual), remaining)
                remaining = currency.round(remaining - applied)
            commands.append(Command.create({
                'aml_id': aml.id,
                'amount_applied': applied,
            }))
        self.line_ids = commands
        return self._reopen()

    def action_clear_allocations(self):
        self.ensure_one()
        self.line_ids.write({'amount_applied': 0.0})
        return self._reopen()

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_reconcile(self):
        """Book the allocations on the transaction's journal entry and reconcile them."""
        self.ensure_one()
        st_line = self.st_line_id
        journal = st_line.journal_id
        company_currency = self.company_currency_id

        if st_line.state != 'posted':
            raise UserError(_("Only posted transactions can be reconciled."))

        applied_lines = self.line_ids.filtered(
            lambda line: not float_is_zero(
                line.amount_applied,
                precision_rounding=(line.aml_currency_id or company_currency).rounding,
            )
        )
        if not applied_lines and not self.counterpart_account_id:
            raise UserError(_(
                "Nothing to reconcile: allocate an amount on at least one journal "
                "item, or choose an account for the remaining amount."
            ))

        _liquidity_line, suspense_line, _other_lines = st_line._seek_for_lines()
        if len(suspense_line) != 1:
            raise UserError(_(
                "The transaction %s is not waiting on the suspense account, so there "
                "is nothing left to reconcile.",
                st_line.display_name,
            ))

        # The suspense line currently balances the entry on its own, so the new lines
        # only have to add up to the very same amounts for the entry to stay balanced.
        transaction_currency = suspense_line.currency_id or company_currency
        target_amount_currency = suspense_line.amount_currency
        target_balance = suspense_line.balance

        counterpart_vals_list = []
        # Keep the pairing so each new line can be reconciled with the items it settles.
        groups = {}
        for line in applied_lines:
            aml = line.aml_id
            if aml.reconciled:
                raise UserError(_(
                    "The journal item %s has been reconciled in the meantime. Reload "
                    "this screen and try again.",
                    aml.display_name,
                ))
            signed_amount_currency, signed_balance = line._signed_applied_amounts()
            amounts = st_line._prepare_counterpart_amounts_using_st_line_rate(
                aml.currency_id,
                -signed_balance,
                -signed_amount_currency,
            )
            balance = amounts['balance']
            counterpart_vals_list.append({
                'name': aml.move_id.name or st_line.payment_ref,
                'move_id': st_line.move_id.id,
                'partner_id': (aml.partner_id or st_line.partner_id).id,
                'account_id': aml.account_id.id,
                'currency_id': transaction_currency.id,
                'amount_currency': amounts['amount_currency'],
                'debit': balance if balance > 0.0 else 0.0,
                'credit': -balance if balance < 0.0 else 0.0,
            })
            key = (aml.account_id.id, aml.partner_id.id)
            groups.setdefault(key, self.env['account.move.line'])
            groups[key] |= aml

        used_amount_currency = sum(vals['amount_currency'] for vals in counterpart_vals_list)
        used_balance = sum(vals['debit'] - vals['credit'] for vals in counterpart_vals_list)

        # Allocating past the transaction amount would flip the remainder's sign, which
        # is never what the user meant.
        if abs(used_amount_currency) - abs(target_amount_currency) > transaction_currency.rounding:
            currency = self.currency_id or company_currency
            raise UserError(_(
                "The allocated amount (%(allocated)s) exceeds the amount left on this "
                "transaction (%(amount)s).",
                allocated=currency.format(self.amount_allocated),
                amount=currency.format(abs(self.amount_open)),
            ))

        remaining_amount_currency = transaction_currency.round(target_amount_currency - used_amount_currency)
        remaining_balance = company_currency.round(target_balance - used_balance)
        has_remaining = not (
            transaction_currency.is_zero(remaining_amount_currency)
            and company_currency.is_zero(remaining_balance)
        )

        commands = [Command.create(vals) for vals in counterpart_vals_list]
        if has_remaining:
            # Whatever is left either goes to the chosen account or stays on the
            # suspense account, which keeps the transaction open for a later match.
            remaining_account = self.counterpart_account_id or journal.suspense_account_id
            commands.append(Command.update(suspense_line.id, {
                'name': self.writeoff_label or suspense_line.name,
                'account_id': remaining_account.id,
                'currency_id': transaction_currency.id,
                'amount_currency': remaining_amount_currency,
                'debit': remaining_balance if remaining_balance > 0.0 else 0.0,
                'credit': -remaining_balance if remaining_balance < 0.0 else 0.0,
            }))
        else:
            commands.append(Command.delete(suspense_line.id))

        st_line.move_id.with_context(force_delete=True).write({'line_ids': commands})

        # Reconcile each new counterpart line with the items it was created for.
        # Grouping by account and partner keeps every reconciliation legal and lets the
        # engine build the partials when an allocation is smaller than a residual.
        _liquidity_line, _suspense_line, new_other_lines = st_line._seek_for_lines()
        for (account_id, partner_id), amls in groups.items():
            new_lines = new_other_lines.filtered(
                lambda line: line.account_id.id == account_id and line.partner_id.id == partner_id
            )
            to_reconcile = (new_lines + amls).filtered(lambda line: not line.reconciled)
            if len(to_reconcile) > 1:
                to_reconcile.reconcile()

        return {'type': 'ir.actions.act_window_close'}


class AccountBankStatementLineReconcileLine(models.TransientModel):
    _name = 'account.bank.statement.line.reconcile.line'
    _description = "Reconcile Bank/Cash Transaction Line"
    _order = 'date asc, id asc'

    wizard_id = fields.Many2one(
        comodel_name='account.bank.statement.line.reconcile',
        required=True,
        ondelete='cascade',
    )
    aml_id = fields.Many2one(
        comodel_name='account.move.line',
        string="Journal Item",
        required=True,
        ondelete='cascade',
    )
    # The picker's domain has to live on this model: a view cannot resolve
    # `parent.<field>` in a domain attribute.
    aml_domain = fields.Char(related='wizard_id.aml_domain')
    move_id = fields.Many2one(related='aml_id.move_id', string="Journal Entry")
    date = fields.Date(related='aml_id.date', string="Date")
    account_id = fields.Many2one(related='aml_id.account_id', string="Account")
    partner_id = fields.Many2one(related='aml_id.partner_id', string="Partner")
    name = fields.Char(related='aml_id.name', string="Label")
    aml_currency_id = fields.Many2one(related='aml_id.currency_id', string="Item Currency")
    amount_residual_currency = fields.Monetary(
        related='aml_id.amount_residual_currency',
        string="Open Amount",
        currency_field='aml_currency_id',
    )
    amount_applied = fields.Monetary(
        string="Allocated",
        currency_field='aml_currency_id',
        help="Part of the open amount settled by this transaction. Always positive.",
    )

    @api.onchange('aml_id')
    def _onchange_aml_id(self):
        """Suggest the full open amount, capped by what is left on the transaction."""
        for line in self:
            if not line.aml_id:
                line.amount_applied = 0.0
                continue
            residual = abs(line.aml_id.amount_residual_currency or line.aml_id.amount_residual)
            wizard = line.wizard_id
            already = sum(
                other._applied_in_transaction_currency()
                for other in wizard.line_ids
                if other != line
            )
            remaining = max(0.0, abs(wizard.amount_open) - already)
            line.amount_applied = min(residual, remaining)

    def _aml_rate(self):
        """Company-currency value of one unit of the journal item's own currency."""
        self.ensure_one()
        aml = self.aml_id
        if aml.amount_residual_currency:
            return abs(aml.amount_residual / aml.amount_residual_currency)
        return 1.0

    def _signed_applied_amounts(self):
        """Applied amount carrying the sign of the item's residual.

        :return: ``(amount in the item's currency, amount in company currency)``
        """
        self.ensure_one()
        company_currency = self.wizard_id.company_currency_id or self.env.company.currency_id
        signed_amount_currency = residual_sign(self.aml_id) * self.amount_applied
        signed_balance = company_currency.round(signed_amount_currency * self._aml_rate())
        return signed_amount_currency, signed_balance

    def _applied_in_transaction_currency(self):
        """Allocated amount converted to the transaction's currency, for the totals."""
        self.ensure_one()
        aml_currency = self.aml_currency_id
        wizard = self.wizard_id
        wizard_currency = wizard.currency_id or wizard.company_currency_id
        if not aml_currency or not wizard_currency or aml_currency == wizard_currency:
            return self.amount_applied
        return aml_currency._convert(
            self.amount_applied,
            wizard_currency,
            wizard.company_id or self.env.company,
            wizard.date or fields.Date.context_today(self),
        )
