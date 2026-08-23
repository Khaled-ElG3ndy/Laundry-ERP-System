from odoo import _, api, fields, models


class AccountTaxReportWizard(models.TransientModel):
    _inherit = "account.tax.report.wizard"

    tax_report_type = fields.Selection(
        [
            ("general", "General Tax Report"),
            ("by_account_tax", "Group by: Account < Tax"),
            ("by_tax_account", "Group by: Tax < Account"),
            ("eg_vat_return", "VAT Return (EG)"),
            ("eg_withholding", "Withholding Taxes (EG)"),
            ("eg_schedule", "Schedule Taxes (EG)"),
            ("eg_other", "Other Taxes (EG)"),
        ],
        string="Tax Report Type",
        required=True,
        default="eg_vat_return",
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

    def check_report(self):
        action = super().check_report()
        form = (action.get("data") or {}).get("form") or {}
        form.update(self.read(["tax_report_type", "currency_unit"])[0])
        currency_code = self.company_id.currency_id.name or self.company_id.currency_id.symbol
        form["currency_unit_options"] = [
            {"value": "base_decimal", "label": _("In %s.", currency_code)},
            {"value": "base", "label": _("In %s", currency_code)},
            {"value": "thousand", "label": _("In K%s", currency_code)},
            {"value": "million", "label": _("In M%s", currency_code)},
        ]
        form["currency_label"] = next(
            option["label"]
            for option in form["currency_unit_options"]
            if option["value"] == form["currency_unit"]
        )
        form["tax_report_type_options"] = [
            {"value": key, "label": _(label)}
            for key, label in self._fields["tax_report_type"].selection
        ]
        form["tax_report_type_label"] = dict(
            (key, _(label))
            for key, label in self._fields["tax_report_type"].selection
        ).get(
            self.tax_report_type,
            self.tax_report_type,
        )
        return action
