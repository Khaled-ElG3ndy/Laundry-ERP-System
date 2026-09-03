from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class PosSession(models.Model):
    _inherit = "pos.session"

    def _is_laundry_deferred_draft_order(self, order):
        """Return True only for legitimate laundry intake drafts kept for later payment."""
        if order.state != "draft":
            return False

        if not order.x_laundry_intake_id:
            return False

        rounding = order.currency_id.rounding or order.company_id.currency_id.rounding or 0.01
        if not float_is_zero(order.amount_paid or 0.0, precision_rounding=rounding):
            return False

        if any(
            not float_is_zero(payment.amount or 0.0, precision_rounding=rounding)
            for payment in order.payment_ids
        ):
            return False

        return True

    def _get_blocking_draft_orders(self):
        self.ensure_one()
        draft_orders = self.order_ids.filtered(lambda order: order.state == "draft")
        allowed_laundry_drafts = draft_orders.filtered(self._is_laundry_deferred_draft_order)
        return draft_orders - allowed_laundry_drafts

    def action_pos_session_closing_control(
        self,
        balancing_account=False,
        amount_to_balance=0,
        bank_payment_method_diffs=None,
    ):
        bank_payment_method_diffs = bank_payment_method_diffs or {}
        for session in self:
            blocking_draft_orders = session._get_blocking_draft_orders()
            if blocking_draft_orders:
                raise UserError(
                    _(
                        "You cannot close the POS when orders are still in draft: %s",
                        ", ".join(blocking_draft_orders.mapped("name")),
                    )
                )
            if session.state == "closed":
                raise UserError(_("This session is already closed."))
            stop_at = session.stop_at or fields.Datetime.now()
            session.write({"state": "closing_control", "stop_at": stop_at})
            if not session.config_id.cash_control:
                return session.action_pos_session_close(
                    balancing_account,
                    amount_to_balance,
                    bank_payment_method_diffs,
                )
            if session.rescue and session.config_id.cash_control:
                default_cash_payment_method_id = session.payment_method_ids.filtered(
                    lambda pm: pm.type == "cash"
                )[0]
                orders = session._get_closed_orders()
                total_cash = sum(
                    orders.payment_ids.filtered(
                        lambda payment: payment.payment_method_id == default_cash_payment_method_id
                    ).mapped("amount")
                ) + session.cash_register_balance_start

                session.cash_register_balance_end_real = total_cash

            return session.action_pos_session_validate(
                balancing_account,
                amount_to_balance,
                bank_payment_method_diffs,
            )

    def _check_if_no_draft_orders(self):
        for session in self:
            blocking_draft_orders = session._get_blocking_draft_orders()
            if blocking_draft_orders:
                raise UserError(
                    _(
                        "There are still orders in draft state in the session. "
                        "Pay or cancel the following orders to validate the session:\n%s",
                        ", ".join(blocking_draft_orders.mapped("name")),
                    )
                )
        return True

    def _cannot_close_session(self, bank_payment_method_diffs=None):
        """Keep core close checks while allowing only validated laundry deferred drafts."""
        bank_payment_method_diffs = bank_payment_method_diffs or {}

        for session in self:
            blocking_draft_orders = session._get_blocking_draft_orders()
            if blocking_draft_orders:
                return {
                    "successful": False,
                    "message": _(
                        "You cannot close the POS when orders are still in draft: %s",
                        ", ".join(blocking_draft_orders.mapped("name")),
                    ),
                    "redirect": False,
                }

            if session.state == "closed":
                return {
                    "successful": False,
                    "type": "alert",
                    "title": "Session already closed",
                    "message": _(
                        "The session has been already closed by another User. "
                        "All sales completed in the meantime have been saved in a "
                        "Rescue Session, which can be reviewed anytime and posted "
                        "to Accounting from Point of Sale's dashboard."
                    ),
                    "redirect": True,
                }

            if bank_payment_method_diffs:
                no_loss_account = self.env["account.journal"]
                no_profit_account = self.env["account.journal"]
                for payment_method in self.env["pos.payment.method"].browse(
                    bank_payment_method_diffs.keys()
                ):
                    journal = payment_method.journal_id
                    compare_to_zero = session.currency_id.compare_amounts(
                        bank_payment_method_diffs.get(payment_method.id),
                        0,
                    )
                    if compare_to_zero == -1 and not journal.loss_account_id:
                        no_loss_account |= journal
                    elif compare_to_zero == 1 and not journal.profit_account_id:
                        no_profit_account |= journal
                message = ""
                if no_loss_account:
                    message += _(
                        "Need loss account for the following journals to post the lost amount: %s\n",
                        ", ".join(no_loss_account.mapped("name")),
                    )
                if no_profit_account:
                    message += _(
                        "Need profit account for the following journals to post the gained amount: %s",
                        ", ".join(no_profit_account.mapped("name")),
                    )
                if message:
                    return {"successful": False, "message": message, "redirect": False}

        return None

    @api.model
    def _ensure_pos_bilingual_record_names(self):
        """Complete translations for POS records created outside module data."""

        translations = {
            "pos.config": [
                (
                    {"مغاسل رغوة بلس", "Foam Plus Laundry"},
                    "Foam Plus Laundry",
                    "مغاسل رغوة بلس",
                ),
            ],
            "pos.category": [
                ({"الملابس", "Clothes"}, "Clothes", "الملابس"),
                ({"المفروشات", "Bedding"}, "Bedding", "المفروشات"),
                ({"المنزل", "Home"}, "Home", "المنزل"),
                ({"منتجات دينية", "Religious Items"}, "Religious Items", "منتجات دينية"),
            ],
            "pos.payment.method": [
                ({"Cash", "نقدي"}, "Cash", "نقدي"),
                ({"Bank", "بطاقة بنكية"}, "Bank", "بطاقة بنكية"),
                ({"Customer Account", "حساب العميل"}, "Customer Account", "حساب العميل"),
            ],
            "product.attribute": [
                ({"نوع النشاء", "Starch Type"}, "Starch Type", "نوع النشاء"),
            ],
            "product.attribute.value": [
                ({"نشاء", "Starch"}, "Starch", "نشاء"),
                ({"بدون نشاء", "No Starch"}, "No Starch", "بدون نشاء"),
            ],
        }

        for model_name, name_groups in translations.items():
            records = self.env[model_name].with_context(active_test=False).search([])
            for record in records:
                english_name = record.with_context(lang="en_US").name or ""
                arabic_name = record.with_context(lang="ar_001").name or ""
                for candidates, english, arabic in name_groups:
                    if english_name in candidates or arabic_name in candidates:
                        english_record = record.with_context(lang="en_US")
                        arabic_record = record.with_context(lang="ar_001")
                        if model_name == "pos.payment.method":
                            # Updating a translated label is safe while a POS
                            # session is open, but the model's public write()
                            # blocks every field except sequence.
                            models.Model.write(english_record, {"name": english})
                            models.Model.write(arabic_record, {"name": arabic})
                        else:
                            english_record.write({"name": english})
                            arabic_record.write({"name": arabic})
                        break
        return True

    def _get_pos_ui_pos_config(self, params):
        config = super()._get_pos_ui_pos_config(params)
        config["laundry_require_ten_digit_phone"] = (
            self.config_id.laundry_require_ten_digit_phone
        )
        config["laundry_sla_calendar_id"] = (
            self.config_id.laundry_sla_calendar_id.id
            if self.config_id.laundry_sla_calendar_id
            else False
        )
        config["laundry_local_order_reset_token"] = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("pos_laundry_receipt.local_order_reset_token", "")
        )
        return config

    def _flatten_pos_partner_ids(self, value):
        ids = []

        def collect(item):
            if isinstance(item, bool) or item in (None, False):
                return
            if isinstance(item, int):
                ids.append(item)
                return
            if isinstance(item, str):
                if item.isdigit():
                    ids.append(int(item))
                return
            if isinstance(item, (list, tuple, set)):
                for child in item:
                    collect(child)

        collect(value)
        return ids

    def _normalize_pos_partner_domain(self, domain):
        normalized = []
        for item in domain or []:
            if isinstance(item, str):
                normalized.append(item)
                continue

            if not isinstance(item, (list, tuple)):
                normalized.append(item)
                continue

            if len(item) >= 3 and item[0] == "id":
                operator = item[1]
                value = item[2]
                if operator in ("in", "not in"):
                    value = self._flatten_pos_partner_ids(value)
                elif operator in ("=", "!=") and isinstance(value, (list, tuple)):
                    flattened = self._flatten_pos_partner_ids(value)
                    value = flattened[0] if flattened else False
                normalized.append([item[0], operator, value])
                continue

            normalized.append(self._normalize_pos_partner_domain(item))
        return normalized

    def get_pos_ui_res_partner_by_params(self, custom_search_params):
        if custom_search_params and custom_search_params.get("domain"):
            custom_search_params = dict(custom_search_params)
            custom_search_params["domain"] = self._normalize_pos_partner_domain(
                custom_search_params["domain"]
            )
        return super().get_pos_ui_res_partner_by_params(custom_search_params)

    @api.model
    def get_pos_assets_version(self):
        """Public entry point for the POS asset watchdog.

        A till that was offline while a deploy happened cannot rely on the bus
        notification any more, because those are garbage collected after about
        two minutes. On reconnect the tab asks for this token and compares it
        with the one it booted with, so it notices the update on its own.
        """
        return self.env["ir.attachment"]._get_pos_bundle_version()
