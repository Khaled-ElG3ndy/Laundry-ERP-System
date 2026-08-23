# -*- coding: utf-8 -*-
{
    'name': 'Accounting Dashboard - Actionable Cards',
    'name_ar': 'لوحة بيانات المحاسبة - بطاقات تفاعلية',
    'version': '17.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Add transactions, payments and reconciliation directly from every accounting dashboard card',
    'description': """
Accounting Dashboard - Actionable Cards
=======================================

Odoo 17 Community ships an accounting dashboard whose Bank and Cash cards are
dead ends: ``account.bank.statement`` has no form view, its list view is marked
``create="false"`` and ``account.bank.statement.line`` has no view at all. The
bank reconciliation widget lives in the Enterprise ``account_accountant`` module,
so a Community database can neither record a bank/cash transaction nor reconcile
one from the dashboard.

This module turns every dashboard card into a working entry point:

* Bank / Cash - New Transaction, Register Payment, Internal Transfer, Reconcile,
  New Statement, Transactions list.
* Customer Invoices - New Invoice, Credit Note, Customer Payment, Reconcile.
* Vendor Bills - Upload, Create Manually, Refund, Vendor Payment, Reconcile.
* Miscellaneous / General - New Entry, Post All Entries, Reconcile.

It also supplies the missing views (bank statement form, statement line
tree/form/search) and a reconciliation wizard that replaces the Enterprise
widget: match a bank/cash transaction against open invoices and bills, or post
the balance to a counterpart account.

Every label is translatable and shipped with Arabic (ar_001) translations, so
the dashboard follows the user's language.
    """,
    'author': 'TelNova Solutions',
    'website': 'https://telnovasolution.com',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/account_bank_statement_views.xml',
        'views/account_move_line_views.xml',
        'wizard/account_reconcile_wizard_views.xml',
        'views/account_journal_dashboard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
