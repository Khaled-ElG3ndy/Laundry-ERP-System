/** @odoo-module **/
/**
 * Defensive patch to ensure products are always proper Product instances
 * This prevents "product.get_unit is not a function" errors
 */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Product } from "@point_of_sale/app/store/models";

patch(PosStore.prototype, {
    async _processData(loadedData) {
        try {
            await super._processData(...arguments);

            // Defensive: Ensure all products in the database are proper Product instances
            const productsInDb = Object.values(this.db.product_by_id);
            const invalidProducts = [];

            for (const product of productsInDb) {
                if (!(product instanceof Product)) {
                    invalidProducts.push(product);
                }
            }

            if (invalidProducts.length > 0) {
                console.warn(`[POS FIX] Found ${invalidProducts.length} products that are not Product instances, converting...`);
                for (const product of invalidProducts) {
                    try {
                        product.pos = this;
                        product.env = this.env;
                        // Add missing methods if needed
                        if (typeof product.get_unit !== 'function') {
                            product.get_unit = function () {
                                var unit_id = this.uom_id;
                                if (!unit_id) {
                                    return undefined;
                                }
                                unit_id = unit_id[0];
                                if (!this.pos) {
                                    return undefined;
                                }
                                return this.pos.units_by_id[unit_id];
                            };
                        }
                    } catch (e) {
                        console.error(`[POS FIX] Error fixing product ${product.id}:`, e);
                    }
                }
            }
        } catch (e) {
            console.error('[POS FIX] Error in _processData:', e);
            throw e;
        }
    },
});

console.log('[POS FIX] Applied PosStore defensive patch');
