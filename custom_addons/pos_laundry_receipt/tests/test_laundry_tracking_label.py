from odoo import Command, fields
from odoo.api import call_kw
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLaundryTrackingLabel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ar_lang = cls.env["res.lang"]._activate_lang("ar_001")
        if not ar_lang:
            ar_lang = cls.env["res.lang"]._create_lang("ar_001", "Arabic")
        cls.env["base.language.install"].create(
            {
                "lang_ids": [Command.set(ar_lang.ids)],
                "overwrite": True,
            }
        ).lang_install()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Laundry Label Test Customer"}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Laundry shirt",
                "available_in_pos": True,
                "list_price": 10.0,
                "taxes_id": [Command.clear()],
            }
        )
        cls.pos_config = cls.env["pos.config"].create(
            {"name": "Laundry Label Test POS"}
        )
        cls.session = cls.env["pos.session"].create(
            {"config_id": cls.pos_config.id}
        )
        cls.order = cls.env["pos.order"].create(
            {
                "company_id": cls.env.company.id,
                "session_id": cls.session.id,
                "partner_id": cls.partner.id,
                "pricelist_id": cls.partner.property_product_pricelist.id,
                "lines": [
                    Command.create(
                        {
                            "name": "Laundry shirt",
                            "product_id": cls.product.id,
                            "price_unit": 10.0,
                            "qty": 2.0,
                            "price_subtotal": 20.0,
                            "price_subtotal_incl": 20.0,
                        }
                    )
                ],
                "amount_total": 20.0,
                "amount_tax": 0.0,
                "amount_paid": 20.0,
                "amount_return": 0.0,
                "last_order_preparation_change": "{}",
            }
        )

    def test_label_is_persisted_and_unique(self):
        self.assertEqual(len(self.order.x_laundry_label_ids), 1)
        self.assertEqual(self.order.x_laundry_label_ids.state, "pending")
        self.order._ensure_laundry_labels()
        self.assertEqual(len(self.order.x_laundry_label_ids), 1)

    def test_workflow_only_allows_next_stage(self):
        with self.assertRaises(UserError):
            self.order.write({"x_laundry_status": "delivered"})
        self.order.action_mark_ready()
        self.assertEqual(self.order.x_laundry_status, "ready")
        with self.assertRaises(UserError):
            self.order.write({"x_laundry_status": "received"})
        self.order.action_mark_delivered()
        self.assertEqual(self.order.x_laundry_status, "delivered")
        histories = self.order.x_laundry_status_history_ids.sorted("id")
        self.assertEqual(histories.mapped("new_status"), ["received", "ready", "delivered"])
        self.assertTrue(histories[0].exited_on)

    def test_qr_url_resolves_and_advances_once(self):
        qr_url = self.order._build_laundry_qr_payload()
        self.assertIn("/pos_laundry_receipt/scan/", qr_url)
        parsed = self.env["pos.order"]._parse_laundry_qr_value(qr_url)
        self.assertEqual(parsed["payload_type"], "url")
        self.assertEqual(parsed["token"], self.order.x_qr_token)
        response = self.env["pos.order"].process_laundry_qr_scan(qr_url)
        self.assertTrue(response["success"])
        self.assertEqual(self.order.x_laundry_status, "ready")

    def test_plain_reference_still_resolves_the_exact_order(self):
        reference = self.order._get_laundry_reference()
        response = self.env["pos.order"].process_laundry_qr_scan(reference)
        self.assertTrue(response["success"])
        self.assertEqual(response["order"]["id"], self.order.id)

    def test_pos_order_fields_normalizes_partner_array_payload(self):
        vals = self.env["pos.order"]._order_fields(
            {
                "user_id": self.env.user.id,
                "pos_session_id": self.session.id,
                "lines": [],
                "name": "TEST/PARTNER/ARRAY",
                "sequence_number": 999,
                "partner_id": [self.partner.id, self.partner.name],
                "date_order": fields.Datetime.now().isoformat(),
                "fiscal_position_id": False,
                "pricelist_id": [self.partner.property_product_pricelist.id],
                "amount_paid": 0.0,
                "amount_total": 0.0,
                "amount_tax": 0.0,
                "amount_return": 0.0,
            }
        )
        self.assertEqual(vals["partner_id"], self.partner.id)
        self.assertEqual(
            vals["pricelist_id"],
            self.partner.property_product_pricelist.id,
        )

    def test_print_history_and_failed_retry_queue(self):
        label = self.order.x_laundry_label_ids
        label._record_print_success(batch_reference="TEST-1")
        self.assertEqual(label.state, "printed")
        self.assertEqual(label.last_format, "epson_pos")
        label._record_print_success(batch_reference="TEST-2")
        self.assertEqual(label.state, "reprinted")
        label._record_print_failure(error_message="simulated", batch_reference="TEST-3")
        self.assertEqual(label.state, "failed")
        self.assertTrue(label.is_pending)
        label._record_print_success(batch_reference="TEST-4")
        self.assertEqual(label.state, "reprinted")
        self.assertFalse(label.is_pending)
        self.assertEqual(len(label.history_ids), 4)
        self.assertEqual(set(label.history_ids.mapped("label_format")), {"epson_pos"})

    def test_print_wizard_has_no_format_selector(self):
        wizard = self.env["pos.laundry.label.print.wizard"].create(
            {"label_ids": [Command.set(self.order.x_laundry_label_ids.ids)]}
        )
        self.assertNotIn("label_format", wizard._fields)

    def test_print_all_pending_header_button_opens_wizard(self):
        action = call_kw(
            self.env["pos.laundry.label"],
            "action_open_all_pending_wizard",
            [[]],
            {},
        )
        self.assertEqual(action["res_model"], "pos.laundry.label.print.wizard")
        wizard = self.env["pos.laundry.label.print.wizard"].browse(action["res_id"])
        self.assertIn(self.order.x_laundry_label_ids, wizard.label_ids)

    def test_print_action_uses_process_epson_printer(self):
        printer = self.env["pos.printer"].create(
            {
                "name": "process",
                "printer_type": "epson_epos",
                "epson_printer_ip": "127.0.0.1",
            }
        )
        action = self.order.x_laundry_label_ids.action_print()
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "pos_laundry_receipt.print_laundry_labels")
        self.assertEqual(action["params"]["printer"]["id"], printer.id)
        self.assertEqual(action["params"]["printer"]["ip"], "127.0.0.1")
        self.assertIn("/pos_laundry_receipt/labels/batch/", action["params"]["html_url"])
        self.assertIn("print=0", action["params"]["html_url"])

    def test_label_currency_text_is_forced_to_sr(self):
        report = self.env[
            "report.pos_laundry_receipt.report_laundry_label_thermal"
        ]
        self.assertEqual(report._normalize_currency_text("Addon 5 ر.س"), "Addon 5 SR")
        self.assertEqual(report._normalize_currency_text("Addon 5 SAR"), "Addon 5 SR")
        self.assertEqual(report._format_amount(20, self.order.currency_id), "20.00\u00a0SR")

    def test_report_is_localized_and_rtl_aware(self):
        label = self.order.x_laundry_label_ids
        report = self.env["ir.actions.report"]
        english, _ = report.with_context(lang="en_US")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        arabic, _ = report.with_context(lang="ar_001")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        self.assertIn(b'dir="ltr"', english)
        self.assertIn(b'dir="rtl"', arabic)
        self.assertIn(b"80mm auto", english)
        self.assertIn(b"width=260", english)
        self.assertIn(b"Laundry Order", english)
        self.assertIn(b"SR", english)
        self.assertNotIn(b"Code128", english)
        self.assertNotIn(b"laundry-label-barcode", english)
        self.assertNotIn(b"barcode_url", english)
        self.assertNotIn(b"Expected", english)
        self.assertIn(b"Priority", english)
        self.assertIn(b"Normal", english)
        self.assertNotIn("طلب الغسيل".encode(), english)
        self.assertNotIn("المتوقع".encode(), arabic)
        self.assertNotIn("ر.س".encode(), arabic)
        self.assertNotIn(b"PHONE", arabic)
        self.assertNotIn(b"Phone", arabic)
        self.assertNotIn(b"Code128", arabic)
        self.assertNotIn(b"laundry-label-barcode", arabic)
        self.assertIn("الأولوية".encode(), arabic)
        self.assertIn("عادي".encode(), arabic)
        self.assertIn("طلب الغسيل".encode(), arabic)
        self.assertIn("الهاتف".encode(), arabic)
        self.assertIn(b"SR", arabic)
        self.assertNotIn(b"Laundry Order", arabic)
        self.assertIn(
            "امسح الرمز للانتقال إلى المرحلة التالية".encode(),
            arabic,
        )
        self.assertNotIn(b"Scan to update the next stage", arabic)

    def test_report_uses_linked_laundry_order_priority_when_available(self):
        if (
            "laundry_order_id" not in self.order._fields
            or "laundry.order" not in self.env
        ):
            self.assertEqual(
                self.env[
                    "report.pos_laundry_receipt.report_laundry_label_thermal"
                ]._get_order_priority_payload(self.order),
                {"key": "normal", "label": "Normal"},
            )
            return

        branch = self.env["laundry.branch"].create(
            {
                "name": "Laundry Label Test Branch",
                "code": "LLT",
            }
        )
        laundry_order = self.env["laundry.order"].create(
            {
                "partner_id": self.partner.id,
                "branch_id": branch.id,
                "company_id": self.env.company.id,
                "pos_order_id": self.order.id,
                "priority": "urgent",
                "promise_date": fields.Datetime.now(),
                "user_id": self.env.uid,
            }
        )
        self.order.write({"laundry_order_id": laundry_order.id})
        label = self.order.x_laundry_label_ids
        report = self.env["ir.actions.report"]
        english, _ = report.with_context(lang="en_US")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        arabic, _ = report.with_context(lang="ar_001")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        self.assertIn(b"Priority", english)
        self.assertIn(b"Urgent", english)
        self.assertIn("الأولوية".encode(), arabic)
        self.assertIn("عاجل".encode(), arabic)
        self.assertNotIn(b"Priority", arabic)
        self.assertNotIn(b"Urgent", arabic)

        laundry_order.write({"priority": "normal"})
        english, _ = report.with_context(lang="en_US")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        arabic, _ = report.with_context(lang="ar_001")._render_qweb_html(
            "pos_laundry_receipt.action_report_laundry_label_thermal",
            label.ids,
            data={"auto_print": False},
        )
        self.assertIn(b"Normal", english)
        self.assertIn("عادي".encode(), arabic)
        self.assertNotIn(b"Normal", arabic)
