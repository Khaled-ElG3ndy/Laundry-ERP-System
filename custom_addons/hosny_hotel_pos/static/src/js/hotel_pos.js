/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";

/**
 * In the hotel POS the cashier picks a customer, never a price tier.
 *
 * Odoo already re-prices the whole order when the customer changes
 * (Order.set_partner -> updatePricelistAndFiscalPosition -> set_pricelist), so
 * there is no pricing logic here. This only removes the manual pricelist
 * control and refuses to start an order without a contract customer, so that
 * the automatic path is the only path.
 */

patch(ProductScreen.prototype, {
    get controlButtons() {
        const buttons = super.controlButtons;
        if (!this.pos.config.is_hotel_pos) {
            return buttons;
        }
        // Tier names ("Hotel Contract - Base"...) mean nothing to a cashier,
        // and picking one by hand is exactly what misprices an order.
        return buttons.filter((button) => button.name !== "SetPricelistButton");
    },
});

patch(PosStore.prototype, {
    /**
     * Why the order cannot be served, or null when it can.
     * `is_hotel_contract` is loaded onto each pricelist by the session loader,
     * so this asks the real question -- "are these agreed prices?" -- rather
     * than inferring it from which pricelist happens to be the default.
     */
    hotelBlockingReason(order) {
        // Messages are written in English only and translated through the
        // module's .po files, so a cashier sees one language -- theirs -- and
        // not the same sentence twice.
        const partner = order && order.get_partner();
        if (!partner) {
            return {
                title: _t("Select the customer first"),
                body: _t(
                    "Choose the hotel or company customer before adding products, " +
                        "so their agreed contract prices are applied."
                ),
            };
        }
        if (!order.pricelist || !order.pricelist.is_hotel_contract) {
            return {
                title: _t("No contract prices"),
                body: _t(
                    "This customer has no agreed contract pricelist, so they cannot " +
                        "be served from this point of sale. Ask a manager to assign " +
                        "their contract prices first."
                ),
            };
        }
        return null;
    },

    async addProductToCurrentOrder(product, options = {}) {
        if (this.config.is_hotel_pos) {
            const order = this.get_order() || this.add_new_order();
            const blocked = this.hotelBlockingReason(order);
            if (blocked) {
                await this.popup.add(ErrorPopup, blocked);
                return;
            }
        }
        return await super.addProductToCurrentOrder(product, options);
    },
});
