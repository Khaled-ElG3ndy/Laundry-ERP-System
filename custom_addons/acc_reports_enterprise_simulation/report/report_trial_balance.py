import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class ReportTrialBalance(models.AbstractModel):
    _inherit = 'report.accounting_pdf_reports.report_trialbalance'

    def _format_trial_balance_amount(self, value):
        value = self._normalize_trial_balance_amount(value)
        currency = self.env.company.currency_id
        precision = currency.decimal_places if currency else 2
        return '{:,.{prec}f}'.format(value, prec=precision)

    def _normalize_trial_balance_amount(self, value, currency=None):
        value = value or 0.0
        currency = currency or self.env.company.currency_id
        if currency and currency.is_zero(value):
            return 0.0
        return value

    def _period_label(self, data):
        date_from = fields.Date.to_date(data.get('date_from')) if data.get('date_from') else False
        date_to = fields.Date.to_date(data.get('date_to')) if data.get('date_to') else False
        if date_from and date_to and date_from.year == date_to.year and date_from.month == date_to.month:
            return format_date(self.env, date_to, date_format="MMMM yyyy")
        if date_to:
            return format_date(self.env, date_to, date_format="MMMM yyyy")
        if date_from:
            return format_date(self.env, date_from, date_format="MMMM yyyy")
        return _('Current Period')

    def _query_account_sums(self, accounts, context):
        if not accounts:
            return {}
        tables, where_clause, where_params = self.env['account.move.line'].with_context(**context)._query_get()
        tables = (tables or 'account_move_line').replace('"', '')
        wheres = ['']
        if where_clause.strip():
            wheres.append(where_clause.strip())
        filters = ' AND '.join(wheres)
        query = (
            'SELECT account_id AS id,'
            ' SUM(debit) AS debit,'
            ' SUM(credit) AS credit,'
            ' (SUM(debit) - SUM(credit)) AS balance'
            ' FROM ' + tables + ' WHERE account_id IN %s ' + filters + ' GROUP BY account_id'
        )
        params = (tuple(accounts.ids),) + tuple(where_params)
        self.env.cr.execute(query, params)
        return {row.pop('id'): row for row in self.env.cr.dictfetchall()}

    def _trial_balance_rows(self, accounts, data):
        display_account = data.get('display_account') or 'not_zero'
        context = dict(data.get('used_context') or self.env.context)
        if data.get('analytic_account_ids'):
            context['analytic_account_ids'] = self.env['account.analytic.account'].browse(data['analytic_account_ids'])

        date_to = fields.Date.to_date(data.get('date_to') or data.get('date')) if (data.get('date_to') or data.get('date')) else False
        date_from = fields.Date.to_date(data.get('date_from')) if data.get('date_from') else False
        period_start = date_from or (date_to.replace(day=1) if date_to else False)

        period_context = dict(context)
        if period_start:
            period_context['date_from'] = period_start.strftime('%Y-%m-%d')
            period_context['strict_range'] = True
        if date_to:
            period_context['date_to'] = date_to.strftime('%Y-%m-%d')
        period_sums = self._query_account_sums(accounts, period_context)

        opening_sums = {}
        if period_start:
            opening_context = dict(context)
            opening_context['date_to'] = fields.Date.subtract(
                period_start,
                days=1,
            ).strftime('%Y-%m-%d')
            opening_context.pop('date_from', None)
            opening_context['strict_range'] = False
            opening_sums = self._query_account_sums(accounts, opening_context)

        rows = []
        for account in accounts.sorted(lambda acc: ((acc.code or ''), (acc.name or ''))):
            company = account.company_id if 'company_id' in account._fields else account.company_ids[:1]
            currency = account.currency_id or company.currency_id or self.env.company.currency_id
            period = period_sums.get(account.id) or {}
            opening = opening_sums.get(account.id) or {}
            opening_balance = opening.get('balance') or 0.0
            debit = period.get('debit') or 0.0
            credit = period.get('credit') or 0.0
            period_balance = debit - credit
            closing_balance = opening_balance + period_balance
            opening_balance = self._normalize_trial_balance_amount(opening_balance, currency)
            debit = self._normalize_trial_balance_amount(debit, currency)
            credit = self._normalize_trial_balance_amount(credit, currency)
            period_balance = self._normalize_trial_balance_amount(period_balance, currency)
            closing_balance = self._normalize_trial_balance_amount(closing_balance, currency)

            has_movement = not currency.is_zero(debit) or not currency.is_zero(credit)
            has_balance = not currency.is_zero(opening_balance) or not currency.is_zero(closing_balance)
            if display_account == 'movement' and not (has_movement or has_balance):
                continue
            if display_account == 'not_zero' and not has_balance:
                continue

            rows.append({
                'id': account.id,
                'code': account.code or '',
                'name': account.name or account.display_name,
                'display_name': account.display_name,
                'opening_balance': opening_balance,
                'debit': debit,
                'credit': credit,
                'period_balance': period_balance,
                'closing_balance': closing_balance,
            })
        return rows

    def _trial_balance_totals(self, rows):
        keys = ['opening_balance', 'debit', 'credit', 'period_balance', 'closing_balance']
        return {
            key: self._normalize_trial_balance_amount(sum(row[key] for row in rows))
            for key in keys
        }

    def _trial_balance_hierarchy_lines(self, rows, unfold_all=False):
        """Shape already computed account rows into the native account.group tree.

        This method deliberately does not query or recompute balances.  Group amounts
        are only presentation subtotals made from the visible leaf account rows.
        """
        if not rows:
            return []

        amount_keys = ['opening_balance', 'debit', 'credit', 'period_balance', 'closing_balance']
        rows_by_account = {row['id']: row for row in rows}
        accounts = self.env['account.account'].browse(list(rows_by_account)).exists()
        direct_rows = {}
        ungrouped_rows = []
        relevant_groups = self.env['account.group']

        for account in accounts:
            row = rows_by_account[account.id]
            if account.group_id:
                direct_rows.setdefault(account.group_id.id, []).append(row)
                group = account.group_id
                while group:
                    relevant_groups |= group
                    group = group.parent_id
            else:
                ungrouped_rows.append(row)

        children = {}
        for group in relevant_groups:
            parent_id = group.parent_id.id if group.parent_id in relevant_groups else False
            children.setdefault(parent_id, self.env['account.group'])
            children[parent_id] |= group

        def group_sort_key(group):
            return (group.code_prefix_start or '', group.name or '', group.id)

        def row_sort_key(row):
            return (row.get('code') or '', row.get('name') or '', row['id'])

        def subtotal(group):
            values = {key: 0.0 for key in amount_keys}
            for row in direct_rows.get(group.id, []):
                for key in amount_keys:
                    values[key] += row[key]
            for child in children.get(group.id, self.env['account.group']):
                child_values = subtotal(child)
                for key in amount_keys:
                    values[key] += child_values[key]
            return {key: self._normalize_trial_balance_amount(value) for key, value in values.items()}

        lines = []

        def append_group(group, parent_key=False, level=0):
            key = 'group_%s' % group.id
            child_groups = children.get(group.id, self.env['account.group']).sorted(group_sort_key)
            child_accounts = sorted(direct_rows.get(group.id, []), key=row_sort_key)
            lines.append({
                'line_type': 'group',
                'key': key,
                'parent_key': parent_key,
                'level': level,
                'name': group.name,
                'code': group.code_prefix_start or '',
                'has_children': bool(child_groups or child_accounts),
                'unfolded': bool(unfold_all),
                **subtotal(group),
            })
            for child in child_groups:
                append_group(child, key, level + 1)
            for row in child_accounts:
                lines.append({
                    **row,
                    'line_type': 'account',
                    'key': 'account_%s' % row['id'],
                    'parent_key': key,
                    'level': level + 1,
                })

        for root in children.get(False, self.env['account.group']).sorted(group_sort_key):
            append_group(root)

        if ungrouped_rows:
            values = {
                key: self._normalize_trial_balance_amount(sum(row[key] for row in ungrouped_rows))
                for key in amount_keys
            }
            lines.append({
                'line_type': 'group',
                'key': 'group_ungrouped',
                'parent_key': False,
                'level': 0,
                'name': _('(Ungrouped)'),
                'code': '',
                'has_children': True,
                'unfolded': bool(unfold_all),
                **values,
            })
            for row in sorted(ungrouped_rows, key=row_sort_key):
                lines.append({
                    **row,
                    'line_type': 'account',
                    'key': 'account_%s' % row['id'],
                    'parent_key': 'group_ungrouped',
                    'level': 1,
                })
        return lines

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data or not data.get('form') or not self.env.context.get('active_model'):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        form = data['form']
        model = self.env.context.get('active_model')
        docs = self.env[model].browse(self.env.context.get('active_ids', []))
        accounts = docs if model == 'account.account' else self.env['account.account'].search([])
        rows = self._trial_balance_rows(accounts, form)
        hierarchy_subtotals = form.get('hierarchy_subtotals') is not False
        report_lines = (
            self._trial_balance_hierarchy_lines(rows, unfold_all=form.get('unfold_all'))
            if hierarchy_subtotals else rows
        )
        return {
            'doc_ids': docids,
            'doc_model': model,
            'docs': docs,
            'data': form,
            'Accounts': rows,
            'report_lines': report_lines,
            'hierarchy_subtotals': hierarchy_subtotals,
            'totals': self._trial_balance_totals(rows),
            'period_label': self._period_label(form),
            'format_tb_amount': self._format_trial_balance_amount,
            'time': time,
        }
