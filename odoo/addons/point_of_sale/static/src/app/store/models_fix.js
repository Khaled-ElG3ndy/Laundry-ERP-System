/** @odoo-module **/
/**
 * Defensive patch to fix "product.get_unit is not a function" error
 * Ensures that OrderLine always has proper Product instances
 */

import { patch } from "@web/core/utils/patch";
import { Orderline } from "@point_of_sale/app/store/models";

patch(Orderline.prototype, {
    /**
     * Override get_unit with defensive checks
     */
    get_unit() {
        if (!this.product) {
            console.warn('[POS FIX] OrderLine has no product assigned', this);
            return undefined;
        }

        // Check if product has the get_unit method
        if (typeof this.product.get_unit !== 'function') {
            console.error('[POS FIX] Product is not a proper Product instance - missing get_unit method',
                this.product.id, this.product);

            // Try to get the unit directly from the product object
            if (this.product.uom_id && this.product.uom_id[0] && this.product.pos && this.product.pos.units_by_id) {
                try {
                    return this.product.pos.units_by_id[this.product.uom_id[0]];
                } catch (e) {
                    console.error('[POS FIX] Failed to get unit from product.uom_id', e);
                }
            }
            return undefined;
        }

        try {
            return this.product.get_unit();
        } catch (e) {
            console.error('[POS FIX] Error calling product.get_unit():', e, this.product);
            return undefined;
        }
    },

    /**
     * Override getDisplayData with safer unit access
     */
    getDisplayData() {
        const baseData = {
            productName: this.get_full_product_name(),
            price: this.getPriceString(),
            qty: this.get_quantity_str(),
            unitPrice: this.env.utils.formatCurrency(this.get_unit_display_price()),
            oldUnitPrice: this.env.utils.formatCurrency(this.get_old_unit_display_price()),
            discount: this.get_discount_str(),
            customerNote: this.get_customer_note(),
            internalNote: this.getNote(),
            comboParent: this.comboParent?.get_full_product_name(),
            pack_lot_lines: this.get_lot_lines(),
            price_without_discount: this.env.utils.formatCurrency(
                this.getUnitDisplayPriceBeforeDiscount()
            ),
            attributes: this.attribute_value_ids
                ? this.findAttribute(this.attribute_value_ids, this.custom_attribute_value_ids)
                : [],
        };

        // Safely get unit name
        try {
            const unit = this.get_unit();
            baseData.unit = unit?.name || '';
        } catch (e) {
            console.error('[POS FIX] Error getting unit name:', e);
            baseData.unit = '';
        }

        return baseData;
    },
});

console.log('[POS FIX] Applied defensive product.get_unit() patch');
