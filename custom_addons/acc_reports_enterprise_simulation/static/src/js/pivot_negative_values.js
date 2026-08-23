/** @odoo-module **/

import { onMounted, onPatched } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";

const NEGATIVE_PIVOT_MODELS = new Set([
    "account.analytic.line",
    "account.invoice.report",
]);

function isNegativeNumber(value) {
    return typeof value === "number" && value < 0;
}

patch(PivotRenderer.prototype, {
    setup() {
        super.setup();
        onMounted(() => this.applyNegativeValueClasses());
        onPatched(() => this.applyNegativeValueClasses());
    },

    applyNegativeValueClasses() {
        if (!NEGATIVE_PIVOT_MODELS.has(this.model?.metaData?.resModel)) {
            return;
        }
        const table = this.tableRef?.el;
        if (!table) {
            return;
        }

        for (const [rowIndex, row] of (this.table.rows || []).entries()) {
            const rowEl = table.querySelector(`tbody tr:nth-child(${rowIndex + 1})`);
            if (!rowEl) {
                continue;
            }
            for (const [cellIndex, cell] of row.subGroupMeasurements.entries()) {
                const cellEl = rowEl.querySelector(`td.o_pivot_cell_value:nth-of-type(${cellIndex + 1})`);
                if (cellEl) {
                    cellEl.classList.toggle("o_acc_pivot_negative_value", isNegativeNumber(cell.value));
                }
            }
        }
    },
});
