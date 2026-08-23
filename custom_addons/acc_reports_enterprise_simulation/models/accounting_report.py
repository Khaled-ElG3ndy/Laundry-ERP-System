import ast

from odoo import fields, models


class AccountingReport(models.TransientModel):
    _inherit = "accounting.report"

    hierarchy_subtotals = fields.Boolean(default=True)
    unfold_all = fields.Boolean(default=False)
    cash_basis = fields.Boolean(default=False)

    def check_report(self):
        res = super().check_report()
        extra = self.read(['hierarchy_subtotals', 'unfold_all', 'cash_basis'])[0]
        extra.pop('id', None)
        form = res.get('data', {}).get('form', {})
        form.update(extra)
        if extra.get('cash_basis'):
            form.setdefault('used_context', {})['cash_basis'] = True
            form.setdefault('comparison_context', {})['cash_basis'] = True
        else:
            if form.get('used_context'):
                form['used_context'].pop('cash_basis', None)
            if form.get('comparison_context'):
                form['comparison_context'].pop('cash_basis', None)
        return res


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _query_get(self, domain=None):
        if self.env.context.get('cash_basis'):
            if not domain:
                domain = []
            elif not isinstance(domain, (list, tuple)):
                domain = ast.literal_eval(domain)
            else:
                domain = list(domain)
            domain += self._get_tax_exigible_domain()
        return super()._query_get(domain=domain)
