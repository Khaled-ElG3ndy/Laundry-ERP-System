/** @odoo-module **/
/**
 * LaundryOrderLinePicker
 * Visual icon grid for fast cashier selection of item category + service.
 * Replaces the standard Many2one dropdowns on laundry.order.line.
 * Designed for touch screens and speed.
 */

import { Component, useState, onWillStart, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// ── CATEGORY ICONS MAP ──────────────────────────────────────────────────────
const CATEGORY_ICONS = {
    'THOBE':   { icon: '👘', color: '#1B4FD8', bg: '#EFF6FF' },
    'SHIRT':   { icon: '👔', color: '#0891B2', bg: '#CFFAFE' },
    'TROUSER': { icon: '👖', color: '#7C3AED', bg: '#EDE9FE' },
    'ABAYA':   { icon: '🧕', color: '#DB2777', bg: '#FCE7F3' },
    'SUIT':    { icon: '🤵', color: '#374151', bg: '#F3F4F6' },
    'BLANKET': { icon: '🛏', color: '#D97706', bg: '#FEF3C7' },
    'CARPET':  { icon: '🪄', color: '#059669', bg: '#D1FAE5' },
    'UNIFORM': { icon: '👷', color: '#DC2626', bg: '#FEE2E2' },
    'KIDS':    { icon: '🧒', color: '#F59E0B', bg: '#FEF9C3' },
    'LINEN':   { icon: '🛌', color: '#6366F1', bg: '#EEF2FF' },
    'CURTAIN': { icon: '🪟', color: '#10B981', bg: '#ECFDF5' },
    'OTHER':   { icon: '📦', color: '#6B7280', bg: '#F9FAFB' },
};

// ── SERVICE ICONS MAP ───────────────────────────────────────────────────────
const SERVICE_ICONS = {
    'WASH_IRON':  { icon: '👕✨', label_ar: 'غسيل + كوي',    color: '#1B4FD8', bg: '#EFF6FF' },
    'WASH_ONLY':  { icon: '🫧',   label_ar: 'غسيل فقط',      color: '#0891B2', bg: '#CFFAFE' },
    'IRON_ONLY':  { icon: '♨️',   label_ar: 'كوي فقط',        color: '#7C3AED', bg: '#EDE9FE' },
    'DRY_CLEAN':  { icon: '🧪',   label_ar: 'تنظيف جاف',      color: '#059669', bg: '#D1FAE5' },
    'DC_IRON':    { icon: '✨',   label_ar: 'جاف + كوي',      color: '#D97706', bg: '#FEF3C7' },
    'BLANKET':    { icon: '🛏️',   label_ar: 'غسيل بطانية',    color: '#DB2777', bg: '#FCE7F3' },
    'CARPET':     { icon: '🪄',   label_ar: 'غسيل سجادة',     color: '#374151', bg: '#F3F4F6' },
    'ABAYA':      { icon: '🧕',   label_ar: 'غسيل عباءة',     color: '#6366F1', bg: '#EEF2FF' },
    'UNIFORM':    { icon: '👷',   label_ar: 'غسيل يونيفورم',  color: '#DC2626', bg: '#FEE2E2' },
    'STAIN':      { icon: '🔬',   label_ar: 'معالجة بقع',     color: '#F59E0B', bg: '#FEF9C3' },
};

export class LaundryOrderLinePicker extends Component {
    static template = "laundry_theme.OrderLinePicker";
    static props = {
        onLineAdded: { type: Function },
        isUrgent: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            categories: [],
            services: [],
            addons: [],
            selectedCategory: null,
            selectedService: null,
            selectedAddons: [],
            qty: 1,
            damageNote: '',
            lineNotes: '',
            step: 'category', // 'category' | 'service' | 'confirm'
            loading: true,
        });

        onWillStart(async () => {
            await this._loadData();
        });
    }

    async _loadData() {
        const [cats, svcs, addons] = await Promise.all([
            this.orm.searchRead('laundry.item.category',
                [['active','=',true]],
                ['id','name','name_ar','code','sequence'],
                { order: 'sequence,name' }
            ),
            this.orm.searchRead('laundry.service.type',
                [['active','=',true]],
                ['id','name','name_ar','code','base_price',
                 'urgent_surcharge_pct','urgent_surcharge_type',
                 'urgent_surcharge_fixed','applicable_category_ids','product_id'],
                { order: 'sequence,name' }
            ),
            this.orm.searchRead('laundry.service.addon',
                [['active','=',true]],
                ['id','name','name_ar','price'],
                { order: 'sequence,name' }
            ),
        ]);
        this.state.categories = cats;
        this.state.services = svcs;
        this.state.addons = addons;
        this.state.loading = false;
    }

    getCategoryIcon(code) {
        return CATEGORY_ICONS[code] || { icon: '📦', color: '#6B7280', bg: '#F9FAFB' };
    }

    getServiceIcon(code) {
        return SERVICE_ICONS[code] || { icon: '🧺', color: '#1B4FD8', bg: '#EFF6FF' };
    }

    get availableServices() {
        if (!this.state.selectedCategory) return this.state.services;
        const catId = this.state.selectedCategory.id;
        return this.state.services.filter(s =>
            !s.applicable_category_ids.length ||
            s.applicable_category_ids.includes(catId)
        );
    }

    selectCategory(cat) {
        this.state.selectedCategory = cat;
        this.state.selectedService = null;
        this.state.step = 'service';
    }

    selectService(svc) {
        this.state.selectedService = svc;
        this.state.step = 'confirm';
    }

    toggleAddon(addon) {
        const idx = this.state.selectedAddons.findIndex(a => a.id === addon.id);
        if (idx >= 0) {
            this.state.selectedAddons.splice(idx, 1);
        } else {
            this.state.selectedAddons.push(addon);
        }
    }

    isAddonSelected(addon) {
        return this.state.selectedAddons.some(a => a.id === addon.id);
    }

    incQty() { this.state.qty = Math.min(99, this.state.qty + 1); }
    decQty() { this.state.qty = Math.max(1, this.state.qty - 1); }

    goBack() {
        if (this.state.step === 'service') {
            this.state.step = 'category';
            this.state.selectedCategory = null;
        } else if (this.state.step === 'confirm') {
            this.state.step = 'service';
            this.state.selectedService = null;
            this.state.selectedAddons = [];
        }
    }

    computeUnitPrice() {
        if (!this.state.selectedService) return 0;
        let price = this.state.selectedService.base_price || 0;
        if (this.props.isUrgent) {
            const svc = this.state.selectedService;
            if (svc.urgent_surcharge_type === 'percent') {
                price += price * ((svc.urgent_surcharge_pct || 0) / 100);
            } else {
                price += svc.urgent_surcharge_fixed || 0;
            }
        }
        return price;
    }

    computeAddonTotal() {
        return this.state.selectedAddons.reduce((s, a) => s + (a.price || 0), 0);
    }

    computeLineTotal() {
        return (this.computeUnitPrice() + this.computeAddonTotal()) * this.state.qty;
    }

    addToOrder() {
        if (!this.state.selectedCategory || !this.state.selectedService) return;
        const line = {
            item_category_id: [this.state.selectedCategory.id, this.state.selectedCategory.name_ar || this.state.selectedCategory.name],
            service_type_id:  [this.state.selectedService.id,  this.state.selectedService.name_ar  || this.state.selectedService.name],
            product_id:       this.state.selectedService.product_id,
            qty:              this.state.qty,
            unit_price:       this.computeUnitPrice(),
            addon_ids:        this.state.selectedAddons.map(a => a.id),
            line_notes:       this.state.lineNotes,
            damage_note:      this.state.damageNote,
        };
        this.props.onLineAdded(line);
        // Reset for next item
        this.state.selectedCategory = null;
        this.state.selectedService = null;
        this.state.selectedAddons = [];
        this.state.qty = 1;
        this.state.damageNote = '';
        this.state.lineNotes = '';
        this.state.step = 'category';
    }
}

registry.category("fields").add("laundry_order_line_picker", LaundryOrderLinePicker);
