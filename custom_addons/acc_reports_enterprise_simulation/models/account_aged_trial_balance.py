from odoo import _, fields, models


class AccountAgedTrialBalance(models.TransientModel):
    _inherit = "account.aged.trial.balance"

    aging_based_on = fields.Selection(
        [("due_date", "Due Date"), ("invoice_date", "Invoice Date")],
        string="Aging Based On",
        required=True,
        default="due_date",
    )
    account_scope = fields.Selection(
        [("trade", "Trade Receivables"), ("non_trade", "Non-trade Receivables")],
        string="Account Scope",
        required=True,
        default="trade",
    )
    partner_category_ids = fields.Many2many("res.partner.category", string="Partner Tags")
    hide_zero_lines = fields.Boolean(default=True)
    unfold_all = fields.Boolean(default=False)
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

    def pre_print_report(self, data):
        data = super().pre_print_report(data)
        extra = self.read([
            "aging_based_on",
            "account_scope",
            "partner_category_ids",
            "hide_zero_lines",
            "unfold_all",
            "currency_unit",
        ])[0]
        category_ids = extra.get("partner_category_ids") or []
        if category_ids:
            partner_domain = [("category_id", "in", category_ids)]
            if data["form"].get("partner_ids"):
                partner_domain.append(("id", "in", data["form"]["partner_ids"]))
            data["form"]["partner_ids"] = self.env["res.partner"].search(partner_domain).ids or [0]
        data["form"].update(extra)

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
        data["form"]["partner_category_options"] = [
            {"id": category.id, "name": category.display_name}
            for category in self.env["res.partner.category"].search([], order="name, id")
        ]
        return data
