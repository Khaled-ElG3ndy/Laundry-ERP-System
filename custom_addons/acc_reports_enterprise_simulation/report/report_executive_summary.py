from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ReportExecutiveSummary(models.AbstractModel):
    _name = "report.acc_reports_enterprise_simulation.executive_summary"
    _description = "Executive Summary"

    ASSET_TYPES = (
        "asset_receivable",
        "asset_cash",
        "asset_current",
        "asset_prepayments",
        "asset_fixed",
        "asset_non_current",
    )
    CURRENT_ASSET_TYPES = ("asset_receivable", "asset_cash", "asset_current", "asset_prepayments")
    LIABILITY_TYPES = ("liability_payable", "liability_current", "liability_credit_card", "liability_non_current")
    CURRENT_LIABILITY_TYPES = ("liability_payable", "liability_current", "liability_credit_card")

    def _company_ids(self, form):
        company = form.get("company_id")
        if isinstance(company, (list, tuple)):
            return [company[0]]
        if company:
            return [company]
        return self.env.companies.ids or [self.env.company.id]

    def _account_ids(self, account_types, form):
        account_model = self.env["account.account"]
        domain = [("account_type", "in", list(account_types))]
        company_ids = self._company_ids(form)
        if "company_id" in account_model._fields:
            domain.append(("company_id", "in", company_ids))
        elif "company_ids" in account_model._fields:
            domain.append(("company_ids", "in", company_ids))
        return account_model.search(domain).ids

    def _move_line_domain(self, form, account_types, period=True):
        account_ids = self._account_ids(account_types, form)
        if not account_ids:
            return [("id", "=", 0)]
        domain = [
            ("account_id", "in", account_ids),
            ("company_id", "in", self._company_ids(form)),
            ("display_type", "not in", ("line_section", "line_note")),
        ]
        if form.get("target_move") == "posted":
            domain.append(("parent_state", "=", "posted"))
        if period and form.get("date_from"):
            domain.append(("date", ">=", form["date_from"]))
        if form.get("date_to"):
            domain.append(("date", "<=", form["date_to"]))
        return domain

    def _sum_balance(self, form, account_types, period=True):
        rows = self.env["account.move.line"].read_group(
            self._move_line_domain(form, account_types, period=period),
            ["balance:sum"],
            [],
        )
        return rows[0].get("balance") or 0.0 if rows else 0.0

    def _sum_domain_balance(self, domain):
        rows = self.env["account.move.line"].read_group(domain, ["balance:sum"], [])
        return rows[0].get("balance") or 0.0 if rows else 0.0

    def _cash_period_lines(self, form):
        return self.env["account.move.line"].search(self._move_line_domain(form, ("asset_cash",), period=True))

    def _currency_unit_config(self, form):
        unit = form.get("currency_unit") or "base_decimal"
        if unit == "million":
            return 1000000.0, 2
        if unit == "thousand":
            return 1000.0, 2
        if unit == "base":
            return 1.0, 0
        return 1.0, 2

    def _currency_prefix(self, form):
        company = self.env["res.company"].browse(self._company_ids(form)[:1])
        currency = company.currency_id or self.env.company.currency_id
        return currency.symbol or currency.name or ""

    def _format_amount(self, form, amount):
        factor, decimals = self._currency_unit_config(form)
        scaled = (amount or 0.0) / factor
        suffix = "-" if scaled < 0 else ""
        prefix = self._currency_prefix(form)
        return {
            "value": scaled,
            "text": "%s %s%s" % (prefix, ("{:,.%sf}" % decimals).format(abs(scaled)), suffix),
            "negative": scaled < 0,
            "zero": abs(scaled) < 0.0000001,
        }

    def _format_number(self, value, decimals=1):
        value = value or 0.0
        suffix = "-" if value < 0 else ""
        return {
            "value": value,
            "text": ("{:,.%sf}" % decimals).format(abs(value)) + suffix,
            "negative": value < 0,
            "zero": abs(value) < 0.0000001,
        }

    def _format_percent(self, value):
        formatted = self._format_number(value, 1)
        formatted["text"] = "%s%%" % formatted["text"]
        return formatted

    def _safe_percent(self, numerator, denominator):
        return (numerator / denominator * 100.0) if denominator else 0.0

    def _line(self, key, label, formatted, row_type="line"):
        return {
            "key": key,
            "label": label,
            "text": formatted["text"],
            "negative": formatted.get("negative"),
            "zero": formatted.get("zero"),
            "row_type": row_type,
        }

    def _section(self, key, label):
        return {"key": key, "label": label, "text": "", "negative": False, "zero": False, "row_type": "section"}

    def _period_label(self, form):
        date_from = fields.Date.to_date(form.get("date_from")) if form.get("date_from") else False
        date_to = fields.Date.to_date(form.get("date_to")) if form.get("date_to") else False
        if date_from and date_to and date_from.year == date_to.year:
            return str(date_to.year)
        return form.get("date_to") or form.get("date_from") or ""

    def _executive_lines(self, form):
        income = -self._sum_balance(form, ("income",), period=True)
        other_income = -self._sum_balance(form, ("income_other",), period=True)
        cost_of_revenue = self._sum_balance(form, ("expense_direct_cost",), period=True)
        expenses = self._sum_balance(form, ("expense", "expense_depreciation", "expense_other"), period=True)
        revenue = income + other_income
        gross_profit = revenue - cost_of_revenue
        net_profit = gross_profit - expenses

        opening_cash = self._sum_balance(form, ("asset_cash",), period=False)
        if form.get("date_from"):
            opening_cash = self._sum_domain_balance(
                [
                    *self._move_line_domain(form, ("asset_cash",), period=False),
                    ("date", "<", form["date_from"]),
                ]
            )
        closing_cash = self._sum_balance(form, ("asset_cash",), period=False)
        cash_flow = closing_cash - opening_cash
        cash_inflow = sum(line.balance for line in self._cash_period_lines(form) if line.balance > 0)

        debtors = self._sum_balance(form, ("asset_receivable",), period=False)
        creditors = self._sum_balance(form, ("liability_payable",), period=False)
        total_assets = self._sum_balance(form, self.ASSET_TYPES, period=False)
        total_liabilities = self._sum_balance(form, self.LIABILITY_TYPES, period=False)
        net_assets = total_assets + total_liabilities

        current_assets = self._sum_balance(form, self.CURRENT_ASSET_TYPES, period=False)
        current_liabilities = self._sum_balance(form, self.CURRENT_LIABILITY_TYPES, period=False)
        date_from = fields.Date.to_date(form.get("date_from")) if form.get("date_from") else False
        date_to = fields.Date.to_date(form.get("date_to")) if form.get("date_to") else False
        days = ((date_to - date_from).days + 1) if date_from and date_to else 365
        debtor_days = (debtors / revenue * days) if revenue else 0.0
        creditor_days = (abs(creditors) / cost_of_revenue * days) if cost_of_revenue else 0.0
        short_cash_forecast = closing_cash + debtors + creditors
        current_ratio = (current_assets / abs(current_liabilities)) if current_liabilities else 0.0

        return [
            self._section("cash", _("Cash")),
            self._line("cash_profit", _("Cash Profit"), self._format_amount(form, cash_flow)),
            self._line("realized_amount", _("Realized Amount"), self._format_amount(form, cash_inflow)),
            self._line("cash_flow", _("Cash Flow"), self._format_amount(form, cash_flow)),
            self._line("bank_closing", _("Bank Closing Balance"), self._format_amount(form, closing_cash)),
            self._section("profitability", _("Profitability")),
            self._line("revenue", _("Revenue"), self._format_amount(form, revenue)),
            self._line("cost_of_revenue", _("Cost of Revenue"), self._format_amount(form, cost_of_revenue)),
            self._line("gross_profit", _("Gross Profit"), self._format_amount(form, gross_profit)),
            self._line("expenses", _("Expenses"), self._format_amount(form, expenses)),
            self._line("net_profit", _("Net Profit"), self._format_amount(form, net_profit)),
            self._section("balance_sheet", _("Balance Sheet")),
            self._line("debtors", _("Debtors"), self._format_amount(form, debtors)),
            self._line("creditors", _("Creditors"), self._format_amount(form, creditors)),
            self._line("net_assets", _("Net Assets"), self._format_amount(form, net_assets)),
            self._section("performance", _("Performance")),
            self._line("gross_margin", _("Gross Margin (Gross Profit / Operating Income)"), self._format_percent(self._safe_percent(gross_profit, revenue))),
            self._line("net_margin", _("Net Margin (Net Profit / Revenue)"), self._format_percent(self._safe_percent(net_profit, revenue))),
            self._line("roi", _("Return on Investment (Net Profit / Assets)"), self._format_percent(self._safe_percent(net_profit, abs(net_assets)))),
            self._section("position", _("Position")),
            self._line("debtor_days", _("Average Debtor Days"), self._format_number(debtor_days, 1)),
            self._line("creditor_days", _("Average Creditor Days"), self._format_number(creditor_days, 1)),
            self._line("short_cash_forecast", _("Short-term Cash Forecast"), self._format_amount(form, short_cash_forecast)),
            self._line("current_ratio", _("Current Assets to Liabilities Ratio"), self._format_number(current_ratio, 1)),
        ]

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        form = data.get("form") or {}
        if not form:
            raise UserError(_("Form content is missing, this report cannot be printed."))
        docs = self.env["account.executive.summary.report"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "account.executive.summary.report",
            "docs": docs,
            "data": form,
            "period_label": self._period_label(form),
            "lines": self._executive_lines(form),
        }
