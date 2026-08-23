/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

patch(PosStore.prototype, {
    async _processData(loadedData) {
        await super._processData(...arguments);
        
        // Load departments
        this.departments = loadedData['fps.product.department'] || [];
        
        // Ensure snap_eligible is available on products
        if (loadedData['product.product']) {
            for (const product of loadedData['product.product']) {
                if (product.snap_eligible === undefined) {
                    product.snap_eligible = true; // Default to true for food
                }
            }
        }
    }
});
