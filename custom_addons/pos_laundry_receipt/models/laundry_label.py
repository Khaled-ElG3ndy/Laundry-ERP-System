import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError


CANONICAL_LABEL_FORMAT = "epson_pos"
DIRECT_LABEL_PRINTER_NAME = "process"

LABEL_FORMAT_SELECTION = [
    (CANONICAL_LABEL_FORMAT, "Epson POS Printer — 80 mm Roll"),
    ("thermal", "Legacy Thermal 80 × 60 mm"),
    ("a4", "Legacy Epson A4 Sticker Sheet (2 × 5)"),
]

LABEL_STATE_SELECTION = [
    ("pending", "Pending"),
    ("printed", "Printed"),
    ("reprinted", "Reprinted"),
    ("failed", "Print Failed"),
]

PRINT_RESULT_SELECTION = [
    ("printed", "Printed"),
    ("reprinted", "Reprinted"),
    ("failed", "Print Failed"),
]


class PosLaundryLabel(models.Model):
    _name = "pos.laundry.label"
    _description = "Laundry Tracking Label"
    _order = "is_pending desc, received_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Label Reference",
        compute="_compute_name",
        store=True,
        index=True,
    )
    order_id = fields.Many2one(
        "pos.order",
        string="Laundry Order",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="order_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        related="order_id.partner_id",
        store=True,
        readonly=True,
        index=True,
    )
    laundry_status = fields.Selection(
        related="order_id.x_laundry_status",
        string="Laundry Status",
        store=True,
        readonly=True,
        index=True,
    )
    payment_status = fields.Selection(
        related="order_id.x_payment_status",
        string="Payment Status",
        store=True,
        readonly=True,
        index=True,
    )
    received_date = fields.Datetime(
        string="Received Date",
        related="order_id.date_order",
        store=True,
        readonly=True,
        index=True,
    )
    expected_delivery_date = fields.Datetime(
        string="Expected Delivery Date",
        compute="_compute_order_summary",
        store=True,
    )
    total_items = fields.Float(
        string="Total Items",
        compute="_compute_order_summary",
        store=True,
    )
    state = fields.Selection(
        selection=LABEL_STATE_SELECTION,
        string="Print Status",
        default="pending",
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    is_pending = fields.Boolean(
        string="Awaiting Successful Print",
        compute="_compute_is_pending",
        store=True,
        index=True,
    )
    print_count = fields.Integer(string="Successful Prints", readonly=True, copy=False)
    failed_count = fields.Integer(string="Failed Attempts", readonly=True, copy=False)
    last_printed_on = fields.Datetime(string="Last Printed On", readonly=True, copy=False)
    last_printed_by_id = fields.Many2one(
        "res.users",
        string="Last Printed By",
        readonly=True,
        copy=False,
    )
    last_format = fields.Selection(
        LABEL_FORMAT_SELECTION,
        string="Last Format",
        readonly=True,
        copy=False,
    )
    last_error = fields.Text(string="Last Print Error", readonly=True, copy=False)
    history_ids = fields.One2many(
        "pos.laundry.label.print.history",
        "label_id",
        string="Print History",
        readonly=True,
    )

    _sql_constraints = [
        (
            "order_unique",
            "UNIQUE(order_id)",
            "A laundry order can only have one tracking label.",
        ),
    ]

    @api.depends("order_id.x_display_reference", "order_id.name")
    def _compute_name(self):
        for label in self:
            label.name = (
                label.order_id.x_display_reference
                or label.order_id.name
                or _("Laundry Label")
            )

    @api.depends("state")
    def _compute_is_pending(self):
        for label in self:
            label.is_pending = label.state in ("pending", "failed")

    @api.depends(
        "order_id.x_laundry_intake_id.delivery_date",
        "order_id.x_laundry_intake_id.line_ids.qty",
        "order_id.lines.qty",
    )
    def _compute_order_summary(self):
        for label in self:
            intake = label.order_id.x_laundry_intake_id
            label.expected_delivery_date = intake.delivery_date if intake else False
            lines = intake.line_ids if intake else label.order_id.lines
            label.total_items = sum(lines.mapped("qty"))

    def _check_print_access(self):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise UserError(_("You are not allowed to print laundry labels."))
        self.check_access_rights("read")
        self.check_access_rule("read")

    def _open_print_wizard(self):
        labels = self.exists()
        if not labels:
            raise UserError(_("Select at least one label to continue."))
        labels._check_print_access()
        wizard = self.env["pos.laundry.label.print.wizard"].create(
            {"label_ids": [(6, 0, labels.ids)]}
        )
        action = self.env.ref(
            "pos_laundry_receipt.action_pos_laundry_label_print_wizard"
        ).read()[0]
        action.update({"res_id": wizard.id, "target": "new"})
        return action

    def action_open_print_wizard(self):
        return self._open_print_wizard()

    @api.model
    def action_open_all_pending_wizard(self, *args, **kwargs):
        labels = self.search([("is_pending", "=", True)])
        if not labels:
            raise UserError(_("There are no pending labels to print."))
        return labels._open_print_wizard()

    def action_preview(self):
        self.ensure_one()
        wizard = self.env["pos.laundry.label.print.wizard"].create(
            {"label_ids": [(6, 0, self.ids)]}
        )
        return wizard.action_preview()

    def action_print(self):
        self.ensure_one()
        wizard = self.env["pos.laundry.label.print.wizard"].create(
            {"label_ids": [(6, 0, self.ids)]}
        )
        return self._get_direct_print_action(wizard=wizard)

    def action_reprint(self):
        self.ensure_one()
        return self.action_print()

    def _get_direct_print_printer(self):
        printer_model = self.env["pos.printer"].sudo()
        if "epson_printer_ip" not in printer_model._fields:
            raise UserError(
                _("Install the POS Epson Printer module before direct label printing.")
            )

        printer = printer_model.search(
            [("name", "=ilike", DIRECT_LABEL_PRINTER_NAME)],
            limit=1,
        )
        if not printer:
            raise UserError(
                _("Could not find a POS printer named '%s'.")
                % DIRECT_LABEL_PRINTER_NAME
            )
        if printer.printer_type != "epson_epos":
            raise UserError(
                _("Printer '%s' must use the Epson printer type.") % printer.name
            )
        if not printer.epson_printer_ip or printer.epson_printer_ip == "0.0.0.0":
            raise UserError(
                _("Printer '%s' does not have a valid Epson IP address.")
                % printer.name
            )
        return printer

    def _get_direct_print_action(self, wizard=None, close_on_done=False):
        labels = self.exists()
        if not labels:
            raise UserError(_("Select at least one label to continue."))
        labels._check_print_access()
        printer = labels._get_direct_print_printer()
        wizard = wizard or self.env["pos.laundry.label.print.wizard"].create(
            {"label_ids": [(6, 0, labels.ids)]}
        )
        return {
            "type": "ir.actions.client",
            "tag": "pos_laundry_receipt.print_laundry_labels",
            "name": _("Print Laundry Labels"),
            "params": {
                "label_ids": labels.ids,
                "html_url": wizard._get_batch_url(auto_print=False),
                "batch_reference": uuid.uuid4().hex,
                "printer": {
                    "id": printer.id,
                    "name": printer.name,
                    "ip": printer.epson_printer_ip,
                },
                "printer_dot_width": 576,
                "close_on_done": close_on_done,
            },
        }

    @api.model
    def record_browser_print_success(self, label_ids, batch_reference=None):
        labels = self.browse([int(label_id) for label_id in (label_ids or [])]).exists()
        if not labels:
            return False
        labels._check_print_access()
        labels._record_print_success(CANONICAL_LABEL_FORMAT, batch_reference)
        return True

    @api.model
    def record_browser_print_failure(
        self,
        label_ids,
        error_message=None,
        batch_reference=None,
    ):
        labels = self.browse([int(label_id) for label_id in (label_ids or [])]).exists()
        if not labels:
            return False
        labels._check_print_access()
        labels._record_print_failure(
            CANONICAL_LABEL_FORMAT,
            error_message,
            batch_reference,
        )
        return True

    def action_view_print_history(self):
        self.ensure_one()
        action = self.env.ref(
            "pos_laundry_receipt.action_pos_laundry_label_print_history"
        ).read()[0]
        action["domain"] = [("label_id", "=", self.id)]
        action["context"] = {"default_label_id": self.id}
        return action

    def _record_print_success(self, label_format=None, batch_reference=None):
        """Record that printable output was generated successfully."""
        label_format = label_format or CANONICAL_LABEL_FORMAT
        batch_reference = batch_reference or uuid.uuid4().hex
        now = fields.Datetime.now()
        history_values = []
        for label in self.sudo():
            is_reprint = label.print_count > 0
            result = "reprinted" if is_reprint else "printed"
            copy_number = label.print_count + 1
            label.write(
                {
                    "state": result,
                    "print_count": copy_number,
                    "last_printed_on": now,
                    "last_printed_by_id": self.env.user.id,
                    "last_format": label_format,
                    "last_error": False,
                }
            )
            history_values.append(
                {
                    "label_id": label.id,
                    "order_id": label.order_id.id,
                    "company_id": label.company_id.id,
                    "result": result,
                    "printed_on": now,
                    "user_id": self.env.user.id,
                    "label_format": label_format,
                    "batch_reference": batch_reference,
                    "copy_number": copy_number,
                }
            )
        if history_values:
            self.env["pos.laundry.label.print.history"].sudo().create(history_values)
        return True

    def _record_print_failure(self, label_format=None, error_message=None, batch_reference=None):
        """Keep failed labels visible and retain a durable failure audit."""
        label_format = label_format or CANONICAL_LABEL_FORMAT
        batch_reference = batch_reference or uuid.uuid4().hex
        now = fields.Datetime.now()
        history_values = []
        safe_error = str(error_message or _("Unknown print error"))[:2000]
        for label in self.sudo():
            label.write(
                {
                    "state": "failed",
                    "failed_count": label.failed_count + 1,
                    "last_format": label_format,
                    "last_error": safe_error,
                }
            )
            history_values.append(
                {
                    "label_id": label.id,
                    "order_id": label.order_id.id,
                    "company_id": label.company_id.id,
                    "result": "failed",
                    "printed_on": now,
                    "user_id": self.env.user.id,
                    "label_format": label_format,
                    "batch_reference": batch_reference,
                    "copy_number": label.print_count + 1,
                    "error_message": safe_error,
                }
            )
        if history_values:
            self.env["pos.laundry.label.print.history"].sudo().create(history_values)
        return True


class PosLaundryLabelPrintHistory(models.Model):
    _name = "pos.laundry.label.print.history"
    _description = "Laundry Label Print History"
    _order = "printed_on desc, id desc"

    label_id = fields.Many2one(
        "pos.laundry.label",
        string="Label",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    order_id = fields.Many2one(
        "pos.order",
        string="Laundry Order",
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        readonly=True,
        index=True,
    )
    result = fields.Selection(
        PRINT_RESULT_SELECTION,
        string="Result",
        required=True,
        readonly=True,
        index=True,
    )
    printed_on = fields.Datetime(
        string="Date & Time",
        required=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        readonly=True,
    )
    label_format = fields.Selection(
        LABEL_FORMAT_SELECTION,
        string="Format",
        required=True,
        readonly=True,
    )
    batch_reference = fields.Char(string="Batch", readonly=True, index=True)
    copy_number = fields.Integer(string="Copy Number", readonly=True)
    error_message = fields.Text(string="Error", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Print history can only be created by the label service."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise UserError(_("Print history is immutable."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Print history is immutable."))
        return super().unlink()
