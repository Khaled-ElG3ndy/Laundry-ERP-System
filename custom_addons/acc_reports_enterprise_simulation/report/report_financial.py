from collections import OrderedDict

from odoo import _, fields, models


class ReportFinancial(models.AbstractModel):
    _inherit = 'report.accounting_pdf_reports.report_financial'

    PNL_GROUPS = OrderedDict([
        ('income', {
            'label': 'Revenue',
            'types': ('income',),
            'sign': -1.0,
        }),
        ('cost_of_revenue', {
            'label': 'Less Cost of Revenue',
            'types': ('expense_direct_cost',),
            'sign': 1.0,
        }),
        ('operating_expenses', {
            'label': 'Less Operating Expenses',
            'types': ('expense', 'expense_depreciation'),
            'sign': 1.0,
        }),
        ('other_income', {
            'label': 'Plus Other Income',
            'types': ('income_other',),
            'sign': -1.0,
        }),
        ('other_expenses', {
            'label': 'Less Other Expenses',
            'types': ('expense_other',),
            'sign': 1.0,
        }),
    ])

    def _report_line_level(self, report, default=0):
        level = report.style_overwrite if report.style_overwrite and report.style_overwrite != '0' else report.level
        level = level if level is not False else default
        try:
            return int(level)
        except (TypeError, ValueError):
            return int(default or 0)

    def _format_preview_date(self, value):
        date = fields.Date.to_date(value) if value else False
        return date.strftime('%d/%m/%Y') if date else ''

    def _financial_period_label(self, data):
        date_from_value = fields.Date.to_date(data.get('date_from')) if data.get('date_from') else False
        date_to_value = fields.Date.to_date(data.get('date_to')) if data.get('date_to') else False
        if (
            date_from_value
            and date_to_value
            and date_from_value.year == date_to_value.year
            and date_from_value.month == 1
            and date_from_value.day == 1
            and date_to_value.month == 12
            and date_to_value.day == 31
        ):
            return str(date_to_value.year)
        date_from = date_from_value.strftime('%d/%m/%Y') if date_from_value else ''
        date_to = date_to_value.strftime('%d/%m/%Y') if date_to_value else ''
        if date_from and date_to:
            return _('From %s to %s', date_from, date_to)
        if date_to:
            return _('As of %s', date_to)
        if date_from:
            return _('Starting From %s', date_from)
        return ''

    def _financial_report_xmlid(self, report):
        if not report:
            return ''
        xmlids = report.get_external_id()
        return xmlids.get(report.id, '')

    def _is_balance_sheet_report(self, report):
        return self._financial_report_xmlid(report) == 'accounting_pdf_reports.account_financial_report_balancesheet0'

    def _is_profit_and_loss_report(self, report):
        return self._financial_report_xmlid(report) == 'accounting_pdf_reports.account_financial_report_profitandloss0'

    def _format_financial_amount(self, amount):
        amount = amount or 0.0
        suffix = '-' if amount < 0 else ''
        return '{:,.2f}{}'.format(abs(amount), suffix)

    def _localized_record(self, record):
        return record.with_context(lang=self.env.lang or self.env.user.lang or 'en_US')

    def _localized_record_name(self, record):
        record = self._localized_record(record)
        return record.name or record.display_name

    def _account_display_name(self, account):
        account = self._localized_record(account)
        return ' '.join(part for part in [account.code, account.name] if part) or account.display_name

    def _line_value_class(self, amount):
        if amount and amount < 0:
            return 'o_acc_financial_negative'
        if not amount:
            return 'o_acc_financial_muted'
        return ''

    def _line_common_values(self, name, balance, line_type='report', level=1, line_kind='report', **extra):
        vals = {
            'name': name,
            'balance': balance or 0.0,
            'type': line_type,
            'level': level,
            'line_kind': line_kind,
            'value_class': self._line_value_class(balance),
        }
        vals.update(extra)
        if 'balance_cmp' in vals and 'comparison_class' not in vals:
            vals['comparison_class'] = self._line_value_class(vals.get('balance_cmp'))
        return vals

    def _show_hierarchy_subtotals(self, data):
        return data.get('hierarchy_subtotals', True) is not False

    def _show_account_details(self, data):
        return True

    def _line_is_folded(self, data):
        return self._show_hierarchy_subtotals(data) and not data.get('unfold_all')

    def _account_line_level(self, report_level, show_hierarchy):
        return report_level + 1 if show_hierarchy else 1

    def _account_domain_for_types(self, account_types, data):
        if not account_types:
            return [('id', '=', 0)]
        used_context = data.get('used_context') or {}
        company_ids = used_context.get('allowed_company_ids') or self.env.companies.ids or [self.env.company.id]
        account_model = self.env['account.account']
        domain = [
            *([('active', '=', True)] if 'active' in self.env['account.account']._fields else []),
            *([('deprecated', '=', False)] if 'deprecated' in self.env['account.account']._fields else []),
            ('account_type', 'in', list(account_types)),
        ]
        if 'company_id' in account_model._fields:
            domain.append(('company_id', 'in', company_ids))
        elif 'company_ids' in account_model._fields:
            domain.append(('company_ids', 'in', company_ids))
        return domain

    def _account_currency(self, account):
        if 'company_id' in account._fields and account.company_id:
            return account.company_id.currency_id
        if 'company_ids' in account._fields and account.company_ids:
            return account.company_ids[:1].currency_id
        return self.env.company.currency_id

    def _compute_group_values(self, data, account_types, sign):
        accounts = self.env['account.account'].search(self._account_domain_for_types(account_types, data), order='code, name')
        current = self.with_context(data.get('used_context') or {})._compute_account_balance(accounts)
        comparison = {}
        if data.get('enable_filter'):
            comparison = self.with_context(data.get('comparison_context') or {})._compute_account_balance(accounts)

        values = {
            'balance': 0.0,
            'debit': 0.0,
            'credit': 0.0,
            'balance_cmp': 0.0,
            'accounts': [],
        }
        for account in accounts:
            account_value = current.get(account.id) or {}
            raw_balance = account_value.get('balance') or 0.0
            raw_debit = account_value.get('debit') or 0.0
            raw_credit = account_value.get('credit') or 0.0
            raw_cmp = (comparison.get(account.id) or {}).get('balance') or 0.0
            balance = raw_balance * sign
            balance_cmp = raw_cmp * sign
            values['balance'] += balance
            values['debit'] += raw_debit
            values['credit'] += raw_credit
            values['balance_cmp'] += balance_cmp
            currency = self._account_currency(account)
            if (
                not currency.is_zero(balance)
                or not currency.is_zero(raw_debit)
                or not currency.is_zero(raw_credit)
                or (data.get('enable_filter') and not currency.is_zero(balance_cmp))
            ):
                values['accounts'].append({
                    'account': account,
                    'balance': balance,
                    'debit': raw_debit,
                    'credit': raw_credit,
                    'balance_cmp': balance_cmp,
                })
        return values

    def _get_profit_and_loss_lines(self, data):
        show_hierarchy = self._show_hierarchy_subtotals(data)
        show_details = self._show_account_details(data)
        group_values = {
            key: self._compute_group_values(data, config['types'], config['sign'])
            for key, config in self.PNL_GROUPS.items()
        }

        income = group_values['income']['balance']
        cost_of_revenue = group_values['cost_of_revenue']['balance']
        operating_expenses = group_values['operating_expenses']['balance']
        other_income = group_values['other_income']['balance']
        other_expenses = group_values['other_expenses']['balance']
        gross_profit = income - cost_of_revenue
        operating_income = gross_profit - operating_expenses
        net_profit = operating_income + other_income - other_expenses

        income_cmp = group_values['income']['balance_cmp']
        cost_cmp = group_values['cost_of_revenue']['balance_cmp']
        operating_expenses_cmp = group_values['operating_expenses']['balance_cmp']
        other_income_cmp = group_values['other_income']['balance_cmp']
        other_expenses_cmp = group_values['other_expenses']['balance_cmp']
        gross_profit_cmp = income_cmp - cost_cmp
        operating_income_cmp = gross_profit_cmp - operating_expenses_cmp
        net_profit_cmp = operating_income_cmp + other_income_cmp - other_expenses_cmp

        def add_group(lines, key):
            config = self.PNL_GROUPS[key]
            values = group_values[key]
            parent_key = 'pnl_%s' % key
            account_lines = []
            if show_details:
                for account_values in values['accounts']:
                    account = account_values['account']
                    account_lines.append(self._line_common_values(
                        self._account_display_name(account),
                        account_values['balance'],
                        line_type='account',
                        level=2 if show_hierarchy else 1,
                        line_kind='account',
                        account_id=account.id,
                        account_type=account.account_type,
                        parent_report_id=parent_key if show_hierarchy else False,
                        folded=self._line_is_folded(data),
                        debit=account_values['debit'],
                        credit=account_values['credit'],
                        balance_cmp=account_values['balance_cmp'],
                    ))
            if show_hierarchy:
                lines.append(self._line_common_values(
                    _(config['label']),
                    values['balance'],
                    level=1,
                    line_kind='report',
                    report_id=parent_key,
                    has_children=bool(account_lines),
                    debit=values['debit'],
                    credit=values['credit'],
                    balance_cmp=values['balance_cmp'],
                ))
            lines += account_lines

        lines = []
        add_group(lines, 'income')
        add_group(lines, 'cost_of_revenue')
        if show_hierarchy:
            lines.append(self._line_common_values(
                _('Gross Profit'),
                gross_profit,
                level=1,
                line_kind='total',
                debit=0.0,
                credit=0.0,
                balance_cmp=gross_profit_cmp,
            ))
        add_group(lines, 'operating_expenses')
        if show_hierarchy:
            lines.append(self._line_common_values(
                _('Operating Income (or Operating Loss)'),
                operating_income,
                level=1,
                line_kind='total',
                debit=0.0,
                credit=0.0,
                balance_cmp=operating_income_cmp,
            ))
        add_group(lines, 'other_income')
        add_group(lines, 'other_expenses')
        if show_hierarchy:
            lines.append(self._line_common_values(
                _('Net Profit'),
                net_profit,
                level=1,
                line_kind='total',
                debit=0.0,
                credit=0.0,
                balance_cmp=net_profit_cmp,
            ))
            lines.append(self._line_common_values(
                _('Less Provisions and Add Drawings'),
                0.0,
                level=1,
                line_kind='report',
                debit=0.0,
                credit=0.0,
                balance_cmp=0.0,
            ))
            lines.append(self._line_common_values(
                _('Net Profit after Provisions and Drawings'),
                net_profit,
                level=1,
                line_kind='total',
                debit=0.0,
                credit=0.0,
                balance_cmp=net_profit_cmp,
            ))
        return lines

    def _get_report_values(self, docids, data=None):
        values = super()._get_report_values(docids, data=data)
        report_data = values.get('data') or {}
        account_report = False
        if report_data.get('account_report_id'):
            account_report = self.env['account.financial.report'].browse(report_data['account_report_id'][0]).exists()
        values['financial_period_label'] = self._financial_period_label(report_data)
        values['financial_report_title'] = report_data.get('report_title') or (
            report_data.get('account_report_id') and report_data['account_report_id'][1]
        ) or values.get('doc_model')
        values['financial_report_layout'] = 'profit_loss' if self._is_profit_and_loss_report(account_report) else 'balance_sheet'
        values['format_financial_amount'] = self._format_financial_amount
        return values

    def _get_hierarchy_account_lines(self, data, account_report):
        lines = []
        show_hierarchy = self._show_hierarchy_subtotals(data)
        show_details = self._show_account_details(data)
        child_reports = account_report._get_children_by_order()
        res = self.with_context(data.get('used_context'))._compute_report_balance(child_reports)
        if data['enable_filter']:
            comparison_res = self.with_context(data.get('comparison_context'))._compute_report_balance(child_reports)
            for report_id, value in comparison_res.items():
                res[report_id]['comp_bal'] = value['balance']
                report_acc = res[report_id].get('account')
                if report_acc:
                    for account_id, val in comparison_res[report_id].get('account').items():
                        report_acc[account_id]['comp_bal'] = val['balance']

        for report in child_reports:
            report_level = self._report_line_level(report)
            balance = res[report.id]['balance'] * float(report.sign)
            sub_lines = []
            if show_details and res[report.id].get('account'):
                for account_id, value in res[report.id]['account'].items():
                    flag = False
                    account = self.env['account.account'].browse(account_id)
                    account_balance = value['balance'] * float(report.sign) or 0.0
                    vals = self._line_common_values(
                        self._account_display_name(account),
                        account_balance,
                        line_type='account',
                        level=self._account_line_level(report_level, show_hierarchy),
                        line_kind='account',
                        account_id=account.id,
                        account_type=account.account_type,
                        parent_report_id=report.id if show_hierarchy else False,
                        folded=self._line_is_folded(data),
                    )
                    if data['debit_credit']:
                        vals['debit'] = value['debit']
                        vals['credit'] = value['credit']
                        if (
                            not self.env.company.currency_id.is_zero(vals['debit'])
                            or not self.env.company.currency_id.is_zero(vals['credit'])
                        ):
                            flag = True
                    if not self.env.company.currency_id.is_zero(vals['balance']):
                        flag = True
                    if data['enable_filter']:
                        vals['balance_cmp'] = value['comp_bal'] * float(report.sign)
                        vals['comparison_class'] = self._line_value_class(vals['balance_cmp'])
                        if not self.env.company.currency_id.is_zero(vals['balance_cmp']):
                            flag = True
                    if flag:
                        sub_lines.append(vals)
                sub_lines = sorted(sub_lines, key=lambda sub_line: sub_line['name'])

            if show_hierarchy:
                vals = self._line_common_values(
                    self._localized_record_name(report),
                    balance,
                    line_type='report',
                    level=report_level,
                    line_kind='section' if report_level == 1 else 'report',
                    report_id=report.id,
                    has_children=bool(sub_lines),
                    account_type=report.type or False,
                )
                if data['debit_credit']:
                    vals['debit'] = res[report.id]['debit']
                    vals['credit'] = res[report.id]['credit']
                if data['enable_filter']:
                    vals['balance_cmp'] = res[report.id]['comp_bal'] * float(report.sign)
                    vals['comparison_class'] = self._line_value_class(vals['balance_cmp'])

                lines.append(vals)
            lines += sub_lines

        if show_hierarchy and self._is_balance_sheet_report(account_report):
            first_child = account_report.children_ids.sorted('sequence')[:1]
            liabilities_and_equity = sum(
                line['balance']
                for line in lines
                if line.get('type') == 'report'
                and line.get('level') == 1
                and (not first_child or line.get('report_id') != first_child.id)
            )
            lines.append(self._line_common_values(
                _('Liabilities + Equity'),
                liabilities_and_equity,
                level=1,
                line_kind='total',
                debit=0.0,
                credit=0.0,
            ))
        return lines

    def get_account_lines(self, data):
        account_report = self.env['account.financial.report'].browse(data['account_report_id'][0]).exists()
        if self._is_profit_and_loss_report(account_report):
            return self._get_profit_and_loss_lines(data)
        return self._get_hierarchy_account_lines(data, account_report)
