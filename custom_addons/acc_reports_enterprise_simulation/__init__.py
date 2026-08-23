from . import controllers
from . import models
from . import report


def set_account_report_html_actions(env):
    xmlids = [
        'accounting_pdf_reports.action_report_general_ledger',
        'accounting_pdf_reports.action_report_partnerledger',
        'accounting_pdf_reports.action_report_trial_balance',
        'accounting_pdf_reports.action_report_financial',
        'accounting_pdf_reports.action_report_account_tax',
        'accounting_pdf_reports.action_report_aged_partner_balance',
        'accounting_pdf_reports.action_report_journal',
        'accounting_pdf_reports.action_report_journal_entries',
        'om_account_daily_reports.action_report_day_book',
        'om_account_daily_reports.action_report_cash_book',
        'om_account_daily_reports.action_report_bank_book',
        'account.action_report_journal',
    ]
    for xmlid in xmlids:
        report = env.ref(xmlid, raise_if_not_found=False)
        if report and report._name == 'ir.actions.report':
            report.sudo().write({'report_type': 'qweb-html'})
