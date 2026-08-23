import logging
import uuid

from odoo import _, http, tools
from odoo.exceptions import AccessError, UserError
from odoo.http import request, content_disposition

from ..models.laundry_label import CANONICAL_LABEL_FORMAT

_logger = logging.getLogger(__name__)


class PosLaundryReceiptController(http.Controller):

    @http.route(
        "/pos_laundry_receipt/receipt/<int:order_id>",
        type="http",
        auth="user",
        website=True,
    )
    def print_laundry_receipt(self, order_id, print="0", **kwargs):
        order = request.env["pos.order"].browse(order_id).exists()
        if not order:
            return request.not_found()

        order.check_access_rights("read")
        order.check_access_rule("read")
        order._ensure_laundry_qr_token()

        report_model = request.env["report.pos_laundry_receipt.report_pos_laundry_receipt"]
        render_values = report_model._get_report_values(
            [order.id],
            data={
                "auto_print": str(print).lower() in ("1", "true", "yes"),
                "is_pdf": False,
            },
        )

        if str(kwargs.get("download", "0")).lower() in ("1", "true", "yes"):
            pdf, _ = request.env["ir.actions.report"].with_context(
                force_report_rendering=True,
                is_pdf=True,
            )._render_qweb_pdf(
                "pos_laundry_receipt.action_report_pos_laundry_receipt",
                [order.id],
                data={"is_pdf": True},
            )

            filename = "%s %s.pdf" % (
                _("Intake Receipt"),
                order.x_display_reference or order.name or order.id,
            )

            return request.make_response(
                pdf,
                [
                    ("Content-Type", "application/pdf"),
                    ("Content-Disposition", content_disposition(filename)),
                ],
            )

        return request.render("pos_laundry_receipt.report_pos_laundry_receipt", render_values)

    @http.route(
        "/pos_laundry_receipt/labels/batch/<int:wizard_id>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def render_laundry_label_batch(
        self,
        wizard_id,
        token="",
        print="0",
        download="0",
        **kwargs,
    ):
        wizard = request.env["pos.laundry.label.print.wizard"].browse(wizard_id).exists()
        if (
            not wizard
            or not token
            or token != wizard.access_token
            or wizard.user_id != request.env.user
        ):
            return request.not_found()

        labels = wizard.label_ids.exists()
        if not labels:
            return request.not_found()
        labels._check_print_access()

        auto_print = str(print).lower() in ("1", "true", "yes")
        is_download = str(download).lower() in ("1", "true", "yes")
        report_ref = "pos_laundry_receipt.action_report_laundry_label_thermal"
        batch_reference = uuid.uuid4().hex
        report_service = request.env["ir.actions.report"].with_context(
            force_report_rendering=True
        )

        try:
            if is_download:
                content, _ = report_service._render_qweb_pdf(
                    report_ref,
                    labels.ids,
                    data={"auto_print": False},
                )
                filename = _("Laundry Labels Epson POS.pdf")
                return request.make_response(
                    content,
                    [
                        ("Content-Type", "application/pdf"),
                        ("Content-Disposition", content_disposition(filename)),
                    ],
                )

            content, _ = report_service._render_qweb_html(
                    report_ref,
                    labels.ids,
                    data={"auto_print": auto_print},
                )
            if auto_print:
                labels._record_print_success(
                    CANONICAL_LABEL_FORMAT,
                    batch_reference,
                )
            return request.make_response(
                content,
                [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Cache-Control", "no-store"),
                ],
            )
        except (AccessError, UserError):
            raise
        except Exception as error:
            _logger.exception(
                "Unable to render laundry label batch %s",
                wizard.id,
            )
            if auto_print:
                labels._record_print_failure(
                    CANONICAL_LABEL_FORMAT,
                    str(error),
                    batch_reference,
                )
            response = request.render(
                "pos_laundry_receipt.laundry_label_print_error",
                {
                    "title": _("Laundry label printing failed"),
                    "message": _(
                        "The labels remain in the print queue. Correct the printer or "
                        "report issue and try again."
                    ),
                },
            )
            response.status_code = 500
            return response

    def _get_scanned_order(self, token):
        if not request.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("You are not allowed to scan laundry labels."))
        order = request.env["pos.order"].search(
            [
                ("x_qr_token", "=", token),
                ("state", "!=", "cancel"),
            ],
            limit=1,
        )
        if not order:
            return order
        order.check_access_rights("read")
        order.check_access_rule("read")
        return order

    def _get_scan_page_values(self, order, message=None, error=None):
        status = order.x_laundry_status
        next_status = order._get_next_laundry_scan_status(status)
        can_advance = bool(next_status)
        blocker = ""
        if next_status == "delivered" and order._get_laundry_payment_status() != "paid":
            can_advance = False
            blocker = order._get_laundry_delivery_payment_required_message()
        language = request.env.context.get("lang") or request.env.user.lang or "en_US"
        intake = order.x_laundry_intake_id
        return {
            "title": _("Laundry Order %(reference)s", reference=order._get_laundry_reference()),
            "order": order,
            "reference": order._get_laundry_reference(),
            "customer": order.partner_id.name or _("Walk-in Customer"),
            "status": order._get_laundry_status_text(status)["label"],
            "payment_status": order._get_payment_status_label(
                order._get_laundry_payment_status()
            ),
            "received_date": tools.format_datetime(
                request.env,
                order.date_order,
                tz=request.env.user.tz,
                dt_format="short",
            ) if order.date_order else False,
            "expected_delivery_date": tools.format_datetime(
                request.env,
                intake.delivery_date,
                tz=request.env.user.tz,
                dt_format="short",
            ) if intake and intake.delivery_date else False,
            "item_preview": order._get_laundry_item_preview(limit=5),
            "next_status": next_status,
            "next_status_label": (
                order._get_laundry_status_text(next_status)["label"]
                if next_status
                else ""
            ),
            "next_action_label": (
                order._get_laundry_status_action_label(status, next_status)
                if next_status
                else ""
            ),
            "can_advance": can_advance,
            "blocker": blocker,
            "message": message,
            "error": error,
            "token": order.x_qr_token,
            "direction": (
                "rtl"
                if language.split("_", 1)[0].lower() in {"ar", "fa", "he", "ur"}
                else "ltr"
            ),
            "company": order.company_id,
        }

    @http.route(
        "/pos_laundry_receipt/scan/<string:token>",
        type="http",
        auth="user",
        methods=["GET"],
    )
    def open_laundry_scan(self, token, **kwargs):
        order = self._get_scanned_order(token)
        if not order:
            return request.not_found()
        return request.render(
            "pos_laundry_receipt.laundry_label_scan_page",
            self._get_scan_page_values(order),
        )

    @http.route(
        "/pos_laundry_receipt/scan/<string:token>/advance",
        type="http",
        auth="user",
        methods=["POST"],
    )
    def advance_laundry_scan(self, token, **kwargs):
        order = self._get_scanned_order(token)
        if not order:
            return request.not_found()
        try:
            order.check_access_rights("write")
            order.check_access_rule("write")
            next_status = order._get_next_laundry_scan_status(order.x_laundry_status)
            if not next_status:
                raise UserError(_("This order has no remaining workflow stage."))
            previous_label = order._get_laundry_status_text(order.x_laundry_status)["label"]
            order._set_laundry_status(next_status)
            message = _(
                "Order moved from %(previous)s to %(current)s.",
                previous=previous_label,
                current=order._get_laundry_status_text(next_status)["label"],
            )
            values = self._get_scan_page_values(order, message=message)
        except (AccessError, UserError) as error:
            values = self._get_scan_page_values(order, error=str(error))
        return request.render(
            "pos_laundry_receipt.laundry_label_scan_page",
            values,
        )
