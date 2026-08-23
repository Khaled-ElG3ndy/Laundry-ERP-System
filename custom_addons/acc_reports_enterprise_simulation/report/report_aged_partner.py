import time
from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class ReportAgedPartnerBalance(models.AbstractModel):
    _inherit = "report.accounting_pdf_reports.report_agedpartnerbalance"

    def _aging_date_expression(self):
        if self.env.context.get("aging_based_on") == "invoice_date":
            return "l.date"
        return "COALESCE(l.date_maturity,l.date)"

    def _account_scope_clause(self):
        scope = self.env.context.get("account_scope")
        if scope == "non_trade":
            return " AND account_account.non_trade IS TRUE"
        if scope == "trade":
            return " AND COALESCE(account_account.non_trade, false) IS FALSE"
        return ""

    def _get_partner_move_lines(self, account_type, partner_ids, date_from, target_move, period_length):
        periods = {}
        start = datetime.strptime(str(date_from), "%Y-%m-%d")
        date_from = datetime.strptime(str(date_from), "%Y-%m-%d").date()
        for i in range(5)[::-1]:
            stop = start - relativedelta(days=period_length)
            period_name = str((5 - (i + 1)) * period_length + 1) + "-" + str((5 - i) * period_length)
            period_stop = (start - relativedelta(days=1)).strftime("%Y-%m-%d")
            if i == 0:
                period_name = "+" + str(4 * period_length)
            periods[str(i)] = {
                "name": period_name,
                "stop": period_stop,
                "start": (i != 0 and stop.strftime("%Y-%m-%d") or False),
            }
            start = stop

        res = []
        total = [0.0 for _idx in range(7)]
        cr = self.env.cr
        user_company = self.env.user.company_id
        user_currency = user_company.currency_id
        company_ids = self.env.context.get("company_ids") or [user_company.id]
        move_state = ["draft", "posted"]
        date = self.env.context.get("date") or fields.Date.today()
        company = self.env["res.company"].browse(self.env.context.get("company_id")) or self.env.company
        date_expr = self._aging_date_expression()
        account_scope_clause = self._account_scope_clause()

        if target_move == "posted":
            move_state = ["posted"]
        arg_list = (tuple(move_state), tuple(account_type))

        reconciliation_clause = "(l.reconciled IS FALSE)"
        cr.execute("SELECT debit_move_id, credit_move_id FROM account_partial_reconcile where max_date > %s", (date_from,))
        reconciled_after_date = []
        for row in cr.fetchall():
            reconciled_after_date += [row[0], row[1]]
        if reconciled_after_date:
            reconciliation_clause = "(l.reconciled IS FALSE OR l.id IN %s)"
            arg_list += (tuple(reconciled_after_date),)
        arg_list += (date_from, tuple(company_ids))
        query = """
            SELECT DISTINCT l.partner_id, UPPER(res_partner.name)
            FROM account_move_line AS l left join res_partner on l.partner_id = res_partner.id, account_account, account_move am
            WHERE (l.account_id = account_account.id)
                AND (l.move_id = am.id)
                AND (am.state IN %s)
                AND (account_account.account_type IN %s)
                """ + account_scope_clause + """
                AND """ + reconciliation_clause + """
                AND (l.date <= %s)
                AND l.company_id IN %s
            ORDER BY UPPER(res_partner.name)"""
        cr.execute(query, arg_list)
        partners = cr.dictfetchall()

        if not partner_ids:
            partner_ids = [partner["partner_id"] for partner in partners if partner["partner_id"]]
        lines = dict((partner["partner_id"] or False, []) for partner in partners)
        if not partner_ids:
            return [], total, {}

        undue_amounts = {}
        query = """SELECT l.id
                FROM account_move_line AS l, account_account, account_move am
                WHERE (l.account_id = account_account.id) AND (l.move_id = am.id)
                    AND (am.state IN %s)
                    AND (account_account.account_type IN %s)
                    """ + account_scope_clause + """
                    AND (""" + date_expr + """ >= %s)
                    AND ((l.partner_id IN %s) OR (l.partner_id IS NULL))
                AND (l.date <= %s)
                AND l.company_id IN %s"""
        cr.execute(query, (tuple(move_state), tuple(account_type), date_from, tuple(partner_ids), date_from, tuple(company_ids)))
        aml_ids = [row[0] for row in cr.fetchall()] if cr.rowcount else []
        for line in self.env["account.move.line"].browse(aml_ids):
            partner_id = line.partner_id.id or False
            undue_amounts.setdefault(partner_id, 0.0)
            line_amount = line.company_id.currency_id._convert(line.balance, user_currency, company, date)
            if user_currency.is_zero(line_amount):
                continue
            for partial_line in line.matched_debit_ids:
                if partial_line.max_date <= date_from:
                    line_amount += partial_line.company_id.currency_id._convert(partial_line.amount, user_currency, company, date)
            for partial_line in line.matched_credit_ids:
                if partial_line.max_date <= date_from:
                    line_amount -= partial_line.company_id.currency_id._convert(partial_line.amount, user_currency, company, date)
            if not user_currency.is_zero(line_amount):
                undue_amounts[partner_id] += line_amount
                lines[partner_id].append({"line": line, "amount": line_amount, "period": 6})

        history = []
        for i in range(5):
            args_list = (tuple(move_state), tuple(account_type), tuple(partner_ids))
            dates_query = "(" + date_expr
            if periods[str(i)]["start"] and periods[str(i)]["stop"]:
                dates_query += " BETWEEN %s AND %s)"
                args_list += (periods[str(i)]["start"], periods[str(i)]["stop"])
            elif periods[str(i)]["start"]:
                dates_query += " >= %s)"
                args_list += (periods[str(i)]["start"],)
            else:
                dates_query += " <= %s)"
                args_list += (periods[str(i)]["stop"],)
            args_list += (date_from, tuple(company_ids))
            query = """SELECT l.id
                    FROM account_move_line AS l, account_account, account_move am
                    WHERE (l.account_id = account_account.id) AND (l.move_id = am.id)
                        AND (am.state IN %s)
                        AND (account_account.account_type IN %s)
                        """ + account_scope_clause + """
                        AND ((l.partner_id IN %s) OR (l.partner_id IS NULL))
                        AND """ + dates_query + """
                    AND (l.date <= %s)
                    AND l.company_id IN %s"""
            cr.execute(query, args_list)
            partners_amount = {}
            aml_ids = [row[0] for row in cr.fetchall()] if cr.rowcount else []
            for line in self.env["account.move.line"].browse(aml_ids):
                partner_id = line.partner_id.id or False
                partners_amount.setdefault(partner_id, 0.0)
                line_amount = line.company_id.currency_id._convert(line.balance, user_currency, company, date)
                if user_currency.is_zero(line_amount):
                    continue
                for partial_line in line.matched_debit_ids:
                    if partial_line.max_date <= date_from:
                        line_amount += partial_line.company_id.currency_id._convert(partial_line.amount, user_currency, company, date)
                for partial_line in line.matched_credit_ids:
                    if partial_line.max_date <= date_from:
                        line_amount -= partial_line.company_id.currency_id._convert(partial_line.amount, user_currency, company, date)
                if not user_currency.is_zero(line_amount):
                    partners_amount[partner_id] += line_amount
                    lines[partner_id].append({"line": line, "amount": line_amount, "period": i + 1})
            history.append(partners_amount)

        for partner in partners:
            if partner["partner_id"] is None:
                partner["partner_id"] = False
            at_least_one_amount = False
            values = {}
            undue_amt = undue_amounts.get(partner["partner_id"], 0.0)
            total[6] += undue_amt
            values["direction"] = undue_amt
            if not float_is_zero(values["direction"], precision_rounding=user_currency.rounding):
                at_least_one_amount = True
            for i in range(5):
                amount = history[i].get(partner["partner_id"], 0.0)
                total[i] += amount
                values[str(i)] = amount
                if not float_is_zero(amount, precision_rounding=user_currency.rounding):
                    at_least_one_amount = True
            values["total"] = sum([values["direction"]] + [values[str(i)] for i in range(5)])
            total[5] += values["total"]
            values["partner_id"] = partner["partner_id"]
            if partner["partner_id"]:
                browsed_partner = self.env["res.partner"].browse(partner["partner_id"])
                values["name"] = browsed_partner.name and len(browsed_partner.name) >= 45 and browsed_partner.name[0:40] + "..." or browsed_partner.name
                values["trust"] = browsed_partner.trust
            else:
                values["name"] = _("Unknown Partner")
                values["trust"] = False
            if at_least_one_amount or self.env.context.get("include_nullified_amount"):
                res.append(values)
        return res, total, lines

    def _unit_config(self, data):
        unit = data.get("currency_unit") or "base_decimal"
        if unit == "million":
            return 1000000.0, 2
        if unit == "thousand":
            return 1000.0, 2
        if unit == "base":
            return 1.0, 0
        return 1.0, 2

    def _format_aged_amount(self, value, data=None):
        factor, decimals = self._unit_config(data or {})
        value = (value or 0.0) / factor
        if self.env.company.currency_id.is_zero(value):
            value = 0.0
        return ("{:,.%sf}" % decimals).format(value)

    def _aged_value_class(self, value):
        value = value or 0.0
        if self.env.company.currency_id.is_zero(value):
            return "o_aged_muted"
        return "o_aged_negative" if value < 0 else ""

    def _aged_period_label(self, data):
        return _("As of %s", data.get("date_from") or "")

    def _format_aged_date(self, value):
        value = fields.Date.to_date(value) if value else False
        return value.strftime("%d/%m/%Y") if value else ""

    def _period_headers(self, data):
        period_length = data.get("period_length") or 30
        return [
            {"key": "direction", "label": _("Not Due")},
            {"key": "4", "label": "1-%s" % period_length},
            {"key": "3", "label": "%s-%s" % (period_length + 1, period_length * 2)},
            {"key": "2", "label": "%s-%s" % (period_length * 2 + 1, period_length * 3)},
            {"key": "1", "label": "%s-%s" % (period_length * 3 + 1, period_length * 4)},
            {"key": "0", "label": _("Older")},
            {"key": "total", "label": _("Total")},
        ]

    def _detail_amounts(self, detail, data):
        amounts = {
            "direction": 0.0,
            "4": 0.0,
            "3": 0.0,
            "2": 0.0,
            "1": 0.0,
            "0": 0.0,
            "total": detail["amount"],
        }
        period = detail.get("period")
        if period == 6:
            amounts["direction"] = detail["amount"]
        elif period in (1, 2, 3, 4, 5):
            key_by_period = {1: "0", 2: "1", 3: "2", 4: "3", 5: "4"}
            amounts[key_by_period[period]] = detail["amount"]
        return amounts

    def _aged_partner_rows(self, partners, line_map, data):
        rows = []
        for partner in partners:
            partner_id = partner.get("partner_id") or False
            detail_rows = []
            for detail in line_map.get(partner_id, []):
                line = detail["line"]
                amounts = self._detail_amounts(detail, data)
                detail_rows.append({
                    "line": line,
                    "move_name": line.move_id.name or line.name or "",
                    "display_name": line.move_id.display_name or line.name or "",
                    "invoice_date": self._format_aged_date(line.date),
                    "due_date": self._format_aged_date(line.date_maturity or line.date),
                    "amounts": amounts,
                })
            rows.append({
                "partner": partner,
                "details": detail_rows,
            })
        return rows

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get("form"):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        form = data["form"]
        target_move = form.get("target_move", "all")
        date_from = form.get("date_from", time.strftime("%Y-%m-%d"))
        if form["result_selection"] == "customer":
            account_type = ["asset_receivable"]
        elif form["result_selection"] == "supplier":
            account_type = ["liability_payable"]
        else:
            account_type = ["asset_receivable", "liability_payable"]

        context = {
            "company_ids": form.get("selected_company_ids") or self.env.context.get("company_ids"),
            "company_id": (form.get("company_id") or [self.env.company.id])[0] if isinstance(form.get("company_id"), (list, tuple)) else form.get("company_id"),
            "aging_based_on": form.get("aging_based_on") or "due_date",
            "account_scope": form.get("account_scope") if form.get("result_selection") == "customer" else False,
            "include_nullified_amount": not form.get("hide_zero_lines", True),
        }
        movelines, total, line_map = self.with_context(**context)._get_partner_move_lines(
            account_type,
            form.get("partner_ids") or [],
            date_from,
            target_move,
            form.get("period_length") or 30,
        )
        values = {
            "doc_ids": self.ids,
            "doc_model": self.env.context.get("active_model") or data.get("model") or "account.aged.trial.balance",
            "data": form,
            "docs": self.env[self.env.context.get("active_model") or data.get("model") or "account.aged.trial.balance"].browse(
                self.env.context.get("active_id") or docids
            ),
            "time": time,
            "get_partner_lines": movelines,
            "get_direction": total,
            "aged_line_map": line_map,
            "aged_partner_rows": self._aged_partner_rows(movelines, line_map, form),
            "aged_headers": self._period_headers(form),
            "aged_period_label": self._aged_period_label(form),
            "format_aged_amount": self._format_aged_amount,
            "aged_value_class": self._aged_value_class,
            "format_aged_date": self._format_aged_date,
        }
        return values
