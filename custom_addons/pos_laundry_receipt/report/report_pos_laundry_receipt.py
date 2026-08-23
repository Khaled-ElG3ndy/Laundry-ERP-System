import base64
import re

from odoo import fields, models
from odoo.modules.module import get_module_resource
from odoo.tools.image import image_data_uri


SERVICE_PRICE_WITH_CURRENCY_PATTERN = re.compile(
    r"(?:\s*[-–—:]\s*)?([+-]?\d[\d,]*(?:\.\d+)?)\s*(SR|SAR|ر\.?س\.?|﷼)\s*$",
    re.IGNORECASE,
)
SERVICE_PRICE_AMOUNT_ONLY_PATTERN = re.compile(
    r"\s*[-–—]\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


class ReportPosLaundryReceipt(models.AbstractModel):
    _name = "report.pos_laundry_receipt.report_pos_laundry_receipt"
    _description = "POS Laundry Receipt Report"

    def _get_report_values(self, docids, data=None):
        data = dict(data or {})
        orders = self.env["pos.order"].browse(docids)
        receipt_payloads = {
            order.id: self._build_receipt_payload(order)
            for order in orders
        }
        return {
            "doc_ids": orders.ids,
            "doc_model": "pos.order",
            "docs": orders,
            "receipt_payloads": receipt_payloads,
            "font_css": self._get_font_css(),
            "auto_print": bool(data.get("auto_print")),
            "is_pdf": bool(data.get("is_pdf")),
        }

    def _build_receipt_payload(self, order):
        company = order.company_id
        partner = order.partner_id
        language_code = self.env.context.get("lang") or self.env.user.lang or "en_US"

        lines = self._build_receipt_lines(order)
        subtotal = sum(line["price_subtotal"] for line in lines)
        total = order.x_laundry_intake_id.amount_total if order.x_laundry_intake_id else order.amount_total
        tax = max(0.0, (total or 0.0) - subtotal)

        return {
            "reference": order.x_display_reference or order.name or "",
            "pickup_date": self._format_receipt_datetime(order, order.date_order),
            "partner_name": partner.name or "",
            "phone": partner.phone or partner.mobile or "",
            "company_name": company.name or "",
            "logo_data_uri": image_data_uri(company.logo) if company.logo else "",
            "x_qr_token": order.x_qr_token or "",
            "qr_value": order._build_laundry_qr_payload(),
            "qr_barcode_url": order._get_laundry_qr_barcode_url(),
            "qr_reference": order._get_laundry_reference(),
            "subtotal": subtotal,
            "tax": tax,
            "total": total or 0.0,
            "currency_symbol": "SR",
            "direction": (
                "rtl"
                if language_code.split("_", 1)[0].lower() in {"ar", "fa", "he", "ur"}
                else "ltr"
            ),
            "lines": lines,
        }

    def _build_receipt_lines(self, order):
        currency_symbol = "SR"
        if order.x_laundry_intake_id:
            return [
                {
                    "product_name": line.product_name,
                    "qty": line.qty,
                    "qty_display": self._format_receipt_quantity(line.qty),
                    "price_unit": line.price_unit,
                    "price_subtotal": line.price_subtotal,
                    "detail_lines": [
                        self._split_detail_label_and_price(detail, currency_symbol)
                        for detail in (line.selection_details or "").splitlines()
                        if detail.strip()
                    ],
                }
                for line in order.x_laundry_intake_id.line_ids
            ]

        return [
            {
                "product_name": line.product_id.display_name,
                "qty": line.qty,
                "qty_display": self._format_receipt_quantity(line.qty),
                "price_unit": line.price_unit,
                "price_subtotal": line.price_subtotal,
                "detail_lines": [],
            }
            for line in order.lines
        ]

    def _normalize_currency_at_end(self, value):
        text = re.sub(r"\s+", " ", str(value or "").strip())
        return re.sub(
            r"(^|[\s:-])(SR|SAR|ر\.?س\.?|﷼)\s+([+-]?\d[\d,]*(?:\.\d+)?)",
            lambda match: "%s%s SR" % (match.group(1), match.group(3)),
            text,
            flags=re.IGNORECASE,
        )

    def _split_detail_label_and_price(self, value, fallback_currency_symbol=""):
        text = self._normalize_currency_at_end(value)
        match = (
            SERVICE_PRICE_WITH_CURRENCY_PATTERN.search(text)
            or SERVICE_PRICE_AMOUNT_ONLY_PATTERN.search(text)
        )
        if not match:
            return {
                "label": text,
                "price": "",
            }

        label = re.sub(r"\s*[-–—:]\s*$", "", text[:match.start()]).strip()
        currency_symbol = "SR"
        price = self._normalize_currency_at_end(
            "%s %s" % (match.group(1), currency_symbol) if currency_symbol else match.group(1)
        )
        return {
            "label": label or text,
            "price": price if label else "",
        }

    def _format_receipt_quantity(self, value):
        number = float(value or 0.0)
        return str(int(number)) if number.is_integer() else "%.2f" % number

    def _format_receipt_datetime(self, record, value):
        if not value:
            return ""
        localized_value = fields.Datetime.context_timestamp(record, value)
        return localized_value.strftime("%m/%d/%Y, %I:%M %p")

    def _get_font_css(self):
        font_files = {
            400: "Tajawal-Regular.ttf",
            500: "Tajawal-Medium.ttf",
            700: "Tajawal-Bold.ttf",
            800: "Tajawal-ExtraBold.ttf",
            900: "Tajawal-Black.ttf",
        }
        rules = []
        for weight, filename in font_files.items():
            font_path = get_module_resource(
                "web",
                "static",
                "fonts",
                "google",
                "Tajawal",
                filename,
            )
            if not font_path:
                continue
            with open(font_path, "rb") as font_file:
                encoded = base64.b64encode(font_file.read()).decode("ascii")
            rules.append(
                """
@font-face {{
    font-family: 'TajawalReceipt';
    src: url(data:font/ttf;base64,{encoded}) format('truetype');
    font-style: normal;
    font-weight: {weight};
}}""".format(encoded=encoded, weight=weight)
            )
        return "\n".join(rules)
