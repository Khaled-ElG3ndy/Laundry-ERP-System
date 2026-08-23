# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import re
import unicodedata
from io import BytesIO

import lxml.html
import xlsxwriter

from odoo import _, http
from odoo.http import content_disposition, request


class AccountingReportPreviewController(http.Controller):
    def _active_ids_from_context(self, context):
        active_ids = context.get('active_ids') or []
        active_id = context.get('active_id')
        if active_id and not active_ids:
            active_ids = [active_id]
        return active_ids

    @http.route(['/acc_reports_enterprise_simulation/export_pdf'], type='http', auth='user', methods=['POST'], csrf=True)
    def export_pdf(self, report_name, data=None, context=None, display_name=None, search_term=None):
        try:
            data = json.loads(data or '{}')
            context = json.loads(context or '{}')
            report = request.env['ir.actions.report']._get_report_from_name(report_name)
            report_env = request.env['ir.actions.report'].with_context(
                **context,
                acc_report_preview_export=True,
            ).sudo()
            active_ids = self._active_ids_from_context(context)
            if (search_term or '').strip():
                html_content = report_env.with_context(debug=False)._render_qweb_html(
                    report.report_name,
                    active_ids,
                    data=data,
                )[0]
                html_content = self._apply_export_search_filter(html_content, search_term)
                report_sudo = report.sudo().with_context(
                    **context,
                    acc_report_preview_export=True,
                    debug=False,
                )
                bodies, _html_ids, header, footer, specific_paperformat_args = report_sudo._prepare_html(
                    html_content,
                    report_model=report_sudo.model,
                )
                pdf_data = report_sudo._run_wkhtmltopdf(
                    bodies,
                    report_ref=report.report_name,
                    header=header,
                    footer=footer,
                    landscape=report_sudo.env.context.get('landscape'),
                    specific_paperformat_args=specific_paperformat_args,
                    set_viewport_size=report_sudo.env.context.get('set_viewport_size'),
                )
            else:
                pdf_data = report_env._render_qweb_pdf(
                    report.report_name,
                    active_ids,
                    data=data,
                )[0]
            report_label = display_name or (data.get('form') or {}).get('download_name') or report.name
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf_data)),
                ('Content-Disposition', content_disposition(f"{report_label}.pdf")),
            ]
            return request.make_response(pdf_data, headers=headers)
        except Exception as e:
            response = request.make_response(http.serialize_exception(e))
            response.status_code = 500
            return response

    @http.route(['/acc_reports_enterprise_simulation/export_xlsx'], type='http', auth='user', methods=['POST'], csrf=True)
    def export_xlsx(self, report_name, data=None, context=None, display_name=None, search_term=None):
        try:
            data = json.loads(data or '{}')
            context = json.loads(context or '{}')

            report = request.env['ir.actions.report']._get_report_from_name(report_name)
            report_env = request.env['ir.actions.report'].with_context(**context).sudo()
            active_ids = self._active_ids_from_context(context)
            rendering_context = report_env._get_rendering_context(report, active_ids, data)
            html_content = report_env._render_qweb_html(report.report_name, active_ids, data=data)[0]
            html_content = self._apply_export_search_filter(html_content, search_term)
            report_label = display_name or (data.get('form') or {}).get('download_name') or report.name
            xlsx_data = self._build_xlsx(report.report_name, report_label, rendering_context, html_content=html_content)
            filename = f"{report_label}.xlsx"
            headers = [
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Length', len(xlsx_data)),
                ('Content-Disposition', content_disposition(filename)),
            ]
            return request.make_response(xlsx_data, headers=headers)
        except Exception as e:
            response = request.make_response(http.serialize_exception(e))
            response.status_code = 500
            return response

    def _safe_sheet_name(self, value):
        value = re.sub(r'[\[\]:*?/\\]', ' ', value or 'Report').strip() or 'Report'
        return value[:31]

    def _normalize_cell_text(self, value):
        return re.sub(r'\s+', ' ', value or '').strip()

    def _normalize_search_text(self, value):
        value = unicodedata.normalize('NFKD', str(value or ''))
        value = re.sub(r'[\u064B-\u065F\u0670]', '', value)
        value = (
            value
            .replace('إ', 'ا')
            .replace('أ', 'ا')
            .replace('آ', 'ا')
            .replace('ى', 'ي')
            .replace('ؤ', 'و')
            .replace('ئ', 'ي')
            .replace('ة', 'ه')
        )
        return re.sub(r'\s+', ' ', value).strip().lower()

    def _first_attr(self, node, xpath):
        values = node.xpath(xpath)
        return str(values[0]) if values else ''

    def _export_row_keys(self, row):
        account_id = row.get('data-account-row-id') or self._first_attr(
            row,
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_account_line ')]/@data-account-id",
        )
        partner_id = self._first_attr(
            row,
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_partner_line ')]/@data-partner-id",
        )
        return {
            'own': {
                'report': row.get('data-report-id') or '',
                'account': account_id or '',
                'partner': partner_id or '',
                'aged_partner': row.get('data-aged-partner-id') or '',
                'tb': row.get('data-tb-line-key') or '',
            },
            'parent': {
                'report': row.get('data-parent-report-id') or '',
                'account': row.get('data-parent-account-id') or '',
                'partner': row.get('data-parent-partner-id') or '',
                'aged_partner': row.get('data-parent-aged-partner-id') or '',
                'tb': row.get('data-parent-tb-key') or '',
            },
        }

    def _apply_export_search_filter(self, html_content, search_term):
        needle = self._normalize_search_text(search_term)
        if not needle:
            return html_content

        root = lxml.html.fromstring(self._decode_html(html_content))
        rows = root.xpath('//tbody/tr')
        relation_kinds = ('report', 'account', 'partner', 'aged_partner', 'tb')
        matching_rows = {}
        matching_own_ids = {kind: set() for kind in relation_kinds}
        matching_parent_ids = {kind: set() for kind in relation_kinds}
        parent_by_child = {kind: {} for kind in relation_kinds}
        children_by_parent = {kind: {} for kind in relation_kinds}
        row_keys = {}

        def add_child(kind, parent_id, child_id):
            if not parent_id or not child_id:
                return
            parent_by_child[kind][child_id] = parent_id
            children_by_parent[kind].setdefault(parent_id, set()).add(child_id)

        for row in rows:
            keys = self._export_row_keys(row)
            row_keys[row] = keys
            for kind in relation_kinds:
                add_child(kind, keys['parent'][kind], keys['own'][kind])

            haystack = self._normalize_search_text(row.text_content())
            matches = needle in haystack
            matching_rows[row] = matches
            if not matches:
                continue
            for kind in relation_kinds:
                if keys['own'][kind]:
                    matching_own_ids[kind].add(keys['own'][kind])
                if keys['parent'][kind]:
                    matching_parent_ids[kind].add(keys['parent'][kind])

        for kind in relation_kinds:
            descendants = list(matching_own_ids[kind])
            for item_id in descendants:
                for child_id in children_by_parent[kind].get(item_id, set()):
                    if child_id not in matching_own_ids[kind]:
                        matching_own_ids[kind].add(child_id)
                        descendants.append(child_id)

            ancestors = list(matching_parent_ids[kind])
            for item_id in ancestors:
                parent_id = parent_by_child[kind].get(item_id)
                if parent_id and parent_id not in matching_parent_ids[kind]:
                    matching_parent_ids[kind].add(parent_id)
                    ancestors.append(parent_id)

        for row in rows:
            keys = row_keys[row]
            visible = matching_rows.get(row) or any(
                (keys['parent'][kind] and keys['parent'][kind] in matching_own_ids[kind])
                or (keys['own'][kind] and keys['own'][kind] in matching_own_ids[kind])
                or (keys['own'][kind] and keys['own'][kind] in matching_parent_ids[kind])
                for kind in relation_kinds
            )
            if not visible:
                parent = row.getparent()
                if parent is not None:
                    parent.remove(row)

        return lxml.html.tostring(root, encoding='unicode')

    def _decode_html(self, html_content):
        if isinstance(html_content, bytes):
            return html_content.decode('utf-8', errors='replace')
        return html_content or ''

    def _strip_export_only_nodes(self, root):
        drop_xpaths = [
            './/script',
            './/style',
            './/button',
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_account_row_tools ')]",
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_account_action_dropdown ')]",
            ".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_preview_hidden_search ')]",
        ]
        for xpath in drop_xpaths:
            for node in root.xpath(xpath):
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
        for node in root.xpath('//*[@style]'):
            style = (node.get('style') or '').replace(' ', '').lower()
            if 'display:none' in style or 'visibility:hidden' in style:
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)

    def _is_total_row(self, row):
        row_class = row.get('class') or ''
        row_style = (row.get('style') or '').replace(' ', '').lower()
        return (
            'o_acc_financial_section' in row_class
            or 'o_acc_financial_total' in row_class
            or 'o_total_row' in row_class
            or 'font-weight:bold' in row_style
        )

    def _is_negative_cell(self, cell, text):
        cell_class = cell.get('class') or ''
        return 'o_acc_financial_negative' in cell_class or text.endswith('-') or text.startswith('-')

    def _is_muted_cell(self, cell):
        cell_class = cell.get('class') or ''
        return 'o_acc_financial_muted' in cell_class

    def _numeric_cell_value(self, cell, text):
        """Return a real spreadsheet number for amount cells, never for labels/codes."""
        cell_class = cell.get('class') or ''
        numeric_classes = (
            'text-end', 'o_value_col', 'o_period_col', 'o_acc_financial_amount',
            'o_acc_financial_metric', 'number', 'amount',
        )
        if not any(css_class in cell_class for css_class in numeric_classes):
            return None
        normalized = text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')).strip()
        negative = normalized.startswith('(') and normalized.endswith(')')
        if normalized.endswith('-'):
            negative = True
        match = re.search(r'-?\d[\d,]*(?:\.\d+)?', normalized)
        if not match:
            return None
        value = float(match.group(0).replace(',', ''))
        return -abs(value) if negative else value

    def _write_html_table_to_sheet(self, workbook, sheet, table, start_row, formats):
        occupied = {}
        max_col = 0
        row_idx = start_row
        for html_row in table.xpath('.//tr'):
            cells = html_row.xpath('./th|./td')
            if not cells:
                continue
            col_idx = 0
            is_header = any(cell.tag.lower() == 'th' for cell in cells)
            is_total = self._is_total_row(html_row)
            for cell in cells:
                while occupied.get((row_idx, col_idx)):
                    col_idx += 1
                text = self._normalize_cell_text(cell.text_content())
                colspan = int(cell.get('colspan') or 1)
                rowspan = int(cell.get('rowspan') or 1)
                number_value = self._numeric_cell_value(cell, text)
                fmt = formats['number'] if number_value is not None else formats['cell']
                if is_header:
                    fmt = formats['header']
                elif is_total:
                    if number_value is not None:
                        fmt = formats['total_number_negative'] if number_value < 0 else formats['total_number']
                    else:
                        fmt = formats['total_negative'] if self._is_negative_cell(cell, text) else formats['total']
                elif self._is_negative_cell(cell, text):
                    fmt = formats['number_negative'] if number_value is not None else formats['negative']
                elif self._is_muted_cell(cell):
                    fmt = formats['number_muted'] if number_value is not None else formats['muted']
                value = number_value if number_value is not None and not is_header else text
                if colspan > 1 or rowspan > 1:
                    sheet.merge_range(
                        row_idx,
                        col_idx,
                        row_idx + rowspan - 1,
                        col_idx + colspan - 1,
                        value,
                        fmt,
                    )
                else:
                    sheet.write(row_idx, col_idx, value, fmt)
                for row_offset in range(rowspan):
                    for col_offset in range(colspan):
                        occupied[(row_idx + row_offset, col_idx + col_offset)] = True
                col_idx += colspan
                max_col = max(max_col, col_idx - 1)
            row_idx += 1
        return row_idx, max_col

    def _build_xlsx_from_html(self, workbook, report_label, html_content):
        root = lxml.html.fromstring(self._decode_html(html_content))
        self._strip_export_only_nodes(root)
        tables = root.xpath('//table[.//tr]')
        if not tables:
            return False

        sheet = workbook.add_worksheet(self._safe_sheet_name(report_label))
        sheet.right_to_left()
        sheet.hide_gridlines(2)
        sheet.set_default_row(22)
        sheet.set_margins(left=0.25, right=0.25, top=0.3, bottom=0.3)
        sheet.fit_to_pages(1, 0)
        sheet.center_horizontally()

        formats = {
            'title': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 13,
                'align': 'right', 'valign': 'vcenter',
            }),
            'cell': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'border': 0,
            }),
            'number': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'left', 'valign': 'vcenter', 'border': 0,
                'num_format': '#,##0.00;[Red]-#,##0.00',
            }),
            'header': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'bottom': 1,
            }),
            'total': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'bg_color': '#D8DADD',
            }),
            'total_negative': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'bg_color': '#D8DADD',
                'font_color': '#E02020',
            }),
            'total_number': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 10,
                'align': 'left', 'valign': 'vcenter', 'bg_color': '#D8DADD',
                'num_format': '#,##0.00;[Red]-#,##0.00',
            }),
            'total_number_negative': workbook.add_format({
                'bold': True, 'font_name': 'Tahoma', 'font_size': 10,
                'align': 'left', 'valign': 'vcenter', 'bg_color': '#D8DADD',
                'font_color': '#E02020', 'num_format': '#,##0.00;[Red]-#,##0.00',
            }),
            'negative': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'font_color': '#E02020',
            }),
            'number_negative': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'left', 'valign': 'vcenter', 'font_color': '#E02020',
                'num_format': '#,##0.00;[Red]-#,##0.00',
            }),
            'muted': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'right', 'valign': 'vcenter', 'font_color': '#C3CAD3',
            }),
            'number_muted': workbook.add_format({
                'font_name': 'Tahoma', 'font_size': 10,
                'align': 'left', 'valign': 'vcenter', 'font_color': '#C3CAD3',
                'num_format': '#,##0.00;[Red]-#,##0.00',
            }),
        }

        row_idx = 0
        sheet.write(row_idx, 0, report_label, formats['title'])
        row_idx += 2
        period = root.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_acc_financial_period ')]")
        balance_label = root.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_acc_financial_balance_label ')]")
        analytic_selection = root.xpath(".//*[contains(concat(' ', normalize-space(@class), ' '), ' o_report_analytic_selection ')]")
        headings = root.xpath('//h1|//h2|//h3')
        lead_texts = [self._normalize_cell_text(node.text_content()) for node in period or headings[:1]]
        lead_texts += [self._normalize_cell_text(node.text_content()) for node in balance_label]
        lead_texts += [self._normalize_cell_text(node.text_content()) for node in analytic_selection[:1]]
        for text in [text for text in lead_texts if text]:
            sheet.write(row_idx, 0, text, formats['title'])
            row_idx += 1
        if lead_texts:
            row_idx += 1

        max_col = 0
        first_table_row = row_idx
        for table in tables:
            row_idx, table_max_col = self._write_html_table_to_sheet(workbook, sheet, table, row_idx, formats)
            max_col = max(max_col, table_max_col)
            row_idx += 2

        for col_idx in range(max_col + 1):
            sheet.set_column(col_idx, col_idx, 22 if col_idx else 44)
        if first_table_row < row_idx:
            sheet.freeze_panes(first_table_row + 1, 0)
            sheet.repeat_rows(first_table_row, first_table_row)
        if max_col >= 5:
            sheet.set_landscape()
        else:
            sheet.set_portrait()
        sheet.print_area(0, 0, max(0, row_idx - 1), max_col)
        return True

    def _build_xlsx(self, report_name, report_label, report_values, html_content=None):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        if html_content and self._build_xlsx_from_html(workbook, report_label, html_content):
            workbook.close()
            return output.getvalue()

        money_format = workbook.add_format({'num_format': '#,##0.00'})
        bold = workbook.add_format({'bold': True})

        if report_name == 'accounting_pdf_reports.report_trialbalance':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Trial Balance')))
            headers = [_('Closing Balance'), _('Credit'), _('Debit'), _('Opening Balance'), _('Account')]
            sheet.write_row(0, 0, headers, bold)
            for row_idx, account in enumerate(report_values.get('Accounts', []), start=1):
                sheet.write_number(row_idx, 0, account.get('closing_balance') or 0.0, money_format)
                sheet.write_number(row_idx, 1, account.get('credit') or 0.0, money_format)
                sheet.write_number(row_idx, 2, account.get('debit') or 0.0, money_format)
                sheet.write_number(row_idx, 3, account.get('opening_balance') or 0.0, money_format)
                sheet.write(row_idx, 4, account.get('display_name') or account.get('name'))

        elif report_name == 'accounting_pdf_reports.report_financial':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Financial Report')))
            comparison_order = ((report_values.get('data') or {}).get('comparison_order')) or 'descending'
            comparison_label = ((report_values.get('data') or {}).get('label_filter')) or _('Comparison')
            if comparison_order == 'ascending':
                headers = [_('Name'), _('Type'), _('Debit'), _('Credit'), comparison_label, _('Balance')]
            else:
                headers = [_('Name'), _('Type'), _('Debit'), _('Credit'), _('Balance'), comparison_label]
            sheet.write_row(0, 0, headers, bold)
            for row_idx, line in enumerate(report_values.get('get_account_lines', []), start=1):
                sheet.write(row_idx, 0, line.get('name'))
                sheet.write(row_idx, 1, line.get('type'))
                sheet.write_number(row_idx, 2, line.get('debit') or 0.0, money_format)
                sheet.write_number(row_idx, 3, line.get('credit') or 0.0, money_format)
                if comparison_order == 'ascending':
                    sheet.write_number(row_idx, 4, line.get('balance_cmp') or 0.0, money_format)
                    sheet.write_number(row_idx, 5, line.get('balance') or 0.0, money_format)
                else:
                    sheet.write_number(row_idx, 4, line.get('balance') or 0.0, money_format)
                    sheet.write_number(row_idx, 5, line.get('balance_cmp') or 0.0, money_format)

        elif report_name == 'accounting_pdf_reports.report_general_ledger':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('General Ledger')))
            headers = [_('Account'), _('Code'), _('Debit'), _('Credit'), _('Balance'), _('Line Date'), _('Partner'), _('Journal'), _('Label'), _('Move')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for account in report_values.get('Accounts', []):
                sheet.write(row_idx, 0, account.get('name'))
                sheet.write(row_idx, 1, account.get('code'))
                sheet.write_number(row_idx, 2, account.get('debit') or 0.0, money_format)
                sheet.write_number(row_idx, 3, account.get('credit') or 0.0, money_format)
                sheet.write_number(row_idx, 4, account.get('balance') or 0.0, money_format)
                row_idx += 1
                for line in account.get('move_lines', []):
                    sheet.write(row_idx, 0, '')
                    sheet.write(row_idx, 1, '')
                    sheet.write_number(row_idx, 2, line.get('debit') or 0.0, money_format)
                    sheet.write_number(row_idx, 3, line.get('credit') or 0.0, money_format)
                    sheet.write_number(row_idx, 4, line.get('balance') or 0.0, money_format)
                    sheet.write(row_idx, 5, str(line.get('ldate') or ''))
                    sheet.write(row_idx, 6, line.get('partner_name'))
                    sheet.write(row_idx, 7, line.get('lcode'))
                    sheet.write(row_idx, 8, line.get('lname'))
                    sheet.write(row_idx, 9, line.get('move_name'))
                    row_idx += 1

        elif report_name == 'accounting_pdf_reports.report_partnerledger':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Partner Ledger')))
            headers = [_('Partner'), _('Date'), _('Journal'), _('Account'), _('Label'), _('Debit'), _('Credit'), _('Balance')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for partner in report_values.get('docs', []):
                lines = report_values['lines'](report_values['data']['form']['target_move'], partner.id, report_values['data']['form'].get('sortby', 'date'), report_values)
                for line in lines:
                    sheet.write(row_idx, 0, partner.name)
                    sheet.write(row_idx, 1, str(line.get('date') or ''))
                    sheet.write(row_idx, 2, line.get('lcode'))
                    sheet.write(row_idx, 3, line.get('a_code'))
                    sheet.write(row_idx, 4, line.get('lname'))
                    sheet.write_number(row_idx, 5, line.get('debit') or 0.0, money_format)
                    sheet.write_number(row_idx, 6, line.get('credit') or 0.0, money_format)
                    sheet.write_number(row_idx, 7, line.get('progress') or 0.0, money_format)
                    row_idx += 1

        elif report_name == 'accounting_pdf_reports.report_agedpartnerbalance':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Aged Partner Balance')))
            headers = [_('Partner'), _('Not Due'), '1-30', '31-60', '61-90', '91-120', '+120', _('Total')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for partner in report_values.get('get_partner_lines', []):
                sheet.write(row_idx, 0, partner.get('name'))
                sheet.write_number(row_idx, 1, partner.get('direction') or 0.0, money_format)
                for idx in range(5):
                    sheet.write_number(row_idx, 2 + idx, partner.get(str(idx)) or 0.0, money_format)
                sheet.write_number(row_idx, 7, partner.get('total') or 0.0, money_format)
                row_idx += 1

        elif report_name == 'accounting_pdf_reports.report_tax':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Tax Report')))
            headers = [_('Tax'), _('Type'), _('Group'), _('Net Amount'), _('Tax Amount')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for group, taxes in report_values.get('lines', {}).items():
                for tax in taxes:
                    sheet.write(row_idx, 0, tax.get('name'))
                    sheet.write(row_idx, 1, tax.get('type'))
                    sheet.write(row_idx, 2, group)
                    sheet.write_number(row_idx, 3, tax.get('net') or 0.0, money_format)
                    sheet.write_number(row_idx, 4, tax.get('tax') or 0.0, money_format)
                    row_idx += 1

        elif report_name == 'accounting_pdf_reports.report_journal':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Journals Audit')))
            headers = [_('Journal'), _('Date'), _('Account'), _('Reference'), _('Label'), _('Debit'), _('Credit')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for journal in report_values.get('docs', []):
                lines = report_values['lines'](report_values['data']['form'].get('target_move', 'all'), journal.id, report_values['data']['form'].get('sort_selection', 'date'), report_values)
                for line in lines:
                    sheet.write(row_idx, 0, journal.name)
                    sheet.write(row_idx, 1, str(line.get('ldate') or ''))
                    sheet.write(row_idx, 2, line.get('a_code'))
                    sheet.write(row_idx, 3, line.get('lref'))
                    sheet.write(row_idx, 4, line.get('lname'))
                    sheet.write_number(row_idx, 5, line.get('debit') or 0.0, money_format)
                    sheet.write_number(row_idx, 6, line.get('credit') or 0.0, money_format)
                    row_idx += 1

        elif report_name == 'accounting_pdf_reports.report_journal_entries':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Journal Entries')))
            headers = [_('Journal Entry'), _('Journal'), _('Date'), _('Partner'), _('Reference'), _('Account'), _('Analytic Account'), _('Debit'), _('Credit')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for entry in report_values.get('docs', []):
                for line in entry.line_ids:
                    sheet.write(row_idx, 0, entry.name)
                    sheet.write(row_idx, 1, entry.journal_id.name)
                    sheet.write(row_idx, 2, str(line.date or ''))
                    sheet.write(row_idx, 3, line.partner_id.display_name or '')
                    sheet.write(row_idx, 4, line.ref or '')
                    sheet.write(row_idx, 5, line.account_id.name or '')
                    sheet.write(row_idx, 6, '')
                    sheet.write_number(row_idx, 7, line.debit or 0.0, money_format)
                    sheet.write_number(row_idx, 8, line.credit or 0.0, money_format)
                    row_idx += 1

        elif report_name == 'om_account_daily_reports.report_daybook':
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Day Book')))
            headers = [_('Date'), _('Journal'), _('Partner'), _('Reference'), _('Move'), _('Entry Label'), _('Debit'), _('Credit'), _('Balance')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for day in report_values.get('Accounts', []):
                sheet.write(row_idx, 0, str(day.get('date') or ''))
                sheet.write(row_idx, 5, _('Total'), bold)
                sheet.write_number(row_idx, 6, day.get('debit') or 0.0, money_format)
                sheet.write_number(row_idx, 7, day.get('credit') or 0.0, money_format)
                sheet.write_number(row_idx, 8, day.get('balance') or 0.0, money_format)
                row_idx += 1
                for line in day.get('move_lines', []):
                    sheet.write(row_idx, 0, str(line.get('ldate') or ''))
                    sheet.write(row_idx, 1, line.get('lcode') or '')
                    sheet.write(row_idx, 2, line.get('lpartner_id') or '')
                    sheet.write(row_idx, 3, line.get('lref') or '')
                    sheet.write(row_idx, 4, line.get('move_name') or '')
                    sheet.write(row_idx, 5, line.get('lname') or '')
                    sheet.write_number(row_idx, 6, line.get('debit') or 0.0, money_format)
                    sheet.write_number(row_idx, 7, line.get('credit') or 0.0, money_format)
                    sheet.write_number(row_idx, 8, line.get('balance') or 0.0, money_format)
                    row_idx += 1

        elif report_name in ('om_account_daily_reports.report_cashbook', 'om_account_daily_reports.report_bankbook'):
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Cash Book') if report_name.endswith('cashbook') else _('Bank Book')))
            headers = [_('Account'), _('Code'), _('Date'), _('Journal'), _('Partner'), _('Reference'), _('Move'), _('Entry Label'), _('Debit'), _('Credit'), _('Balance')]
            sheet.write_row(0, 0, headers, bold)
            row_idx = 1
            for account in report_values.get('Accounts', []):
                sheet.write(row_idx, 0, account.get('name') or '', bold)
                sheet.write(row_idx, 1, account.get('code') or '', bold)
                sheet.write_number(row_idx, 8, account.get('debit') or 0.0, money_format)
                sheet.write_number(row_idx, 9, account.get('credit') or 0.0, money_format)
                sheet.write_number(row_idx, 10, account.get('balance') or 0.0, money_format)
                row_idx += 1
                for line in account.get('move_lines', []):
                    sheet.write(row_idx, 0, account.get('name') or '')
                    sheet.write(row_idx, 1, account.get('code') or '')
                    sheet.write(row_idx, 2, str(line.get('ldate') or ''))
                    sheet.write(row_idx, 3, line.get('lcode') or '')
                    sheet.write(row_idx, 4, line.get('partner_name') or line.get('lpartner_id') or '')
                    sheet.write(row_idx, 5, line.get('lref') or '')
                    sheet.write(row_idx, 6, line.get('move_name') or '')
                    sheet.write(row_idx, 7, line.get('lname') or '')
                    sheet.write_number(row_idx, 8, line.get('debit') or 0.0, money_format)
                    sheet.write_number(row_idx, 9, line.get('credit') or 0.0, money_format)
                    sheet.write_number(row_idx, 10, line.get('balance') or 0.0, money_format)
                    row_idx += 1

        else:
            sheet = workbook.add_worksheet(self._safe_sheet_name(_('Report')))
            sheet.write(0, 0, report_label, bold)

        workbook.close()
        return output.getvalue()
