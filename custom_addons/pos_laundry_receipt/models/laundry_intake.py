import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

LAUNDRY_PRIORITY_SELECTION = [
    ("normal", "Normal"),
    ("urgent", "Urgent"),
]


class PosLaundryIntake(models.Model):
    _name = "pos.laundry.intake"
    _description = "POS Laundry Intake"
    _order = "id desc"

    name = fields.Char(string="Intake Reference", required=True, copy=False, default="New")
    partner_id = fields.Many2one("res.partner", string="Customer")
    partner_name = fields.Char(string="Customer Name")
    phone = fields.Char(string="Phone")
    pickup_date = fields.Datetime(string="Intake Date", default=fields.Datetime.now)
    delivery_date = fields.Datetime(string="Delivery Date")
    priority = fields.Selection(
        selection=LAUNDRY_PRIORITY_SELECTION,
        string="Priority",
        default="normal",
        copy=False,
        index=True,
    )
    note = fields.Text(string="Notes")
    amount_total = fields.Float(string="Total")
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id.id,
        required=True,
    )
    pos_config_id = fields.Many2one("pos.config", string="Point of Sale")
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company.id,
        required=True,
    )
    line_ids = fields.One2many("pos.laundry.intake.line", "intake_id", string="Items")
    state = fields.Selection(
        [
            ("received", "Received"),
            ("ready", "Ready"),
            ("delivered", "Delivered"),
        ],
        default="received",
        string="Status",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("pos_config_id") and not vals.get("company_id"):
                config = self.env["pos.config"].browse(vals["pos_config_id"]).exists()
                if config:
                    vals["company_id"] = config.company_id.id
            if vals.get("state", "received") != "received":
                raise UserError(
                    _("New laundry intakes must start in the Received stage.")
                )
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("pos.laundry.intake")
                    or "New"
                )
        return super().create(vals_list)

    def write(self, vals):
        if "priority" in vals and not self.env.context.get("laundry_initial_intake_sync"):
            linked_orders = self.env["pos.order"].sudo().search(
                [("x_laundry_intake_id", "in", self.ids)],
                limit=1,
            )
            if linked_orders:
                raise UserError(
                    _(
                        "Laundry priority is locked after intake because it "
                        "is part of the historical SLA snapshot."
                    )
                )
        if "state" in vals:
            target = vals["state"]
            next_state = {"received": "ready", "ready": "delivered"}
            if target not in ("received", "ready", "delivered"):
                raise UserError(_("Invalid laundry status."))
            for intake in self:
                if intake.state != target and next_state.get(intake.state) != target:
                    raise UserError(
                        _(
                            "Laundry intakes can only move from Received to Ready to Delivered."
                        )
                    )
        return super().write(vals)


class PosLaundryIntakeLine(models.Model):
    _name = "pos.laundry.intake.line"
    _description = "POS Laundry Intake Line"

    intake_id = fields.Many2one(
        "pos.laundry.intake",
        string="Intake",
        required=True,
        ondelete="cascade",
    )
    product_id = fields.Many2one("product.product", string="Item")
    product_name = fields.Char(string="Description", required=True)
    selection_details = fields.Text(string="Service Details")
    qty = fields.Float(string="Quantity", default=1.0)
    price_unit = fields.Float(string="Unit Price", default=0.0)
    price_subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
    )

    @api.depends("qty", "price_unit")
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = (line.qty or 0.0) * (line.price_unit or 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# PosOrder inherit
# ─────────────────────────────────────────────────────────────────────────────

class PosOrder(models.Model):
    """
    Inherits pos.order to:

    1. Carry the laundry-intake link through the full order lifecycle.
    2. Override _process_order so that when a finalized (non-draft) order is
       created and it carries a laundry_intake_id in its JSON payload, the
       link is written to the new pos.order record immediately — without
       any ambiguous retroactive search.
    3. Provide mark_as_cancelled helper so the JS layer can cleanly cancel
       a phantom draft before creating the payment copy.
    """

    _inherit = "pos.order"
    
    @api.model_create_multi
    def create(self, vals_list):
        """
        Force sequence assignment even for draft POS orders.

        Odoo normally leaves draft orders with name="/"
        until finalization. For the laundry workflow we need
        draft orders to immediately receive a real sequence.
        """

        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("pos.laundry.intake") or "/"
                )

        return super().create(vals_list)

    def _compute_order_name(self):
        """
        Override to use the LND sequence for POS order names.
        Ensures consistency whether the order is created as draft or paid directly.
        """
        if len(self.refunded_order_ids) != 0:
            return ','.join(self.refunded_order_ids.mapped('name')) + _(' REFUND')
        return self.env["ir.sequence"].next_by_code("pos.laundry.intake") or "/"

    def _process_order(self, order, draft, existing_order):
        """
        Called by create_from_ui for every non-draft order finalization.

        The standard flow:
          create_from_ui(orders, draft=False)
              └─ _process_order(order_dict, draft=False, existing_order)
                     └─ create() or write()    ← sequence assigned HERE for new records

        We intercept after the parent call to link the laundry intake when:
          - the order is being finalized (draft=False)
          - the frontend has passed laundry_intake_id in the JSON payload
          - the newly created pos.order does not yet have the link set
        """
        order_id = super()._process_order(order, draft, existing_order)

        if not draft and order_id:
            order_data = order.get("data", {})
            intake_id = order_data.get("laundry_intake_id")
            processed_order = self.env["pos.order"].browse(order_id)

            if processed_order.name and processed_order.name.startswith("Shop/"):
                processed_order.name = (
                    self.env["ir.sequence"].next_by_code("pos.laundry.intake")
                    or processed_order.name
                )

            if intake_id:
                if processed_order.exists() and not processed_order.x_laundry_intake_id:
                    intake = self.env["pos.laundry.intake"].browse(intake_id)
                    if intake.exists():
                        processed_order.with_context(
                            laundry_initial_intake_sync=True
                        ).write({
                            "x_laundry_intake_id": intake.id,
                            "x_laundry_priority": intake.priority,
                        })

            if processed_order.exists() and processed_order.x_laundry_intake_id:
                intake = processed_order.x_laundry_intake_id
                if intake.state == "received":
                    intake.write({"state": "ready"})

        return order_id

    @api.model
    def cancel_draft_order(self, order_id):
        """
        Safely cancel a draft order that will be superseded by a payment copy.

        Called from the JS payOrder() fallback path when load_server_orders()
        is unavailable and we need to prevent two live records for the same job.

        Returns True on success, False if the order doesn't exist or is already
        past the draft stage.
        """
        if not order_id:
            return False

        order = self.browse(order_id)
        if not order.exists():
            return False

        if order.state not in ("draft", "new"):
            # Already paid / cancelled — do not touch
            return False

        order.write({"state": "cancel"})
        return True


# ─────────────────────────────────────────────────────────────────────────────
# PosSession
# ─────────────────────────────────────────────────────────────────────────────

class PosSession(models.Model):
    _inherit = "pos.session"

    # ── Primary entry-point called from frontend ──────────────────────────────

    @api.model
    def create_laundry_intake_from_ui(self, payload):
        """
        Create a pos.laundry.intake record from the POS frontend.

        KEY DESIGN POINTS
        ─────────────────
        • The frontend MUST push the current order to the backend (draft=True)
          BEFORE calling this method so that the pos.order record already
          exists in the DB with its pos_reference populated.

        • We search for the order by pos_reference (the unique frontend uid).
          This is always unambiguous — unlike searching by name='/' which
          matches every un-sequenced draft.

        • If the order is not yet in the DB (network race, etc.) we create the
          intake anyway and return its id.  The frontend can call
          finalize_laundry_order_link() after a successful push, or the
          _process_order override will handle it at payment time.
        """
        if isinstance(payload, list):
            payload = payload[0] if payload else {}

        # ── Partner resolution ────────────────────────────────────────────────
        partner = (
            self.env["res.partner"].browse(payload["partner_id"])
            if payload.get("partner_id")
            else self.env["res.partner"]
        )

        # ── Delivery date normalisation ───────────────────────────────────────
        delivery_date = payload.get("delivery_date") or False
        if delivery_date:
            delivery_date = delivery_date.replace("T", " ")
            if len(delivery_date) == 16:
                delivery_date += ":00"
        priority = payload.get("priority") or "normal"
        if priority not in dict(LAUNDRY_PRIORITY_SELECTION):
            priority = "normal"

        # ── Attempt immediate order lookup ────────────────────────────────────
        # We search by pos_reference because it is the unique frontend UID.
        # The draft order should already exist because the frontend pushes it
        # before calling this method.
        pos_reference = payload.get("pos_reference")
        pos_order = None

        if pos_reference:
            pos_order = self.env["pos.order"].search(
                [("pos_reference", "=", pos_reference)],
                limit=1,
            )
            if pos_order:
                _logger.info(
                    "create_laundry_intake_from_ui: matched existing pos.order %s for pos_reference=%s",
                    pos_order.name,
                    pos_reference,
                )

        if not pos_order and payload.get("server_id"):
            pos_order = self.env["pos.order"].browse(payload["server_id"])
            if pos_order.exists():
                _logger.info(
                    "create_laundry_intake_from_ui: matched existing pos.order %s for server_id=%s",
                    pos_order.name,
                    payload["server_id"],
                )

        # ── Build intake vals ─────────────────────────────────────────────────
        intake_vals = {
            # Use the saved POS order reference when the backend already has the order.
            "name": pos_order.name if pos_order else payload.get("order_name") or payload.get("pos_reference") or "New",
            "partner_id": partner.id if partner else False,
            "partner_name": (
                partner.name if partner else (payload.get("partner_name") or _("Walk-in Customer"))
            ),
            "phone": partner.mobile or partner.phone or payload.get("phone") or "",
            "delivery_date": delivery_date,
            "priority": priority,
            "note": payload.get("note") or "",
            "amount_total": payload.get("amount_total") or 0.0,
            "pos_config_id": payload.get("pos_config_id") or False,
            "line_ids": [],
        }

        for line in payload.get("lines", []):
            detail_lines = [
                str(detail).strip()
                for detail in (line.get("detail_lines") or [])
                if str(detail).strip()
            ]
            intake_vals["line_ids"].append(
                (
                    0,
                    0,
                    {
                        "product_id": line.get("product_id") or False,
                        "product_name": line.get("product_name") or "Item",
                        "selection_details": "\n".join(detail_lines),
                        "qty": line.get("qty") or 0.0,
                        "price_unit": line.get("price_unit") or 0.0,
                    },
                )
            )

        intake = self.env["pos.laundry.intake"].create(intake_vals)

        _logger.info(
            "create_laundry_intake_from_ui: created intake %s for pos_reference=%s order_name=%s",
            intake.name,
            pos_reference,
            pos_order.name if pos_order else None,
        )

        # Ensure the intake uses the canonical order reference when we already
        # matched the backend POS order. This prevents the frontend's predicted
        # draft order name from leaking into the printed receipt.
        if pos_order and intake.name != pos_order.name:
            intake.write({"name": pos_order.name})

        # ── Link intake to pos.order ──────────────────────────────────────────
        if pos_order:
            pos_order.with_context(laundry_initial_intake_sync=True).write({
                "x_laundry_intake_id": intake.id,
                "x_laundry_priority": intake.priority,
            })
            pos_order._ensure_laundry_qr_token()

        qr_value = intake.name
        qr_barcode_url = "/report/barcode/?barcode_type=QR&width=220&height=220&value=%s" % intake.name
        if pos_order:
            qr_value = pos_order._build_laundry_qr_payload()
            qr_barcode_url = pos_order._get_laundry_qr_barcode_url()

        # ── Return full receipt payload ───────────────────────────────────────
        return {
            "id": intake.id,
            "name": intake.name,
            "pos_order_id": pos_order.id if pos_order else False,
            "x_display_reference": pos_order.name if pos_order else intake.name,
            "partner_name": intake.partner_name or "",
            "phone": intake.phone or "",
            "pickup_date": (
                intake.pickup_date
                and fields.Datetime.to_string(intake.pickup_date)
                or ""
            ),
            "delivery_date": (
                intake.delivery_date
                and fields.Datetime.to_string(intake.delivery_date)
                or ""
            ),
            "priority": intake.priority,
            "note": intake.note or "",
            "amount_total": intake.amount_total,
            "currency_symbol": intake.currency_id.symbol or "",
            "qr_value": qr_value,
            "qr_barcode_url": qr_barcode_url,
            "qr_reference": pos_order.name if pos_order else intake.name,
            "pos_reference": pos_order.pos_reference if pos_order else (pos_reference or ""),
            "x_qr_token": pos_order.x_qr_token if pos_order else "",
            "lines": [
                {
                    "product_name": l.product_name,
                    "selection_details": l.selection_details or "",
                    "detail_lines": [
                        detail.strip()
                        for detail in (l.selection_details or "").splitlines()
                        if detail.strip()
                    ],
                    "qty": l.qty,
                    "price_unit": l.price_unit,
                    "price_subtotal": l.price_subtotal,
                }
                for l in intake.line_ids
            ],
        }

    # ── Deferred link (called after order push when immediate link failed) ────

    @api.model
    def finalize_laundry_order_link(self, pos_reference, intake_id):
        """
        Explicitly link a pos.order to a pos.laundry.intake by pos_reference.

        Called from the frontend after a successful draft push in the rare case
        where create_laundry_intake_from_ui could not find the order (network
        race / slow sync).

        Returns True when the link was written, False otherwise.
        """
        if not pos_reference or not intake_id:
            return False

        pos_order = self.env["pos.order"].search(
            [("pos_reference", "=", pos_reference)],
            limit=1,
        )

        if not pos_order:
            pos_order = self.env["pos.order"].search(
                [
                    ("name", "=", pos_reference),
                    ("state", "in", ("draft", "new")),
                ],
                limit=1,
            )

        if not pos_order:
            return False

        intake = self.env["pos.laundry.intake"].browse(intake_id)
        if not intake.exists():
            return False

        if intake.name != pos_order.name:
            _logger.info(
                "finalize_laundry_order_link: aligning intake.name %s -> pos.order.name %s",
                intake.name,
                pos_order.name,
            )
            intake.write({"name": pos_order.name})

        pos_order.with_context(laundry_initial_intake_sync=True).write({
            "x_laundry_intake_id": intake.id,
            "x_laundry_priority": intake.priority,
        })
        pos_order._ensure_laundry_qr_token()
        return True

    # ── Status transition helper ──────────────────────────────────────────────

    @api.model
    def mark_laundry_order_paid(self, original_order_id):
        """
        Transition the linked laundry intake to 'ready' when the original
        draft order is being paid.

        Called by the JS payOrder() flow when it successfully loads the
        original order via load_server_orders() and sends it to PaymentScreen.
        """
        if not original_order_id:
            return False

        pos_order = self.env["pos.order"].browse(original_order_id)
        if pos_order.exists() and pos_order.x_laundry_intake_id:
            intake = pos_order.x_laundry_intake_id
            if intake.state == "received":
                intake.write({"state": "ready"})

        return True
