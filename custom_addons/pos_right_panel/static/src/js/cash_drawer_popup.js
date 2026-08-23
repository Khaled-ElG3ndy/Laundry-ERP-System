/** @odoo-module **/

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { useState } from "@odoo/owl";

export class CashDrawerPopup extends AbstractAwaitablePopup {
    static template = "pos_right_panel.CashDrawerPopup";

    setup() {
        super.setup();
        this.state = useState({
            action: "in",
            amount: "",
            reason: "",
        });
    }

    setAction(action) {
        this.state.action = action;
    }

    setQuickAmount(value) {
        this.state.amount = String(value);
    }

    confirm() {
        this.props.close({
            confirmed: true,
            payload: {
                action: this.state.action,
                amount: this.state.amount,
                reason: this.state.reason,
            },
        });
    }

    cancel() {
        this.props.close({
            confirmed: false,
            payload: null,
        });
    }
}