from odoo import api, fields, models


class ReportPartnerLedger(models.AbstractModel):
    _inherit = "report.accounting_pdf_reports.report_partnerledger"

    def _format_partner_ledger_amount(self, value):
        value = value or 0.0
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            value = 0.0
        precision = currency.decimal_places if currency else 2
        amount = "{:,.{prec}f}".format(abs(value), prec=precision)
        symbol = currency.symbol if currency else ""
        formatted = "%s %s" % (symbol, amount) if symbol else amount
        return "%s-" % formatted if value < 0 else formatted

    def _partner_ledger_value_class(self, value):
        value = value or 0.0
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            return "o_muted"
        return "o_negative" if value < 0 else ""

    def _format_partner_ledger_date(self, value):
        value = fields.Date.to_date(value) if value else False
        return value.strftime("%d/%m/%Y") if value else ""

    @api.model
    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        partner_rows = []
        totals = {"debit": 0.0, "credit": 0.0, "balance": 0.0}
        for partner in values.get("docs", []):
            lines = values["lines"](values["data"], partner)
            line_ids = [line.get("id") for line in lines if line.get("id")]
            move_lines = self.env["account.move.line"].browse(line_ids).exists()
            move_lines_by_id = {line.id: line for line in move_lines}
            for line in lines:
                move_line = move_lines_by_id.get(line.get("id"))
                line.update({
                    "line_amount": (line.get("debit") or 0.0) - (line.get("credit") or 0.0),
                    "account_code": move_line.account_id.code if move_line else "",
                    "account_name": move_line.account_id.display_name if move_line else line.get("a_name", ""),
                    "date_maturity": move_line.date_maturity if move_line else False,
                    "matching_number": move_line.matching_number if move_line else "",
                    "move_id": move_line.move_id.id if move_line else False,
                })
            debit = values["sum_partner"](values["data"], partner, "debit")
            credit = values["sum_partner"](values["data"], partner, "credit")
            balance = values["sum_partner"](values["data"], partner, "debit - credit")
            totals["debit"] += debit
            totals["credit"] += credit
            totals["balance"] += balance
            partner_rows.append({
                "partner": partner,
                "lines": lines,
                "amount": balance,
                "debit": debit,
                "credit": credit,
                "balance": balance,
            })
        values.update({
            "partner_rows": partner_rows,
            "partner_ledger_totals": totals,
            "format_pl_amount": self._format_partner_ledger_amount,
            "format_pl_date": self._format_partner_ledger_date,
            "pl_value_class": self._partner_ledger_value_class,
        })
        return values
