import json
import logging
import re
import secrets
from datetime import datetime, time, timedelta
from urllib.parse import quote, unquote, urlparse

import pytz

from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression
from odoo.tools import float_compare, float_is_zero
from odoo.tools.misc import format_date

_logger = logging.getLogger(__name__)

LAUNDRY_STATUS_SELECTION = [
    ("received", "Received"),
    ("ready", "Ready"),
    ("delivered", "Delivered"),
]

LAUNDRY_STATUS_META = {
    "received": {
        "icon": "fa-inbox",
        "color": "#2563eb",
        "surface": "#eff6ff",
        "badge": "#dbeafe",
        "sequence": 10,
    },
    "ready": {
        "icon": "fa-check-circle",
        "color": "#16a34a",
        "surface": "#f0fdf4",
        "badge": "#dcfce7",
        "sequence": 20,
    },
    "delivered": {
        "icon": "fa-truck",
        "color": "#166534",
        "surface": "#ecfdf5",
        "badge": "#d1fae5",
        "sequence": 30,
    },
}

PAYMENT_STATUS_META = {
    "unpaid": {"color": "#6b7280", "surface": "#f1f5f9"},
    "partial": {"color": "#d97706", "surface": "#fef3c7"},
    "paid": {"color": "#15803d", "surface": "#dcfce7"},
    "refunded": {"color": "#0f766e", "surface": "#ccfbf1"},
    "cancelled": {"color": "#dc2626", "surface": "#fee2e2"},
}

LAUNDRY_PRIORITY_SELECTION = [
    ("normal", "Normal"),
    ("urgent", "Urgent"),
]

LAUNDRY_PRIORITY_META = {
    "normal": {
        "icon": "fa-flag-o",
        "color": "#0f766e",
        "surface": "#ccfbf1",
        "sequence": 10,
    },
    "urgent": {
        "icon": "fa-bolt",
        "color": "#dc2626",
        "surface": "#fee2e2",
        "sequence": 20,
    },
}

LAUNDRY_SLA_STATUS_SELECTION = [
    ("on_track", "On Track"),
    ("due_soon", "Due Soon"),
    ("overdue", "Overdue"),
    ("delivered_on_time", "Delivered On Time"),
    ("delivered_late", "Delivered Late"),
]

LAUNDRY_SLA_STATUS_META = {
    "on_track": {"color": "#0f766e", "surface": "#ccfbf1", "icon": "fa-clock-o"},
    "due_soon": {"color": "#d97706", "surface": "#fef3c7", "icon": "fa-hourglass-half"},
    "overdue": {"color": "#dc2626", "surface": "#fee2e2", "icon": "fa-exclamation-triangle"},
    "delivered_on_time": {"color": "#15803d", "surface": "#dcfce7", "icon": "fa-check-circle"},
    "delivered_late": {"color": "#b91c1c", "surface": "#fee2e2", "icon": "fa-times-circle"},
}

LAUNDRY_DUE_SOON_HOURS = 4
LAUNDRY_FRIDAY_WEEKDAY = 4

DASHBOARD_LAUNDRY_STATUSES = ("received", "ready", "delivered")
POS_ORDER_BOARD_LAUNDRY_STATUSES = ("received", "ready", "delivered")
POS_ORDER_BOARD_PAYMENT_STATUSES = ("unpaid", "partial", "paid", "refunded", "cancelled")
PENDING_BOARD_LAUNDRY_STATUSES = ("received", "ready")
LEGACY_LAUNDRY_STATUS_MAP = {
    "washing": "received",
    "ironing": "received",
}
PENDING_BOARD_STATUS_TRANSITIONS = {
    "received": ("ready",),
    "ready": ("delivered",),
}
VALID_LAUNDRY_STATUS_TRANSITIONS = {
    "received": "ready",
    "ready": "delivered",
}
QR_SCAN_STATUS_TRANSITIONS = {
    "received": "ready",
    "ready": "delivered",
}
INTAKE_STATE_BY_LAUNDRY_STATUS = {
    "received": "received",
    "ready": "ready",
    "delivered": "delivered",
}


class PosOrder(models.Model):
    _inherit = "pos.order"

    x_laundry_intake_id = fields.Many2one(
        "pos.laundry.intake",
        string="Laundry Intake",
        copy=False,
        index=True,
    )
    x_display_reference = fields.Char(
        string="Order Reference",
        compute="_compute_display_reference",
        store=True,
    )
    x_laundry_invoice_number = fields.Char(
        string="Paid Invoice Number",
        compute="_compute_laundry_invoice_number",
        store=True,
        index=True,
        readonly=True,
    )
    x_qr_token = fields.Char(
        string="QR Token",
        copy=False,
        index=True,
    )
    x_laundry_status = fields.Selection(
        selection=LAUNDRY_STATUS_SELECTION,
        string="Laundry Status",
        default="received",
        required=True,
        copy=False,
        index=True,
    )
    x_laundry_priority = fields.Selection(
        selection=LAUNDRY_PRIORITY_SELECTION,
        string="Priority",
        default="normal",
        copy=False,
        index=True,
    )
    x_laundry_worker_id = fields.Many2one(
        "res.users",
        string="Worker",
        copy=False,
        readonly=True,
        index=True,
    )
    x_laundry_sla_deadline = fields.Datetime(
        string="SLA Deadline",
        copy=False,
        readonly=True,
        index=True,
    )
    x_laundry_sla_status = fields.Selection(
        selection=LAUNDRY_SLA_STATUS_SELECTION,
        string="SLA Status",
        compute="_compute_laundry_sla_status",
        search="_search_laundry_sla_status",
    )
    x_laundry_sla_remaining_display = fields.Char(
        string="Remaining Time",
        compute="_compute_laundry_sla_status",
    )
    x_laundry_delivered_on = fields.Datetime(
        string="Delivered On",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        index=True,
    )
    x_laundry_delivered_on_time = fields.Boolean(
        string="Delivered On Time",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        index=True,
    )
    x_laundry_duration_minutes = fields.Float(
        string="Average Duration (Minutes)",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        group_operator="avg",
    )
    x_laundry_delay_minutes = fields.Float(
        string="Average Delay (Minutes)",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        group_operator="avg",
    )
    x_laundry_on_time_percentage = fields.Float(
        string="On-Time %",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        group_operator="avg",
    )
    x_laundry_on_time_order_count = fields.Integer(
        string="On-Time Orders",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        group_operator="sum",
    )
    x_laundry_late_order_count = fields.Integer(
        string="Late Orders",
        compute="_compute_laundry_delivery_metrics",
        store=True,
        group_operator="sum",
    )
    laundry_status = fields.Selection(
        selection=LAUNDRY_STATUS_SELECTION,
        string="Laundry Status",
        related="x_laundry_status",
        store=True,
        readonly=False,
        copy=False,
        index=True,
    )
    x_laundry_status_history_ids = fields.One2many(
        "pos.order.laundry.status.history",
        "order_id",
        string="Laundry Status History",
        readonly=True,
    )
    x_laundry_label_ids = fields.One2many(
        "pos.laundry.label",
        "order_id",
        string="Tracking Label",
        readonly=True,
    )
    x_laundry_label_count = fields.Integer(
        string="Label Count",
        compute="_compute_laundry_label_count",
    )
    x_payment_status = fields.Selection(
        [
            ("unpaid", "Unpaid"),
            ("partial", "Partially Paid"),
            ("paid", "Paid"),
            ("refunded", "Refunded"),
            ("cancelled", "Cancelled"),
        ],
        string="Payment Status",
        compute="_compute_x_payment_status",
        store=True,
    )
    @api.depends("name", "x_laundry_intake_id")
    def _compute_display_reference(self):
        for order in self:
            order_name = (order.name or "").strip()
            if order_name and order_name != "/":
                order.x_display_reference = order_name
            elif order.x_laundry_intake_id:
                order.x_display_reference = order.x_laundry_intake_id.name or order.name
            else:
                order.x_display_reference = order.name

    @api.depends("account_move", "account_move.name")
    def _compute_laundry_invoice_number(self):
        for order in self:
            order.x_laundry_invoice_number = order.account_move.name if order.account_move else False

    @api.depends("amount_paid", "amount_total", "state", "currency_id")
    def _compute_x_payment_status(self):
        for order in self:
            order.x_payment_status = order._get_laundry_payment_status()

    @api.depends("x_laundry_label_ids")
    def _compute_laundry_label_count(self):
        for order in self:
            order.x_laundry_label_count = len(order.x_laundry_label_ids)

    @api.depends(
        "date_order",
        "x_laundry_sla_deadline",
        "x_laundry_status",
        "x_laundry_status_history_ids.new_status",
        "x_laundry_status_history_ids.changed_on",
    )
    def _compute_laundry_delivery_metrics(self):
        for order in self:
            delivered_history = order.x_laundry_status_history_ids.filtered(
                lambda line: line.new_status == "delivered" and line.changed_on
            )[:1]
            delivered_on = delivered_history.changed_on if delivered_history else False
            order.x_laundry_delivered_on = delivered_on

            if not delivered_on:
                order.x_laundry_delivered_on_time = False
                order.x_laundry_duration_minutes = 0.0
                order.x_laundry_delay_minutes = 0.0
                order.x_laundry_on_time_percentage = 0.0
                order.x_laundry_on_time_order_count = 0
                order.x_laundry_late_order_count = 0
                continue

            if order.date_order:
                duration_seconds = max(0, (delivered_on - order.date_order).total_seconds())
                order.x_laundry_duration_minutes = duration_seconds / 60.0
            else:
                order.x_laundry_duration_minutes = 0.0

            if order.x_laundry_sla_deadline:
                delay_seconds = max(0, (delivered_on - order.x_laundry_sla_deadline).total_seconds())
                order.x_laundry_delay_minutes = delay_seconds / 60.0
                order.x_laundry_delivered_on_time = delay_seconds <= 0
                order.x_laundry_on_time_percentage = 100.0 if delay_seconds <= 0 else 0.0
                order.x_laundry_on_time_order_count = 1 if delay_seconds <= 0 else 0
                order.x_laundry_late_order_count = 0 if delay_seconds <= 0 else 1
            else:
                order.x_laundry_delay_minutes = 0.0
                order.x_laundry_delivered_on_time = False
                order.x_laundry_on_time_percentage = 0.0
                order.x_laundry_on_time_order_count = 0
                order.x_laundry_late_order_count = 0

    @api.depends(
        "x_laundry_status",
        "x_laundry_sla_deadline",
        "x_laundry_delivered_on",
        "x_laundry_delivered_on_time",
        "x_laundry_delay_minutes",
    )
    def _compute_laundry_sla_status(self):
        now = fields.Datetime.now()
        due_soon_delta = timedelta(hours=LAUNDRY_DUE_SOON_HOURS)
        for order in self:
            deadline = order.x_laundry_sla_deadline
            if order.x_laundry_status == "delivered":
                if order.x_laundry_delivered_on and not order.x_laundry_delivered_on_time:
                    order.x_laundry_sla_status = "delivered_late"
                    order.x_laundry_sla_remaining_display = _("%s late") % order._format_laundry_duration(
                        order.x_laundry_delay_minutes
                    )
                elif order.x_laundry_delivered_on:
                    order.x_laundry_sla_status = "delivered_on_time"
                    order.x_laundry_sla_remaining_display = _("Delivered on time")
                else:
                    order.x_laundry_sla_status = False
                    order.x_laundry_sla_remaining_display = ""
                continue

            if not deadline:
                order.x_laundry_sla_status = False
                order.x_laundry_sla_remaining_display = ""
                continue

            remaining = deadline - now
            remaining_minutes = abs(remaining.total_seconds()) / 60.0
            if remaining.total_seconds() < 0:
                order.x_laundry_sla_status = "overdue"
                order.x_laundry_sla_remaining_display = _("%s overdue") % order._format_laundry_duration(
                    remaining_minutes
                )
            elif remaining <= due_soon_delta:
                order.x_laundry_sla_status = "due_soon"
                order.x_laundry_sla_remaining_display = _("%s remaining") % order._format_laundry_duration(
                    remaining_minutes
                )
            else:
                order.x_laundry_sla_status = "on_track"
                order.x_laundry_sla_remaining_display = _("%s remaining") % order._format_laundry_duration(
                    remaining_minutes
                )

    @api.model
    def _search_laundry_sla_status(self, operator, value):
        if operator not in ("=", "!=", "in", "not in"):
            raise UserError(_("Unsupported SLA status search operator."))

        if operator in ("=", "!="):
            values = [value]
        else:
            values = list(value or [])

        now = fields.Datetime.now()
        due_soon_deadline = now + timedelta(hours=LAUNDRY_DUE_SOON_HOURS)
        status_domains = {
            "overdue": [
                ("x_laundry_status", "in", ["received", "ready"]),
                ("x_laundry_sla_deadline", "!=", False),
                ("x_laundry_sla_deadline", "<", now),
            ],
            "due_soon": [
                ("x_laundry_status", "in", ["received", "ready"]),
                ("x_laundry_sla_deadline", ">=", now),
                ("x_laundry_sla_deadline", "<=", due_soon_deadline),
            ],
            "on_track": [
                ("x_laundry_status", "in", ["received", "ready"]),
                "|",
                ("x_laundry_sla_deadline", "=", False),
                ("x_laundry_sla_deadline", ">", due_soon_deadline),
            ],
            "delivered_on_time": [
                ("x_laundry_status", "=", "delivered"),
                ("x_laundry_delivered_on_time", "=", True),
            ],
            "delivered_late": [
                ("x_laundry_status", "=", "delivered"),
                ("x_laundry_delivered_on", "!=", False),
                ("x_laundry_delivered_on_time", "=", False),
            ],
        }

        domains = [status_domains[key] for key in values if key in status_domains]
        domain = expression.OR(domains) if domains else [("id", "=", 0)]
        if operator in ("!=", "not in"):
            matching_ids = self.search(domain).ids
            return [("id", "not in", matching_ids)] if matching_ids else []
        return domain

    @api.model
    def _format_laundry_duration(self, minutes):
        minutes = max(0, int(round(minutes or 0)))
        days, day_remainder = divmod(minutes, 24 * 60)
        hours, minute_remainder = divmod(day_remainder, 60)
        if days:
            if hours:
                return _("%(days)s d %(hours)s h") % {"days": days, "hours": hours}
            return _("%s d") % days
        if hours:
            if minute_remainder:
                return _("%(hours)s h %(minutes)s m") % {
                    "hours": hours,
                    "minutes": minute_remainder,
                }
            return _("%s h") % hours
        return _("%s m") % minute_remainder

    def _calculate_laundry_sla_deadline(self, priority=False):
        self.ensure_one()
        base_datetime = fields.Datetime.to_datetime(self.date_order) or fields.Datetime.now()
        calendar = self._get_laundry_sla_calendar()
        timezone = self._get_laundry_sla_timezone(calendar)

        base_datetime = self._ensure_aware_utc(base_datetime)
        local_start = base_datetime.astimezone(timezone)
        required_working_days = 1 if (priority or self.x_laundry_priority) == "urgent" else 2
        deadline_date = self._get_nth_laundry_working_date(
            local_start.date(),
            required_working_days,
            calendar,
            timezone,
        )
        if not deadline_date:
            return False

        deadline_local = self._get_laundry_workday_deadline_local(
            deadline_date,
            calendar,
            timezone,
        )
        if not deadline_local:
            return False
        return deadline_local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _ensure_laundry_sla_deadline_snapshot(self, force=False):
        """Persist the intake-time SLA deadline once, then keep it immutable.

        The branch calendar and priority are historical inputs.  They should
        not silently recalculate old orders when a POS branch calendar changes
        later.
        """
        for order in self:
            if not force and order.x_laundry_sla_deadline:
                continue
            deadline = order._calculate_laundry_sla_deadline()
            order.with_context(laundry_allow_sla_deadline_write=True).write(
                {"x_laundry_sla_deadline": deadline or False}
            )
        return True

    @api.model
    def _ensure_aware_utc(self, value):
        if not value:
            value = fields.Datetime.now()
        value = fields.Datetime.to_datetime(value)
        if value.tzinfo:
            return value.astimezone(pytz.UTC)
        return pytz.UTC.localize(value)

    def _get_laundry_sla_calendar(self):
        self.ensure_one()
        return (
            self.config_id.laundry_sla_calendar_id
            or self.company_id.resource_calendar_id
            or self.env.company.resource_calendar_id
        )

    def _get_laundry_sla_timezone(self, calendar=False):
        self.ensure_one()
        timezone_name = (
            (calendar and calendar.tz)
            or (self.company_id.partner_id and self.company_id.partner_id.tz)
            or (self.env.company.partner_id and self.env.company.partner_id.tz)
            or self.env.user.tz
            or "UTC"
        )
        try:
            return pytz.timezone(timezone_name)
        except Exception:
            return pytz.UTC

    def _get_nth_laundry_working_date(self, start_date, required_working_days, calendar, timezone):
        self.ensure_one()
        cursor_date = start_date
        found = 0
        for _index in range(370):
            if self._is_laundry_working_date(cursor_date, calendar, timezone):
                found += 1
                if found >= required_working_days:
                    return cursor_date
            cursor_date += timedelta(days=1)
        _logger.warning(
            "Unable to calculate laundry SLA deadline for order %s after scanning one year.",
            self.id,
        )
        return False

    @api.model
    def _is_laundry_excluded_workday(self, local_date):
        """Central business-day exclusion for laundry SLA calculations."""
        return local_date.weekday() == LAUNDRY_FRIDAY_WEEKDAY

    @api.model
    def _is_laundry_working_date(self, local_date, calendar, timezone):
        if self._is_laundry_excluded_workday(local_date):
            return False
        if not calendar:
            return False
        intervals = self._get_laundry_work_intervals_for_date(local_date, calendar, timezone)
        return any(stop > start for start, stop, _meta in intervals)

    @api.model
    def _get_laundry_work_intervals_for_date(self, local_date, calendar, timezone):
        if not calendar or self._is_laundry_excluded_workday(local_date):
            return []
        start_local = timezone.localize(datetime.combine(local_date, time.min))
        end_local = timezone.localize(datetime.combine(local_date, time.max))
        intervals = calendar._work_intervals_batch(
            start_local.astimezone(pytz.UTC),
            end_local.astimezone(pytz.UTC),
            tz=timezone,
            compute_leaves=True,
        )[False]
        return [
            (start, stop, meta)
            for start, stop, meta in intervals
            if start.astimezone(timezone).date() == local_date
        ]

    @api.model
    def _get_laundry_workday_deadline_local(self, local_date, calendar, timezone):
        intervals = self._get_laundry_work_intervals_for_date(local_date, calendar, timezone)
        if intervals:
            return max(stop.astimezone(timezone) for _start, stop, _meta in intervals)
        return False

    def _get_laundry_payment_status(self, vals=None):
        self.ensure_one()
        vals = vals or {}
        state = vals.get("state", self.state)
        amount_total = vals.get("amount_total", self.amount_total)
        amount_paid = vals.get("amount_paid", self.amount_paid)
        currency = self.currency_id
        if vals.get("currency_id"):
            currency = self.env["res.currency"].browse(vals["currency_id"])

        if state == "cancel":
            return "cancelled"
        if amount_total < 0:
            return "refunded"

        rounding = currency.rounding or self.company_id.currency_id.rounding or 0.01
        if float_compare(amount_paid, amount_total, precision_rounding=rounding) >= 0:
            return "paid"
        if float_is_zero(amount_paid, precision_rounding=rounding):
            return "unpaid"
        return "partial"

    @api.model
    def _get_laundry_delivery_payment_required_message(self):
        return _("Delivery cannot be confirmed until the payment status is Paid.")

    @api.model
    def _normalize_laundry_pos_scalar_id(self, value):
        if isinstance(value, bool) or value in (None, False):
            return False
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            return int(value) if value.isdigit() else False

        ids = []

        def collect(item):
            if isinstance(item, bool) or item in (None, False):
                return
            if isinstance(item, int):
                ids.append(item)
                return
            if isinstance(item, str):
                item = item.strip()
                if item.isdigit():
                    ids.append(int(item))
                return
            if isinstance(item, (list, tuple, set)):
                for child in item:
                    collect(child)

        collect(value)
        return ids[0] if ids else False

    @api.model
    def _order_fields(self, ui_order):
        vals = super()._order_fields(ui_order)
        for field_name in ("partner_id", "fiscal_position_id", "pricelist_id"):
            if field_name in vals:
                vals[field_name] = self._normalize_laundry_pos_scalar_id(
                    vals.get(field_name)
                )
        return vals

    def _check_laundry_delivery_payment(self, vals=None):
        for order in self:
            if order._get_laundry_payment_status(vals) != "paid":
                raise UserError(order._get_laundry_delivery_payment_required_message())

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "partner_id" in vals:
                vals["partner_id"] = self._normalize_laundry_pos_scalar_id(
                    vals.get("partner_id")
                )
            if not self.env.context.get("laundry_allow_worker_assignment"):
                vals.pop("x_laundry_worker_id", None)
            if not self.env.context.get("laundry_allow_sla_deadline_write"):
                vals.pop("x_laundry_sla_deadline", None)
            prepared_vals = self._prepare_laundry_status_vals(vals)
            requested_status = prepared_vals.get("x_laundry_status", "received")
            if requested_status != "received":
                raise UserError(
                    _("New laundry orders must start in the Received stage.")
                )
            prepared_vals.setdefault("x_qr_token", self._generate_qr_token())
            vals.clear()
            vals.update(prepared_vals)
        orders = super().create(vals_list)
        history_values = []
        for order in orders:
            history_values.append({
                "order_id": order.id,
                "new_status": order.x_laundry_status,
                "changed_by_id": self.env.user.id,
            })
        if history_values:
            self.env["pos.order.laundry.status.history"].sudo().create(history_values)
        orders._ensure_laundry_labels()
        orders.filtered("x_laundry_intake_id")._ensure_laundry_sla_deadline_snapshot()
        return orders

    def write(self, vals):
        vals = self._prepare_laundry_status_vals(vals)
        initial_intake_sync = self.env.context.get("laundry_initial_intake_sync")
        if "x_laundry_sla_deadline" in vals and not self.env.context.get("laundry_allow_sla_deadline_write"):
            raise UserError(
                _(
                    "Laundry SLA deadlines are locked after intake. "
                    "Use an authorized SLA recalculation operation to change them."
                )
            )
        if "x_laundry_intake_id" in vals:
            new_intake_id = vals["x_laundry_intake_id"] or False
            for order in self:
                if order.x_laundry_intake_id and order.x_laundry_intake_id.id != new_intake_id:
                    raise UserError(
                        _(
                            "The linked laundry intake is locked after receipt "
                            "to keep the order, SLA, and label history consistent."
                        )
                    )
            if new_intake_id and not initial_intake_sync:
                raise UserError(
                    _("Laundry intake links can only be set by the intake workflow.")
                )
        if "x_laundry_priority" in vals and not initial_intake_sync:
            for order in self:
                if (
                    order.x_laundry_intake_id
                    and vals["x_laundry_priority"] != order.x_laundry_priority
                ):
                    raise UserError(
                        _(
                            "Laundry priority is locked after intake because it "
                            "is part of the historical SLA snapshot."
                        )
                    )
        if "x_laundry_worker_id" in vals and not self.env.context.get("laundry_allow_worker_assignment"):
            vals.pop("x_laundry_worker_id", None)
        if "x_laundry_status" in vals:
            self._lock_laundry_workflow_rows()
            self._check_laundry_status_transition(vals["x_laundry_status"])
            if vals["x_laundry_status"] == "delivered":
                vals["x_laundry_worker_id"] = self.env.user.id
        if vals.get("x_laundry_status") == "delivered":
            self._check_laundry_delivery_payment(vals)

        tracked_orders = {}
        open_history_by_order = {}
        if "x_laundry_status" in vals:
            for order in self:
                tracked_orders[order.id] = order.x_laundry_status
            open_histories = self.env["pos.order.laundry.status.history"].sudo().search(
                [
                    ("order_id", "in", self.ids),
                    ("exited_on", "=", False),
                ],
                order="changed_on desc, id desc",
            )
            for history in open_histories:
                open_history_by_order.setdefault(history.order_id.id, history)

        result = super().write(vals)

        if "x_laundry_status" in vals:
            changed_on = fields.Datetime.now()
            history_values = []
            for order in self:
                old_status = tracked_orders.get(order.id)
                if old_status and old_status != order.x_laundry_status:
                    open_history = open_history_by_order.get(order.id)
                    if open_history:
                        duration_seconds = max(
                            0,
                            int((changed_on - open_history.changed_on).total_seconds()),
                        )
                        open_history.write(
                            {
                                "exited_on": changed_on,
                                "duration_seconds": duration_seconds,
                            }
                        )
                    history_values.append({
                        "order_id": order.id,
                        "old_status": old_status,
                        "new_status": order.x_laundry_status,
                        "changed_by_id": self.env.user.id,
                        "changed_on": changed_on,
                    })
            if history_values:
                self.env["pos.order.laundry.status.history"].sudo().create(history_values)

        if initial_intake_sync and any(key in vals for key in ("x_laundry_intake_id", "x_laundry_priority")):
            self._ensure_laundry_sla_deadline_snapshot(force=True)

        return result

    def _lock_laundry_workflow_rows(self):
        order_ids = [order_id for order_id in self.ids if order_id]
        if not order_ids:
            return True
        self.env.cr.execute(
            "SELECT id FROM pos_order WHERE id IN %s FOR UPDATE",
            [tuple(order_ids)],
        )
        self.invalidate_recordset(["x_laundry_status", "laundry_status", "x_payment_status"])
        return True

    def _check_laundry_status_transition(self, target_status):
        target_status = self._normalize_laundry_status(target_status)
        if target_status not in dict(LAUNDRY_STATUS_SELECTION):
            raise UserError(_("Invalid laundry status."))
        for order in self:
            current_status = self._normalize_laundry_status(order.x_laundry_status)
            if current_status == target_status:
                continue
            if VALID_LAUNDRY_STATUS_TRANSITIONS.get(current_status) != target_status:
                raise UserError(
                    _(
                        "Invalid laundry workflow transition: %(current)s → %(target)s. "
                        "Orders can only move from Received to Ready to Delivered."
                    )
                    % {
                        "current": order._get_laundry_status_text(current_status)["label"],
                        "target": order._get_laundry_status_text(target_status)["label"],
                    }
                )

    @api.model
    def _normalize_laundry_status(self, status):
        return LEGACY_LAUNDRY_STATUS_MAP.get(status, status)

    @api.model
    def _prepare_laundry_status_vals(self, vals):
        prepared_vals = dict(vals or {})
        alias_status = prepared_vals.pop("laundry_status", False)
        source_status = prepared_vals.get("x_laundry_status")
        if alias_status and not source_status:
            prepared_vals["x_laundry_status"] = alias_status
        if prepared_vals.get("x_laundry_status"):
            prepared_vals["x_laundry_status"] = self._normalize_laundry_status(prepared_vals["x_laundry_status"])
        return prepared_vals

    def _set_laundry_status(self, status):
        self.ensure_one()
        status = self._normalize_laundry_status(status)
        if status not in dict(LAUNDRY_STATUS_SELECTION):
            raise UserError(_("Invalid laundry status."))
        if status == "delivered":
            self._check_laundry_delivery_payment()
        self.write({"x_laundry_status": status})
        intake_state = INTAKE_STATE_BY_LAUNDRY_STATUS.get(status)
        if self.x_laundry_intake_id and intake_state and self.x_laundry_intake_id.state != intake_state:
            self.x_laundry_intake_id.write({"state": intake_state})
        return True

    @api.model
    def _generate_qr_token(self):
        return secrets.token_hex(12)

    def _ensure_laundry_qr_token(self):
        for order in self:
            if not order.x_qr_token:
                order.with_context(mail_notrack=True).write({
                    "x_qr_token": self._generate_qr_token(),
                })
        return True

    def _ensure_laundry_labels(self):
        """Idempotently persist one queue label for every order."""
        # Cancelled POS documents are accounting lifecycle records, not an
        # additional laundry workflow stage.
        orders = self.exists().filtered(lambda order: order.state != "cancel")
        if not orders:
            return self.env["pos.laundry.label"]
        existing = self.env["pos.laundry.label"].sudo().search(
            [("order_id", "in", orders.ids)]
        )
        existing_order_ids = set(existing.mapped("order_id").ids)
        missing_values = [
            {"order_id": order.id}
            for order in orders
            if order.id not in existing_order_ids
        ]
        created = (
            self.env["pos.laundry.label"].sudo().create(missing_values)
            if missing_values
            else self.env["pos.laundry.label"]
        )
        return existing | created

    def _get_laundry_reference(self):
        self.ensure_one()
        order_name = (self.name or "").strip()
        if order_name and order_name != "/":
            _logger.info(
                "_get_laundry_reference: order=%s canonical_reference=%s",
                self.id,
                order_name,
            )
            return order_name
        reference = (
            (self.x_display_reference or "").strip()
            or (self.x_laundry_intake_id.name or "").strip()
            or (self.pos_reference or "").strip()
            or order_name
        )
        _logger.info(
            "_get_laundry_reference: order=%s fallback_reference=%s",
            self.id,
            reference,
        )
        return reference

    def _build_laundry_qr_payload(self):
        self.ensure_one()
        self._ensure_laundry_qr_token()
        return self._get_laundry_scan_url()

    def _get_laundry_scan_url(self):
        self.ensure_one()
        self._ensure_laundry_qr_token()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        path = "/pos_laundry_receipt/scan/%s" % quote(self.x_qr_token, safe="")
        return "%s%s" % (base_url.rstrip("/"), path) if base_url else path

    def _get_laundry_qr_barcode_url(self):
        self.ensure_one()
        return "/report/barcode/?barcode_type=QR&width=220&height=220&value=%s" % quote(
            self._build_laundry_qr_payload(),
            safe="",
        )

    @api.model
    def _parse_laundry_qr_value(self, qr_value):
        raw_value = (qr_value or "").strip()
        result = {
            "raw_value": raw_value,
            "normalized_value": raw_value,
            "payload_type": "plain",
            "order_reference": raw_value,
            "pos_reference": "",
            "token": "",
        }
        if not raw_value:
            return result

        parsed_url = urlparse(raw_value)
        token_match = re.search(
            r"/pos_laundry_receipt/scan/([^/?#]+)",
            parsed_url.path or "",
        )
        if token_match:
            token = unquote(token_match.group(1)).strip()
            result.update(
                {
                    "payload_type": "url",
                    "order_reference": "",
                    "pos_reference": "",
                    "token": token,
                    "normalized_value": token,
                }
            )
            return result

        if raw_value.startswith("{") and raw_value.endswith("}"):
            try:
                payload = json.loads(raw_value)
            except Exception:
                return result

            if isinstance(payload, dict):
                result["payload_type"] = "json"
                result["order_reference"] = (payload.get("order") or payload.get("reference") or "").strip()
                result["pos_reference"] = (payload.get("pos_reference") or "").strip()
                result["token"] = (payload.get("token") or "").strip()
                result["normalized_value"] = (
                    result["order_reference"]
                    or result["pos_reference"]
                    or result["token"]
                    or raw_value
                )
        return result

    def _matches_scanned_reference(self, scanned_reference):
        self.ensure_one()
        value = (scanned_reference or "").strip().lower()
        if not value:
            return False
        candidates = {
            (self._get_laundry_reference() or "").strip().lower(),
            (self.x_display_reference or "").strip().lower(),
            (self.x_laundry_invoice_number or "").strip().lower(),
            (self.account_move.name if self.account_move else "").strip().lower(),
            (self.x_laundry_intake_id.name or "").strip().lower(),
            (self.name or "").strip().lower(),
            (self.pos_reference or "").strip().lower(),
        }
        return value in {candidate for candidate in candidates if candidate}

    @api.model
    def _get_next_laundry_scan_status(self, current_status):
        return QR_SCAN_STATUS_TRANSITIONS.get(self._normalize_laundry_status(current_status))

    @api.model
    def _build_qr_scan_response(self, *, success, code, message, order=False, scanned_value="", parsed=False):
        payload = {
            "success": success,
            "code": code,
            "message": message,
            "scanned_value": scanned_value,
            "order": False,
            "parsed": parsed or {},
        }
        if order:
            payload["order"] = order._serialize_pending_laundry_board_order()
        return payload

    def action_move_to_washing(self):
        for order in self:
            order._set_laundry_status("received")
        return True

    def action_move_to_ironing(self):
        for order in self:
            order._set_laundry_status("received")
        return True

    def action_mark_ready(self):
        for order in self:
            order._set_laundry_status("ready")
        return True

    def action_mark_delivered(self):
        for order in self:
            order._set_laundry_status("delivered")
        return True

    def action_print_laundry_receipt(self):
        self.ensure_one()
        laundry_order_field = self._fields.get("laundry_order_id")
        laundry_order = laundry_order_field and self.laundry_order_id

        if laundry_order and not self.x_laundry_intake_id:
            report_action = self.env.ref(
                "laundry_base.action_report_laundry_receipt",
                raise_if_not_found=False,
            )
            if report_action:
                return report_action.report_action(laundry_order)

        if not self.x_laundry_intake_id:
            raise UserError(
                _(
                    "This POS order is not linked to a laundry receipt, so the intake invoice cannot be printed."
                )
            )

        self._ensure_laundry_qr_token()
        return {
            "type": "ir.actions.act_url",
            "name": _("Laundry Receipt"),
            "url": "/pos_laundry_receipt/receipt/%s?print=1" % self.id,
            "target": "new",
        }

    def _get_laundry_label(self):
        self.ensure_one()
        labels = self._ensure_laundry_labels()
        return labels.filtered(lambda label: label.order_id == self)[:1]

    def action_preview_laundry_label(self):
        self.ensure_one()
        return self._get_laundry_label().action_preview()

    def action_print_laundry_label(self):
        self.ensure_one()
        return self._get_laundry_label().action_print()

    def action_view_laundry_label(self):
        self.ensure_one()
        label = self._get_laundry_label()
        return {
            "type": "ir.actions.act_window",
            "name": _("Laundry Label"),
            "res_model": "pos.laundry.label",
            "res_id": label.id,
            "views": [[False, "form"]],
            "target": "current",
        }

    @api.model
    def get_laundry_label_action(self, order_id, operation="preview"):
        order = self.browse(order_id).exists()
        if not order:
            raise UserError(_("The selected order could not be found."))
        order.check_access_rights("read")
        order.check_access_rule("read")
        if operation == "print":
            return order.action_print_laundry_label()
        return order.action_preview_laundry_label()

    @api.model
    def get_laundry_tracking_url(self, *args):
        action = self.env.ref("pos_laundry_receipt.action_pos_laundry_order_tracking_dashboard")
        menu = self.env.ref("pos_laundry_receipt.menu_pos_laundry_order_tracking")
        return "/web#action=%s&menu_id=%s" % (action.id, menu.id)

    @api.model
    def get_laundry_tracking_dashboard_data(self):
        orders = self.search(
            [
                ("state", "!=", "cancel"),
                ("x_laundry_status", "in", DASHBOARD_LAUNDRY_STATUSES),
            ],
            order="date_order desc, id desc",
        )
        orders._ensure_laundry_labels()
        label_action = self.env.ref(
            "pos_laundry_receipt.action_pos_laundry_label_queue"
        )
        pending_label_count = self.env["pos.laundry.label"].search_count(
            [("is_pending", "=", True)]
        )
        sla_counters = {
            "urgent": len(orders.filtered(lambda order: order.x_laundry_priority == "urgent")),
            "due_soon": len(orders.filtered(lambda order: order.x_laundry_sla_status == "due_soon")),
            "overdue": len(orders.filtered(lambda order: order.x_laundry_sla_status == "overdue")),
            "delivered_on_time": len(orders.filtered(lambda order: order.x_laundry_sla_status == "delivered_on_time")),
            "delivered_late": len(orders.filtered(lambda order: order.x_laundry_sla_status == "delivered_late")),
        }

        return {
            "statuses": self._build_laundry_status_payload(DASHBOARD_LAUNDRY_STATUSES),
            "ui_labels": self._get_laundry_tracking_dashboard_ui_labels(),
            "orders": orders._serialize_laundry_dashboard_orders(),
            "label_queue_action_id": label_action.id,
            "pending_label_count": pending_label_count,
            "sla_counters": sla_counters,
            "generated_at": fields.Datetime.now(),
        }

    @api.model
    def _get_laundry_tracking_dashboard_ui_labels(self):
        """Return short dashboard labels translated in the active Odoo language.

        The backend already supplies translated status/payment/SLA values.  These
        static card captions follow the same path so the live dashboard does not
        depend on generic JavaScript translation keys that may be shared with
        other modules.
        """
        return {
            "priority": _("Priority"),
            "deadline": _("Deadline"),
            "remaining": _("Remaining"),
            "sla_status": _("SLA Status"),
            "worker": _("Worker"),
        }

    @api.model
    def get_laundry_sla_performance_dashboard_data(
        self,
        analytics_period="month",
        analytics_date_from=False,
        analytics_date_to=False,
    ):
        orders = self.search(
            [
                ("state", "!=", "cancel"),
                ("x_laundry_status", "in", DASHBOARD_LAUNDRY_STATUSES),
            ],
            order="x_laundry_sla_deadline asc, date_order desc, id desc",
        )
        orders.invalidate_recordset([
            "x_laundry_sla_status",
            "x_laundry_sla_remaining_display",
        ])
        action = self.env.ref("pos_laundry_receipt.action_pos_laundry_worker_performance")
        return {
            "labels": self._get_laundry_sla_performance_dashboard_labels(),
            "orders": orders._serialize_laundry_sla_performance_dashboard_orders(),
            "counters": {
                "active_urgent": len(
                    orders.filtered(
                        lambda order: order.x_laundry_priority == "urgent"
                        and order.x_laundry_status != "delivered"
                    )
                ),
                "due_soon": len(
                    orders.filtered(lambda order: order.x_laundry_sla_status == "due_soon")
                ),
                "overdue": len(
                    orders.filtered(lambda order: order.x_laundry_sla_status == "overdue")
                ),
                "delivered_on_time": len(
                    orders.filtered(
                        lambda order: order.x_laundry_sla_status == "delivered_on_time"
                    )
                ),
            },
            "branches": self._build_laundry_sla_option_payload(orders.mapped("config_id")),
            "workers": self._build_laundry_sla_option_payload(
                orders.mapped("x_laundry_worker_id")
            ),
            "stages": self._build_laundry_status_payload(DASHBOARD_LAUNDRY_STATUSES),
            "analytics": self._get_laundry_delivery_performance_analytics(
                analytics_period=analytics_period,
                date_from=analytics_date_from,
                date_to=analytics_date_to,
            ),
            "report_action_id": action.id,
            "generated_at": fields.Datetime.now(),
        }

    @api.model
    def _build_laundry_sla_option_payload(self, records):
        return [
            {"id": record.id, "name": record.display_name}
            for record in records.sorted(lambda item: item.display_name or "")
            if record
        ]

    @api.model
    def _get_laundry_sla_performance_dashboard_labels(self):
        return {
            "page_title": _("SLA & Performance"),
            "refresh": _("Refresh"),
            "detailed_reports": _("Detailed Reports"),
            "search_placeholder": _("Search by order number, customer, branch, or worker"),
            "all": _("All"),
            "normal": _("Normal"),
            "urgent": _("Urgent"),
            "urgent_filter": (
                "مستعجل" if (self.env.lang or "").startswith("ar") else _("Urgent")
            ),
            "active_urgent": _("Active Urgent"),
            "due_soon": _("Due Soon"),
            "overdue": _("Overdue"),
            "on_track": _("On Track"),
            "delivered_on_time": _("Delivered On Time"),
            "delivered_late": _("Delivered Late"),
            "branch": _("Branch"),
            "worker": _("Worker"),
            "current_stage": _("Current Stage"),
            "all_branches": _("All Branches"),
            "all_workers": _("All Workers"),
            "all_stages": _("All Stages"),
            "group_by": _("Group By"),
            "no_grouping": _("No Grouping"),
            "sla_status": _("SLA Status"),
            "priority": _("Priority"),
            "order_number": _("Order Number"),
            "customer": _("Customer"),
            "deadline": _("Deadline"),
            "remaining_time": _("Remaining Time"),
            "received_time": _("Received Time"),
            "time_in_stage": _("Time in Current Stage"),
            "item_count": _("Item Count"),
            "open_order": _("Open Order"),
            "view_history": _("View History"),
            "more_filters": _("More Filters"),
            "show_all": _("Show All"),
            "view_all": _("View All"),
            "back_to_overview": _("Back to Overview"),
            "empty_category": _("No orders in this category"),
            "performance_analytics": _("Performance Analytics"),
            "today": _("Today"),
            "this_week": _("This Week"),
            "this_month": _("This Month"),
            "custom_range": _("Custom Range"),
            "date_from": _("Date From"),
            "date_to": _("Date To"),
            "on_time_delivery_rate": _("On-Time Delivery Rate"),
            "average_processing_time": _("Average Processing Time"),
            "average_delay": _("Average Delay"),
            "urgent_sla_compliance": _("Urgent SLA Compliance"),
            "normal_sla_compliance": _("Normal SLA Compliance"),
            "on_time_vs_late": _("On-Time vs Late"),
            "weekly_on_time_percentage": _("Weekly On-Time Percentage"),
            "performance_by_worker": _("Performance by Worker"),
            "performance_by_branch": _("Performance by Branch"),
            "performance_by_priority": _("Performance by Priority"),
            "worker": _("Worker"),
            "delivered_orders": _("Delivered Orders"),
            "delivered_on_time_count": _("Delivered On Time"),
            "delivered_late_count": _("Delivered Late"),
            "on_time_percentage": _("On-Time Percentage"),
            "branch": _("Branch"),
            "overdue_orders": _("Overdue Orders"),
            "no_delivery_data": _("No sufficient delivery data for the selected period"),
            "on_time": _("On Time"),
            "late": _("Late"),
            "total": _("Total"),
            "previous": _("Previous"),
            "next": _("Next"),
            "pagination_summary": _("Showing %(start)s-%(end)s of %(total)s orders"),
            "unassigned": _("Unassigned"),
            "no_deadline": _("No deadline"),
            "not_available": _("Not available"),
            "empty_state": _("No orders currently require attention"),
            "orders": _("Orders"),
        }

    @api.model
    def _get_laundry_delivery_performance_analytics(
        self,
        analytics_period="month",
        date_from=False,
        date_to=False,
    ):
        period = analytics_period if analytics_period in ("today", "week", "month", "custom") else "month"
        period_bounds = self._get_laundry_performance_period_bounds(period, date_from, date_to)
        delivered_orders = self.search(
            [
                ("state", "!=", "cancel"),
                ("x_laundry_status", "=", "delivered"),
                ("x_laundry_delivered_on", "!=", False),
                ("x_laundry_delivered_on", ">=", period_bounds["start_utc"]),
                ("x_laundry_delivered_on", "<", period_bounds["end_utc"]),
            ],
            order="x_laundry_delivered_on desc, id desc",
        )
        delivered_orders.invalidate_recordset([
            "x_laundry_delivered_on",
            "x_laundry_delivered_on_time",
            "x_laundry_duration_minutes",
            "x_laundry_delay_minutes",
        ])

        total_delivered = len(delivered_orders)
        on_time_orders = delivered_orders.filtered("x_laundry_delivered_on_time")
        late_orders = delivered_orders - on_time_orders
        urgent_orders = delivered_orders.filtered(lambda order: order.x_laundry_priority == "urgent")
        normal_orders = delivered_orders.filtered(lambda order: order.x_laundry_priority == "normal")
        processing_minutes = [
            minutes
            for minutes in (
                self._get_laundry_processing_minutes(order)
                for order in delivered_orders
            )
            if minutes is not False
        ]
        delay_minutes = [self._get_laundry_delay_minutes(order) for order in late_orders]
        on_time_rate = self._laundry_percentage(len(on_time_orders), total_delivered)
        urgent_compliance = self._laundry_percentage(
            len(urgent_orders.filtered("x_laundry_delivered_on_time")),
            len(urgent_orders),
        )
        normal_compliance = self._laundry_percentage(
            len(normal_orders.filtered("x_laundry_delivered_on_time")),
            len(normal_orders),
        )
        urgent_compliance_display = (
            self._format_laundry_percentage(urgent_compliance)
            if urgent_orders
            else _("Not available")
        )
        normal_compliance_display = (
            self._format_laundry_percentage(normal_compliance)
            if normal_orders
            else _("Not available")
        )
        average_processing = self._laundry_average(processing_minutes)
        average_delay = self._laundry_average(delay_minutes)
        worker_rows = self._build_laundry_performance_group_payload(
            delivered_orders,
            key_getter=lambda order: order.x_laundry_worker_id.id or 0,
            label_getter=lambda order: order.x_laundry_worker_id.name or _("Unassigned"),
        )
        branch_rows = self._build_laundry_performance_group_payload(
            delivered_orders,
            key_getter=lambda order: order.config_id.id or 0,
            label_getter=lambda order: order.config_id.display_name or _("Not available"),
        )
        priority_rows = self._build_laundry_performance_group_payload(
            delivered_orders,
            key_getter=lambda order: order.x_laundry_priority or "normal",
            label_getter=lambda order: self._get_laundry_priority_label(
                order.x_laundry_priority or "normal"
            ),
        )

        return {
            "period": period,
            "date_from": fields.Date.to_string(period_bounds["start_date"]),
            "date_to": fields.Date.to_string(period_bounds["end_date"]),
            "has_data": bool(total_delivered),
            "kpis": [
                self._build_laundry_performance_kpi(
                    "on_time_delivery_rate",
                    _("On-Time Delivery Rate"),
                    self._format_laundry_percentage(on_time_rate),
                    on_time_rate,
                    "success",
                    "fa-percent",
                ),
                self._build_laundry_performance_kpi(
                    "delivered_on_time",
                    _("Delivered On Time"),
                    len(on_time_orders),
                    len(on_time_orders),
                    "success",
                    "fa-check-circle",
                ),
                self._build_laundry_performance_kpi(
                    "delivered_late",
                    _("Delivered Late"),
                    len(late_orders),
                    len(late_orders),
                    "danger",
                    "fa-clock-o",
                ),
                self._build_laundry_performance_kpi(
                    "average_processing_time",
                    _("Average Processing Time"),
                    self._format_laundry_duration(average_processing),
                    average_processing,
                    "neutral",
                    "fa-hourglass-half",
                ),
                self._build_laundry_performance_kpi(
                    "average_delay",
                    _("Average Delay"),
                    self._format_laundry_duration(average_delay),
                    average_delay,
                    "warning",
                    "fa-exclamation-triangle",
                ),
                self._build_laundry_performance_kpi(
                    "urgent_sla_compliance",
                    _("Urgent SLA Compliance"),
                    urgent_compliance_display,
                    urgent_compliance,
                    "urgent",
                    "fa-bolt",
                ),
                self._build_laundry_performance_kpi(
                    "normal_sla_compliance",
                    _("Normal SLA Compliance"),
                    normal_compliance_display,
                    normal_compliance,
                    "success",
                    "fa-flag-o",
                ),
            ],
            "charts": {
                "on_time_vs_late": [
                    {
                        "key": "on_time",
                        "label": _("On Time"),
                        "value": len(on_time_orders),
                        "percentage": on_time_rate,
                        "tone": "success",
                    },
                    {
                        "key": "late",
                        "label": _("Late"),
                        "value": len(late_orders),
                        "percentage": self._laundry_percentage(len(late_orders), total_delivered),
                        "tone": "danger",
                    },
                ],
                "weekly_on_time": self._build_laundry_weekly_on_time_payload(
                    delivered_orders,
                    period_bounds["timezone"],
                ),
                "by_worker": worker_rows,
                "by_branch": branch_rows,
                "by_priority": priority_rows,
            },
            "worker_rows": worker_rows,
            "branch_rows": branch_rows,
            "priority_rows": priority_rows,
        }

    @api.model
    def _get_laundry_performance_period_bounds(self, period, date_from=False, date_to=False):
        timezone = pytz.timezone(
            self.env.user.tz
            or self.env.company.partner_id.tz
            or self.env.company.resource_calendar_id.tz
            or "UTC"
        )
        today = fields.Date.context_today(self)
        if period == "today":
            start_date = today
            end_date_exclusive = today + timedelta(days=1)
        elif period == "week":
            start_date = today - timedelta(days=today.weekday())
            end_date_exclusive = start_date + timedelta(days=7)
        elif period == "custom":
            start_date = fields.Date.to_date(date_from) if date_from else today
            end_date = fields.Date.to_date(date_to) if date_to else start_date
            if end_date < start_date:
                start_date, end_date = end_date, start_date
            end_date_exclusive = end_date + timedelta(days=1)
        else:
            start_date = today.replace(day=1)
            end_date_exclusive = (
                start_date.replace(year=start_date.year + 1, month=1)
                if start_date.month == 12
                else start_date.replace(month=start_date.month + 1)
            )

        local_start = timezone.localize(datetime.combine(start_date, time.min))
        local_end = timezone.localize(datetime.combine(end_date_exclusive, time.min))
        start_utc = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = local_end.astimezone(pytz.UTC).replace(tzinfo=None)
        return {
            "timezone": timezone,
            "start_date": start_date,
            "end_date": end_date_exclusive - timedelta(days=1),
            "start_utc": fields.Datetime.to_string(start_utc),
            "end_utc": fields.Datetime.to_string(end_utc),
        }

    @api.model
    def _build_laundry_performance_kpi(self, key, label, display_value, value, tone, icon):
        return {
            "key": key,
            "label": label,
            "display_value": display_value,
            "value": value,
            "tone": tone,
            "icon": icon,
        }

    @api.model
    def _build_laundry_performance_group_payload(self, orders, key_getter, label_getter):
        groups = {}
        for order in orders:
            key = key_getter(order)
            if key not in groups:
                groups[key] = {
                    "key": str(key),
                    "label": label_getter(order),
                    "orders": self.browse(),
                }
            groups[key]["orders"] |= order

        rows = []
        for group in groups.values():
            group_orders = group["orders"]
            on_time_orders = group_orders.filtered("x_laundry_delivered_on_time")
            late_orders = group_orders - on_time_orders
            processing_minutes = [
                minutes
                for minutes in (
                    self._get_laundry_processing_minutes(order)
                    for order in group_orders
                )
                if minutes is not False
            ]
            delay_minutes = [self._get_laundry_delay_minutes(order) for order in late_orders]
            on_time_percentage = self._laundry_percentage(len(on_time_orders), len(group_orders))
            average_processing = self._laundry_average(processing_minutes)
            average_delay = self._laundry_average(delay_minutes)
            rows.append({
                "key": group["key"],
                "label": group["label"],
                "delivered_orders": len(group_orders),
                "delivered_on_time": len(on_time_orders),
                "delivered_late": len(late_orders),
                "overdue_orders": len(late_orders),
                "on_time_percentage": on_time_percentage,
                "on_time_percentage_display": self._format_laundry_percentage(on_time_percentage),
                "average_processing_minutes": average_processing,
                "average_processing_display": self._format_laundry_duration(average_processing),
                "average_delay_minutes": average_delay,
                "average_delay_display": self._format_laundry_duration(average_delay),
            })
        return sorted(
            rows,
            key=lambda row: (
                -row["delivered_orders"],
                -row["on_time_percentage"],
                row["label"] or "",
            ),
        )

    @api.model
    def _build_laundry_weekly_on_time_payload(self, orders, timezone):
        weeks = {}
        for order in orders:
            if not order.x_laundry_delivered_on:
                continue
            delivered_on = self._ensure_aware_utc(order.x_laundry_delivered_on)
            local_delivered = delivered_on.astimezone(timezone)
            week_start = local_delivered.date() - timedelta(days=local_delivered.weekday())
            if week_start not in weeks:
                weeks[week_start] = {"total": 0, "on_time": 0}
            weeks[week_start]["total"] += 1
            if order.x_laundry_delivered_on_time:
                weeks[week_start]["on_time"] += 1
        return [
            {
                "key": fields.Date.to_string(week_start),
                "label": format_date(self.env, week_start, date_format="MMM d"),
                "value": self._laundry_percentage(values["on_time"], values["total"]),
                "display_value": self._format_laundry_percentage(
                    self._laundry_percentage(values["on_time"], values["total"])
                ),
                "delivered_orders": values["total"],
            }
            for week_start, values in sorted(weeks.items())
        ]

    @api.model
    def _get_laundry_processing_minutes(self, order):
        received_history = order.x_laundry_status_history_ids.filtered(
            lambda history: history.new_status == "received" and history.changed_on
        )[:1]
        received_on = (
            received_history.changed_on
            if received_history and received_history.changed_on
            else order.date_order
        )
        delivered_on = order.x_laundry_delivered_on
        if not received_on or not delivered_on:
            return False
        return max(0, (delivered_on - received_on).total_seconds() / 60.0)

    @api.model
    def _get_laundry_delay_minutes(self, order):
        if order.x_laundry_delay_minutes:
            return max(0, order.x_laundry_delay_minutes)
        if order.x_laundry_delivered_on and order.x_laundry_sla_deadline:
            return max(
                0,
                (order.x_laundry_delivered_on - order.x_laundry_sla_deadline).total_seconds() / 60.0,
            )
        return 0.0

    @api.model
    def _laundry_average(self, values):
        values = [value for value in values if value is not False]
        return sum(values) / len(values) if values else 0.0

    @api.model
    def _laundry_percentage(self, numerator, denominator):
        return (float(numerator) / float(denominator) * 100.0) if denominator else 0.0

    @api.model
    def _format_laundry_percentage(self, value):
        return "%s%%" % int(round(value or 0))

    @api.model
    def get_pending_laundry_board_data(self):
        orders = self.search(
            [
                ("state", "!=", "cancel"),
                ("laundry_status", "in", POS_ORDER_BOARD_LAUNDRY_STATUSES),
            ],
            order="date_order desc, id desc",
        )
        orders._ensure_laundry_labels()
        return {
            "statuses": self._build_laundry_status_payload(POS_ORDER_BOARD_LAUNDRY_STATUSES),
            "payment_statuses": self._build_payment_status_payload(POS_ORDER_BOARD_PAYMENT_STATUSES),
            "orders": orders._serialize_pending_laundry_board_orders(),
            "generated_at": fields.Datetime.now(),
        }

    @api.model
    def update_laundry_order_status(self, order_id, status):
        order = self.browse(order_id).exists()
        if not order:
            raise UserError(_("The selected order could not be found."))

        order.check_access_rights("write")
        order.check_access_rule("write")
        order._set_laundry_status(status)
        return order._serialize_pending_laundry_board_order()

    @api.model
    def mark_pending_laundry_order_ready_from_reference(self, reference):
        result = self.process_laundry_qr_scan(reference)
        if not result.get("success") and result.get("code") not in ("already_ready", "already_delivered"):
            raise UserError(result.get("message") or _("No laundry order matches this QR code."))

        payload = result.get("order") or {}
        payload.update({
            "scan_result": result.get("code"),
            "scanned_reference": result.get("scanned_value"),
        })
        return payload

    @api.model
    def process_laundry_qr_scan(self, qr_value):
        _logger.info("process_laundry_qr_scan: scanned=%s", qr_value)
        parsed = self._parse_laundry_qr_value(qr_value)
        normalized_value = parsed.get("normalized_value") or ""
        if not normalized_value:
            return self._build_qr_scan_response(
                success=False,
                code="invalid_qr",
                message=_("The QR code is invalid or empty."),
                scanned_value=normalized_value,
                parsed=parsed,
            )

        order = self.env["pos.order"]
        token = parsed.get("token")
        order_reference = parsed.get("order_reference")
        pos_reference = parsed.get("pos_reference")

        if token:
            order = self.search(
                [("x_qr_token", "=", token), ("state", "!=", "cancel")],
                order="date_order desc, id desc",
                limit=1,
            )
            if order and order_reference and not order._matches_scanned_reference(order_reference):
                return self._build_qr_scan_response(
                    success=False,
                    code="invalid_qr",
                    message=_("The QR code data does not match the expected order."),
                    order=order,
                    scanned_value=normalized_value,
                    parsed=parsed,
                )
            if order and pos_reference and (order.pos_reference or "").strip().lower() != pos_reference.strip().lower():
                return self._build_qr_scan_response(
                    success=False,
                    code="invalid_qr",
                    message=_("The QR code does not match this order's POS reference."),
                    order=order,
                    scanned_value=normalized_value,
                    parsed=parsed,
                )

        if not order:
            search_terms = []
            for term in (order_reference, pos_reference, normalized_value):
                normalized_term = (term or "").strip()
                if normalized_term and normalized_term not in search_terms:
                    search_terms.append(normalized_term)

            for term in search_terms:
                order = self.search(
                    [
                        ("state", "!=", "cancel"),
                        "|",
                        "|",
                        "|",
                        ("x_display_reference", "=ilike", term),
                        ("name", "=ilike", term),
                        ("pos_reference", "=ilike", term),
                        ("x_laundry_invoice_number", "=ilike", term),
                    ],
                    order="date_order desc, id desc",
                    limit=1,
                )
                if order:
                    break

        if not order:
            return self._build_qr_scan_response(
                success=False,
                code="order_not_found",
                message=_("No laundry order matches this code."),
                scanned_value=normalized_value,
                parsed=parsed,
            )

        order._ensure_laundry_qr_token()

        if token and order.x_qr_token != token:
            return self._build_qr_scan_response(
                success=False,
                code="invalid_qr",
                message=_("The QR security token does not match this order."),
                order=order,
                scanned_value=normalized_value,
                parsed=parsed,
            )

        order._lock_laundry_workflow_rows()
        status = order._normalize_laundry_status(order.laundry_status or order.x_laundry_status or "received")
        if status == "delivered":
            return self._build_qr_scan_response(
                success=False,
                code="already_delivered",
                message=_("This order has already been delivered."),
                order=order,
                scanned_value=normalized_value,
                parsed=parsed,
            )
        target_status = order._get_next_laundry_scan_status(status)
        if not target_status:
            return self._build_qr_scan_response(
                success=False,
                code="invalid_status_transition",
                message=_("This order cannot be moved to the next stage by QR."),
                order=order,
                scanned_value=normalized_value,
                parsed=parsed,
            )

        previous_label = order._get_laundry_status_text(status)["label"]
        target_label = order._get_laundry_status_text(target_status)["label"]
        if target_status == "delivered" and order._get_laundry_payment_status() != "paid":
            return self._build_qr_scan_response(
                success=False,
                code="payment_required",
                message=order._get_laundry_delivery_payment_required_message(),
                order=order,
                scanned_value=normalized_value,
                parsed=parsed,
            )
        order._set_laundry_status(target_status)
        return self._build_qr_scan_response(
            success=True,
            code="updated",
            message=_("Order status updated from %(old_status)s to %(new_status)s")
            % {
                "old_status": previous_label,
                "new_status": target_label,
            },
            order=order,
            scanned_value=normalized_value,
            parsed=parsed,
        )

    @api.model
    def _get_laundry_dashboard_statuses(self):
        return self._build_laundry_status_payload(DASHBOARD_LAUNDRY_STATUSES)

    @api.model
    def _get_laundry_status_text(self, status):
        texts = {
            "received": {
                "label": _("Received"),
                "description": _("Orders received and waiting for service"),
            },
            "ready": {
                "label": _("Ready"),
                "description": _("Completed orders ready for customer delivery"),
            },
            "delivered": {
                "label": _("Delivered"),
                "description": _("Orders delivered to the customer"),
            },
        }
        return texts.get(status, {"label": status, "description": ""})

    @api.model
    def _get_payment_status_label(self, status):
        return {
            "unpaid": _("Unpaid"),
            "partial": _("Partially Paid"),
            "paid": _("Paid"),
            "refunded": _("Refunded"),
            "cancelled": _("Cancelled"),
        }.get(status, status)

    @api.model
    def _get_laundry_priority_label(self, priority):
        return {
            "normal": _("Normal"),
            "urgent": _("Urgent"),
        }.get(priority, priority or "")

    @api.model
    def _get_laundry_sla_status_label(self, status):
        return {
            "on_track": _("On Track"),
            "due_soon": _("Due Soon"),
            "overdue": _("Overdue"),
            "delivered_on_time": _("Delivered On Time"),
            "delivered_late": _("Delivered Late"),
        }.get(status, status or "")

    @api.model
    def _get_laundry_status_action_label(self, current_status, target_status):
        return {
            ("received", "ready"): _("Mark Ready"),
            ("ready", "delivered"): _("Confirm Delivery"),
        }.get((current_status, target_status), self._get_laundry_status_text(target_status)["label"])

    @api.model
    def _build_laundry_status_payload(self, status_keys):
        statuses = []
        for key in status_keys:
            meta = LAUNDRY_STATUS_META[key]
            text = self._get_laundry_status_text(key)
            statuses.append({
                "key": key,
                "label": text["label"],
                "icon": meta["icon"],
                "color": meta["color"],
                "surface": meta.get("surface", "#ffffff"),
                "badge": meta.get("badge", meta["color"]),
                "description": text["description"],
                "sequence": meta["sequence"],
            })
        return statuses

    @api.model
    def _build_payment_status_payload(self, status_keys):
        statuses = []
        for sequence, key in enumerate(status_keys, start=1):
            meta = PAYMENT_STATUS_META[key]
            statuses.append({
                "key": key,
                "label": self._get_payment_status_label(key),
                "color": meta["color"],
                "surface": meta.get("surface", "#f8fafc"),
                "sequence": sequence * 10,
            })
        return statuses

    def _serialize_laundry_dashboard_orders(self):
        return [order._serialize_laundry_dashboard_order() for order in self]

    def _serialize_laundry_sla_performance_dashboard_orders(self):
        return [order._serialize_laundry_sla_performance_dashboard_order() for order in self]

    def _serialize_pending_laundry_board_orders(self):
        return [order._serialize_pending_laundry_board_order() for order in self]

    def _get_laundry_item_preview(self, limit=3):
        self.ensure_one()
        intake = self.x_laundry_intake_id
        if intake:
            source_lines = intake.line_ids
            item_rows = [
                {
                    "name": line.product_name or _("Item"),
                    "qty": line.qty,
                    "details": [
                        value.strip()
                        for value in (line.selection_details or "").splitlines()
                        if value.strip()
                    ][:2],
                }
                for line in source_lines[:limit]
            ]
        else:
            source_lines = self.lines
            item_rows = [
                {
                    "name": line.product_id.display_name or _("Item"),
                    "qty": line.qty,
                    "details": [],
                }
                for line in source_lines[:limit]
            ]
        return {
            "items": item_rows,
            "total_items": sum(source_lines.mapped("qty")),
            "more_lines": max(0, len(source_lines) - len(item_rows)),
        }

    def _serialize_laundry_dashboard_order(self):
        self.ensure_one()
        dashboard_status = self._normalize_laundry_status(self.x_laundry_status)
        status_meta = LAUNDRY_STATUS_META[dashboard_status]
        status_text = self._get_laundry_status_text(dashboard_status)
        payment_status = self._get_laundry_payment_status()
        payment_meta = PAYMENT_STATUS_META.get(payment_status, PAYMENT_STATUS_META["unpaid"])
        partner_name = self.partner_id.name or _("Walk-in Customer")
        partner_phone = " ".join(
            value.strip()
            for value in [self.partner_id.mobile or "", self.partner_id.phone or ""]
            if value and value.strip()
        )
        current_status_history = self.x_laundry_status_history_ids.filtered(
            lambda line: line.new_status == dashboard_status
        )[:1]
        ready_status_history = self.x_laundry_status_history_ids.filtered(
            lambda line: line.new_status == "ready"
        )[:1]
        current_status_since = (
            fields.Datetime.to_string(current_status_history.changed_on)
            if current_status_history and current_status_history.changed_on
            else fields.Datetime.to_string(self.date_order) if self.date_order else False
        )
        ready_since = (
            fields.Datetime.to_string(ready_status_history.changed_on)
            if ready_status_history and ready_status_history.changed_on
            else False
        )
        item_preview = self._get_laundry_item_preview()
        label = self.x_laundry_label_ids[:1]
        accounting_reference = self.x_laundry_invoice_number or (
            self.account_move.name if self.account_move else ""
        )
        return {
            "id": self.id,
            "name": self.x_display_reference or self.name,
            "x_display_reference": self.x_display_reference or "",
            "account_move_name": accounting_reference,
            "invoice_number": accounting_reference,
            "x_laundry_invoice_number": accounting_reference,
            "partner_name": partner_name,
            "partner_phone": partner_phone,
            "amount_total": self.amount_total,
            "amount_paid": self.amount_paid,
            "amount_due": max(self.amount_total - self.amount_paid, 0.0),
            "currency_id": self.currency_id.id,
            "date_order": fields.Datetime.to_string(self.date_order) if self.date_order else False,
            "laundry_status": dashboard_status,
            "laundry_status_label": status_text["label"],
            "x_laundry_status": dashboard_status,
            "x_laundry_status_label": status_text["label"],
            "x_laundry_priority": self.x_laundry_priority or "",
            "x_laundry_priority_label": self._get_laundry_priority_label(self.x_laundry_priority),
            "x_payment_status": payment_status,
            "x_payment_status_label": self._get_payment_status_label(payment_status),
            "x_laundry_sla_deadline": (
                fields.Datetime.to_string(self.x_laundry_sla_deadline)
                if self.x_laundry_sla_deadline
                else False
            ),
            "x_laundry_sla_status": self.x_laundry_sla_status or "",
            "x_laundry_sla_status_label": self._get_laundry_sla_status_label(
                self.x_laundry_sla_status
            ),
            "x_laundry_sla_remaining_display": self.x_laundry_sla_remaining_display or "",
            "x_laundry_worker_id": self.x_laundry_worker_id.id or False,
            "x_laundry_worker_name": self.x_laundry_worker_id.name or "",
            "status_color": status_meta["color"],
            "status_surface": status_meta.get("surface", "#ffffff"),
            "status_badge": status_meta.get("badge", status_meta["color"]),
            "payment_color": payment_meta["color"],
            "payment_surface": payment_meta.get("surface", "#f8fafc"),
            "priority_color": LAUNDRY_PRIORITY_META.get(
                self.x_laundry_priority,
                LAUNDRY_PRIORITY_META["normal"],
            )["color"],
            "priority_surface": LAUNDRY_PRIORITY_META.get(
                self.x_laundry_priority,
                LAUNDRY_PRIORITY_META["normal"],
            )["surface"],
            "sla_color": LAUNDRY_SLA_STATUS_META.get(
                self.x_laundry_sla_status,
                LAUNDRY_SLA_STATUS_META["on_track"],
            )["color"],
            "sla_surface": LAUNDRY_SLA_STATUS_META.get(
                self.x_laundry_sla_status,
                LAUNDRY_SLA_STATUS_META["on_track"],
            )["surface"],
            "current_status_since": current_status_since,
            "ready_since": ready_since,
            "item_preview": item_preview["items"],
            "total_items": item_preview["total_items"],
            "more_item_lines": item_preview["more_lines"],
            "label_id": label.id if label else False,
            "label_state": label.state if label else "pending",
        }

    def _serialize_laundry_sla_performance_dashboard_order(self):
        self.ensure_one()
        payload = self._serialize_laundry_dashboard_order()
        received_history = self.x_laundry_status_history_ids.filtered(
            lambda line: line.new_status == "received" and line.changed_on
        )[:1]
        current_history = self.x_laundry_status_history_ids.filtered(
            lambda line: line.new_status == payload["x_laundry_status"] and line.changed_on
        )
        open_current_history = current_history.filtered(lambda line: not line.exited_on)[:1]
        current_history = open_current_history or current_history[:1]
        payload.update({
            "config_id": self.config_id.id or False,
            "config_name": self.config_id.display_name or "",
            "received_on": (
                fields.Datetime.to_string(received_history.changed_on)
                if received_history and received_history.changed_on
                else payload["date_order"]
            ),
            "current_stage_duration_display": (
                current_history.duration_display if current_history else ""
            ),
            "x_laundry_delivered_on": (
                fields.Datetime.to_string(self.x_laundry_delivered_on)
                if self.x_laundry_delivered_on
                else False
            ),
            "x_laundry_delivered_on_time": bool(self.x_laundry_delivered_on_time),
        })
        return payload

    def _serialize_pending_laundry_board_order(self):
        self.ensure_one()
        self._ensure_laundry_qr_token()
        payload = self._serialize_laundry_dashboard_order()
        payload.update({
            "pos_reference": self.pos_reference or "",
            "x_display_reference": self.x_display_reference or "",
            "x_laundry_intake_id": self.x_laundry_intake_id.id or 0,
            "x_laundry_intake_ref": self.x_laundry_intake_id.name or "",
            "x_qr_token": self.x_qr_token or "",
            "qr_value": self._build_laundry_qr_payload(),
            "qr_barcode_url": self._get_laundry_qr_barcode_url(),
            "available_actions": self._get_pending_laundry_status_actions(payload["laundry_status"]),
        })
        return payload

    @api.model
    def _get_pending_laundry_status_actions(self, current_status):
        actions = []
        for target_status in PENDING_BOARD_STATUS_TRANSITIONS.get(current_status, ()):
            meta = LAUNDRY_STATUS_META[target_status]
            actions.append({
                "key": target_status,
                "label": self._get_laundry_status_action_label(current_status, target_status),
                "icon": meta["icon"],
                "color": meta["color"],
            })
        return actions

    def _export_for_ui(self, order):
        result = super()._export_for_ui(order)
        accounting_reference = order.x_laundry_invoice_number or (
            order.account_move.name if order.account_move else ""
        )
        result.update({
            "name": order.x_display_reference or order.pos_reference or order.name,
            "pos_reference": order.pos_reference or "",
            "laundry_intake_id": order.x_laundry_intake_id.id or 0,
            "laundry_intake_name": order.x_display_reference or order.x_laundry_intake_id.name or "",
            "x_display_reference": order.x_display_reference or "",
            "account_move_name": accounting_reference,
            "invoice_number": accounting_reference,
            "x_laundry_invoice_number": accounting_reference,
            "x_qr_token": order.x_qr_token or "",
            "laundry_status": order.laundry_status or "received",
            "x_laundry_status": order.x_laundry_status or "received",
            "laundry_priority": order.x_laundry_priority or "normal",
            "x_laundry_priority": order.x_laundry_priority or "normal",
        })
        return result

    @api.model
    def create_from_ui(self, orders, draft=False):
        result = super().create_from_ui(orders, draft=draft)
        if not result:
            return result

        orders_by_id = {
            order.id: order
            for order in self.browse([row["id"] for row in result if row.get("id")]).exists()
        }

        for row in result:
            order = orders_by_id.get(row.get("id"))
            if not order:
                continue
            display_reference = order.x_display_reference or order.x_laundry_intake_id.name or ""
            accounting_reference = order.x_laundry_invoice_number or (
                order.account_move.name if order.account_move else ""
            )
            row["name"] = display_reference or order.name or row.get("name") or row.get("pos_reference")
            row["x_display_reference"] = display_reference
            row["laundry_intake_name"] = display_reference
            row["account_move_name"] = accounting_reference
            row["invoice_number"] = accounting_reference
            row["x_laundry_invoice_number"] = accounting_reference

        return result

    @api.model
    def create_sale_quotation_from_ui(self, payload):
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("You are not allowed to create quotations from POS."))

        payload = payload or {}
        partner_id = payload.get("partner_id")
        if not partner_id:
            raise UserError(_("Select a customer before creating a quotation."))

        raw_lines = payload.get("lines") or []
        if not raw_lines:
            raise UserError(_("Add at least one product before creating a quotation."))

        company = self.env["res.company"].browse(payload.get("company_id") or self.env.company.id).exists()
        if not company:
            company = self.env.company

        partner = self.env["res.partner"].browse(partner_id).exists()
        if not partner:
            raise UserError(_("The selected customer could not be found."))

        sale_order_vals = {
            "partner_id": partner.id,
            "company_id": company.id,
            "origin": payload.get("order_name") or False,
            "client_order_ref": payload.get("customer_reference") or False,
        }

        pricelist_id = payload.get("pricelist_id")
        if pricelist_id:
            sale_order_vals["pricelist_id"] = pricelist_id

        salesperson_id = payload.get("salesperson_id")
        if salesperson_id:
            sale_order_vals["user_id"] = salesperson_id

        order_lines = []
        Product = self.env["product.product"].with_company(company).sudo()
        for line in raw_lines:
            product = Product.browse(line.get("product_id")).exists()
            quantity = float(line.get("qty") or 0)
            if not product or quantity <= 0:
                continue

            description = (line.get("description") or product.get_product_multiline_description_sale() or product.display_name or "").strip()
            customer_note = (line.get("customer_note") or "").strip()
            if customer_note:
                description = f"{description}\n{customer_note}" if description else customer_note

            order_lines.append(Command.create({
                "product_id": product.id,
                "product_uom_qty": quantity,
                "price_unit": float(line.get("price_unit") or 0),
                "discount": float(line.get("discount") or 0),
                "name": description or product.display_name,
            }))

        if not order_lines:
            raise UserError(_("There are no valid order lines to create a quotation."))

        sale_order_vals["order_line"] = order_lines
        sale_order = self.env["sale.order"].with_company(company).sudo().create(sale_order_vals)

        return {
            "id": sale_order.id,
            "name": sale_order.name,
            "state": sale_order.state,
        }


class PosOrderLaundryStatusHistory(models.Model):
    _name = "pos.order.laundry.status.history"
    _description = "POS Laundry Order Status History"
    _order = "changed_on desc, id desc"

    order_id = fields.Many2one("pos.order", string="POS Order", required=True, ondelete="cascade")
    old_status = fields.Selection(selection=LAUNDRY_STATUS_SELECTION, string="From Status")
    new_status = fields.Selection(selection=LAUNDRY_STATUS_SELECTION, string="To Status", required=True)
    changed_by_id = fields.Many2one(
        "res.users",
        string="Changed By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    changed_on = fields.Datetime(string="Changed On", default=fields.Datetime.now, required=True, readonly=True)
    exited_on = fields.Datetime(string="Exited On", readonly=True)
    duration_seconds = fields.Integer(string="Duration (Seconds)", readonly=True)
    duration_display = fields.Char(
        string="Duration in Stage",
        compute="_compute_duration_display",
    )
    company_id = fields.Many2one(
        "res.company",
        related="order_id.company_id",
        string="Company",
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends("changed_on", "exited_on", "duration_seconds")
    def _compute_duration_display(self):
        now = fields.Datetime.now()
        for history in self:
            seconds = history.duration_seconds
            if not history.exited_on and history.changed_on:
                seconds = max(0, int((now - history.changed_on).total_seconds()))
            if seconds < 60:
                history.duration_display = _("Less than a minute")
            elif seconds < 3600:
                minutes = seconds // 60
                history.duration_display = _("%(count)s min", count=minutes)
            elif seconds < 86400:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                history.duration_display = _(
                    "%(hours)s h %(minutes)s min",
                    hours=hours,
                    minutes=minutes,
                )
            else:
                days = seconds // 86400
                hours = (seconds % 86400) // 3600
                history.duration_display = _(
                    "%(days)s d %(hours)s h",
                    days=days,
                    hours=hours,
                )

    @api.model
    def _backfill_durations(self):
        """Close historical stages using the following transition timestamp."""
        histories = self.sudo().search([], order="order_id, changed_on, id")
        by_order = {}
        for history in histories:
            by_order.setdefault(history.order_id.id, []).append(history)
        for order_histories in by_order.values():
            for index, history in enumerate(order_histories[:-1]):
                next_history = order_histories[index + 1]
                if not history.exited_on:
                    history.write(
                        {
                            "exited_on": next_history.changed_on,
                            "duration_seconds": max(
                                0,
                                int(
                                    (
                                        next_history.changed_on - history.changed_on
                                    ).total_seconds()
                                ),
                            ),
                        }
                    )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise UserError(_("Status history can only be created by the workflow service."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise UserError(_("Status history is immutable."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Status history is immutable."))
        return super().unlink()
