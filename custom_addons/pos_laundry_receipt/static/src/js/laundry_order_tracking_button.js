/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";

export class LaundryOrderTrackingButton extends Component {
    static template = "pos_laundry_receipt.LaundryOrderTrackingButton";

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get buttonLabel() {
        return _t("Track Order");
    }

    async onClick() {
        let url;
        try {
            url = await this.orm.call("pos.order", "get_laundry_tracking_url", []);
        } catch (error) {
            console.error("Failed to get laundry tracking URL:", error);
            this.notification.add(_t("Failed to open laundry order tracking."), {
                type: "danger",
            });
            return;
        }

        const trackingWindow = window.open(url, "_blank");
        if (!trackingWindow) {
            this.notification.add(_t("The pop-up was blocked. Please allow pop-ups to track the order."), {
                type: "warning",
            });
        }
    }
}

ProductScreen.addControlButton({
    component: LaundryOrderTrackingButton,
    condition: function () {
        return true;
    },
});
