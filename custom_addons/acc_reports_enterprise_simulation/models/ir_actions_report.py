import re

from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _build_wkhtmltopdf_args(self, *args, **kwargs):
        command_args = super()._build_wkhtmltopdf_args(*args, **kwargs)
        if '--encoding' not in command_args:
            command_args.extend(['--encoding', 'utf-8'])
        return command_args

    def _ensure_utf8_html(self, html):
        if not html:
            return html
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')
        lower_html = html[:1000].lower()
        if 'charset=' in lower_html or 'charset="' in lower_html or "charset='" in lower_html:
            return html
        if '<head' in lower_html:
            return re.sub(r'(<head\b[^>]*>)', r'\1<meta charset="utf-8"/>', html, count=1, flags=re.IGNORECASE)
        if '<html' in lower_html:
            return re.sub(r'(<html\b[^>]*>)', r'\1<head><meta charset="utf-8"/></head>', html, count=1, flags=re.IGNORECASE)
        return '<!DOCTYPE html><html><head><meta charset="utf-8"/></head><body>%s</body></html>' % html

    def _run_wkhtmltopdf(
        self,
        bodies,
        report_ref=False,
        header=None,
        footer=None,
        landscape=False,
        specific_paperformat_args=None,
        set_viewport_size=False,
    ):
        if self.env.context.get('acc_report_preview_export'):
            specific_paperformat_args = {
                **(specific_paperformat_args or {}),
                'data-report-margin-top': '5',
                'data-report-header-spacing': '0',
                'data-report-margin-bottom': '8',
                'data-report-dpi': '110',
            }
        return super()._run_wkhtmltopdf(
            [self._ensure_utf8_html(body) for body in bodies],
            report_ref=report_ref,
            header=self._ensure_utf8_html(header),
            footer=self._ensure_utf8_html(footer),
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )
