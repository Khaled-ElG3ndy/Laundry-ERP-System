import time

from odoo import _, api, fields, models
from odoo.tools.misc import format_date


class ReportGeneralLedger(models.AbstractModel):
    _inherit = "report.accounting_pdf_reports.report_general_ledger"

    def _get_account_move_entry(self, accounts, analytic_account_ids, partner_ids, init_balance, sortby, display_account):
        account_lines = super()._get_account_move_entry(
            accounts,
            analytic_account_ids,
            partner_ids,
            init_balance,
            sortby,
            display_account,
        )
        accounts_by_key = {
            (account.code or "", account.name or ""): account.id
            for account in accounts
        }
        for account_line in account_lines:
            account_line["id"] = accounts_by_key.get((
                account_line.get("code") or "",
                account_line.get("name") or "",
            ))
        return account_lines

    def _format_general_ledger_amount(self, value):
        value = value or 0.0
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            value = 0.0
        precision = currency.decimal_places if currency else 2
        symbol = currency.symbol if currency else ""
        amount = "{:,.{prec}f}".format(abs(value), prec=precision)
        formatted = "%s %s" % (symbol, amount) if symbol else amount
        return "%s-" % formatted if value < 0 else formatted

    def _general_ledger_value_class(self, value):
        value = value or 0.0
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            return "o_muted"
        return "o_negative" if value < 0 else ""

    def _general_ledger_period_label(self, data):
        data = data or {}
        date_from = fields.Date.to_date(data.get("date_from")) if data.get("date_from") else False
        date_to = fields.Date.to_date(data.get("date_to")) if data.get("date_to") else False
        target_date = date_to or date_from
        if target_date:
            return format_date(self.env, target_date, date_format="MMMM yyyy")
        return _("General Ledger")

    def _format_general_ledger_date(self, value):
        value = fields.Date.to_date(value) if value else False
        return value.strftime("%d-%m-%Y") if value else ""

    def _general_ledger_line_label(self, line):
        label = (line or {}).get("lname") or (line or {}).get("move_name") or ""
        if label == "Initial Balance":
            return _("Opening Balance")
        return label or _("Journal Items")

    def _general_ledger_totals(self, accounts):
        keys = ("debit", "credit", "balance")
        return {key: sum((account.get(key) or 0.0) for account in accounts) for key in keys}

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        accounts = values.get("Accounts") or []
        values.update({
            "general_ledger_period_label": self._general_ledger_period_label(values.get("data") or {}),
            "general_ledger_totals": self._general_ledger_totals(accounts),
            "format_gl_amount": self._format_general_ledger_amount,
            "format_gl_date": self._format_general_ledger_date,
            "gl_line_label": self._general_ledger_line_label,
            "gl_value_class": self._general_ledger_value_class,
            "time": time,
        })
        return values
