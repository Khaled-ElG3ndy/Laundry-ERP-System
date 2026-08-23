/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { formatMonetary } from "@web/views/fields/formatters";
import { KeepLast } from "@web/core/utils/concurrency";
import { useSortable } from "@web/core/utils/sortable_owl";
import { useSetupAction } from "@web/webclient/actions/action_hook";
import { Component, onRendered, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const { DateTime } = luxon;
const QR_SCAN_DUPLICATE_WINDOW = 2_500;
const QR_RETRY_UNLOCK_DELAY = 1_400;
const QR_MODAL_CLOSE_DELAY = 120;
const ORDERS_PER_PAGE = 8;

function getTotalPages(itemCount) {
    return Math.max(1, Math.ceil((itemCount || 0) / ORDERS_PER_PAGE));
}

function getSafePage(page, itemCount) {
    return Math.min(getTotalPages(itemCount), Math.max(1, parseInt(page, 10) || 1));
}

function paginateItems(items, page) {
    const safeItems = Array.isArray(items) ? items : [];
    const safePage = getSafePage(page, safeItems.length);
    const startIndex = (safePage - 1) * ORDERS_PER_PAGE;
    const endIndex = Math.min(startIndex + ORDERS_PER_PAGE, safeItems.length);
    return {
        items: safeItems.slice(startIndex, endIndex),
        page: safePage,
        totalPages: getTotalPages(safeItems.length),
        totalItems: safeItems.length,
        startNumber: safeItems.length ? startIndex + 1 : 0,
        endNumber: endIndex,
    };
}

function getOrderReferenceNumber(order) {
    const candidates = [
        order?.name,
        order?.x_display_reference,
        order?.x_laundry_intake_ref,
        order?.pos_reference,
    ];
    for (const candidate of candidates) {
        const matches = String(candidate || "").match(/\d+/g);
        if (matches?.length) {
            return parseInt(matches[matches.length - 1], 10) || 0;
        }
    }
    return 0;
}

function sortOrdersByReferenceDesc(orders) {
    return [...(orders || [])].sort((left, right) => {
        const leftNumber = getOrderReferenceNumber(left);
        const rightNumber = getOrderReferenceNumber(right);
        if (leftNumber !== rightNumber) {
            return rightNumber - leftNumber;
        }
        return (right.id || 0) - (left.id || 0);
    });
}

function hasHtml5QrCodeSupport() {
    return Boolean(
        typeof window !== "undefined" &&
        window.Html5Qrcode &&
        navigator.mediaDevices?.getUserMedia
    );
}

function getHtml5QrCodeClass() {
    return window.Html5Qrcode || null;
}

function getHtml5QrFormats() {
    return window.Html5QrcodeSupportedFormats || null;
}

function getRearCamera(cameras = []) {
    return (
        cameras.find((camera) =>
            /back|rear|environment|traseira|trasera|arriere|rueck|후면/i.test(camera?.label || "")
        ) || cameras[0] || null
    );
}

function afterNextPaint() {
    return new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
}

const OPERATIONAL_FILTER_KEYS = ["received", "ready", "delivered"];
const MAIN_DASHBOARD_FILTER_KEYS = ["all", ...OPERATIONAL_FILTER_KEYS, "delivered_today"];

function normalizeMainDashboardFilter(filterKey) {
    return MAIN_DASHBOARD_FILTER_KEYS.includes(filterKey) ? filterKey : "all";
}

const QUICK_ACTIONS = {
    received: [{ status: "ready", label: _t("Mark Ready") }],
    ready: [{ status: "delivered", label: _t("Confirm Delivery") }],
    delivered: [],
};

export class LaundryTrackingDashboard extends Component {
    static template = "pos_laundry_receipt.LaundryTrackingDashboard";
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
        this.originalTitleBrand = this.titleService.getParts().zopenerp || "Odoo";
        this.keepLast = new KeepLast();
        this.boardRef = useRef("board");
        this.scanner = null;
        this.scanLock = false;
        this.closeModalTimer = null;
        this.lastScanFingerprint = "";
        this.lastScanAt = 0;
        this.scannerElementId = `laundry-backend-qr-reader-${Date.now()}-${Math.round(
            Math.random() * 10_000
        )}`;
        this.loadDashboard = this.loadDashboard.bind(this);
        this.setFilter = this.setFilter.bind(this);
        this.onSearchInput = this.onSearchInput.bind(this);
        this.updateOrderStatus = this.updateOrderStatus.bind(this);
        this.getQuickActions = this.getQuickActions.bind(this);
        this.formatAmount = this.formatAmount.bind(this);
        this.formatOrderDate = this.formatOrderDate.bind(this);
        this.formatDeadline = this.formatDeadline.bind(this);
        this.formatGeneratedAt = this.formatGeneratedAt.bind(this);
        this.formatAge = this.formatAge.bind(this);
        this.formatAgeBadge = this.formatAgeBadge.bind(this);
        this.isDelayedOrder = this.isDelayedOrder.bind(this);
        this.getStatusCardMeta = this.getStatusCardMeta.bind(this);
        this.openOrder = this.openOrder.bind(this);
        this.openLabelQueue = this.openLabelQueue.bind(this);
        this.previewLabel = this.previewLabel.bind(this);
        this.printLabel = this.printLabel.bind(this);
        this.openScannerModal = this.openScannerModal.bind(this);
        this.closeScannerModal = this.closeScannerModal.bind(this);
        this.changeColumnPage = this.changeColumnPage.bind(this);

        const pastState = this.props.state || {};
        this.state = useState({
            loading: true,
            orders: [],
            statuses: [],
            labelQueueActionId: false,
            pendingLabelCount: 0,
            slaCounters: {},
            uiLabels: {},
            generatedAt: false,
            selectedFilter: normalizeMainDashboardFilter(pastState.selectedFilter),
            searchTerm: pastState.searchTerm || "",
            updatingOrderIds: {},
            draggingOrderId: false,
            highlightedStatus: false,
            isScannerSupported: hasHtml5QrCodeSupport(),
            scannerVisible: false,
            scannerClosing: false,
            scannerBooting: false,
            scannerProcessing: false,
            scannerError: "",
            scannerFeedback: "",
            scannerHint: "",
            columnPages: pastState.columnPages || {},
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });

        onRendered(() => {
            const pageTitle = _t("Laundry Order Tracking");
            this.env.config.setDisplayName(pageTitle);
            this.titleService.setParts({
                zopenerp: null,
                action: pageTitle,
            });
        });

        onWillUnmount(() => {
            this.titleService.setParts({
                action: null,
                zopenerp: this.originalTitleBrand,
            });
            this.scanLock = false;
            if (this.closeModalTimer) {
                clearTimeout(this.closeModalTimer);
                this.closeModalTimer = null;
            }
            void this.stopScanner();
        });

        useSetupAction({
            getLocalState: () => ({
                selectedFilter: this.state.selectedFilter,
                searchTerm: this.state.searchTerm,
                columnPages: { ...this.state.columnPages },
            }),
        });

        useSortable({
            ref: this.boardRef,
            elements: ".o_laundry_board_card",
            groups: ".o_laundry_board_column_body",
            connectGroups: true,
            handle: ".o_laundry_card_drag_handle",
            ignore: "button,a,input,textarea,.dropdown,.o_no_drag",
            cursor: "grabbing",
            onDragStart: ({ element }) => {
                this.state.draggingOrderId = parseInt(element.dataset.orderId, 10);
            },
            onGroupEnter: ({ group }) => {
                const order = this.state.orders.find(
                    (item) => item.id === this.state.draggingOrderId
                );
                const targetStatus = group?.dataset?.status;
                this.state.highlightedStatus = this.canMoveOrder(order, targetStatus)
                    ? targetStatus
                    : false;
            },
            onGroupLeave: () => {
                this.state.highlightedStatus = false;
            },
            onDragEnd: () => {
                this.state.draggingOrderId = false;
                this.state.highlightedStatus = false;
            },
            onDrop: ({ element, parent }) => {
                const orderId = parseInt(element.dataset.orderId, 10);
                const targetStatus = parent?.dataset?.status;
                const order = this.state.orders.find((item) => item.id === orderId);
                if (orderId && targetStatus && this.canMoveOrder(order, targetStatus)) {
                    this.updateOrderStatus(orderId, targetStatus);
                } else if (orderId && targetStatus) {
                    this.notification.add(
                        _t("Orders can only move from Received to Ready to Delivered."),
                        { type: "warning" }
                    );
                    void this.loadDashboard();
                }
            },
        });
    }

    get display() {
        return {
            controlPanel: {
                "top-right": false,
                "bottom-right": false,
            },
        };
    }

    get filters() {
        return [
            { key: "all", label: _t("All") },
            ...OPERATIONAL_FILTER_KEYS.map((key) => ({
                key,
                label: this.getStatusLabel(key),
            })),
        ];
    }

    get textDirection() {
        return localization.direction || document.documentElement.dir || "ltr";
    }

    get uiText() {
        return {
            refresh: _t("Refresh"),
            scanQr: _t("Scan QR"),
            scanning: _t("Starting camera..."),
            dashboardTitle: _t("Laundry Order Tracking"),
            labelQueue: _t("Label Print Queue"),
            pendingLabels: _t("Pending Labels"),
            previewLabel: _t("Preview Label"),
            printLabel: _t("Print Label"),
            reprintLabel: _t("Reprint Label"),
            moreItems: _t("more item lines"),
            items: _t("Items"),
            paidInvoiceNumber: _t("Paid Invoice Number"),
            searchPlaceholder: _t("Search by Order No., Paid Invoice No., Customer Name, or Mobile Number"),
            loading: _t("Loading laundry orders..."),
            emptyTitle: _t("No orders match the current view"),
            emptyText: _t("Try another filter or clear the search to see more orders."),
            dragToMove: _t("Drag to Move"),
            priorityLabel: this.state.uiLabels.priority || _t("Priority"),
            deadlineLabel: this.state.uiLabels.deadline || _t("Deadline"),
            remainingLabel: this.state.uiLabels.remaining || _t("Remaining"),
            slaStatusLabel: this.state.uiLabels.sla_status || _t("SLA Status"),
            workerLabel: this.state.uiLabels.worker || _t("Worker"),
            walkInCustomer: _t("Walk-in Customer"),
            viewOrder: _t("Open Order"),
            ageLabel: _t("Order Age"),
            stageAgeReceived: _t("Since Intake"),
            stageAgeReady: _t("Since Ready"),
            stageAgeDelivered: _t("Since Delivery"),
            intakeLabel: _t("Intake Reference"),
            posReferenceLabel: _t("POS Reference"),
            noColumnOrders: _t("There are no orders at this stage"),
            scannerTitle: _t("Scan QR"),
            scannerSubtitle: _t("Point the camera at the receipt code and the order status will update immediately"),
            scannerLiveLabel: _t("Live Scanner"),
            scannerReadyLabel: _t("Ready to Scan"),
            scannerSuccessLabel: _t("Success"),
            scannerProcessingLabel: _t("Checking"),
            scannerAttentionLabel: _t("Warning"),
            scannerFrameHint: _t("Place the receipt code inside the frame for automatic scanning."),
            scannerPointCamera: _t("Point the camera at the QR code inside the scan frame"),
            scannerProcessing: _t("Checking the order and updating its status..."),
            scannerSuccessHint: _t("The status was updated successfully. You can continue scanning."),
            scannerClose: _t("Close"),
            scannerSecureContext: _t("Camera access requires a secure HTTPS connection."),
            scannerPermissionDenied: _t("Camera permission was denied. Enable camera access and try again."),
            scannerCameraUnavailable: _t("No suitable camera was found for scanning."),
            scannerCameraBusy: _t("The camera is being used by another application. Close it and try again."),
            scannerStartFailed: _t("Unable to start the QR scanner. Try again."),
            scannerUnsupported: _t("This device or browser does not support QR scanning on this screen."),
        };
    }

    get summaryCards() {
        return [
            {
                key: "all",
                icon: "fa-clone",
                label: _t("All Orders"),
                value: this.state.orders.length,
            },
            {
                key: "received",
                icon: "fa-inbox",
                label: this.getStatusLabel("received"),
                value: this.state.orders.filter((order) => order.x_laundry_status === "received").length,
            },
            {
                key: "ready",
                icon: "fa-check-circle",
                label: this.getStatusLabel("ready"),
                value: this.state.orders.filter((order) => order.x_laundry_status === "ready").length,
            },
            {
                key: "delivered_today",
                icon: "fa-calendar-check-o",
                label: _t("Delivered Today"),
                value: this.state.orders.filter((order) => this.isTodayOrder(order, "delivered")).length,
            },
        ];
    }

    get filteredOrders() {
        const term = (this.state.searchTerm || "").trim().toLowerCase();
        return this.state.orders.filter((order) => {
            if (!this.passesFilter(order)) {
                return false;
            }
            if (!term) {
                return true;
            }
            const rawHaystack = [
                order.name,
                order.x_display_reference,
                order.partner_name,
                order.pos_reference,
                order.account_move_name,
                order.invoice_number,
                order.x_laundry_invoice_number,
                order.partner_phone,
                order.x_laundry_priority_label,
                order.x_laundry_sla_status_label,
                order.x_laundry_worker_name,
            ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            if (rawHaystack.includes(term)) {
                return true;
            }
            const digitQuery = term.replace(/\D+/g, "");
            if (!digitQuery) {
                return false;
            }
            const digitHaystack = [
                order.partner_phone,
                order.name,
                order.x_display_reference,
                order.pos_reference,
                order.account_move_name,
                order.invoice_number,
                order.x_laundry_invoice_number,
            ].map((value) => String(value || "").replace(/\D+/g, ""));
            return digitHaystack.some((digits) => digits.includes(digitQuery));
        });
    }

    get columns() {
        const orderMap = {};
        for (const status of this.state.statuses) {
            orderMap[status.key] = [];
        }

        for (const order of this.filteredOrders) {
            if (orderMap[order.x_laundry_status]) {
                orderMap[order.x_laundry_status].push(order);
            }
        }

        return this.state.statuses.map((status) => {
            const orders = sortOrdersByReferenceDesc(orderMap[status.key]);
            const pagination = paginateItems(orders, this.state.columnPages[status.key]);
            return {
                ...status,
                count: orders.length,
                page: pagination.page,
                totalPages: pagination.totalPages,
                pageStatus: this.formatPageStatus(pagination),
                visibleOrders: pagination.items,
                hasPager: pagination.totalPages > 1,
            };
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            const data = await this.keepLast.add(
                this.orm.call("pos.order", "get_laundry_tracking_dashboard_data", [])
            );
            this.state.statuses = [...(data.statuses || [])].sort((left, right) => left.sequence - right.sequence);
            this.state.orders = data.orders || [];
            this.state.labelQueueActionId = data.label_queue_action_id || false;
            this.state.pendingLabelCount = data.pending_label_count || 0;
            this.state.slaCounters = data.sla_counters || {};
            this.state.uiLabels = data.ui_labels || {};
            this.state.generatedAt = data.generated_at || false;
        } catch (error) {
            console.error("Failed to load laundry dashboard data:", error);
            this.notification.add(_t("Unable to load laundry order tracking."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    passesFilter(order) {
        switch (this.state.selectedFilter) {
            case "received":
                return order.x_laundry_status === "received";
            case "ready":
                return order.x_laundry_status === "ready";
            case "delivered":
                return order.x_laundry_status === "delivered";
            case "delivered_today":
                return this.isTodayOrder(order, "delivered");
            default:
                return true;
        }
    }

    isTodayOrder(order, status = false) {
        if (!order.date_order) {
            return false;
        }
        if (status && order.x_laundry_status !== status) {
            return false;
        }
        const orderDate = deserializeDateTime(order.date_order);
        return orderDate.hasSame(DateTime.local(), "day");
    }

    getOrderAgeHours(order) {
        const stageStart = this.getStageStartDate(order);
        if (!stageStart) {
            return 0;
        }
        if (!stageStart?.isValid) {
            return 0;
        }
        return Math.max(0, DateTime.local().diff(stageStart, "hours").hours || 0);
    }

    getStageStartDate(order) {
        const referenceDate =
            order.x_laundry_status === "ready"
                ? order.ready_since || order.current_status_since || order.date_order
                : order.current_status_since || order.date_order;
        if (!referenceDate) {
            return false;
        }
        return deserializeDateTime(referenceDate);
    }

    isDelayedOrder(order) {
        return order?.x_laundry_sla_status === "overdue";
    }

    formatAge(order) {
        const ageHours = this.getOrderAgeHours(order);
        if (ageHours < 1) {
            return _t("Less than an hour");
        }
        if (ageHours < 24) {
            const hours = Math.floor(ageHours);
            return `${hours} ${hours === 1 ? _t("hour") : _t("hours")}`;
        }
        const days = Math.floor(ageHours / 24);
        if (days === 1) {
            return _t("One day");
        }
        return `${days} ${_t("days")}`;
    }

    formatAgeBadge(order) {
        return `${this.getAgeLabel(order)} : ${this.formatAge(order)}`;
    }

    getAgeLabel(order) {
        switch (order.x_laundry_status) {
            case "ready":
                return this.uiText.stageAgeReady;
            case "delivered":
                return this.uiText.stageAgeDelivered;
            default:
                return this.uiText.stageAgeReceived;
        }
    }

    getStatusCardMeta(order) {
        const statusMeta = this.state.statuses.find((status) => status.key === order.x_laundry_status);
        return statusMeta || {
            label: order.x_laundry_status_label,
            description: "",
            color: order.status_color || "#2563eb",
        };
    }

    getStatusLabel(statusKey) {
        const statusMeta = this.state.statuses.find((status) => status.key === statusKey);
        if (statusMeta?.label) {
            return statusMeta.label;
        }
        if (statusKey === "received") {
            return _t("Received");
        }
        if (statusKey === "ready") {
            return _t("Ready");
        }
        if (statusKey === "delivered") {
            return _t("Delivered");
        }
        return statusKey || "";
    }

    isUpdating(orderId) {
        return !!this.state.updatingOrderIds[orderId];
    }

    canMoveOrder(order, targetStatus) {
        return Boolean(
            order &&
            (
                (order.x_laundry_status === "received" && targetStatus === "ready") ||
                (order.x_laundry_status === "ready" && targetStatus === "delivered")
            )
        );
    }

    setFilter(filterKey) {
        this.state.selectedFilter = normalizeMainDashboardFilter(filterKey);
        this.state.columnPages = {};
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value || "";
        this.state.columnPages = {};
    }

    changeColumnPage(statusKey, nextPage, itemCount) {
        this.state.columnPages[statusKey] = getSafePage(nextPage, itemCount);
    }

    describeScannerError(error) {
        if (!window.isSecureContext && window.location.hostname !== "localhost") {
            return this.uiText.scannerSecureContext;
        }
        const message = String(error?.message || error || "");
        if (/NotAllowedError|Permission|denied/i.test(message)) {
            return this.uiText.scannerPermissionDenied;
        }
        if (/NotFoundError|OverconstrainedError|camera/i.test(message)) {
            return this.uiText.scannerCameraUnavailable;
        }
        if (/NotReadableError|TrackStartError|busy|Could not start video source/i.test(message)) {
            return this.uiText.scannerCameraBusy;
        }
        return this.uiText.scannerStartFailed;
    }

    async stopScanner() {
        const scanner = this.scanner;
        this.scanner = null;
        if (!scanner) {
            return;
        }
        try {
            await scanner.stop();
        } catch {
            // noop
        }
        try {
            await scanner.clear();
        } catch {
            // noop
        }
    }

    async startScanner() {
        const Html5Qrcode = getHtml5QrCodeClass();
        if (!Html5Qrcode) {
            throw new Error(this.uiText.scannerUnsupported);
        }

        await this.stopScanner();
        this.scanner = new Html5Qrcode(this.scannerElementId);
        const config = {
            fps: 10,
            disableFlip: true,
            rememberLastUsedCamera: false,
        };
        const formats = getHtml5QrFormats();
        if (formats?.QR_CODE) {
            config.formatsToSupport = [formats.QR_CODE];
        }
        const onScanSuccess = (decodedText) => {
            void this.handleDecodedQr(decodedText);
        };
        const onScanFailure = () => { };

        try {
            await this.scanner.start({ facingMode: "environment" }, config, onScanSuccess, onScanFailure);
            return;
        } catch (primaryError) {
            const cameras = await Html5Qrcode.getCameras();
            const rearCamera = getRearCamera(cameras);
            if (!rearCamera) {
                throw primaryError;
            }
            await this.scanner.start(rearCamera.id, config, onScanSuccess, onScanFailure);
        }
    }

    async openScannerModal() {
        if (!this.state.isScannerSupported) {
            this.notification.add(this.uiText.scannerUnsupported, { type: "warning" });
            return;
        }
        this.scanLock = false;
        this.lastScanFingerprint = "";
        this.lastScanAt = 0;
        this.state.scannerVisible = true;
        this.state.scannerClosing = false;
        this.state.scannerBooting = true;
        this.state.scannerProcessing = false;
        this.state.scannerError = "";
        this.state.scannerFeedback = "";
        this.state.scannerHint = this.uiText.scannerPointCamera;

        await afterNextPaint();
        try {
            await this.startScanner();
        } catch (error) {
            console.error("Failed to start backend QR scanner:", error);
            this.state.scannerError = this.describeScannerError(error);
            this.notification.add(this.state.scannerError, { type: "warning" });
        } finally {
            this.state.scannerBooting = false;
        }
    }

    async closeScannerModal() {
        if (this.closeModalTimer) {
            clearTimeout(this.closeModalTimer);
            this.closeModalTimer = null;
        }
        this.scanLock = false;
        this.state.scannerBooting = false;
        this.state.scannerProcessing = false;
        this.state.scannerClosing = true;
        await this.stopScanner();
        this.closeModalTimer = setTimeout(() => {
            this.state.scannerVisible = false;
            this.state.scannerClosing = false;
            this.state.scannerError = "";
            this.state.scannerFeedback = "";
            this.state.scannerHint = "";
        }, QR_MODAL_CLOSE_DELAY);
    }

    unlockScannerSoon(delay = QR_RETRY_UNLOCK_DELAY) {
        setTimeout(() => {
            this.scanLock = false;
            if (!this.state.scannerProcessing) {
                this.state.scannerFeedback = "";
                if (!this.state.scannerError) {
                    this.state.scannerHint = this.uiText.scannerPointCamera;
                }
            }
        }, delay);
    }

    async handleDecodedQr(decodedText) {
        const normalizedValue = String(decodedText || "").trim();
        if (!normalizedValue || !this.state.scannerVisible || this.scanLock) {
            return;
        }
        const now = Date.now();
        if (
            this.lastScanFingerprint === normalizedValue &&
            now - this.lastScanAt < QR_SCAN_DUPLICATE_WINDOW
        ) {
            return;
        }

        this.scanLock = true;
        this.lastScanFingerprint = normalizedValue;
        this.lastScanAt = now;
        this.state.scannerProcessing = true;
        this.state.scannerFeedback = "";
        this.state.scannerError = "";
        this.state.scannerHint = this.uiText.scannerProcessing;

        try {
            const response = await this.orm.call("pos.order", "process_laundry_qr_scan", [
                normalizedValue,
            ]);
            await this.handleQrScanResponse(response);
        } catch (error) {
            console.error("Backend QR scan processing failed:", error);
            this.state.scannerProcessing = false;
            this.state.scannerFeedback = "error";
            this.state.scannerError = _t("Unable to process the QR code. Try again.");
            this.notification.add(this.state.scannerError, { type: "danger" });
            this.unlockScannerSoon();
        }
    }

    async handleQrScanResponse(response) {
        const code = response?.code || "invalid_qr";
        const message = response?.message || _t("Unable to read this code or find the requested order.");

        if (response?.order) {
            this.replaceOrder(response.order);
        }

        if (code === "updated") {
            this.state.scannerFeedback = "success";
            this.state.scannerHint = this.uiText.scannerSuccessHint;
            this.state.scannerError = "";
            this.state.scannerProcessing = false;
            this.notification.add(message, { type: "success" });
            this.unlockScannerSoon(650);
            void this.loadDashboard();
            return;
        }

        if (code === "already_ready" || code === "already_delivered" || code === "cancelled") {
            this.state.scannerFeedback = code === "already_ready" ? "info" : "warning";
            this.state.scannerHint = message;
            this.state.scannerProcessing = false;
            this.notification.add(message, {
                type: code === "already_ready" ? "info" : "warning",
            });
            this.unlockScannerSoon();
            void this.loadDashboard();
            return;
        }

        this.state.scannerProcessing = false;
        this.state.scannerFeedback = "error";
        this.state.scannerError = message;
        this.state.scannerHint = message;
        this.notification.add(message, { type: "danger" });
        this.unlockScannerSoon();
    }

    async updateOrderStatus(orderId, targetStatus) {
        const order = this.state.orders.find((item) => item.id === orderId);
        if (!this.canMoveOrder(order, targetStatus) || this.isUpdating(orderId)) {
            return;
        }

        const previousStatus = order.x_laundry_status;
        const previousColor = order.status_color;
        const statusMeta = this.state.statuses.find((status) => status.key === targetStatus);
        this.state.updatingOrderIds[orderId] = true;
        order.x_laundry_status = targetStatus;
        if (statusMeta) {
            order.status_color = statusMeta.color;
        }

        try {
            const updatedOrder = await this.orm.call(
                "pos.order",
                "update_laundry_order_status",
                [orderId, targetStatus]
            );
            this.replaceOrder(updatedOrder);
        } catch (error) {
            order.x_laundry_status = previousStatus;
            order.status_color = previousColor;
            console.error("Failed to update laundry status:", error);
            this.notification.add(_t("Unable to update the order stage."), {
                type: "danger",
            });
        } finally {
            delete this.state.updatingOrderIds[orderId];
        }
    }

    replaceOrder(updatedOrder) {
        const index = this.state.orders.findIndex((order) => order.id === updatedOrder.id);
        if (index >= 0) {
            this.state.orders.splice(index, 1, updatedOrder);
        }
    }

    getQuickActions(order) {
        return QUICK_ACTIONS[order.x_laundry_status] || [];
    }

    formatAmount(order) {
        return formatMonetary(order.amount_total, { currencyId: order.currency_id });
    }

    formatOrderDate(order) {
        if (!order.date_order) {
            return "-";
        }
        return formatDateTime(deserializeDateTime(order.date_order));
    }

    formatDeadline(order) {
        if (!order.x_laundry_sla_deadline) {
            return "-";
        }
        return formatDateTime(deserializeDateTime(order.x_laundry_sla_deadline));
    }

    formatGeneratedAt() {
        if (!this.state.generatedAt) {
            return "";
        }
        return formatDateTime(deserializeDateTime(this.state.generatedAt));
    }

    formatPageStatus(pagination) {
        if (!pagination?.totalItems) {
            return "";
        }
        return `${pagination.startNumber}-${pagination.endNumber} / ${pagination.totalItems}`;
    }

    get scannerStatusText() {
        return this.state.scannerError || this.state.scannerHint || this.uiText.scannerPointCamera;
    }

    get scannerStatusMeta() {
        if (this.state.scannerError || this.state.scannerFeedback === "error") {
            return { tone: "error", icon: "fa-exclamation-circle", label: this.uiText.scannerAttentionLabel };
        }
        if (this.state.scannerProcessing || this.state.scannerBooting) {
            return { tone: "processing", icon: "fa-refresh", label: this.uiText.scannerProcessingLabel };
        }
        if (this.state.scannerFeedback === "success") {
            return { tone: "success", icon: "fa-check-circle", label: this.uiText.scannerSuccessLabel };
        }
        if (this.state.scannerFeedback === "warning") {
            return { tone: "warning", icon: "fa-exclamation-circle", label: this.uiText.scannerAttentionLabel };
        }
        if (this.state.scannerFeedback === "info") {
            return { tone: "info", icon: "fa-info-circle", label: this.uiText.scannerReadyLabel };
        }
        return { tone: "ready", icon: "fa-crosshairs", label: this.uiText.scannerReadyLabel };
    }

    async openOrder(orderId) {
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "pos.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openLabelQueue() {
        if (this.state.labelQueueActionId) {
            await this.actionService.doAction(this.state.labelQueueActionId);
        }
    }

    async _runLabelAction(orderId, operation) {
        try {
            const action = await this.orm.call(
                "pos.order",
                "get_laundry_label_action",
                [orderId, operation]
            );
            if (action) {
                await this.actionService.doAction(action);
            }
        } catch (error) {
            console.error("Laundry label action failed:", error);
            this.notification.add(_t("Unable to open the laundry label."), {
                type: "danger",
            });
        }
    }

    async previewLabel(orderId) {
        await this._runLabelAction(orderId, "preview");
    }

    async printLabel(orderId) {
        await this._runLabelAction(orderId, "print");
    }
}

registry.category("actions").add(
    "pos_laundry_receipt.laundry_tracking_dashboard",
    LaundryTrackingDashboard
);
