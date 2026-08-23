from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _get_no_pos_overpayment_message(self):
        language = (self.env.user.lang or self.env.context.get("lang") or "").lower()
        if language.startswith("ar"):
            return "يجب أن يكون المبلغ المدفوع مساويا لإجمالي الفاتورة. لا يسمح بدفع مبلغ زائد أو تسجيل باقي."
        return (
            "The paid amount must exactly match the invoice total. "
            "Overpayment and change are not allowed."
        )

    @api.model
    def _check_no_pos_overpayment_from_ui(self, order_data, draft=False):
        if draft:
            return

        amount_total = float(order_data.get("amount_total") or 0.0)
        if amount_total <= 0:
            return

        session = self.env["pos.session"].browse(order_data.get("pos_session_id"))
        currency = session.currency_id or self.env.company.currency_id
        rounding = currency.rounding or 0.01
        amount_return = float(order_data.get("amount_return") or 0.0)
        payment_total = sum(
            float(payment[2].get("amount") or 0.0)
            for payment in order_data.get("statement_ids") or []
            if len(payment) >= 3 and isinstance(payment[2], dict)
        )

        if not float_is_zero(amount_return, precision_rounding=rounding) or not float_is_zero(
            payment_total - amount_total,
            precision_rounding=rounding,
        ):
            raise UserError(self._get_no_pos_overpayment_message())

    @api.model
    def create_from_ui(self, orders, draft=False):
        for order in orders:
            self._check_no_pos_overpayment_from_ui(order.get("data") or {}, draft=draft)
        return super().create_from_ui(orders, draft=draft)
