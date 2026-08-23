/** @odoo-module **/

import { localization } from "@web/core/l10n/localization";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { KeepLast } from "@web/core/utils/concurrency";
import { Component, onRendered, onWillStart, onWillUnmount, useState } from "@odoo/owl";

const SLA_FILTERS = [
    "all",
    "normal",
    "urgent",
    "due_soon",
    "overdue",
];
const VALID_FILTERS = [
    ...SLA_FILTERS,
    "active_urgent",
    "on_track",
    "delivered_on_time",
    "delivered_late",
];
const PAGE_SIZE = 12;
const OVERVIEW_PREVIEW_LIMIT = 3;
const PERFORMANCE_TABLE_PREVIEW_LIMIT = 3;
const PERFORMANCE_PERIODS = ["today", "week", "month", "custom"];

function parseDateTime(value) {
    if (!value) {
        return null;
    }
    const dateTime = deserializeDateTime(value);
    return dateTime?.isValid ? dateTime : null;
}

function deadlineSortValue(order) {
    const deadline = parseDateTime(order.x_laundry_sla_deadline);
    return deadline ? deadline.toMillis() : Number.MAX_SAFE_INTEGER;
}

export class LaundrySlaPerformanceDashboard extends Component {
    static template = "pos_laundry_receipt.LaundrySlaPerformanceDashboard";
    static components = { Layout };
    static props = {
        action: { type: Object, optional: true },
        state: { type: Object, optional: true },
        "*": true,
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.titleService = useService("title");
        this.keepLast = new KeepLast();
        this.originalTitleBrand = this.titleService.getParts().zopenerp || "Odoo";
        this.loadDashboard = this.loadDashboard.bind(this);
        this.setFilter = this.setFilter.bind(this);
        this.onSearchInput = this.onSearchInput.bind(this);
        this.onBranchChange = this.onBranchChange.bind(this);
        this.onWorkerChange = this.onWorkerChange.bind(this);
        this.onStageChange = this.onStageChange.bind(this);
        this.toggleAdvancedFilters = this.toggleAdvancedFilters.bind(this);
        this.setAnalyticsPeriod = this.setAnalyticsPeriod.bind(this);
        this.onAnalyticsDateFromChange = this.onAnalyticsDateFromChange.bind(this);
        this.onAnalyticsDateToChange = this.onAnalyticsDateToChange.bind(this);
        this.expandPerformanceTable = this.expandPerformanceTable.bind(this);
        this.setPage = this.setPage.bind(this);
        this.previousPage = this.previousPage.bind(this);
        this.nextPage = this.nextPage.bind(this);
        this.backToOverview = this.backToOverview.bind(this);
        this.openReport = this.openReport.bind(this);
        this.openOrder = this.openOrder.bind(this);

        const pastState = this.props.state || {};
        this.state = useState({
            loading: true,
            orders: [],
            counters: {},
            labels: {},
            branches: [],
            workers: [],
            stages: [],
            analytics: {},
            selectedFilter: VALID_FILTERS.includes(pastState.selectedFilter)
                ? pastState.selectedFilter
                : "all",
            selectedBranch: pastState.selectedBranch || "",
            selectedWorker: pastState.selectedWorker || "",
            selectedStage: pastState.selectedStage || "",
            searchTerm: pastState.searchTerm || "",
            showAdvancedFilters: Boolean(pastState.showAdvancedFilters),
            page: Number(pastState.page || 1),
            analyticsPeriod: PERFORMANCE_PERIODS.includes(pastState.analyticsPeriod)
                ? pastState.analyticsPeriod
                : "month",
            analyticsDateFrom: pastState.analyticsDateFrom || "",
            analyticsDateTo: pastState.analyticsDateTo || "",
            expandedPerformanceTables: pastState.expandedPerformanceTables || {},
            reportActionId: false,
            generatedAt: false,
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });

        onRendered(() => {
            const title = this.labels.page_title || "SLA & Performance";
            this.env.config.setDisplayName(title);
            this.titleService.setParts({
                zopenerp: null,
                action: title,
            });
        });

        onWillUnmount(() => {
            this.titleService.setParts({
                action: null,
                zopenerp: this.originalTitleBrand,
            });
        });
    }

    get display() {
        return {
            controlPanel: false,
        };
    }

    get textDirection() {
        return localization.direction || document.documentElement.dir || "ltr";
    }

    get labels() {
        return this.state.labels || {};
    }

    get filterOptions() {
        return SLA_FILTERS.map((key) => ({ key, label: this.getFilterLabel(key) }));
    }

    get isOverviewMode() {
        return this.state.selectedFilter === "all";
    }

    get showPagination() {
        return !this.isOverviewMode && this.totalPages > 1;
    }

    get summaryCards() {
        return [
            {
                key: "active_urgent",
                icon: "fa-bolt",
                label: this.labels.active_urgent,
                value: this.state.counters.active_urgent || 0,
                tone: "urgent",
            },
            {
                key: "due_soon",
                icon: "fa-hourglass-o",
                label: this.labels.due_soon,
                value: this.state.counters.due_soon || 0,
                tone: "warning",
            },
            {
                key: "overdue",
                icon: "fa-clock-o",
                label: this.labels.overdue,
                value: this.state.counters.overdue || 0,
                tone: "danger",
            },
            {
                key: "delivered_on_time",
                icon: "fa-check",
                label: this.labels.delivered_on_time,
                value: this.state.counters.delivered_on_time || 0,
                tone: "success",
            },
        ];
    }

    get analytics() {
        return this.state.analytics || {};
    }

    get hasAnalyticsData() {
        return Boolean(this.analytics.has_data);
    }

    get performancePeriodOptions() {
        return PERFORMANCE_PERIODS.map((key) => ({
            key,
            label: {
                today: this.labels.today,
                week: this.labels.this_week,
                month: this.labels.this_month,
                custom: this.labels.custom_range,
            }[key] || key,
        }));
    }

    getPerformanceTableRows(key) {
        const rows = key === "branch" ? this.analytics.branch_rows || [] : this.analytics.worker_rows || [];
        if (this.state.expandedPerformanceTables[key]) {
            return rows;
        }
        return rows.slice(0, PERFORMANCE_TABLE_PREVIEW_LIMIT);
    }

    shouldShowPerformanceTableViewAll(key) {
        const rows = key === "branch" ? this.analytics.branch_rows || [] : this.analytics.worker_rows || [];
        return rows.length > PERFORMANCE_TABLE_PREVIEW_LIMIT && !this.state.expandedPerformanceTables[key];
    }

    get scopedOrders() {
        return [...this.state.orders].sort((left, right) => this.compareOrders(left, right));
    }

    get filteredOrders() {
        return this.scopedOrders.filter((order) => this.passesFilter(order));
    }

    get totalPages() {
        return Math.max(1, Math.ceil(this.filteredOrders.length / PAGE_SIZE));
    }

    get pageStart() {
        if (!this.filteredOrders.length) {
            return 0;
        }
        return (this.safePage - 1) * PAGE_SIZE + 1;
    }

    get pageEnd() {
        return Math.min(this.safePage * PAGE_SIZE, this.filteredOrders.length);
    }

    get safePage() {
        return Math.min(Math.max(Number(this.state.page || 1), 1), this.totalPages);
    }

    get paginatedOrders() {
        const page = this.safePage;
        const start = (page - 1) * PAGE_SIZE;
        return this.filteredOrders.slice(start, start + PAGE_SIZE);
    }

    get paginationPages() {
        const total = this.totalPages;
        const current = this.safePage;
        const start = Math.max(1, Math.min(current - 2, total - 4));
        const end = Math.min(total, start + 4);
        const pages = [];
        for (let page = start; page <= end; page++) {
            pages.push(page);
        }
        return pages;
    }

    get paginationSummary() {
        const template =
            this.labels.pagination_summary || "Showing %(start)s-%(end)s of %(total)s orders";
        return template
            .replace("%(start)s", this.pageStart)
            .replace("%(end)s", this.pageEnd)
            .replace("%(total)s", this.filteredOrders.length);
    }

    get sectionDefinitions() {
        return [
            {
                key: "overdue",
                label: this.labels.overdue,
                icon: "fa-clock-o",
                tone: "danger",
                filterKey: "overdue",
            },
            {
                key: "due_soon",
                label: this.labels.due_soon,
                icon: "fa-hourglass-o",
                tone: "warning",
                filterKey: "due_soon",
            },
            {
                key: "active_urgent",
                label: this.labels.active_urgent,
                icon: "fa-bolt",
                tone: "urgent",
                filterKey: "active_urgent",
            },
            {
                key: "on_track",
                label: this.labels.on_track,
                icon: "fa-check-circle-o",
                tone: "success",
                filterKey: "on_track",
            },
        ];
    }

    get sectionedOrders() {
        if (!this.isOverviewMode) {
            return [this.filteredSection];
        }

        return this.sectionDefinitions.map((section) => {
            const orders = this.getOrdersForSection(section.key);
            return {
                ...section,
                orders: orders.slice(0, OVERVIEW_PREVIEW_LIMIT),
                totalCount: orders.length,
            };
        });
    }

    get filteredSection() {
        const definition = this.getFilteredSectionDefinition();
        return {
            ...definition,
            filterKey: false,
            orders: this.paginatedOrders,
            totalCount: this.filteredOrders.length,
        };
    }

    passesFilter(order) {
        switch (this.state.selectedFilter) {
            case "active_urgent":
                return order.x_laundry_priority === "urgent" && order.x_laundry_status !== "delivered";
            case "normal":
                return order.x_laundry_priority === "normal";
            case "urgent":
                return order.x_laundry_priority === "urgent";
            case "due_soon":
                return order.x_laundry_sla_status === "due_soon";
            case "overdue":
                return order.x_laundry_sla_status === "overdue";
            case "on_track":
                return this.matchesSection(order, "on_track");
            case "delivered_on_time":
                return order.x_laundry_sla_status === "delivered_on_time";
            case "delivered_late":
                return order.x_laundry_sla_status === "delivered_late";
            default:
                return true;
        }
    }

    compareOrders(left, right) {
        const leftRank = this.getSortRank(left);
        const rightRank = this.getSortRank(right);
        if (leftRank !== rightRank) {
            return leftRank - rightRank;
        }
        const leftDeadline = deadlineSortValue(left);
        const rightDeadline = deadlineSortValue(right);
        if (leftDeadline !== rightDeadline) {
            return leftDeadline - rightDeadline;
        }
        return (right.id || 0) - (left.id || 0);
    }

    getSortRank(order) {
        if (order.x_laundry_sla_status === "overdue") {
            return 0;
        }
        if (order.x_laundry_sla_status === "due_soon") {
            return 1;
        }
        if (order.x_laundry_priority === "urgent" && order.x_laundry_status !== "delivered") {
            return 2;
        }
        if (order.x_laundry_status !== "delivered") {
            return 3;
        }
        return 4;
    }

    getFilterLabel(key) {
        return {
            all: this.labels.all,
            normal: this.labels.normal,
            urgent: this.labels.urgent_filter || this.labels.urgent,
            due_soon: this.labels.due_soon,
            overdue: this.labels.overdue,
            on_track: this.labels.on_track,
            delivered_on_time: this.labels.delivered_on_time,
            delivered_late: this.labels.delivered_late,
        }[key] || key;
    }

    getPriorityClass(order) {
        return order.x_laundry_priority === "urgent" ? "is-urgent" : "is-normal";
    }

    getSlaClass(order) {
        return `is-${order.x_laundry_sla_status || "unknown"}`;
    }

    getOrderCardClasses(order) {
        return [this.getPriorityClass(order), this.getSlaClass(order), this.getSectionClass(order)]
            .filter(Boolean)
            .join(" ");
    }

    getRemainingText(order) {
        return order.x_laundry_sla_remaining_display || this.labels.no_deadline;
    }

    getOrdersForSection(sectionKey) {
        return this.scopedOrders.filter((order) => this.matchesSection(order, sectionKey));
    }

    matchesSection(order, sectionKey) {
        switch (sectionKey) {
            case "overdue":
                return order.x_laundry_sla_status === "overdue";
            case "due_soon":
                return order.x_laundry_sla_status === "due_soon";
            case "active_urgent":
                return order.x_laundry_priority === "urgent" && order.x_laundry_status !== "delivered";
            case "on_track":
                return (
                    order.x_laundry_status !== "delivered" &&
                    order.x_laundry_sla_status !== "overdue" &&
                    order.x_laundry_sla_status !== "due_soon" &&
                    order.x_laundry_priority !== "urgent"
                );
            default:
                return true;
        }
    }

    getFilteredSectionDefinition() {
        const filterKey = this.state.selectedFilter;
        const section = this.sectionDefinitions.find((item) => item.key === filterKey);
        if (section) {
            return section;
        }
        const toneByFilter = {
            normal: "success",
            urgent: "urgent",
            delivered_on_time: "success",
            delivered_late: "danger",
        };
        const iconByFilter = {
            normal: "fa-flag-o",
            urgent: "fa-bolt",
            delivered_on_time: "fa-check",
            delivered_late: "fa-clock-o",
        };
        return {
            key: filterKey,
            label: this.getFilterLabel(filterKey),
            icon: iconByFilter[filterKey] || "fa-list",
            tone: toneByFilter[filterKey] || "neutral",
        };
    }

    getOrderSectionKey(order) {
        if (order.x_laundry_sla_status === "overdue") {
            return "overdue";
        }
        if (order.x_laundry_sla_status === "due_soon") {
            return "due_soon";
        }
        if (order.x_laundry_priority === "urgent" && order.x_laundry_status !== "delivered") {
            return "active_urgent";
        }
        return "on_track";
    }

    getSectionClass(order) {
        return `is-section-${this.getOrderSectionKey(order)}`;
    }

    formatDate(value) {
        const dateTime = parseDateTime(value);
        if (!dateTime) {
            return this.labels.not_available;
        }
        const locale = (
            localization.code ||
            localization.language ||
            document.documentElement.lang ||
            navigator.language ||
            "en-US"
        ).replace("_", "-");
        try {
            return new Intl.DateTimeFormat(locale, {
                day: "2-digit",
                month: "short",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
            }).format(dateTime.toJSDate());
        } catch {
            return formatDateTime(dateTime);
        }
    }

    normalizePage() {
        this.state.page = this.safePage;
    }

    setFilter(filterKey) {
        this.state.selectedFilter = VALID_FILTERS.includes(filterKey) ? filterKey : "all";
        this.state.page = 1;
    }

    backToOverview() {
        this.setFilter("all");
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value || "";
        this.state.page = 1;
    }

    onBranchChange(ev) {
        this.state.selectedBranch = ev.target.value || "";
        this.state.page = 1;
    }

    onWorkerChange(ev) {
        this.state.selectedWorker = ev.target.value || "";
        this.state.page = 1;
    }

    onStageChange(ev) {
        this.state.selectedStage = ev.target.value || "";
        this.state.page = 1;
    }

    toggleAdvancedFilters() {
        this.state.showAdvancedFilters = !this.state.showAdvancedFilters;
    }

    setPage(page) {
        this.state.page = Math.min(Math.max(Number(page || 1), 1), this.totalPages);
    }

    previousPage() {
        this.setPage(this.safePage - 1);
    }

    nextPage() {
        this.setPage(this.safePage + 1);
    }

    async setAnalyticsPeriod(period) {
        this.state.analyticsPeriod = PERFORMANCE_PERIODS.includes(period) ? period : "month";
        this.state.expandedPerformanceTables = {};
        await this.loadDashboard();
    }

    async onAnalyticsDateFromChange(ev) {
        this.state.analyticsDateFrom = ev.target.value || "";
        this.state.analyticsPeriod = "custom";
        this.state.expandedPerformanceTables = {};
        await this.loadDashboard();
    }

    async onAnalyticsDateToChange(ev) {
        this.state.analyticsDateTo = ev.target.value || "";
        this.state.analyticsPeriod = "custom";
        this.state.expandedPerformanceTables = {};
        await this.loadDashboard();
    }

    expandPerformanceTable(key) {
        this.state.expandedPerformanceTables = {
            ...this.state.expandedPerformanceTables,
            [key]: true,
        };
    }

    getChartWidth(value) {
        const number = Number(value || 0);
        return `${Math.max(2, Math.min(100, number))}%`;
    }

    getCountChartWidth(value, values) {
        const maxValue = Math.max(...(values || []).map((item) => Number(item.value || 0)), 1);
        return `${Math.max(2, Math.min(100, (Number(value || 0) / maxValue) * 100))}%`;
    }

    async openReport() {
        if (this.state.reportActionId) {
            await this.actionService.doAction(this.state.reportActionId);
        }
    }

    async openOrder(orderId) {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            name: this.labels.open_order,
            res_model: "pos.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            const data = await this.keepLast.add(
                this.orm.call("pos.order", "get_laundry_sla_performance_dashboard_data", [
                    this.state.analyticsPeriod,
                    this.state.analyticsDateFrom || false,
                    this.state.analyticsDateTo || false,
                ])
            );
            this.state.orders = data.orders || [];
            this.state.counters = data.counters || {};
            this.state.labels = data.labels || {};
            this.state.branches = data.branches || [];
            this.state.workers = data.workers || [];
            this.state.stages = data.stages || [];
            this.state.analytics = data.analytics || {};
            this.state.reportActionId = data.report_action_id || false;
            this.state.generatedAt = data.generated_at || false;
        } finally {
            this.state.loading = false;
        }
    }

}

registry.category("actions").add(
    "pos_laundry_receipt.laundry_sla_performance_dashboard",
    LaundrySlaPerformanceDashboard
);
