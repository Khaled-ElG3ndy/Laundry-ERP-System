from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class ReportCashFlowStatement(models.AbstractModel):
    _name = "report.acc_reports_enterprise_simulation.cash_flow"
    _description = "Cash Flow Statement"

    def _cash_line_domain(self, form, mode):
        company_ids = form.get("selected_company_ids") or [self.env.company.id]
        domain = [
            ("account_id.account_type", "=", "asset_cash"),
            ("company_id", "in", company_ids),
            ("display_type", "not in", ("line_section", "line_note")),
        ]
        if form.get("target_move") == "posted":
            domain.append(("parent_state", "=", "posted"))
        if form.get("journal_ids"):
            domain.append(("journal_id", "in", form["journal_ids"]))
        if mode == "opening":
            if form.get("date_from"):
                domain.append(("date", "<", form["date_from"]))
            else:
                domain.append(("id", "=", 0))
        elif mode == "closing":
            if form.get("date_to"):
                domain.append(("date", "<=", form["date_to"]))
        else:
            if form.get("date_from"):
                domain.append(("date", ">=", form["date_from"]))
            if form.get("date_to"):
                domain.append(("date", "<=", form["date_to"]))
        return domain

    def _sum_cash_balance(self, form, mode):
        result = self.env["account.move.line"].read_group(
            self._cash_line_domain(form, mode),
            ["balance:sum"],
            [],
        )
        return result[0].get("balance") or 0.0 if result else 0.0

    def _empty_amounts(self):
        return {
            "customer_advance": 0.0,
            "operating_profit": 0.0,
            "supplier_payment": 0.0,
            "operating_expense": 0.0,
            "investing_income": 0.0,
            "investing_expense": 0.0,
            "financing_income": 0.0,
            "financing_expense": 0.0,
            "unclassified_income": 0.0,
            "unclassified_expense": 0.0,
        }

    def _bucket_for_counterpart(self, account_type, amount):
        if account_type == "asset_receivable":
            return "customer_advance" if amount >= 0 else "operating_expense"
        if account_type == "liability_payable":
            return "operating_profit" if amount >= 0 else "supplier_payment"
        if account_type in ("income", "income_other"):
            return "operating_profit" if amount >= 0 else "operating_expense"
        if account_type in ("expense", "expense_direct_cost", "expense_depreciation"):
            return "operating_profit" if amount >= 0 else "operating_expense"
        if account_type in ("asset_fixed",):
            return "investing_income" if amount >= 0 else "investing_expense"
        if account_type in (
            "liability_current",
            "liability_non_current",
            "liability_credit_card",
            "equity",
            "equity_unaffected",
        ):
            return "financing_income" if amount >= 0 else "financing_expense"
        return "unclassified_income" if amount >= 0 else "unclassified_expense"

    def _cash_flow_amounts(self, form):
        amounts = self._empty_amounts()
        cash_lines = self.env["account.move.line"].search(self._cash_line_domain(form, "period"), order="date, move_id, id")
        for cash_line in cash_lines:
            counterparts = cash_line.move_id.line_ids.filtered(
                lambda line: line.id != cash_line.id
                and line.account_id.account_type != "asset_cash"
                and line.display_type not in ("line_section", "line_note")
            )
            total_weight = sum(abs(line.balance) for line in counterparts)
            if not counterparts or not total_weight:
                continue
            for line in counterparts:
                amount = cash_line.balance * (abs(line.balance) / total_weight)
                amounts[self._bucket_for_counterpart(line.account_id.account_type, amount)] += amount
        return amounts

    def _currency_unit_config(self, form):
        unit = form.get("currency_unit") or "base_decimal"
        if unit == "million":
            return 1000000.0, 2
        if unit == "thousand":
            return 1000.0, 2
        if unit == "base":
            return 1.0, 0
        return 1.0, 2

    def _format_amount(self, amount, form):
        factor, decimals = self._currency_unit_config(form)
        scaled = amount / factor
        return {
            "value": scaled,
            "text": ("{:,.%sf}" % decimals).format(scaled),
            "is_negative": scaled < 0,
        }

    def _period_label(self, form):
        date_from = form.get("date_from")
        date_to = form.get("date_to")
        start = fields.Date.to_date(date_from) if date_from else False
        end = fields.Date.to_date(date_to) if date_to else False
        if start and end and start.day == 1 and start.year == end.year and start.month == end.month:
            return format_date(self.env, end, date_format="MMMM yyyy")
        if start and end:
            return "%s - %s" % (date_from, date_to)
        return date_to or date_from or ""

    def _line(self, form, key, label, amount, row_type="line"):
        formatted = self._format_amount(amount, form)
        return {
            "key": key,
            "label": label,
            "amount": formatted["value"],
            "amount_text": formatted["text"],
            "amount_is_negative": formatted["is_negative"],
            "raw_amount": amount,
            "row_type": row_type,
        }

    def _cash_flow_lines(self, form):
        opening = self._sum_cash_balance(form, "opening")
        closing = self._sum_cash_balance(form, "closing")
        net_change = closing - opening
        amounts = self._cash_flow_amounts(form)
        return [
            self._line(form, "opening", _("Cash and Cash Equivalents, Beginning of Period"), opening, "total"),
            self._line(form, "net_change", _("Net Increase in Cash and Cash Equivalents"), net_change, "total"),
            self._line(form, "operating", _("Cash Flows from Operating Activities"), 0.0, "section"),
            self._line(form, "customer_advance", _("Advance Payments from Customers"), amounts["customer_advance"]),
            self._line(form, "operating_profit", _("Operating Activity Profit"), amounts["operating_profit"]),
            self._line(form, "supplier_payment", _("Advance Payments to Vendors"), amounts["supplier_payment"]),
            self._line(form, "operating_expense", _("Operating Activity Expenses"), amounts["operating_expense"]),
            self._line(form, "investing", _("Cash Flows from Investing and Extraordinary Activities"), 0.0, "section"),
            self._line(form, "investing_income", _("Income"), amounts["investing_income"]),
            self._line(form, "investing_expense", _("Expenses"), amounts["investing_expense"]),
            self._line(form, "financing", _("Cash Flows from Financing Activities"), 0.0, "section"),
            self._line(form, "financing_income", _("Income"), amounts["financing_income"]),
            self._line(form, "financing_expense", _("Expenses"), amounts["financing_expense"]),
            self._line(form, "unclassified", _("Cash Flows from Unclassified Activities"), 0.0, "section"),
            self._line(form, "unclassified_income", _("Income"), amounts["unclassified_income"]),
            self._line(form, "unclassified_expense", _("Expenses"), amounts["unclassified_expense"]),
            self._line(form, "closing", _("Cash and Cash Equivalents, Closing Balance"), closing, "total closing"),
        ]

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        form = data.get("form") or {}
        if not form:
            raise UserError(_("Form content is missing, this report cannot be printed."))
        docs = self.env["account.cash.flow.report"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "account.cash.flow.report",
            "docs": docs,
            "data": form,
            "period_label": self._period_label(form),
            "lines": self._cash_flow_lines(form),
        }
