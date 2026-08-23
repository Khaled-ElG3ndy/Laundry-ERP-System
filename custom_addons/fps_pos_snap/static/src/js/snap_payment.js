/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { Order } from "@point_of_sale/app/store/models";
import { _t } from "@web/core/l10n/translation";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";

function round2(val) {
    return Math.round(val * 100) / 100;
}

patch(Order.prototype, {
    getSnapEligibleTotal() {
        let total = 0;
        for (const line of this.get_orderlines()) {
            if (line.product.snap_eligible === true) {
                total += line.get_price_without_tax();
            }
        }
        return round2(total);
    },
    
    getSnapPaidAmount() {
        let total = 0;
        for (const pl of this.get_paymentlines()) {
            if (pl.payment_method && pl.payment_method.is_snap_ebt === true) {
                total += pl.amount;
            }
        }
        return round2(total);
    },
    
    getRemainingSnapEligible() {
        return round2(Math.max(0, this.getSnapEligibleTotal() - this.getSnapPaidAmount()));
    }
});

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        if (paymentMethod.is_snap_ebt !== true) {
            return await super.addNewPaymentLine(paymentMethod);
        }
        
        const snapEligible = this.currentOrder.getSnapEligibleTotal();
        const remaining = this.currentOrder.getRemainingSnapEligible();
        const dueNow = this.currentOrder.get_due();
        
        console.log('[SNAP] Eligible:', snapEligible, 'Remaining:', remaining, 'Due:', dueNow);
        
        if (snapEligible <= 0) {
            await this.popup.add(ErrorPopup, {
                title: _t('EBT SNAP Not Allowed'),
                body: _t('No SNAP-eligible food items in this order. Use Cash or Card.'),
            });
            return false;
        }
        
        if (remaining <= 0.01) {
            await this.popup.add(ErrorPopup, {
                title: _t('EBT Limit Reached'),
                body: _t('All food items paid. Use Cash or Card for remaining balance.'),
            });
            return false;
        }
        
        const result = await super.addNewPaymentLine(paymentMethod);
        
        if (this.selectedPaymentLine && this.selectedPaymentLine.payment_method.is_snap_ebt === true) {
            const maxEbt = round2(Math.min(remaining, dueNow));
            this.selectedPaymentLine.set_amount(maxEbt);
            console.log('[SNAP] EBT set to:', maxEbt);
            
            const afterEbt = round2(dueNow - maxEbt);
            if (afterEbt > 0.01) {
                this.notification.add(
                    'EBT: $' + maxEbt.toFixed(2) + ' | Cash/Card needed: $' + afterEbt.toFixed(2),
                    { type: 'warning' }
                );
            }
        }
        
        return result;
    },
    
    async validateOrder(isForceValidate) {
        const snapPaid = this.currentOrder.getSnapPaidAmount();
        const snapEligible = this.currentOrder.getSnapEligibleTotal();
        
        if (snapPaid > snapEligible + 0.01) {
            await this.popup.add(ErrorPopup, {
                title: _t('EBT Overpayment'),
                body: 'EBT $' + snapPaid.toFixed(2) + ' exceeds food $' + snapEligible.toFixed(2),
            });
            return false;
        }
        
        return await super.validateOrder(isForceValidate);
    }
});
