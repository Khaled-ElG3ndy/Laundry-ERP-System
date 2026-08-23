from odoo import fields, models


class AccountBalanceReport(models.TransientModel):
    _inherit = "account.balance.report"

    hierarchy_subtotals = fields.Boolean(default=True)
    unfold_all = fields.Boolean(default=False)
    cash_basis = fields.Boolean(default=False)

    def check_report(self):
        res = super().check_report()
        form = res.get("data", {}).get("form", {})
        extra = self.read(["hierarchy_subtotals", "unfold_all", "cash_basis"])[0]
        extra.pop("id", None)
        form.update(extra)
        if extra.get("cash_basis"):
            form.setdefault("used_context", {})["cash_basis"] = True
        elif form.get("used_context"):
            form["used_context"].pop("cash_basis", None)
        return res
