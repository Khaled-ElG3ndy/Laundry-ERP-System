/** @odoo-module **/

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";

// The action the cashier asked for on the way out. Editing a service opens the
// laundry configurator, which is a popup of its own; rather than stack two large
// dialogs, this one closes and hands the request back to the product screen,
// which reopens the review once the edit is done. Quantity changes and removals
// need no second dialog, so those happen in place and the list updates itself.
export const PREVIEW_ACTION = {
    EDIT: "edit",
    NONE: "none",
};

export class OrderPreviewPopup extends AbstractAwaitablePopup {
    static template = "pos_right_panel.OrderPreviewPopup";
    static defaultProps = {
        // Enter must not confirm: the body is a list of controls, and a stray
        // keypress closing the review mid-check would be its own bug.
        confirmKey: false,
        cancelKey: "Escape",
    };

    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        this.requestedAction = { action: PREVIEW_ACTION.NONE, line: null };
    }

    // ── Direction ────────────────────────────────────────────────────────────
    // point_of_sale.index ships a bare <html> and pos_app.scss pins
    // `.pos { direction: ltr }`, so nothing upstream declares a direction. The
    // dialog states its own, exactly like the cart lines do.
    get textDirection() {
        return localization.direction === "rtl" ? "rtl" : "ltr";
    }

    // ── Data ─────────────────────────────────────────────────────────────────
    get order() {
        return this.pos?.get_order?.() || null;
    }

    get lines() {
        const order = this.order;
        if (!order) {
            return [];
        }

        return order.get_orderlines().map((line, index) => ({
            line,
            index,
            key: line.cid || index,
            data: line.getDisplayData(),
            isSelected: order.get_selected_orderline() === line,
        }));
    }

    get hasLines() {
        return this.lines.length > 0;
    }

    get itemCount() {
        return this.lines.length;
    }

    get customerName() {
        return this.order?.get_partner()?.name || _t("Walk-in customer");
    }

    get orderReference() {
        return this.order?.name || "";
    }

    formatCurrency(amount) {
        return this.env.utils.formatCurrency(amount || 0);
    }

    get totalText() {
        return this.formatCurrency(this.order?.get_total_with_tax());
    }

    get taxText() {
        return this.formatCurrency(this.order?.get_total_tax());
    }

    get subtotalText() {
        return this.formatCurrency(this.order?.get_total_without_tax());
    }

    get uiText() {
        return {
            title: _t("Review Order"),
            empty: _t("This order has no items yet."),
            items: _t("Items"),
            subtotal: _t("Subtotal"),
            taxes: _t("Taxes"),
            total: _t("Total"),
            close: _t("Close"),
            edit: _t("Edit service"),
            remove: _t("Remove item"),
            increase: _t("Increase quantity"),
            decrease: _t("Decrease quantity"),
        };
    }

    // ── Actions ──────────────────────────────────────────────────────────────
    selectLine(line) {
        this.order?.select_orderline(line);
    }

    changeQuantity(line, delta) {
        const next = (line.get_quantity() || 0) + delta;

        // One is the floor: taking a line to zero is what the remove button is
        // for, and a zero-quantity line left in the cart reads as a mistake.
        if (next < 1) {
            return;
        }

        try {
            line.set_quantity(next);
        } catch {
            // assert_editable throws on an order that is already being paid.
            // The cart is the wrong place to surface that, so leave the line
            // untouched and let the payment screen explain itself.
            return;
        }

        this.order?.select_orderline(line);
    }

    removeLine(line) {
        const order = this.order;
        if (!order) {
            return;
        }

        try {
            order.removeOrderline(line);
        } catch {
            return;
        }
    }

    editLine(line) {
        this.requestedAction = { action: PREVIEW_ACTION.EDIT, line };
        this.confirm();
    }

    async getPayload() {
        return this.requestedAction;
    }
}
