import json
from datetime import date, datetime
from urllib.parse import quote

from odoo import Command, _, api, fields, models
from odoo.tools.safe_eval import safe_eval
from odoo.tools import json_default


class AccountReportPreviewHelper(models.TransientModel):
    _name = 'acc.report.preview.helper'
    _description = 'Accounting Report Preview Helper'

    @api.model
    def _today(self):
        return fields.Date.context_today(self)

    @api.model
    def _month_start(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1)

    @api.model
    def _available_report_companies(self):
        return self.env.user.company_ids.sorted(lambda company: company.name or company.display_name)

    @api.model
    def _normalize_company_ids(self, company_ids=None):
        accessible_companies = self._available_report_companies()
        accessible_ids = set(accessible_companies.ids)
        if company_ids is None:
            company_ids = self.env.context.get('allowed_company_ids') or [self.env.company.id]
        if isinstance(company_ids, (int, str)):
            company_ids = [company_ids]

        normalized_ids = []
        for company_id in company_ids or []:
            try:
                company_id = int(company_id)
            except (TypeError, ValueError):
                continue
            if company_id in accessible_ids and company_id not in normalized_ids:
                normalized_ids.append(company_id)

        if not normalized_ids:
            fallback = self.env.company if self.env.company in accessible_companies else accessible_companies[:1]
            normalized_ids = fallback.ids
        return normalized_ids

    @api.model
    def _selected_company_ids_from_payload(self, form_data=None, updates=None):
        updates = updates or {}
        form_data = form_data or {}
        if 'selected_company_ids' in updates:
            return self._normalize_company_ids(updates.get('selected_company_ids'))
        if form_data.get('selected_company_ids'):
            return self._normalize_company_ids(form_data.get('selected_company_ids'))
        return self._normalize_company_ids([self._company_id_from_form_data(form_data)])

    @api.model
    def _company_label(self, company_ids):
        companies = self.env['res.company'].browse(company_ids).exists()
        all_companies = self._available_report_companies()
        if len(companies) > 1 and set(companies.ids) == set(all_companies.ids):
            return _('All')
        if len(companies) > 1:
            return ' / '.join(companies.mapped('display_name'))
        return companies.display_name if companies else self.env.company.display_name

    @api.model
    def _report_base_name(self, report_action):
        action_data = report_action.get('data') or {}
        form_data = action_data.get('form') or {}
        if report_action.get('report_name') == 'accounting_pdf_reports.report_financial':
            account_report = form_data.get('account_report_id')
            if isinstance(account_report, (list, tuple)):
                if len(account_report) > 1 and account_report[1]:
                    return account_report[1]
                if account_report:
                    account_report = account_report[0]
            if account_report:
                report = self.env['account.financial.report'].browse(account_report).exists()
                if report:
                    return report.display_name
        return report_action.get('display_name') or report_action.get('name')

    @api.model
    def _company_context(self, company_ids, include_company_id=False):
        context = {
            'allowed_company_ids': company_ids,
            'company_ids': company_ids,
        }
        if include_company_id and len(company_ids) == 1:
            context['company_id'] = company_ids[0]
        return context

    @api.model
    def _all_company_journal_ids(self, company_ids=None):
        company_ids = self._normalize_company_ids(company_ids)
        return self.env['account.journal'].search([
            ('company_id', 'in', company_ids),
        ]).ids

    @api.model
    def _analytic_account_options(self, company_ids=None):
        company_ids = self._normalize_company_ids(company_ids)
        analytic_accounts = self.env['account.analytic.account'].search([
            ('company_id', 'in', company_ids),
        ], order='name, id')
        return [{'id': acc.id, 'name': acc.display_name} for acc in analytic_accounts]

    @api.model
    def _journal_options(self, company_ids=None):
        company_ids = self._normalize_company_ids(company_ids)
        journals = self.env['account.journal'].search([
            ('company_id', 'in', company_ids),
        ], order='sequence, name, id')
        return [{'id': journal.id, 'name': journal.display_name} for journal in journals]

    @api.model
    def _wizard_defaults(self, extra_vals=None, company_ids=None):
        company_ids = self._normalize_company_ids(company_ids)
        vals = {
            'company_id': company_ids[0],
            'journal_ids': [Command.set(self._all_company_journal_ids(company_ids))],
            'target_move': 'posted',
        }
        if extra_vals:
            vals.update(extra_vals)
        return vals

    @api.model
    def _run_report(
        self,
        model_name,
        extra_vals=None,
        extra_context=None,
        selected_company_ids=None,
        report_title=None,
        report_slug=None,
    ):
        company_ids = self._normalize_company_ids(selected_company_ids)
        company_context = self._company_context(company_ids)
        model = self.env[model_name].with_company(self.env['res.company'].browse(company_ids[0]))
        report_context = {
            'discard_logo_check': True,
            'lang': self.env.lang or self.env.user.lang or 'en_US',
            **company_context,
            **(extra_context or {}),
        }
        wizard = model.with_context(**report_context).create(
            {
                field_name: value
                for field_name, value in self._wizard_defaults(extra_vals, company_ids).items()
                if field_name in model._fields
            }
        )
        report_action = wizard.check_report()
        report_action['context'] = {
            **(report_action.get('context') or {}),
            **company_context,
            'lang': self.env.lang or self.env.user.lang or 'en_US',
            'active_model': wizard._name,
            'active_id': wizard.id,
            'active_ids': wizard.ids,
        }
        if report_action.get('data'):
            report_action['data']['ids'] = wizard.ids
            report_action['data']['model'] = wizard._name
        self._apply_company_scope_to_report_action(report_action, company_ids)
        if report_title:
            form_data = (report_action.get('data') or {}).get('form') or {}
            company_label = form_data.get('company_label') or self._company_label(company_ids)
            download_name = '%s - %s' % (report_title, company_label)
            form_data.update({
                'report_title': report_title,
                'download_name': download_name,
            })
            report_action.update({
                'name': report_title,
                'display_name': download_name,
            })
        if report_slug:
            report_action['report_slug_override'] = report_slug
        return self._build_client_action(report_action)

    @api.model
    def _merge_company_scope(self, context, company_ids, include_company_id=False):
        context = dict(context or {})
        context.update({
            'allowed_company_ids': company_ids,
            'company_ids': company_ids,
        })
        if include_company_id and len(company_ids) == 1:
            context['company_id'] = company_ids[0]
        else:
            context.pop('company_id', None)
        return context

    @api.model
    def _apply_company_scope_to_report_action(self, report_action, company_ids):
        action_data = report_action.get('data') or {}
        form_data = action_data.get('form') or {}
        if not form_data:
            return

        company_label = self._company_label(company_ids)
        report_title = self._report_base_name(report_action)
        download_name = '%s - %s' % (report_title, company_label)
        form_data['selected_company_ids'] = company_ids
        form_data['company_label'] = company_label
        form_data['report_title'] = report_title
        form_data['download_name'] = download_name
        analytic_accounts = self.env['account.analytic.account'].browse(
            form_data.get('analytic_account_ids') or []
        ).exists()
        form_data['analytic_account_names'] = analytic_accounts.mapped('display_name')
        form_data['journal_ids'] = [
            journal_id
            for journal_id in (form_data.get('journal_ids') or [])
            if self.env['account.journal'].browse(journal_id).company_id.id in company_ids
        ] or self._all_company_journal_ids(company_ids)
        if form_data.get('used_context'):
            form_data['used_context'] = self._merge_company_scope(
                form_data['used_context'],
                company_ids,
                include_company_id=True,
            )
        if form_data.get('comparison_context'):
            form_data['comparison_context'] = self._merge_company_scope(
                form_data['comparison_context'],
                company_ids,
                include_company_id=True,
            )
        elif action_data.get('model') in ('account.daybook.report', 'account.cashbook.report', 'account.bankbook.report'):
            form_data['comparison_context'] = self._merge_company_scope({
                'journal_ids': form_data.get('journal_ids') or False,
                'state': form_data.get('target_move') or '',
                'date_from': form_data.get('date_from') or False,
                'date_to': form_data.get('date_to') or False,
                'strict_range': True if form_data.get('date_from') else False,
            }, company_ids, include_company_id=True)

        report_action['context'] = self._merge_company_scope(report_action.get('context'), company_ids)
        report_action['display_name'] = download_name
        report_action['data'] = self._serialize_report_value(report_action.get('data') or {})
        report_action['context'] = self._serialize_report_value(report_action.get('context') or {})

    @api.model
    def _serialize_report_value(self, value):
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, dict):
            return {
                key: self._serialize_report_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._serialize_report_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._serialize_report_value(item) for item in value)
        return value

    @api.model
    def _build_client_action(self, report_action):
        action_context = report_action.get('context') or {}
        action_data = report_action.get('data') or {}
        form_data = action_data.get('form') or {}
        report_slug = self._report_url_slug(report_action)
        report_url = f"/report/html/{report_action['report_name']}"
        if action_data:
            options = quote(json.dumps(action_data, default=json_default))
            context = quote(json.dumps(action_context, default=json_default))
            report_url = f"{report_url}?options={options}&context={context}"
        elif action_context.get('active_ids'):
            docids = ','.join(str(docid) for docid in action_context['active_ids'])
            context = quote(json.dumps(action_context, default=json_default))
            report_url = f"{report_url}/{docids}?context={context}"

        return {
            'type': 'ir.actions.client',
            # A slash-containing client-action tag becomes /odoo/report/<slug>
            # in Odoo 19, without exposing the technical addon name.
            'tag': 'report/%s' % report_slug,
            'name': report_action.get('name'),
            'display_name': form_data.get('report_title') or report_action.get('name') or report_action.get('display_name'),
            'target': 'current',
            'params': {
                'display_name': form_data.get('report_title') or report_action.get('name') or report_action.get('display_name'),
                'name': report_action.get('name'),
                'report_file': report_action.get('report_file'),
                'report_name': report_action.get('report_name'),
                'report_slug': report_slug,
                'report_url': report_url,
                'download_name': form_data.get('download_name') or report_action.get('display_name') or report_action.get('name'),
                'context': action_context,
                'data': action_data,
                'preview_lang': self.env.lang or self.env.user.lang or 'en_US',
                'wizard_model': action_data.get('model'),
                'show_unposted_notice': self._has_unposted_entries(form_data),
                'company_options': [
                    {'id': company.id, 'name': company.display_name}
                    for company in self._available_report_companies()
                ],
                'selected_company_ids': self._selected_company_ids_from_payload(form_data),
                'company_label': form_data.get('company_label') or self._company_label(
                    self._selected_company_ids_from_payload(form_data)
                ),
                'journal_options': self._journal_options(self._selected_company_ids_from_payload(form_data)),
                'analytic_account_options': self._analytic_account_options(self._selected_company_ids_from_payload(form_data)),
            },
        }

    @api.model
    def _report_url_slug(self, report_action):
        """Return the stable customer-facing URL name for the current report."""
        if report_action.get('report_slug_override'):
            return report_action['report_slug_override']

        action_data = report_action.get('data') or {}
        form_data = action_data.get('form') or {}
        wizard_model = action_data.get('model')
        model_slugs = {
            'account.balance.report': 'trial-balance',
            'account.report.general.ledger': 'general-ledger',
            'account.report.partner.ledger': 'partner-ledger',
            'account.tax.report.wizard': 'tax-report',
            'account.print.journal': 'journals-audit',
            'account.daybook.report': 'day-book',
            'account.cashbook.report': 'cash-book',
            'account.bankbook.report': 'bank-book',
        }
        if wizard_model in model_slugs:
            return model_slugs[wizard_model]
        if wizard_model == 'account.cash.flow.report':
            return 'cash-flow-statement'

        if wizard_model == 'accounting.report':
            account_report = form_data.get('account_report_id')
            account_report_id = account_report[0] if isinstance(account_report, (list, tuple)) else account_report
            if account_report_id == self.env.ref(
                'accounting_pdf_reports.account_financial_report_profitandloss0'
            ).id:
                return 'profit-and-loss'
            if account_report_id == self.env.ref(
                'accounting_pdf_reports.account_financial_report_balancesheet0'
            ).id:
                return 'balance-sheet'

        if wizard_model == 'account.aged.trial.balance':
            return {
                'customer': 'aged-receivable',
                'supplier': 'aged-payable',
                'customer_supplier': 'aged-partner-balance',
            }.get(form_data.get('result_selection'), 'aged-partner-balance')

        report_name = (report_action.get('report_name') or 'accounting-report').split('.')[-1]
        return report_name.removeprefix('report_').replace('_', '-')

    @api.model
    def _has_unposted_entries(self, form_data):
        if not form_data:
            return False
        company_ids = self._selected_company_ids_from_payload(form_data)
        date_limit = form_data.get('date_to') or form_data.get('date') or form_data.get('date_from')
        if not date_limit:
            return False

        domain = [
            ('state', '=', 'draft'),
            ('company_id', 'in', company_ids),
            ('date', '<=', date_limit),
        ]
        if form_data.get('journal_ids'):
            domain.append(('journal_id', 'in', form_data['journal_ids']))
        return bool(self.env['account.move'].search_count(domain))

    @api.model
    def _coerce_field_value(self, field, value):
        if value == '':
            return False
        if field.type == 'many2one':
            if isinstance(value, (list, tuple)):
                return value[0] if value else False
            return value or False
        if field.type in ('many2many', 'one2many'):
            return [Command.set(value or [])]
        if field.type == 'boolean':
            return bool(value)
        return value

    @api.model
    def _prepare_wizard_vals(self, wizard_model, form_data, updates=None):
        model = self.env[wizard_model]
        updates = updates or {}
        vals = {}
        for field_name, field in model._fields.items():
            if field_name not in form_data and field_name not in updates:
                continue
            value = updates[field_name] if field_name in updates else form_data.get(field_name)
            vals[field_name] = self._coerce_field_value(field, value)
        return vals

    @api.model
    def rerun_report_preview(self, wizard_model, form_data, updates=None):
        updates = dict(updates or {})
        company_ids = self._selected_company_ids_from_payload(form_data, updates)
        company_selection_changed = 'selected_company_ids' in updates
        updates.pop('selected_company_ids', None)
        if company_selection_changed:
            updates.update({
                'company_id': company_ids[0],
                'journal_ids': self._all_company_journal_ids(company_ids),
            })
            if 'account_ids' in (form_data or {}):
                updates['account_ids'] = []
        vals = self._prepare_wizard_vals(wizard_model, form_data or {}, updates=updates)
        return self._run_report(wizard_model, vals, selected_company_ids=company_ids)

    @api.model
    def _company_id_from_form_data(self, form_data):
        company_id = (form_data or {}).get('company_id')
        if isinstance(company_id, (list, tuple)):
            return company_id[0] if company_id else self.env.company.id
        return company_id or self.env.company.id

    @api.model
    def _report_date_search_context(self, form_data):
        form_data = form_data or {}
        date_from = form_data.get('date_from')
        date_to = form_data.get('date_to') or form_data.get('date')
        context = {}
        if date_from:
            context['date_from'] = date_from
        if date_to:
            context['date_to'] = date_to
        if date_from and date_to:
            context['search_default_date_between'] = True
        elif date_to:
            context['search_default_date_before'] = True
        return context

    @api.model
    def _journal_item_action_domain(self, form_data, account_id):
        form_data = form_data or {}
        company_ids = self._selected_company_ids_from_payload(form_data)
        date_to = form_data.get('date_to') or form_data.get('date')
        domain = [
            ('display_type', 'not in', ('line_section', 'line_note')),
            ('parent_state', '!=', 'cancel'),
            ('account_id', '=', account_id),
            ('company_id', 'in', company_ids),
        ]
        if form_data.get('target_move') == 'posted':
            domain.append(('parent_state', '=', 'posted'))
        if form_data.get('date_from'):
            domain.append(('date', '>=', form_data['date_from']))
        if date_to:
            domain.append(('date', '<=', date_to))
        if form_data.get('journal_ids'):
            domain.append(('journal_id', 'in', form_data['journal_ids']))
        if form_data.get('partner_ids'):
            domain.append(('partner_id', 'in', form_data['partner_ids']))
        return domain

    @api.model
    def _tax_report_journal_item_domain(self, form_data, tax_ids, drilldown_type):
        """Return exactly the move lines that contribute to a tax report amount."""
        form_data = form_data or {}
        company_ids = self._selected_company_ids_from_payload(form_data)
        date_to = form_data.get('date_to') or form_data.get('date')
        domain = [
            ('display_type', 'not in', ('line_section', 'line_note')),
            ('parent_state', '!=', 'cancel'),
            ('company_id', 'in', company_ids),
        ]
        if drilldown_type == 'base':
            # The tax report calculates the taxable base from the taxes applied
            # to the accounting line.
            domain.append(('tax_ids', 'in', tax_ids))
        else:
            # Tax amounts are posted on the dedicated tax line.
            domain.append(('tax_line_id', 'in', tax_ids))
        if form_data.get('target_move') == 'posted':
            domain.append(('parent_state', '=', 'posted'))
        if form_data.get('date_from'):
            domain.append(('date', '>=', form_data['date_from']))
        if date_to:
            domain.append(('date', '<=', date_to))
        if form_data.get('journal_ids'):
            domain.append(('journal_id', 'in', form_data['journal_ids']))
        return domain

    @api.model
    def _named_window_action(self, action, title):
        action = dict(action or {})
        for key in ('id', 'xml_id', 'binding_model_id', 'binding_type', 'binding_view_types'):
            action.pop(key, None)
        action.update({
            'name': title,
            'display_name': title,
        })
        return action

    @api.model
    def action_open_tax_report_target(self, form_data, tax_ids, drilldown_type, label=None):
        """Open the internal Journal Items view for the clicked tax-report amount."""
        try:
            tax_ids = sorted({int(tax_id) for tax_id in (tax_ids or []) if int(tax_id) > 0})
        except (TypeError, ValueError):
            return False
        if not tax_ids or drilldown_type not in ('base', 'tax'):
            return False

        tax_ids = self.env['account.tax'].browse(tax_ids).exists().ids
        if not tax_ids:
            return False

        title = 'Journal Items'
        if label:
            title = '%s - %s' % (title, label)
        action = self._named_window_action(
            self.env['ir.actions.act_window']._for_xml_id('account.action_account_moves_all'),
            title,
        )
        context = action.get('context') or {}
        if isinstance(context, str):
            context = safe_eval(context, {'active_id': False, 'active_ids': []})
        action.update({
            'domain': self._tax_report_journal_item_domain(form_data, tax_ids, drilldown_type),
            'context': {
                **context,
                **self._company_context(self._selected_company_ids_from_payload(form_data)),
                **self._report_date_search_context(form_data),
                'search_default_posted': 1 if (form_data or {}).get('target_move') == 'posted' else 0,
            },
        })
        return action

    @api.model
    def action_open_trial_balance_account_target(self, form_data, account_id, target):
        account = self.env['account.account'].browse(account_id).exists()
        if not account:
            return False

        if target == 'general_ledger':
            date_to = fields.Date.to_date((form_data or {}).get('date_to') or (form_data or {}).get('date') or self._today())
            updates = {
                'account_ids': [account.id],
                'display_account': 'movement',
                'initial_balance': True,
                'sortby': 'sort_date',
            }
            if not (form_data or {}).get('date_from'):
                updates['date_from'] = date_to.replace(day=1)
            vals = self._prepare_wizard_vals('account.report.general.ledger', form_data or {}, updates=updates)
            return self._run_report(
                'account.report.general.ledger',
                vals,
                selected_company_ids=self._selected_company_ids_from_payload(form_data),
            )

        if target == 'journal_items':
            title = account.display_name
            action = self._named_window_action(
                self.env['ir.actions.act_window']._for_xml_id('account.action_account_moves_all'),
                title,
            )
            context = action.get('context') or {}
            if isinstance(context, str):
                context = safe_eval(context, {'active_id': account.id, 'active_ids': [account.id]})
            action.update({
                'domain': self._journal_item_action_domain(form_data, account.id),
                'context': {
                    **context,
                    **self._company_context(self._selected_company_ids_from_payload(form_data)),
                    **self._report_date_search_context(form_data),
                    'search_default_account_id': [account.id],
                    'default_account_id': account.id,
                    'search_default_posted': 1 if (form_data or {}).get('target_move') == 'posted' else 0,
                },
            })
            return action

        return False

    @api.model
    def action_open_partner_ledger_target(self, form_data, partner_id, target):
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return False

        if target == 'partner':
            return {
                'type': 'ir.actions.act_window',
                'name': partner.display_name,
                'res_model': 'res.partner',
                'res_id': partner.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
                'display_name': partner.display_name,
                'context': self._company_context(self._selected_company_ids_from_payload(form_data)),
            }

        if target == 'journal_items':
            title = partner.display_name
            action = self._named_window_action(
                self.env['ir.actions.act_window']._for_xml_id('account.action_account_moves_all'),
                title,
            )
            context = action.get('context') or {}
            if isinstance(context, str):
                context = safe_eval(context, {'active_id': partner.id, 'active_ids': [partner.id]})
            domain = [
                ('display_type', 'not in', ('line_section', 'line_note')),
                ('parent_state', '!=', 'cancel'),
                ('partner_id', '=', partner.id),
                ('company_id', 'in', self._selected_company_ids_from_payload(form_data)),
            ]
            if (form_data or {}).get('target_move') == 'posted':
                domain.append(('parent_state', '=', 'posted'))
            if (form_data or {}).get('date_from'):
                domain.append(('date', '>=', form_data['date_from']))
            date_to = (form_data or {}).get('date_to') or (form_data or {}).get('date')
            if date_to:
                domain.append(('date', '<=', date_to))
            if (form_data or {}).get('journal_ids'):
                domain.append(('journal_id', 'in', form_data['journal_ids']))
            action.update({
                'domain': domain,
                'context': {
                    **context,
                    **self._company_context(self._selected_company_ids_from_payload(form_data)),
                    **self._report_date_search_context(form_data),
                    'search_default_partner_id': [partner.id],
                    'default_partner_id': partner.id,
                    'search_default_posted': 1 if (form_data or {}).get('target_move') == 'posted' else 0,
                },
            })
            return action

        return False

    @api.model
    def action_open_partner_ledger_line_target(self, form_data, move_id, target):
        move = self.env['account.move'].browse(move_id).exists()
        if not move:
            return False

        if target == 'open_move':
            return {
                'type': 'ir.actions.act_window',
                'name': move.display_name,
                'res_model': 'account.move',
                'res_id': move.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
                'display_name': move.display_name,
                'context': {
                    **self._company_context(self._selected_company_ids_from_payload(form_data)),
                    **self._report_date_search_context(form_data),
                    'default_move_type': move.move_type,
                },
            }

        return False

    @api.model
    def action_open_aged_partner_target(self, form_data, partner_id, target):
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return False

        if target == 'partner':
            return {
                'type': 'ir.actions.act_window',
                'name': partner.display_name,
                'res_model': 'res.partner',
                'res_id': partner.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
                'display_name': partner.display_name,
                'context': self._company_context(self._selected_company_ids_from_payload(form_data)),
            }

        if target == 'partner_ledger':
            date_to = fields.Date.to_date(
                (form_data or {}).get('date_from')
                or (form_data or {}).get('date_to')
                or self._today()
            )
            result_selection = (form_data or {}).get('result_selection') or 'customer'
            vals = self._prepare_wizard_vals(
                'account.report.partner.ledger',
                form_data or {},
                updates={
                    'date_from': date_to.replace(month=1, day=1),
                    'date_to': date_to,
                    'result_selection': result_selection if result_selection in ('customer', 'supplier', 'customer_supplier') else 'customer',
                    'partner_ids': [partner.id],
                    'reconciled': False,
                },
            )
            return self._run_report(
                'account.report.partner.ledger',
                vals,
                selected_company_ids=self._selected_company_ids_from_payload(form_data),
                report_title=_('Customer Ledger'),
                report_slug='partner-ledger',
            )

        return False

    @api.model
    def action_open_balance_sheet_preview(self):
        return self._run_report(
            'accounting.report',
            {
                'account_report_id': self.env.ref(
                    'accounting_pdf_reports.account_financial_report_balancesheet0'
                ).id,
                'date_to': self._today(),
            },
            report_title=_('Balance Sheet'),
            report_slug='balance-sheet',
        )

    @api.model
    def action_open_profit_and_loss_preview(self):
        return self._run_report(
            'accounting.report',
            {
                'account_report_id': self.env.ref(
                    'accounting_pdf_reports.account_financial_report_profitandloss0'
                ).id,
                'date_to': self._today(),
            },
            report_title=_('Profit and Loss'),
            report_slug='profit-and-loss',
        )

    @api.model
    def action_open_cash_flow_statement_preview(self):
        date_from, date_to = self.env['account.cash.flow.report']._last_closed_month_range()
        return self._run_report(
            'account.cash.flow.report',
            {
                'date_from': date_from,
                'date_to': date_to,
            },
            report_title=_('Cash Flow Statement'),
            report_slug='cash-flow-statement',
        )

    @api.model
    def action_open_general_ledger_preview(self):
        return self._run_report(
            'account.report.general.ledger',
            {
                'date_to': self._today(),
            },
            report_title=_('General Ledger'),
            report_slug='general-ledger',
        )

    @api.model
    def action_open_partner_ledger_preview(self):
        return self._run_report(
            'account.report.partner.ledger',
            {
                'date_to': self._today(),
                'result_selection': 'customer_supplier',
            },
            report_title=_('Partner Ledger'),
            report_slug='partner-ledger',
        )

    @api.model
    def action_open_trial_balance_preview(self):
        return self._run_report(
            'account.balance.report',
            {
                'date_to': self._today(),
            },
            report_title=_('Trial Balance'),
            report_slug='trial-balance',
        )

    @api.model
    def action_open_tax_report_preview(self):
        date_from, date_to = self.env['account.cash.flow.report']._last_closed_month_range()
        return self._run_report(
            'account.tax.report.wizard',
            {
                'date_from': date_from,
                'date_to': date_to,
            },
            report_title=_('Tax Report'),
            report_slug='tax-report',
        )

    @api.model
    def action_open_aged_partner_balance_preview(self):
        return self._run_report(
            'account.aged.trial.balance',
            {
                'date_from': self._today(),
                'result_selection': 'customer_supplier',
            },
            report_title=_('Aged Partner Balance'),
            report_slug='aged-partner-balance',
        )

    @api.model
    def action_open_aged_receivable_preview(self):
        return self._run_report(
            'account.aged.trial.balance',
            {
                'date_from': self._today(),
                'result_selection': 'customer',
            },
            report_title=_('Aged Receivable'),
            report_slug='aged-receivable',
        )

    @api.model
    def action_open_aged_payable_preview(self):
        return self._run_report(
            'account.aged.trial.balance',
            {
                'date_from': self._today(),
                'result_selection': 'supplier',
            },
            report_title=_('Aged Payable'),
            report_slug='aged-payable',
        )

    @api.model
    def action_open_journal_audit_preview(self):
        return self._run_report(
            'account.print.journal',
            {
                'date_to': self._today(),
                'sort_selection': 'move_name',
            },
            report_title=_('Journals Audit'),
            report_slug='journals-audit',
        )

    @api.model
    def action_open_daybook_preview(self):
        return self._run_report(
            'account.daybook.report',
            {
                'date_from': self._month_start(),
                'date_to': self._today(),
            },
            report_title=_('All Journals'),
            report_slug='day-book',
        )

    @api.model
    def action_open_cashbook_preview(self):
        return self._run_report(
            'account.cashbook.report',
            {
                'date_from': self._month_start(),
                'date_to': self._today(),
                'sortby': 'sort_date',
                'display_account': 'movement',
            },
            report_title=_('Cash Book'),
            report_slug='cash-book',
        )

    @api.model
    def action_open_bankbook_preview(self):
        return self._run_report(
            'account.bankbook.report',
            {
                'date_from': self._month_start(),
                'date_to': self._today(),
                'sortby': 'sort_date',
                'display_account': 'movement',
            },
            report_title=_('Bank Book'),
            report_slug='bank-book',
        )

    @api.model
    def action_open_executive_summary_preview(self):
        today = self._today()
        return self._run_report(
            'account.executive.summary.report',
            {
                'date_from': today.replace(month=1, day=1),
                'date_to': today,
            },
            report_title=_('Executive Summary'),
            report_slug='executive-summary',
        )

    @api.model
    def sync_report_menu_labels(self):
        menu_labels = {
            'account.account_reports_legal_statements_menu': 'Statement Reports',
            'accounting_pdf_reports.menu_account_report_bs': 'Balance Sheet',
            'accounting_pdf_reports.menu_account_report_pl': 'Profit and Loss',
            'acc_reports_enterprise_simulation.menu_cash_flow_statement': 'Cash Flow Statement',
            'accounting_pdf_reports.menu_finance_entries_accounting_ledgers': 'Ledgers',
            'accounting_pdf_reports.menu_general_balance_report': 'Trial Balance',
            'accounting_pdf_reports.menu_general_ledger': 'General Ledger',
            'acc_reports_enterprise_simulation.account_reports_partners_reports_menu': 'Partner Reports',
            'accounting_pdf_reports.menu_partner_ledger': 'Partner Ledger',
            'accounting_pdf_reports.menu_aged_receivable': 'Aged Receivable',
            'accounting_pdf_reports.menu_aged_payable': 'Aged Payable',
            'acc_reports_enterprise_simulation.account_reports_taxes_and_fiscal_menu': 'Taxes and Fiscal',
            'accounting_pdf_reports.menu_account_report': 'Tax Report',
            'acc_reports_enterprise_simulation.menu_financial_report': 'Financial Report',
            'account.account_reports_management_menu': 'Management',
            'account.menu_action_account_invoice_report_all': 'Invoice Analysis',
            'account.menu_action_analytic_reporting': 'Analytic Reporting',
            'acc_reports_enterprise_simulation.menu_executive_summary': 'Executive Summary',
        }
        for xmlid, label in menu_labels.items():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if not menu:
                continue
            menu.with_context(lang='en_US').write({'name': label})

        balance_sheet_labels = {
            'accounting_pdf_reports.account_financial_report_assets0': {
                'en_US': 'Assets',
                'ar_001': 'الأصول',
            },
            'accounting_pdf_reports.account_financial_report_liabilitysum0': {
                'en_US': 'Liabilities',
                'ar_001': 'التزامات',
            },
            'accounting_pdf_reports.account_financial_report_liability0': {
                'en_US': 'Creditors',
                'ar_001': 'الدائنون',
            },
        }
        for xmlid, labels in balance_sheet_labels.items():
            report = self.env.ref(xmlid, raise_if_not_found=False)
            if not report:
                continue
            for lang, label in labels.items():
                report.with_context(lang=lang).write({'name': label})
        return True
