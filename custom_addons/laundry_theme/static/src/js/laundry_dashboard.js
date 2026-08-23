/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class LaundryDashboard extends Component {
    static template = "laundry_theme.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");

        this.state = useState({
            activeTab: "dashboard",
            loading: true,
            stats: {
                total_active: 0,
                ready: 0,
                urgent: 0,
                overdue: 0,
                issues: 0,
                today_revenue: 0,
            },
            orders: [],
            filterState: "all",
        });

        onWillStart(async () => {
            await this._loadStats();
            await this._loadOrders();
        });
    }

    // ── BOUND HANDLERS FOR OWL TEMPLATES ──

    onTabDashboard() { this._setTab("dashboard"); }
    onTabOrders()    { this._setTab("orders"); }
    onTabPipeline()  { this._setTab("pipeline"); }
    onTabReady()     { this._setTab("ready"); }

    onFilterAll()     { this._setFilter("all"); }
    onFilterUrgent()  { this._setFilter("urgent"); }
    onFilterOverdue() { this._setFilter("overdue"); }
    onFilterReady()   { this._setFilter("ready"); }
    onFilterIssue()   { this._setFilter("issue"); }

    onNewOrder()      { this._newOrder(); }
    onGoKanban()      { this._goKanban(); }
    onGoReady()       { this._goReady(); }

    onOpenOrder(ev) {
        const id = parseInt(ev.currentTarget.dataset.id);
        if (id) this._openOrder(id);
    }

    // ── INTERNAL METHODS ──

    _setTab(tab) {
        this.state.activeTab = tab;
        if (tab !== "new") {
            this._loadStats();
            this._loadOrders();
        }
    }

    _setFilter(f) {
        this.state.filterState = f;
        this._loadOrders(f);
    }

    async _loadStats() {
        try {
            const active = await this.orm.searchRead(
                "laundry.order",
                [["state", "not in", ["cancelled", "delivered", "picked_up"]]],
                ["state", "priority", "is_overdue", "amount_total", "payment_state"],
                { limit: 500 }
            );
            const todayStr = new Date().toISOString().split("T")[0] + " 00:00:00";
            const todayPaid = await this.orm.searchRead(
                "laundry.order",
                [["date_order", ">=", todayStr], ["payment_state", "=", "paid"]],
                ["amount_total"],
                { limit: 1000 }
            );
            this.state.stats = {
                total_active: active.length,
                ready:        active.filter(o => o.state === "ready").length,
                urgent:       active.filter(o => o.priority === "urgent").length,
                overdue:      active.filter(o => o.is_overdue).length,
                issues:       active.filter(o => o.state === "issue").length,
                today_revenue: todayPaid.reduce((s, o) => s + (o.amount_total || 0), 0),
            };
        } catch (e) { console.error("[Laundry] Stats:", e); }
    }

    async _loadOrders(filterOverride) {
        this.state.loading = true;
        try {
            const f = filterOverride || this.state.filterState;
            const domain = [["state", "not in", ["cancelled", "delivered", "picked_up"]]];
            if (f === "urgent")  domain.push(["priority", "=", "urgent"]);
            if (f === "overdue") domain.push(["is_overdue", "=", true]);
            if (f === "ready")   domain.push(["state", "=", "ready"]);
            if (f === "issue")   domain.push(["state", "=", "issue"]);

            this.state.orders = await this.orm.searchRead(
                "laundry.order",
                domain,
                ["name", "partner_id", "state", "priority", "is_urgent",
                 "is_overdue", "promise_date", "payment_state",
                 "amount_total", "bag_reference", "branch_id", "line_count"],
                { order: "is_urgent desc, is_overdue desc, promise_date asc", limit: 80 }
            );
        } catch (e) { console.error("[Laundry] Orders:", e); }
        finally { this.state.loading = false; }
    }

    async _openOrder(id) {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "laundry.order",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async _newOrder() {
        await this.actionService.doAction("laundry_theme.new_order");
    }

    async _goKanban() {
        this._setTab("pipeline");
    }

    async _goReady() {
        await this.actionService.doAction("laundry_base.action_laundry_order_ready");
    }

    // ── HELPERS ──

    stateLabel(state) {
        return {
            received: "مستلم", tagged: "مُصنّف", sorted: "مُرتَّب",
            washing: "في الغسيل", drying: "في التجفيف", ironing: "في الكوي",
            packing: "في التعبئة", ready: "جاهز", issue: "إشكالية",
            out_for_delivery: "في الطريق", rewash: "إعادة غسيل",
        }[state] || state;
    }

    formatDate(dt) {
        if (!dt) return "—";
        return dt.substring(0, 16).replace("T", " ");
    }

    get pipelineCols() {
        const stages = [
            { key: "received", label: "مستلم" },
            { key: "tagged",   label: "مُصنّف" },
            { key: "washing",  label: "في الغسيل" },
            { key: "ironing",  label: "في الكوي" },
            { key: "packing",  label: "في التعبئة" },
            { key: "ready",    label: "جاهز" },
            { key: "issue",    label: "إشكالية" },
        ];
        return stages.map(s => ({
            ...s,
            orders: this.state.orders.filter(o => o.state === s.key),
        }));
    }
}

registry.category("actions").add("laundry_theme.dashboard", LaundryDashboard);
