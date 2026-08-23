from datetime import timedelta

from odoo import _, api, fields, models


class AccountCashFlowReport(models.TransientModel):
    _name = "account.cash.flow.report"
    _description = "Cash Flow Statement"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Start Date", required=True)
    date_to = fields.Date(string="End Date", required=True)
    target_move = fields.Selection(
        [("posted", "All Posted Entries"), ("all", "All Entries")],
        string="Target Moves",
        required=True,
        default="posted",
    )
    currency_unit = fields.Selection(
        [
            ("base_decimal", "Currency with decimals"),
            ("base", "Currency"),
            ("thousand", "Thousands"),
            ("million", "Millions"),
        ],
        string="Currency Unit",
        required=True,
        default="base_decimal",
    )
    journal_ids = fields.Many2many(
        "account.journal",
        string="Journals",
        required=True,
        default=lambda self: self.env["account.journal"].search([("company_id", "=", self.env.company.id)]),
    )

    @api.model
    def _last_closed_month_range(self):
        today = fields.Date.context_today(self)
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        date_from, date_to = self._last_closed_month_range()
        vals.setdefault("date_from", date_from)
        vals.setdefault("date_to", date_to)
        return vals

    def _build_contexts(self, data):
        form = data["form"]
        return {
            "journal_ids": form.get("journal_ids") or False,
            "state": form.get("target_move") or "",
            "date_from": form.get("date_from") or False,
            "date_to": form.get("date_to") or False,
            "strict_range": True if form.get("date_from") else False,
            "company_id": form.get("company_id")[0] if isinstance(form.get("company_id"), (list, tuple)) else form.get("company_id"),
        }

    def check_report(self):
        self.ensure_one()
        data = {
            "ids": self.ids,
            "model": self._name,
            "form": self.read(["date_from", "date_to", "journal_ids", "target_move", "currency_unit", "company_id"])[0],
        }
        data["form"]["used_context"] = self._build_contexts(data)
        currency_code = self.company_id.currency_id.name or self.company_id.currency_id.symbol
        data["form"]["currency_unit_options"] = [
            {"value": "base_decimal", "label": _("In %s.", currency_code)},
            {"value": "base", "label": _("In %s", currency_code)},
            {"value": "thousand", "label": _("In K%s", currency_code)},
            {"value": "million", "label": _("In M%s", currency_code)},
        ]
        data["form"]["currency_label"] = next(
            option["label"]
            for option in data["form"]["currency_unit_options"]
            if option["value"] == data["form"]["currency_unit"]
        )
        return self.env.ref("acc_reports_enterprise_simulation.action_report_cash_flow_statement").report_action(
            self,
            data=data,
            config=False,
        )
