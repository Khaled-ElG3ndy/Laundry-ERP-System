/** @odoo-module **/
import { Component } from "@odoo/owl";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { OrderlineCustomerNoteButton } from "@point_of_sale/app/screens/product_screen/control_buttons/customer_note_button/customer_note_button";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { onMounted, useRef, useState } from "@odoo/owl";

const SELECTED_ORDER_STORAGE_PREFIX = "pos_laundry_receipt_selected_order";
const LOCAL_ORDER_RESET_STORAGE_PREFIX = "pos_laundry_receipt_local_order_reset";

function removeLocalStorageKeysStartingWith(prefix) {
    if (typeof window === "undefined" || !window.localStorage || !prefix) {
        return;
    }
    for (let index = window.localStorage.length - 1; index >= 0; index--) {
        const key = window.localStorage.key(index);
        if (key && key.startsWith(prefix)) {
            window.localStorage.removeItem(key);
        }
    }
}

function hasPaymentLines(order) {
    return Boolean(order?.paymentlines && order.paymentlines.length > 0);
}

function isBlankStartupOrder(order) {
    return Boolean(
        order &&
        order.get_orderlines().length === 0 &&
        !hasPaymentLines(order) &&
        !order.server_id &&
        !order.finalized &&
        !order.laundry_intake_id
    );
}

function isCompletedLaundryIntakeDraft(order) {
    return Boolean(
        order &&
        order.laundry_intake_id &&
        !order.finalized &&
        !hasPaymentLines(order)
    );
}

function isRestorableOrder(order) {
    return Boolean(
        order &&
        !order.finalized &&
        !isBlankStartupOrder(order) &&
        !isCompletedLaundryIntakeDraft(order) &&
        (order.get_orderlines().length > 0 || hasPaymentLines(order) || order.server_id)
    );
}

function getSelectedOrderStorageKey(pos) {
    const configId = pos?.config?.id || "unknown";
    const sessionId = pos?.pos_session?.id || "unknown";
    return `${SELECTED_ORDER_STORAGE_PREFIX}_${configId}_${sessionId}`;
}

function getLocalOrderResetStorageKey(pos) {
    const configId = pos?.config?.id || "unknown";
    const configUuid = pos?.config?.uuid || "unknown";
    return `${LOCAL_ORDER_RESET_STORAGE_PREFIX}_${configId}_${configUuid}`;
}

function applyLocalOrderResetIfNeeded(pos) {
    const resetToken = String(pos?.config?.laundry_local_order_reset_token || "").trim();
    if (typeof window === "undefined" || !pos?.db || !resetToken) {
        return false;
    }

    const resetKey = getLocalOrderResetStorageKey(pos);
    if (window.localStorage.getItem(resetKey) === resetToken) {
        return false;
    }

    pos.db.remove_all_orders();
    pos.db.remove_all_unpaid_orders();
    pos.db.save("unpaid_orders_to_remove", []);
    pos.db.save("TO_REFUND_LINES", {});
    removeLocalStorageKeysStartingWith(SELECTED_ORDER_STORAGE_PREFIX);
    window.localStorage.setItem(resetKey, resetToken);
    return true;
}

function getRememberedSelectedOrderUid(pos) {
    if (typeof window === "undefined" || !pos) {
        return "";
    }
    return window.localStorage.getItem(getSelectedOrderStorageKey(pos)) || "";
}

function isRefundOrder(order) {
    if (!order) {
        return false;
    }

    const totalWithTax = Number(order.get_total_with_tax?.() ?? 0);
    const totalPaid = Number(order.get_total_paid?.() ?? 0);
    const change = Number(order.get_change?.() ?? 0);

    return totalWithTax < 0 || totalPaid < 0 || change < 0;
}

function rememberSelectedOrder(pos, order) {
    if (typeof window === "undefined" || !pos) {
        return;
    }

    if (!order?.uid || isCompletedLaundryIntakeDraft(order)) {
        window.localStorage.removeItem(getSelectedOrderStorageKey(pos));
        return;
    }

    window.localStorage.setItem(getSelectedOrderStorageKey(pos), order.uid);
}

export class LaundryCustomerNotePopup extends AbstractAwaitablePopup {
    static template = "pos_laundry_receipt.LaundryCustomerNotePopup";
    static classes = ["o_laundry_receipt_popup_wrapper"];
    static defaultProps = {
        title: _t("Add Customer Note"),
        confirmText: _t("Add"),
        cancelText: _t("Cancel"),
        startingValue: "",
        placeholder: _t("Add an item note here..."),
        subtitle: _t("Add a short, clear note for this item."),
    };

    setup() {
        super.setup();
        this.state = useState({
            inputValue: this.props.startingValue || "",
        });
        this.inputRef = useRef("input");
        onMounted(() => {
            this.inputRef.el?.focus();
        });
    }

    getPayload() {
        return this.state.inputValue || "";
    }
}

patch(PosStore.prototype, {
    async after_load_server_data() {
        applyLocalOrderResetIfNeeded(this);
        return super.after_load_server_data(...arguments);
    },

    set_start_order() {
        if (!this.orders.length) {
            const result = super.set_start_order(...arguments);
            rememberSelectedOrder(this, this.selectedOrder);
            return result;
        }

        if (this.selectedOrder && !isCompletedLaundryIntakeDraft(this.selectedOrder)) {
            rememberSelectedOrder(this, this.selectedOrder);
            return;
        }

        const rememberedUid = getRememberedSelectedOrderUid(this);
        const rememberedOrder = this.orders.find(
            (order) =>
                order.uid === rememberedUid &&
                (isBlankStartupOrder(order) || isRestorableOrder(order))
        );
        const firstRestorableOrder = [...this.orders].reverse().find((order) =>
            isRestorableOrder(order)
        );
        const emptyOrder = this.orders.find((order) => isBlankStartupOrder(order));

        this.selectedOrder =
            rememberedOrder ||
            firstRestorableOrder ||
            emptyOrder ||
            this.add_new_order();

        if (this.isOpenOrderShareable()) {
            this.ordersToUpdateSet.add(this.selectedOrder);
        }
        rememberSelectedOrder(this, this.selectedOrder);
    },

    loadOpenOrders(openOrders) {
        const rememberedUid = getRememberedSelectedOrderUid(this);
        let selectedOrder = this.selectedOrder;

        for (const json of openOrders) {
            const existingOrder = this.orders.find((order) => order.server_id === json.id);
            if (existingOrder) {
                continue;
            }

            this._createOrder(json);

            if (!selectedOrder) {
                selectedOrder = this.orders[this.orders.length - 1];
            }
        }

        if (isCompletedLaundryIntakeDraft(selectedOrder)) {
            selectedOrder = null;
        }

        const rememberedOrder = this.orders.find(
            (order) =>
                order.uid === rememberedUid &&
                (isBlankStartupOrder(order) || isRestorableOrder(order))
        );
        const firstRestorableOrder = [...this.orders].reverse().find((order) =>
            isRestorableOrder(order)
        );
        const emptyOrder = this.orders.find((order) => isBlankStartupOrder(order));

        if (rememberedOrder) {
            selectedOrder = rememberedOrder;
        } else if (!selectedOrder || isBlankStartupOrder(selectedOrder)) {
            selectedOrder =
                firstRestorableOrder ||
                emptyOrder ||
                selectedOrder;
        }

        if (!selectedOrder || isCompletedLaundryIntakeDraft(selectedOrder)) {
            selectedOrder = emptyOrder || this.add_new_order();
        }

        if (selectedOrder) {
            this.selectedOrder = selectedOrder;
            rememberSelectedOrder(this, selectedOrder);
        }
    },

    set_order(order) {
        const result = super.set_order(...arguments);
        rememberSelectedOrder(this, order || this.selectedOrder);
        return result;
    },

    add_new_order() {
        const order = super.add_new_order(...arguments);
        rememberSelectedOrder(this, order);
        return order;
    },

    removeOrder(order) {
        const rememberedUid = getRememberedSelectedOrderUid(this);
        const removedSelectedOrderUid = this.selectedOrder?.uid;
        const result = super.removeOrder(...arguments);

        if (order?.uid === rememberedUid || order?.uid === removedSelectedOrderUid) {
            const blankOrder = [...this.orders].reverse().find((candidate) =>
                isBlankStartupOrder(candidate)
            );
            let fallbackOrder = blankOrder || null;

            if (!fallbackOrder) {
                fallbackOrder = this.add_new_order();
            } else if (this.selectedOrder?.uid !== fallbackOrder.uid) {
                this.set_order(fallbackOrder);
            }

            rememberSelectedOrder(this, fallbackOrder);
        }

        return result;
    },
});

patch(ProductScreen.prototype, {
    async onClickPay() {
        const order = this.pos.get_order();
        if (
            order?.get_orderlines().length &&
            !order.laundry_intake_id &&
            !isRefundOrder(order)
        ) {
            await this.popup.add(ErrorPopup, {
                title: _t("Laundry Intake Required"),
                body: _t(
                    "You cannot proceed to payment before saving the laundry intake for this order."
                ),
            });
            return;
        }

        return super.onClickPay(...arguments);
    },
});

patch(OrderlineCustomerNoteButton.prototype, {
    async onClick() {
        const selectedOrderline = this.pos.get_order().get_selected_orderline();
        if (!selectedOrderline) {
            return;
        }

        const { confirmed, payload: inputNote } = await this.popup.add(
            LaundryCustomerNotePopup,
            {
                startingValue: selectedOrderline.get_customer_note(),
                title: _t("Add Customer Note"),
                confirmText: _t("Add"),
                cancelText: _t("Cancel"),
                placeholder: _t("Add an item note here..."),
            }
        );

        if (confirmed) {
            selectedOrderline.set_customer_note(inputNote);
        }
    },
});

export class NewOrderButton extends Component {
    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.isSaving = false;
    }

    get buttonLabel() {
        return _t("New Order");
    }

    async onClick() {
        if (this.isSaving) return;
        this.isSaving = true;

        const order = this.pos.get_order();

        try {
            if (!order || order.get_orderlines().length === 0) {
                this.notification.add(_t("The Current Order Is Empty"), { type: "warning" });
                this.isSaving = false;
                return;
            }

            // Save the current order as a draft locally first and register it for sync.
            order.save_to_db();
            this.pos.addOrderToUpdateSet();

            // Try to persist the draft to the backend when possible using the standard POS draft sync flow.
            let synced = false;
            try {
                await this.pos.sendDraftToServer();
                synced = true;
            } catch (draftError) {
                console.warn("Unable to sync draft order to server", draftError);
                this.notification.add(
                    _t("The order was saved locally as a draft. The update will be sent when the connection is restored."),
                    { type: "warning" }
                );
            }

            // Open a fresh order after the current one is saved as draft.
            this.pos.add_new_order();

            this.notification.add(
                synced
                    ? _t("The order was saved as a draft and a new order was opened")
                    : _t("The order was saved locally as a draft and a new order was opened"),
                { type: synced ? "success" : "warning" }
            );

        } catch (error) {
            console.error("Error:", error);
            this.notification.add(
                _t("An Error Occurred While Saving"),
                { type: "danger" }
            );
        }

        this.isSaving = false;
    }
}

NewOrderButton.template = "pos_laundry_receipt.NewOrderButton";
ProductScreen.addControlButton({
    component: NewOrderButton,
    position: ["after", "PendingOrdersButton"],
});
