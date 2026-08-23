/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";

patch(AbstractAwaitablePopup.prototype, {
    async confirm() {
        this.el?.classList?.add("closing");
        await new Promise((resolve) => setTimeout(resolve, 200));
        return super.confirm(...arguments);
    },

    async cancel() {
        this.el?.classList?.add("closing");
        await new Promise((resolve) => setTimeout(resolve, 200));
        return super.cancel(...arguments);
    },
});
