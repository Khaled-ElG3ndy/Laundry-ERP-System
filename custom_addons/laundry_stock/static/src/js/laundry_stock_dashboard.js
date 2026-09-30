/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { formatFloat } from "@web/core/utils/numbers";
import { Component, onWillStart, useState } from "@odoo/owl";

/** One line icon, drawn from the Feather set react-icons ships as `fi`. */
export class LfsIcon extends Component {
    static template = "laundry_stock.Icon";
    static props = { name: { type: String } };
}

/**
 * The inventory dashboard: what is on the shelves, what leaves them, and what
 * has to be bought before it runs out. One call to the server fills it.
 */
export class LaundryStockDashboard extends Component {
    static template = "laundry_stock.Dashboard";
    static components = { LfsIcon };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            error: false,
            branchId: null,
            months: 7,
            data: null,
        });

        // Every label the template shows, so the .po file reaches all of them.
        this.text = {
            title: _t("Inventory Dashboard"),
            subtitle: _t("Supplies, consumption and purchasing at a glance"),
            allBranches: _t("All branches"),
            refresh: _t("Refresh"),
            loading: _t("Loading…"),
            notReady: _t("This branch has no warehouse laid out yet. Open the branch and press “Set Up Warehouse”."),
            needsOpening: _t("The store is set up but still counted as empty. Enter what is on the shelves to bring these figures to life."),
            needsOpeningCta: _t("Enter the opening stock"),
            stockValue: _t("Stock Value"),
            stockValueHint: _t("supplies in stock"),
            toReorder: _t("To Reorder"),
            toReorderHint: _t("below the minimum"),
            outOfStock: _t("Out of Stock"),
            outOfStockHint: _t("nothing left on the shelf"),
            monthCost: _t("Consumed This Month"),
            monthCostHint: _t("issue documents"),
            toApprove: _t("Awaiting Approval"),
            toApproveHint: _t("purchase requests"),
            incoming: _t("Incoming Receipts"),
            incomingHint: _t("receipts not validated"),
            consumptionTitle: _t("Consumption over the last 7 months"),
            consumptionEmpty: _t("No material has been issued yet."),
            zonesTitle: _t("Stock by storage zone"),
            zonesEmpty: _t("The store is still empty — enter the opening stock."),
            zoneItems: _t("items"),
            reorderTitle: _t("Buy before it runs out"),
            reorderEmpty: _t("Every supply is above its minimum."),
            reorderOnHand: _t("On hand"),
            reorderMinimum: _t("Minimum"),
            reorderSuggested: _t("Suggested"),
            topTitle: _t("Most used materials"),
            topHint: _t("last three months"),
            topEmpty: _t("Nothing consumed in this period."),
            recentTitle: _t("Latest movements"),
            recentEmpty: _t("No material issue yet."),
            recentLines: _t("line(s)"),
            actionIssueFromSales: _t("Issue from Sales"),
            actionIssue: _t("Issue Materials"),
            actionRequest: _t("Purchase Request"),
            actionCount: _t("Count Stock"),
            actionOpening: _t("Opening Stock"),
            actionReport: _t("Consumption Analysis"),
            seeAll: _t("See all"),
        };

        onWillStart(() => this.load());
    }

    /**
     * Odoo's backend leaves `dir` off the document and mirrors through its RTL
     * stylesheet instead — and this server builds that stylesheet without
     * rtlcss, so nothing is mirrored. The dashboard therefore states its own
     * direction, which is what its logical properties read.
     */
    get direction() {
        return localization.direction === "rtl" ? "rtl" : "ltr";
    }

    // ── DATA ────────────────────────────────────────────────

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "laundry.stock.dashboard",
                "get_dashboard_data",
                [],
                { branch_id: this.state.branchId, months: this.state.months },
            );
        } catch (error) {
            this.state.error = error.data && error.data.message
                ? error.data.message
                : String(error);
        } finally {
            this.state.loading = false;
        }
    }

    onBranchChange(ev) {
        const value = ev.target.value;
        this.state.branchId = value ? parseInt(value, 10) : null;
        this.load();
    }

    onRefresh() {
        this.load();
    }

    // ── FORMATTING ──────────────────────────────────────────

    get currency() {
        return (this.state.data && this.state.data.currency) || { symbol: "", position: "after" };
    }

    /**
     * An amount and its symbol are one thing and read left to right, even on
     * an Arabic page. Without the isolate the bidi algorithm lays the two runs
     * out in the paragraph's direction and "5,397 SR" reaches the eye as
     * "SR 5,397".
     */
    money(value) {
        const amount = formatFloat(value || 0, { digits: [16, 0] });
        const text = this.currency.position === "before"
            ? `${this.currency.symbol} ${amount}`
            : `${amount} ${this.currency.symbol}`;
        return `\u2066${text}\u2069`;
    }

    quantity(value, digits = 2) {
        return formatFloat(value || 0, { digits: [16, digits] });
    }

    // ── CHART GEOMETRY ──────────────────────────────────────

    get monthlyMax() {
        const series = (this.state.data && this.state.data.monthly) || [];
        return Math.max(...series.map((point) => point.cost), 0) || 1;
    }

    /** Height of a month column, as a percentage of the tallest one. */
    monthHeight(point) {
        const share = (point.cost / this.monthlyMax) * 100;
        return point.cost > 0 ? Math.max(share, 3) : 0;
    }

    /**
     * A freshly set up store reads as "everything is out of stock", which is
     * true but unhelpful — say what to do about it instead.
     */
    get needsOpening() {
        const kpis = this.state.data && this.state.data.kpis;
        return Boolean(kpis && kpis.supply_count > 0 && !kpis.stock_value
                       && !kpis.month_cost);
    }

    get monthlyTotal() {
        const series = (this.state.data && this.state.data.monthly) || [];
        return series.reduce((total, point) => total + point.cost, 0);
    }

    /** Only the tallest column carries a printed value. */
    isPeak(point) {
        return point.cost > 0 && point.cost === this.monthlyMax;
    }

    get monthlyHasData() {
        const series = (this.state.data && this.state.data.monthly) || [];
        return series.some((point) => point.cost > 0);
    }

    get zonesMax() {
        const zones = (this.state.data && this.state.data.zones) || [];
        return Math.max(...zones.map((zone) => zone.value), 0) || 1;
    }

    zoneWidth(zone) {
        const share = (zone.value / this.zonesMax) * 100;
        return zone.value > 0 ? Math.max(share, 2) : 0;
    }

    get topMax() {
        const rows = (this.state.data && this.state.data.top_materials) || [];
        return Math.max(...rows.map((row) => row.cost), 0) || 1;
    }

    topWidth(row) {
        return Math.max((row.cost / this.topMax) * 100, 2);
    }

    /** How alarming a shortage is: full bar means the minimum is met. */
    reorderWidth(row) {
        return Math.max(row.share * 100, 3);
    }

    // ── NAVIGATION ──────────────────────────────────────────

    _open(xmlId, extra = {}) {
        return this.action.doAction(xmlId, {
            additionalContext: this.state.branchId
                ? { default_branch_id: this.state.branchId, ...extra }
                : extra,
        });
    }

    onOpenReorder() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.text.reorderTitle,
            res_model: "product.template",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_laundry_supply", "=", true]],
            context: { search_default_filter_to_reorder: 1 },
        });
    }

    onOpenProduct(ev) {
        const id = parseInt(ev.currentTarget.dataset.id, 10);
        if (!id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    onOpenIssue(ev) {
        const id = parseInt(ev.currentTarget.dataset.id, 10);
        if (!id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "laundry.stock.issue",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    onIssueFromSales() { this._open("laundry_stock.action_laundry_pos_consumption"); }
    onIssue() { this._open("laundry_stock.action_laundry_stock_issue"); }
    onRequest() { this._open("laundry_stock.action_laundry_purchase_request"); }
    onCount() { this._open("laundry_stock.action_laundry_stock_count"); }
    onOpening() { this._open("laundry_stock.action_laundry_opening_stock"); }
    onReport() { this._open("laundry_stock.action_laundry_consumption_report"); }
    onStock() { this._open("laundry_stock.action_laundry_stock_quant"); }
    onApprovals() { this._open("laundry_stock.action_laundry_purchase_request_to_approve"); }
    onIncoming() { this._open("laundry_stock.action_laundry_stock_receipt"); }
}

registry.category("actions").add("laundry_stock.dashboard", LaundryStockDashboard);
