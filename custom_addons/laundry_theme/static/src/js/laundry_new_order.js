/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const CAT_ICONS = {
    THOBE:   { e: '👘', c: '#1B4FD8', b: '#EFF6FF' },
    SHIRT:   { e: '👔', c: '#0891B2', b: '#CFFAFE' },
    TROUSER: { e: '👖', c: '#7C3AED', b: '#EDE9FE' },
    ABAYA:   { e: '🧕', c: '#DB2777', b: '#FCE7F3' },
    SUIT:    { e: '🤵', c: '#374151', b: '#F3F4F6' },
    BLANKET: { e: '🛏️', c: '#D97706', b: '#FEF3C7' },
    CARPET:  { e: '🪄', c: '#059669', b: '#D1FAE5' },
    UNIFORM: { e: '👷', c: '#DC2626', b: '#FEE2E2' },
    KIDS:    { e: '🧒', c: '#F59E0B', b: '#FEF9C3' },
    LINEN:   { e: '🛌', c: '#6366F1', b: '#EEF2FF' },
    CURTAIN: { e: '🪟', c: '#10B981', b: '#ECFDF5' },
    OTHER:   { e: '📦', c: '#6B7280', b: '#F9FAFB' },
};

const SVC_ICONS = {
    WASH_IRON: { e: '✨', c: '#1B4FD8', b: '#EFF6FF' },
    WASH_ONLY: { e: '🫧', c: '#0891B2', b: '#CFFAFE' },
    IRON_ONLY: { e: '♨️', c: '#7C3AED', b: '#EDE9FE' },
    DRY_CLEAN: { e: '🧪', c: '#059669', b: '#D1FAE5' },
    DC_IRON:   { e: '💎', c: '#D97706', b: '#FEF3C7' },
    BLANKET:   { e: '🛏️', c: '#DB2777', b: '#FCE7F3' },
    CARPET:    { e: '🏠', c: '#374151', b: '#F3F4F6' },
    ABAYA:     { e: '🧕', c: '#6366F1', b: '#EEF2FF' },
    UNIFORM:   { e: '👷', c: '#DC2626', b: '#FEE2E2' },
    STAIN:     { e: '🔬', c: '#F59E0B', b: '#FEF9C3' },
};

export class LaundryNewOrder extends Component {
    static template = "laundry_theme.NewOrder";
    static props = ["*"];

    setup() {
        this.orm           = useService("orm");
        this.actionService = useService("action");
        this.notification  = useService("notification");

        this.state = useState({
            screen: "customer",   // customer | items | payment

            // Master data
            categories: [],
            services: [],
            addons: [],
            branch: null,
            commercialAccounts: [],

            // Customer step
            customerType: null,        // 'individual' | 'commercial'
            customerSearch: "",
            customerResults: [],
            selectedCustomer: null,
            selectedCommercial: null,
            showNewCustomer: false,
            newCustomerName: "",
            newCustomerPhone: "",

            // Items step — split view
            selectedCategory: null,
            selectedService: null,
            selectedAddons: [],
            qty: 1,
            damageNote: "",
            basket: [],

            // Payment step
            isUrgent: false,
            promiseDate: "",
            paymentMethod: "cash",     // cash | card | on_account
            cashTendered: 0,
            bagReference: "",
            orderNotes: "",

            loading: false,
            saving: false,
        });

        onWillStart(async () => {
            await this._loadData();
            this._setDefaultPromiseDate();
        });
    }

    async _loadData() {
        const [cats, svcs, addons, branches, accounts] = await Promise.all([
            this.orm.searchRead("laundry.item.category",
                [["active","=",true]], ["id","name","name_ar","code","sequence"],
                { order: "sequence,name" }),
            this.orm.searchRead("laundry.service.type",
                [["active","=",true]],
                ["id","name","name_ar","code","base_price",
                 "urgent_surcharge_pct","urgent_surcharge_type",
                 "urgent_surcharge_fixed","applicable_category_ids"],
                { order: "sequence,name" }),
            this.orm.searchRead("laundry.service.addon",
                [["active","=",true]], ["id","name","name_ar","price"],
                { order: "sequence,name" }),
            this.orm.searchRead("laundry.branch",
                [["active","=",true]], ["id","name","name_ar"], { limit: 1 }),
            this.orm.searchRead("laundry.commercial.account",
                [["state","=","active"]], ["id","name","code","partner_id"],
                { order: "name" }),
        ]);
        this.state.categories       = cats;
        this.state.services         = svcs;
        this.state.addons           = addons;
        this.state.branch           = branches[0] || null;
        this.state.commercialAccounts = accounts;
    }

    _setDefaultPromiseDate() {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(17, 0, 0, 0);
        const p = n => String(n).padStart(2,"0");
        this.state.promiseDate =
            `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}` +
            `T${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    // ── CUSTOMER ─────────────────────────────────────────

    selectType(type) {
        this.state.customerType    = type;
        this.state.selectedCustomer  = null;
        this.state.selectedCommercial = null;
        this.state.customerSearch   = "";
        this.state.customerResults  = [];
    }

    async onCustomerSearchInput(ev) {
        const q = ev.target.value;
        this.state.customerSearch = q;
        if (q.length < 2) { this.state.customerResults = []; return; }
        this.state.customerResults = await this.orm.searchRead(
            "res.partner",
            [["name","ilike",q]],
            ["id","name","phone","mobile"], { limit: 8 }
        );
    }

    selectCustomer(c) {
        this.state.selectedCustomer = c;
        this.state.customerSearch   = c.name;
        this.state.customerResults  = [];
    }

    selectCommercial(acc) {
        this.state.selectedCommercial = acc;
        this.state.selectedCustomer   = { id: acc.partner_id[0], name: acc.partner_id[1] };
    }

    clearCustomer() {
        this.state.selectedCustomer   = null;
        this.state.selectedCommercial = null;
        this.state.customerSearch     = "";
    }

    async createAndSelectCustomer() {
        if (!this.state.newCustomerName.trim()) return;
        this.state.loading = true;
        try {
            const id = await this.orm.create("res.partner", [{
                name: this.state.newCustomerName.trim(),
                phone: this.state.newCustomerPhone.trim(),
                customer_rank: 1,
            }]);
            const p = await this.orm.read("res.partner", [id], ["id","name","phone","mobile"]);
            this.selectCustomer(p[0]);
            this.state.showNewCustomer  = false;
            this.state.newCustomerName  = "";
            this.state.newCustomerPhone = "";
        } finally { this.state.loading = false; }
    }

    goToItems() {
        if (!this.state.selectedCustomer) {
            this.notification.add("اختر العميل أولاً", { type: "warning" });
            return;
        }
        this.state.screen = "items";
    }

    // ── ITEMS ─────────────────────────────────────────────

    getCatIcon(code)  { return CAT_ICONS[code]  || { e:"📦", c:"#6B7280", b:"#F9FAFB" }; }
    getSvcIcon(code)  { return SVC_ICONS[code]  || { e:"🧺", c:"#1B4FD8", b:"#EFF6FF" }; }

    get filteredServices() {
        if (!this.state.selectedCategory) return this.state.services;
        const catId = this.state.selectedCategory.id;
        return this.state.services.filter(s =>
            !s.applicable_category_ids.length ||
            s.applicable_category_ids.includes(catId)
        );
    }

    pickCategory(cat) {
        this.state.selectedCategory = cat;
        this.state.selectedService  = null;
        this.state.selectedAddons   = [];
        this.state.qty              = 1;
        this.state.damageNote       = "";
    }

    pickService(svc) {
        this.state.selectedService = svc;
    }

    toggleAddon(addon) {
        const idx = this.state.selectedAddons.findIndex(a => a.id === addon.id);
        if (idx >= 0) this.state.selectedAddons.splice(idx, 1);
        else this.state.selectedAddons.push(addon);
    }

    isAddonSelected(addon) {
        return this.state.selectedAddons.some(a => a.id === addon.id);
    }

    incQty() { this.state.qty = Math.min(99, this.state.qty + 1); }
    decQty() { this.state.qty = Math.max(1,  this.state.qty - 1); }
    setQty(n) { const v = parseInt(n); if (v > 0 && v < 100) this.state.qty = v; }

    get lineUnitPrice() {
        if (!this.state.selectedService) return 0;
        let p = this.state.selectedService.base_price || 0;
        if (this.state.isUrgent) {
            const s = this.state.selectedService;
            if (s.urgent_surcharge_type === "percent")
                p += p * ((s.urgent_surcharge_pct || 0) / 100);
            else p += s.urgent_surcharge_fixed || 0;
        }
        return p;
    }

    get lineAddonTotal() {
        return this.state.selectedAddons.reduce((s,a) => s + (a.price||0), 0);
    }

    get lineTotal() {
        return (this.lineUnitPrice + this.lineAddonTotal) * this.state.qty;
    }

    addLineToBasket() {
        const cat = this.state.selectedCategory;
        const svc = this.state.selectedService;
        if (!cat || !svc) {
            this.notification.add("اختر الملبس والخدمة أولاً", { type: "warning" });
            return;
        }
        this.state.basket.push({
            uid:         Date.now(),
            category:    cat,
            service:     svc,
            addons:      [...this.state.selectedAddons],
            qty:         this.state.qty,
            unit_price:  this.lineUnitPrice,
            subtotal:    this.lineTotal,
            damage_note: this.state.damageNote,
            cat_icon:    this.getCatIcon(cat.code),
            svc_icon:    this.getSvcIcon(svc.code),
        });
        // Reset service + addons but keep category for fast re-entry
        this.state.selectedService  = null;
        this.state.selectedAddons   = [];
        this.state.qty              = 1;
        this.state.damageNote       = "";
    }

    removeFromBasket(uid) {
        const idx = this.state.basket.findIndex(l => l.uid === uid);
        if (idx >= 0) this.state.basket.splice(idx, 1);
    }

    get orderTotal() {
        return this.state.basket.reduce((s,l) => s + l.subtotal, 0);
    }

    get basketItemCount() {
        return this.state.basket.reduce((s,l) => s + l.qty, 0);
    }

    goToPayment() {
        if (!this.state.basket.length) {
            this.notification.add("أضف قطعة واحدة على الأقل", { type: "warning" });
            return;
        }
        this.state.screen = "payment";
    }

    // ── PAYMENT ───────────────────────────────────────────

    get changeAmount() {
        if (this.state.paymentMethod !== "cash") return 0;
        return Math.max(0, this.state.cashTendered - this.orderTotal);
    }

    get isPaymentReady() {
        if (this.state.paymentMethod === "on_account") return true;
        if (this.state.paymentMethod === "card") return true;
        return this.state.cashTendered >= this.orderTotal;
    }

    get cashPresets() {
        const t = this.orderTotal;
        const all = [10,20,50,100,200,500];
        const above = all.filter(v => v >= t).slice(0,4);
        return [Math.ceil(t), ...above].filter((v,i,a) => a.indexOf(v) === i).slice(0,5);
    }

    setCashPreset(amount) { this.state.cashTendered = amount; }

    async confirmOrder() {
        if (this.state.saving || !this.isPaymentReady) return;
        this.state.saving = true;
        try {
            const lines = this.state.basket.map(l => [0, 0, {
                item_category_id: l.category.id,
                service_type_id:  l.service.id,
                qty:              l.qty,
                unit_price:       l.unit_price,
                addon_ids:        [[6, 0, l.addons.map(a => a.id)]],
                damage_note:      l.damage_note || "",
            }]);

            let promise = false;
            if (this.state.promiseDate)
                promise = this.state.promiseDate.replace("T"," ") + ":00";

            const orderId = await this.orm.create("laundry.order", [{
                partner_id:            this.state.selectedCustomer.id,
                branch_id:             this.state.branch ? this.state.branch.id : false,
                commercial_account_id: this.state.selectedCommercial ? this.state.selectedCommercial.id : false,
                priority:              this.state.isUrgent ? "urgent" : "normal",
                payment_state:         this.state.paymentMethod === "on_account" ? "on_account" :
                                       this.state.cashTendered >= this.orderTotal ? "paid" : "unpaid",
                payment_method:        this.state.paymentMethod,
                cash_tendered:         this.state.cashTendered,
                promise_date:          promise,
                bag_reference:         this.state.bagReference,
                customer_notes:        this.state.orderNotes,
                order_line_ids:        lines,
            }]);

            this.notification.add("✓ تم إنشاء الطلب بنجاح!", { type: "success" });
            await new Promise(r => setTimeout(r, 700));
            window.location.href = `/odoo/laundry-orders/${orderId}`;
        } catch(e) {
            console.error(e);
            this.notification.add("خطأ: " + (e?.data?.message || e?.message || e), { type: "danger", sticky: true });
            this.state.saving = false;
        }
    }

    goBack() { this.actionService.doAction("laundry_theme.dashboard"); }
}

registry.category("actions").add("laundry_theme.new_order", LaundryNewOrder);
