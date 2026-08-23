from odoo import _, api, fields, models


class AccountExecutiveSummaryReport(models.TransientModel):
    _name = "account.executive.summary.report"
    _description = "Executive Summary"

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

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        vals.setdefault("date_from", today.replace(month=1, day=1))
        vals.setdefault("date_to", today)
        return vals

    def _build_contexts(self, data):
        form = data["form"]
        return {
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
            "form": self.read(["date_from", "date_to", "target_move", "currency_unit", "company_id"])[0],
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
        return self.env.ref("acc_reports_enterprise_simulation.action_report_executive_summary").report_action(
            self,
            data=data,
            config=False,
        )
