import time

from odoo import models


def _liquidity_account_ids_from_journals(report, journal_type, data):
    journal_domain = [('type', '=', journal_type)]
    journal_ids = (data.get('form') or {}).get('journal_ids') or []
    if journal_ids:
        journal_domain.append(('id', 'in', journal_ids))
    journals = report.env['account.journal'].search(journal_domain)
    account_ids = []
    for journal in journals:
        for payment_method in journal.outbound_payment_method_line_ids | journal.inbound_payment_method_line_ids:
            if payment_method.payment_account_id:
                account_ids.append(payment_method.payment_account_id.id)
    return account_ids


def _empty_liquidity_report_values(report, docids, data):
    form_data = data.get('form') or {}
    model = report.env.context.get('active_model')
    docs = report.env[model].browse(report.env.context.get('active_ids', [])) if model else report
    codes = []
    if form_data.get('journal_ids'):
        codes = report.env['account.journal'].browse(form_data['journal_ids']).mapped('code')
    return {
        'doc_ids': docids,
        'doc_model': model,
        'data': form_data,
        'docs': docs,
        'time': time,
        'Accounts': [],
        'print_journal': codes,
    }


def _ensure_liquidity_accounts(report, journal_type, docids, data):
    data = data or {}
    form_data = data.get('form') or {}
    account_ids = form_data.get('account_ids') or []
    if not account_ids:
        account_ids = _liquidity_account_ids_from_journals(report, journal_type, data)
        form_data['account_ids'] = account_ids
    if not account_ids:
        return _empty_liquidity_report_values(report, docids, data)
    return None


class ReportCashBook(models.AbstractModel):
    _inherit = 'report.om_account_daily_reports.report_cashbook'

    def _get_report_values(self, docids, data=None):
        empty_values = _ensure_liquidity_accounts(self, 'cash', docids, data)
        if empty_values is not None:
            return empty_values
        return super()._get_report_values(docids, data=data)


class ReportBankBook(models.AbstractModel):
    _inherit = 'report.om_account_daily_reports.report_bankbook'

    def _get_report_values(self, docids, data=None):
        empty_values = _ensure_liquidity_accounts(self, 'bank', docids, data)
        if empty_values is not None:
            return empty_values
        return super()._get_report_values(docids, data=data)
