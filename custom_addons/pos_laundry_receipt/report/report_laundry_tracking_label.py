import re
from urllib.parse import quote

from odoo import fields, models, tools, _
from odoo.tools.image import image_data_uri


class LaundryTrackingLabelReportMixin:
    def _get_report_values(self, docids, data=None):
        data = dict(data or {})
        labels = self.env["pos.laundry.label"].browse(docids).exists()
        labels._check_print_access()
        labels.mapped("order_id")._ensure_laundry_qr_token()
        payloads = [self._build_label_payload(label) for label in labels]
        return {
            "doc_ids": labels.ids,
            "doc_model": "pos.laundry.label",
            "docs": labels,
            "payloads": payloads,
            "auto_print": bool(data.get("auto_print")),
        }

    def _build_label_payload(self, label):
        order = label.order_id
        intake = order.x_laundry_intake_id
        source_lines = intake.line_ids if intake else order.lines
        source_line_count = len(source_lines)
        visible_lines = source_lines[:5]
        items = []
        for line in visible_lines:
            if intake:
                name = (
                    line.product_id.display_name
                    if line.product_id
                    else line.product_name or _("Item")
                )
                details = [
                    self._normalize_currency_text(detail.strip())
                    for detail in (line.selection_details or "").splitlines()
                    if detail.strip()
                ][:2]
                amount = line.price_subtotal
            else:
                name = line.product_id.display_name or _("Item")
                details = []
                amount = line.price_subtotal_incl
            items.append(
                {
                    "name": name,
                    "qty": self._format_quantity(line.qty),
                    "details": details,
                    "amount": self._format_amount(amount, order.currency_id),
                }
            )

        language_code = self.env.context.get("lang") or self.env.user.lang or "en_US"
        direction = (
            "rtl"
            if language_code.split("_", 1)[0].lower() in {"ar", "fa", "he", "ur"}
            else "ltr"
        )
        company = order.company_id
        payment_status = order._get_laundry_payment_status()
        priority = self._get_order_priority_payload(order)
        return {
            "label_id": label.id,
            "reference": order._get_laundry_reference(),
            "customer": order.partner_id.name or _("Walk-in Customer"),
            "phone": (
                order.partner_id.mobile
                or order.partner_id.phone
                or (intake and intake.phone)
                or ""
            ),
            "laundry_status": order._get_laundry_status_text(
                order.x_laundry_status
            )["label"],
            "payment_status": order._get_payment_status_label(payment_status),
            "payment_status_key": payment_status,
            "priority": priority,
            "received_date": self._format_date(order.date_order),
            "received_time": self._format_time(order.date_order),
            "total_items": self._format_quantity(sum(source_lines.mapped("qty"))),
            "item_line_count": source_line_count,
            "total_amount": self._format_amount(
                order.amount_total,
                order.currency_id,
            ),
            "items": items,
            "more_item_lines": max(0, source_line_count - len(items)),
            "qr_url": order._get_laundry_scan_url(),
            "qr_barcode_url": self._get_label_qr_barcode_url(order),
            "company_name": self._get_localized_company_name(company),
            "logo_data_uri": image_data_uri(company.logo) if company.logo else "",
            "direction": direction,
            "text_laundry_service": _("Laundry Service"),
            "text_laundry_order": _("Laundry Order"),
            "text_customer": _("Customer"),
            "text_phone": _("Phone"),
            "text_status": _("Status"),
            "text_payment_status": _("Payment Status"),
            "text_priority": _("Priority"),
            "text_received": _("Received"),
            "text_items": _("Items"),
            "text_amount": _("Amount"),
            "text_more_items": _("more item lines"),
            "text_scan": _("Scan to update the next stage"),
            "text_total_items": _("Total Items"),
            "text_total_amount": _("Total Amount"),
        }

    def _get_localized_company_name(self, company):
        company_name = (company.name or "").strip()
        normalized_name = company_name.replace(" ", "").lower()
        if "رغوة" in normalized_name or "foamplus" in normalized_name:
            return _("Foam Plus Laundry")
        return company_name

    def _get_label_qr_barcode_url(self, order):
        order.ensure_one()
        return "/report/barcode/?barcode_type=QR&width=260&height=260&value=%s" % quote(
            order._build_laundry_qr_payload(),
            safe="",
        )

    def _get_order_priority_payload(self, order):
        order.ensure_one()
        priority_key = ""

        if order._fields.get("laundry_order_id") and order.laundry_order_id:
            laundry_order = order.laundry_order_id
            if laundry_order._fields.get("priority"):
                priority_key = laundry_order.priority or ""
        if not priority_key and order._fields.get("x_laundry_intake_id") and order.x_laundry_intake_id:
            intake = order.x_laundry_intake_id
            if intake._fields.get("priority"):
                priority_key = intake.priority or ""
        if not priority_key and order._fields.get("x_laundry_priority"):
            priority_key = order.x_laundry_priority or ""
        if not priority_key and order._fields.get("priority"):
            priority_key = order.priority or ""

        priority_key = (priority_key or "").strip()
        if not priority_key:
            return {}

        if priority_key == "urgent":
            label = _("Urgent")
        elif priority_key == "normal":
            label = _("Normal")
        else:
            label = priority_key

        return {
            "key": priority_key,
            "label": label,
        }

    def _format_amount(self, amount, currency):
        numeric_value = tools.formatLang(
            self.env,
            amount,
            digits=currency.decimal_places,
        )
        return "%s\u00a0SR" % numeric_value

    def _normalize_currency_text(self, value):
        return re.sub(r"\bSAR\b|ر\.?\s?س\.?|﷼", "SR", value or "", flags=re.IGNORECASE)

    def _format_date(self, value):
        if not value:
            return ""
        return tools.format_date(
            self.env,
            fields.Datetime.to_datetime(value),
            date_format="dd/MM/yyyy",
        )

    def _format_time(self, value):
        if not value:
            return ""
        return tools.format_time(
            self.env,
            fields.Datetime.to_datetime(value),
            tz=self.env.user.tz,
            time_format="hh:mm a",
        )

    def _format_quantity(self, value):
        number = float(value or 0.0)
        return str(int(number)) if number.is_integer() else ("%.2f" % number)


class ReportLaundryTrackingLabelThermal(
    LaundryTrackingLabelReportMixin,
    models.AbstractModel,
):
    _name = "report.pos_laundry_receipt.report_laundry_label_thermal"
    _description = "Laundry Tracking Label Epson POS Report"


class ReportLaundryTrackingLabelA4(
    LaundryTrackingLabelReportMixin,
    models.AbstractModel,
):
    _name = "report.pos_laundry_receipt.report_laundry_label_a4"
    _description = "Laundry Tracking Label Legacy A4 Redirect"
