import json

from odoo import http
from odoo.addons.web.controllers.report import ReportController
from odoo.http import content_disposition, request
from odoo.tools.safe_eval import safe_eval, time


class ReportInlinePreviewController(ReportController):
    def _get_report_and_docids(self, reportname, docids=None):
        report = request.env['ir.actions.report']._get_report_from_name(reportname)
        ids = [int(docid) for docid in (docids or '').split(',') if docid.isdigit()]
        return report, ids

    def _get_pdf_filename(self, reportname, docids=None):
        report, ids = self._get_report_and_docids(reportname, docids)
        filename = f'{report.name}.pdf'
        if ids:
            records = request.env[report.model].browse(ids)
            if report.print_report_name and len(records) == 1:
                report_name = safe_eval(report.print_report_name, {'object': records, 'time': time})
                if report_name:
                    filename = f'{report_name}.pdf'
        return filename

    def _set_inline_pdf_header(self, response, reportname, docids=None):
        if not response:
            return response
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = content_disposition(
            self._get_pdf_filename(reportname, docids),
            disposition_type='inline',
        )
        return response

    def _parse_report_url(self, url):
        pattern = '/report/pdf/'
        if pattern not in url:
            return None, None
        report_ref = url.split(pattern, 1)[1].split('?', 1)[0]
        if '/' in report_ref:
            return report_ref.split('/', 1)
        return report_ref, None

    @http.route()
    def report_routes(self, reportname, docids=None, converter=None, **data):
        response = super().report_routes(reportname, docids=docids, converter=converter, **data)
        if converter == 'pdf':
            self._set_inline_pdf_header(response, reportname, docids)
        return response

    @http.route()
    def report_download(self, data, context=None, token=None):
        response = super().report_download(data, context=context, token=token)
        try:
            url, report_type = json.loads(data)
        except (TypeError, ValueError, json.JSONDecodeError):
            return response

        if report_type != 'qweb-pdf':
            return response

        reportname, docids = self._parse_report_url(url)
        if not reportname:
            return response
        return self._set_inline_pdf_header(response, reportname, docids)
