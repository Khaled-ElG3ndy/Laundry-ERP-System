/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { getDefaultConfig } from "@web/views/view";
import { useSetupAction } from "@web/webclient/actions/action_hook";
import { useEnrichWithActionLinks } from "@web/webclient/actions/reports/report_hook";

import { Component, onWillStart, useRef, useState, useSubEnv, xml } from "@odoo/owl";

const dialogLabels = {
    apply: _t("Apply"),
    cancel: _t("Cancel"),
    clearAll: _t("Clear All"),
    comparisonFrom: _t("Comparison From"),
    comparisonTo: _t("Comparison To"),
    selectAll: _t("Select All"),
};

const reportMethodBySlug = {
    "aged-partner-balance": "action_open_aged_partner_balance_preview",
    "aged-payable": "action_open_aged_payable_preview",
    "aged-receivable": "action_open_aged_receivable_preview",
    "balance-sheet": "action_open_balance_sheet_preview",
    "bank-book": "action_open_bank_book_preview",
    "cash-book": "action_open_cash_book_preview",
    "cash-flow-statement": "action_open_cash_flow_statement_preview",
    "day-book": "action_open_day_book_preview",
    "executive-summary": "action_open_executive_summary_preview",
    "general-ledger": "action_open_general_ledger_preview",
    "journals-audit": "action_open_journals_audit_preview",
    "partner-ledger": "action_open_partner_ledger_preview",
    "profit-and-loss": "action_open_profit_and_loss_preview",
    "tax-report": "action_open_tax_report_preview",
    "trial-balance": "action_open_trial_balance_preview",
};

class ChoiceDialog extends Component {
    setup() {
        this.labels = dialogLabels;
        this.state = useState({
            value: this.props.value,
        });
    }

    async confirm() {
        return this.props.onConfirm(this.state.value);
    }
}
ChoiceDialog.components = { Dialog };
ChoiceDialog.props = {
    close: Function,
    title: String,
    value: String,
    choices: Array,
    onConfirm: Function,
};
ChoiceDialog.template = xml`
<Dialog title="props.title" size="'md'">
    <div class="d-flex flex-column gap-2">
        <t t-foreach="props.choices" t-as="choice" t-key="choice.value">
            <label class="d-flex align-items-center gap-2">
                <input type="radio" name="preview_choice"
                    t-att-checked="state.value === choice.value"
                    t-on-change="() => state.value = choice.value"/>
                <span t-esc="choice.label"/>
            </label>
        </t>
    </div>
    <t t-set-slot="footer">
        <button class="btn btn-secondary" t-on-click="props.close" t-esc="labels.cancel"/>
        <button class="btn btn-primary" t-on-click="confirm" t-esc="labels.apply"/>
    </t>
</Dialog>`;

class DateDialog extends Component {
    setup() {
        this.labels = dialogLabels;
        const initialState = {};
        for (const field of this.props.fields) {
            initialState[field.name] = this.props.values[field.name] || "";
        }
        this.state = useState(initialState);
    }

    async confirm() {
        return this.props.onConfirm({ ...this.state });
    }
}
DateDialog.components = { Dialog };
DateDialog.props = {
    close: Function,
    title: String,
    fields: Array,
    values: Object,
    onConfirm: Function,
};
DateDialog.template = xml`
<Dialog title="props.title" size="'md'">
    <div class="d-flex flex-column gap-3">
        <t t-foreach="props.fields" t-as="field" t-key="field.name">
            <div>
                <label class="form-label" t-esc="field.label"/>
                <input type="date" class="form-control" t-model="state[field.name]"/>
            </div>
        </t>
    </div>
    <t t-set-slot="footer">
        <button class="btn btn-secondary" t-on-click="props.close" t-esc="labels.cancel"/>
        <button class="btn btn-primary" t-on-click="confirm" t-esc="labels.apply"/>
    </t>
</Dialog>`;

class ComparisonDialog extends Component {
    setup() {
        this.labels = dialogLabels;
        this.state = useState({
            date_from_cmp: this.props.values.date_from_cmp || "",
            date_to_cmp: this.props.values.date_to_cmp || "",
        });
    }

    async confirm() {
        return this.props.onConfirm({
            enable_filter: !!(this.state.date_from_cmp && this.state.date_to_cmp),
            filter_cmp: this.state.date_from_cmp && this.state.date_to_cmp ? "filter_date" : "filter_no",
            date_from_cmp: this.state.date_from_cmp || false,
            date_to_cmp: this.state.date_to_cmp || false,
            label_filter: this.props.label || _t("Comparison"),
        });
    }
}
ComparisonDialog.components = { Dialog };
ComparisonDialog.props = {
    close: Function,
    title: String,
    values: Object,
    label: { type: String, optional: true },
    onConfirm: Function,
};
ComparisonDialog.template = xml`
<Dialog title="props.title" size="'md'">
    <div class="d-flex flex-column gap-3">
        <div>
            <label class="form-label" t-esc="labels.comparisonFrom"/>
            <input type="date" class="form-control" t-model="state.date_from_cmp"/>
        </div>
        <div>
            <label class="form-label" t-esc="labels.comparisonTo"/>
            <input type="date" class="form-control" t-model="state.date_to_cmp"/>
        </div>
    </div>
    <t t-set-slot="footer">
        <button class="btn btn-secondary" t-on-click="props.close" t-esc="labels.cancel"/>
        <button class="btn btn-primary" t-on-click="confirm" t-esc="labels.apply"/>
    </t>
</Dialog>`;

class JournalsDialog extends Component {
    setup() {
        this.labels = dialogLabels;
        this.state = useState({
            selectedIds: [...(this.props.selectedIds || [])],
        });
    }

    isSelected(journalId) {
        return this.state.selectedIds.includes(journalId);
    }

    toggle(journalId) {
        if (this.isSelected(journalId)) {
            this.state.selectedIds = this.state.selectedIds.filter((id) => id !== journalId);
        } else {
            this.state.selectedIds = [...this.state.selectedIds, journalId];
        }
    }

    selectAll() {
        this.state.selectedIds = this.props.options.map((option) => option.id);
    }

    clearAll() {
        this.state.selectedIds = [];
    }

    async confirm() {
        return this.props.onConfirm({ journal_ids: [...this.state.selectedIds] });
    }
}
JournalsDialog.components = { Dialog };
JournalsDialog.props = {
    close: Function,
    title: String,
    options: Array,
    selectedIds: Array,
    onConfirm: Function,
};
JournalsDialog.template = xml`
<Dialog title="props.title" size="'lg'">
    <div class="d-flex gap-2 mb-3">
        <button class="btn btn-outline-secondary btn-sm" t-on-click="selectAll" t-esc="labels.selectAll"/>
        <button class="btn btn-outline-secondary btn-sm" t-on-click="clearAll" t-esc="labels.clearAll"/>
    </div>
    <div class="d-flex flex-column gap-2" style="max-height: 50vh; overflow: auto;">
        <t t-foreach="props.options" t-as="journal" t-key="journal.id">
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox"
                    t-att-checked="isSelected(journal.id)"
                    t-on-change="() => toggle(journal.id)"/>
                <span t-esc="journal.name"/>
            </label>
        </t>
    </div>
    <t t-set-slot="footer">
        <button class="btn btn-secondary" t-on-click="props.close" t-esc="labels.cancel"/>
        <button class="btn btn-primary" t-on-click="confirm" t-att-disabled="!state.selectedIds.length" t-esc="labels.apply"/>
    </t>
</Dialog>`;



class AccountingReportPreviewClientAction extends Component {
    static storageKey = "acc_reports_enterprise_simulation.last_report_params";

    setup() {
        useSubEnv({
            config: {
                ...getDefaultConfig(),
                ...this.env.config,
            },
        });
        useSetupAction();

        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.params = this._getInitialParams();
        const initialForm = (this.params.data && this.params.data.form) || {};
        const initialJournalIds = initialForm.journal_ids || [];
        const initialAnalyticIds = initialForm.analytic_account_ids || [];
        const initialPartnerCategoryIds = initialForm.partner_category_ids || [];
        this.uiState = useState({
            journalDraftIds: [...initialJournalIds],
            analyticDraftIds: [...initialAnalyticIds],
            partnerCategoryDraftIds: [...initialPartnerCategoryIds],
            periodLengthDraft: initialForm.period_length || 30,
            searchTerm: "",
            refreshVersion: 0,
            basePeriod: this._extractPeriodState(initialForm),
        });
        this.title = this.params.display_name || this.params.name;
        this.reportUrl = this.params.report_url;
        this.iframe = useRef("iframe");
        useEnrichWithActionLinks(this.iframe);
        onWillStart(async () => {
            if (!this.params?.report_url || !this.params?.report_name) {
                const params = await this._fetchInitialParamsFromSlug();
                if (params) {
                    this._setParams(params);
                }
            } else {
                this._rememberParams();
            }
        });
    }

    _getInitialParams() {
        const actionParams = this.props.action.params || {};
        if (actionParams.report_url && actionParams.report_name) {
            return this._normalizeParamsForCurrentLanguage(actionParams);
        }
        return this._restoreParams() || actionParams;
    }

    _currentSlug() {
        const actionParams = this.props.action.params || {};
        if (actionParams.report_slug) {
            return actionParams.report_slug;
        }
        const tag = this.props.action.tag || "";
        if (tag.startsWith("report/")) {
            return tag.slice("report/".length);
        }
        try {
            const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
            const action = hashParams.get("action") || "";
            if (action.startsWith("report/")) {
                return action.slice("report/".length);
            }
        } catch {
            return "";
        }
        return "";
    }

    _storageLanguageCode() {
        return localization.code || document.documentElement.lang || "en_US";
    }

    _storageKey() {
        return `${AccountingReportPreviewClientAction.storageKey}.${this._storageLanguageCode()}.${this._currentSlug() || "report"}`;
    }

    _normalizeParamsForCurrentLanguage(params) {
        if (!params || !params.report_url || !params.report_name) {
            return params || {};
        }
        return {
            ...params,
            preview_lang: this._storageLanguageCode(),
        };
    }

    _paramsMatchCurrentContext(params) {
        if (!params?.report_url || !params?.report_name) {
            return false;
        }
        if (params.preview_lang !== this._storageLanguageCode()) {
            return false;
        }
        const slug = this._currentSlug();
        return !slug || !params.report_slug || params.report_slug === slug;
    }

    _restoreParams() {
        try {
            const value = window.sessionStorage.getItem(this._storageKey());
            const params = value ? JSON.parse(value) : false;
            return this._paramsMatchCurrentContext(params) ? params : false;
        } catch {
            return false;
        }
    }

    _rememberParams() {
        if (!this.params?.report_url || !this.params?.report_name) {
            return;
        }
        try {
            window.sessionStorage.setItem(
                this._storageKey(),
                JSON.stringify(this._normalizeParamsForCurrentLanguage(this.params))
            );
        } catch {
            // Storage can be disabled in private/browser-restricted sessions.
        }
    }

    async _fetchInitialParamsFromSlug() {
        const method = reportMethodBySlug[this._currentSlug()];
        if (!method) {
            return false;
        }
        const action = await this.orm.call("acc.report.preview.helper", method, []);
        return action?.params ? this._normalizeParamsForCurrentLanguage(action.params) : false;
    }

    _syncUiStateFromParams() {
        if (!this.uiState) {
            return;
        }
        const form = (this.params.data && this.params.data.form) || {};
        this.uiState.journalDraftIds = [...(form.journal_ids || [])];
        this.uiState.analyticDraftIds = [...(form.analytic_account_ids || [])];
        this.uiState.partnerCategoryDraftIds = [...(form.partner_category_ids || [])];
        this.uiState.periodLengthDraft = form.period_length || 30;
        this.uiState.basePeriod = this._extractPeriodState(form);
    }

    _setParams(params, { refresh = false } = {}) {
        this.params = this._normalizeParamsForCurrentLanguage(params || {});
        this.title = this.params.display_name || this.params.name;
        this.reportUrl = this.params.report_url;
        this._syncUiStateFromParams();
        if (refresh && this.uiState) {
            this.uiState.refreshVersion++;
        }
        this._rememberParams();
    }

    onIframeLoaded(ev) {
        const iframeDocument = ev.target.contentWindow.document;
        const direction = this._direction();
        const language = this._languageCode();
        this.iframeDocument = iframeDocument;
        iframeDocument.documentElement.setAttribute("dir", direction);
        iframeDocument.documentElement.setAttribute("lang", language);
        iframeDocument.body.setAttribute("dir", direction);
        iframeDocument.body.setAttribute("lang", language);
        iframeDocument.body.classList.add("o_in_iframe", "container-fluid", "o_acc_reports_enterprise_simulation_iframe");
        iframeDocument.body.classList.remove("container");
        this._injectIframeStyles(iframeDocument);
        this._applyCompanyLabelToIframe();
        this._applyIframeEnhancements();
    }

    _direction() {
        return localization.direction || document.documentElement.dir || "ltr";
    }

    _isRTL() {
        return this._direction() === "rtl";
    }

    _languageCode() {
        return (localization.code || document.documentElement.lang || "en-US").replace("_", "-");
    }

    _parseDate(value) {
        return value ? new Date(`${value}T00:00:00`) : null;
    }

    _toDateString(date) {
        if (!date) {
            return false;
        }
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }

    _shiftDays(value, days) {
        const date = this._parseDate(value);
        if (!date) {
            return false;
        }
        date.setDate(date.getDate() + days);
        return this._toDateString(date);
    }

    _shiftYears(value, years) {
        const date = this._parseDate(value);
        if (!date) {
            return false;
        }
        date.setFullYear(date.getFullYear() + years);
        return this._toDateString(date);
    }

    _endOfMonth(date) {
        if (!date) {
            return null;
        }
        return new Date(date.getFullYear(), date.getMonth() + 1, 0);
    }

    _endOfQuarter(date) {
        if (!date) {
            return null;
        }
        const quarterEndMonth = Math.floor(date.getMonth() / 3) * 3 + 2;
        return new Date(date.getFullYear(), quarterEndMonth + 1, 0);
    }

    _endOfYear(date) {
        if (!date) {
            return null;
        }
        return new Date(date.getFullYear(), 11, 31);
    }

    _formatMonthYear(date) {
        return new Intl.DateTimeFormat(this._languageCode(), {
            month: "long",
            year: "numeric",
        }).format(date);
    }

    _formatQuarterLabel(date) {
        const quarterStartMonth = Math.floor(date.getMonth() / 3) * 3;
        const start = new Date(date.getFullYear(), quarterStartMonth, 1);
        const end = new Date(date.getFullYear(), quarterStartMonth + 2, 1);
        const monthFormatter = new Intl.DateTimeFormat(this._languageCode(), { month: "long" });
        return `${monthFormatter.format(start)} - ${monthFormatter.format(end)} ${date.getFullYear()}`;
    }

    _getDateFieldConfig(form) {
        const fields = [];
        if ("date_from" in form) {
            fields.push({ name: "date_from", label: _t("Start Date") });
        }
        if ("date_to" in form) {
            fields.push({ name: "date_to", label: _t("End Date") });
        }
        if (!fields.length && "date" in form) {
            fields.push({ name: "date", label: _t("Date") });
        }
        return fields;
    }

    _shiftMonths(date, months) {
        return new Date(date.getFullYear(), date.getMonth() + months, 1);
    }

    _shiftQuarters(date, quarters) {
        return new Date(date.getFullYear(), date.getMonth() + quarters * 3, 1);
    }

    _startOfMonth(date) {
        return new Date(date.getFullYear(), date.getMonth(), 1);
    }

    _startOfQuarter(date) {
        const quarterStartMonth = Math.floor(date.getMonth() / 3) * 3;
        return new Date(date.getFullYear(), quarterStartMonth, 1);
    }

    _startOfYear(date) {
        return new Date(date.getFullYear(), 0, 1);
    }

    _sameDate(left, right) {
        return !!left && !!right && left.getTime() === right.getTime();
    }

    _formatDateButtonLabel(form) {
        const start = this._parseDate(form.date_from || form.date || form.date_to);
        const end = this._parseDate(form.date_to || form.date || form.date_from);
        if (!start || !end) {
            return "";
        }
        if (
            "date_from" in form &&
            "date_to" in form &&
            this._sameDate(start, this._startOfMonth(end)) &&
            this._sameDate(end, this._endOfMonth(end))
        ) {
            return this._formatMonthYear(end);
        }
        if (
            "date_from" in form &&
            "date_to" in form &&
            this._sameDate(start, this._startOfQuarter(end)) &&
            this._sameDate(end, this._endOfQuarter(end))
        ) {
            return this._formatQuarterLabel(end);
        }
        if (
            "date_from" in form &&
            "date_to" in form &&
            this._sameDate(start, this._startOfYear(end)) &&
            this._sameDate(end, this._endOfYear(end))
        ) {
            return String(end.getFullYear());
        }
        if ("date_from" in form && "date_to" in form && form.date_from && form.date_to) {
            return `${this._formatDate(form.date_from)} - ${this._formatDate(form.date_to)}`;
        }
        return this._formatDate(form.date_to || form.date || form.date_from);
    }

    _getReferenceDate(button) {
        const form = (this.params.data && this.params.data.form) || {};
        return this._parseDate(form.date_to || form.date || form.date_from || button.value) || new Date();
    }

    _getDatePresetUpdates(button, preset, step = 0) {
        const referenceDate = this._getReferenceDate(button);
        if (preset === "end_of_month") {
            const shifted = this._shiftMonths(referenceDate, step);
            if (button.isRange) {
                return {
                    date_from: this._toDateString(this._startOfMonth(shifted)),
                    date_to: this._toDateString(this._endOfMonth(shifted)),
                };
            }
            return { [button.primaryField]: this._toDateString(this._endOfMonth(shifted)) };
        }
        if (preset === "end_of_quarter") {
            const shifted = this._shiftQuarters(this._startOfQuarter(referenceDate), step);
            const quarterStart = this._startOfQuarter(shifted);
            const quarterEnd = this._endOfQuarter(shifted);
            if (button.isRange) {
                return {
                    date_from: this._toDateString(quarterStart),
                    date_to: this._toDateString(quarterEnd),
                };
            }
            return { [button.primaryField]: this._toDateString(quarterEnd) };
        }
        if (preset === "end_of_year") {
            const shiftedYear = new Date(referenceDate.getFullYear() + step, 0, 1);
            if (button.isRange) {
                return {
                    date_from: this._toDateString(this._startOfYear(shiftedYear)),
                    date_to: this._toDateString(this._endOfYear(shiftedYear)),
                };
            }
            return { [button.primaryField]: this._toDateString(this._endOfYear(shiftedYear)) };
        }
        return { [button.primaryField]: button.value };
    }

    _getDatePresetOptions(button) {
        const referenceDate = this._getReferenceDate(button);
        return [
            {
                value: "end_of_month",
                label: _t("Month"),
                meta: this._formatMonthYear(referenceDate),
            },
            {
                value: "end_of_quarter",
                label: _t("Quarter"),
                meta: this._formatQuarterLabel(referenceDate),
            },
            {
                value: "end_of_year",
                label: _t("Year"),
                meta: String(referenceDate.getFullYear()),
            },
        ];
    }

    _shiftDatePresetValue(button, preset, step) {
        return this._getDatePresetUpdates(button, preset, step);
    }

    _getDatePresetValue(button, preset) {
        const updates = this._getDatePresetUpdates(button, preset);
        if (button.isRange) {
            return `${updates.date_from || ""}|${updates.date_to || ""}`;
        }
        return updates[button.primaryField];
    }

    _currentDatePreset(button) {
        const form = (this.params.data && this.params.data.form) || {};
        const currentValue = button.isRange
            ? `${form.date_from || ""}|${form.date_to || ""}`
            : button.value;
        if (!currentValue || currentValue === "|") {
            return "specific_date";
        }
        for (const option of this._getDatePresetOptions(button)) {
            if (this._getDatePresetValue(button, option.value) === currentValue) {
                return option.value;
            }
        }
        return "specific_date";
    }

    _getComparisonMode(form) {
        if (!form.enable_filter || form.filter_cmp !== "filter_date" || !form.date_to_cmp) {
            return "no_comparison";
        }
        const previous = this._getComparisonUpdates("previous_period", form);
        if (previous.date_from_cmp === (form.date_from_cmp || false) && previous.date_to_cmp === (form.date_to_cmp || false)) {
            return "previous_period";
        }
        const lastYear = this._getComparisonUpdates("same_period_last_year", form);
        if (lastYear.date_from_cmp === (form.date_from_cmp || false) && lastYear.date_to_cmp === (form.date_to_cmp || false)) {
            return "same_period_last_year";
        }
        return "specific_date";
    }

    _currentComparisonMode() {
        const form = (this.params.data && this.params.data.form) || {};
        if (this._supportsNativeComparison(form)) {
            return this._getComparisonMode(form);
        }
        if (this._supportsPeriodComparison(form)) {
            return this._getPeriodComparisonMode(form);
        }
        return "no_comparison";
    }

    _currentComparisonOrder() {
        const form = (this.params.data && this.params.data.form) || {};
        return form.comparison_order || "descending";
    }

    _getComparisonUpdates(mode, form = (this.params.data && this.params.data.form) || {}) {
        const start = form.date_from || form.date_to || form.date || false;
        const end = form.date_to || form.date_from || form.date || false;
        if (mode === "no_comparison") {
            return {
                enable_filter: false,
                filter_cmp: "filter_no",
                date_from_cmp: false,
                date_to_cmp: false,
                label_filter: false,
            };
        }
        if (!end) {
            return {};
        }
        if (mode === "previous_period") {
            if (form.date_from) {
                const startDate = this._parseDate(form.date_from);
                const endDate = this._parseDate(form.date_to || form.date_from);
                const diffDays = Math.round((endDate - startDate) / 86400000) + 1;
                const previousEnd = this._shiftDays(form.date_from, -1);
                const previousStart = this._shiftDays(form.date_from, -diffDays);
                return {
                    enable_filter: true,
                    filter_cmp: "filter_date",
                    date_from_cmp: previousStart,
                    date_to_cmp: previousEnd,
                    label_filter: _t("Previous Period"),
                };
            }
            const previousDate = this._shiftDays(end, -1);
            return {
                enable_filter: true,
                filter_cmp: "filter_date",
                date_from_cmp: previousDate,
                date_to_cmp: previousDate,
                label_filter: _t("Previous Period"),
            };
        }
        if (mode === "same_period_last_year") {
            return {
                enable_filter: true,
                filter_cmp: "filter_date",
                date_from_cmp: start ? this._shiftYears(start, -1) : false,
                date_to_cmp: this._shiftYears(end, -1),
                label_filter: _t("Same Period Last Year"),
            };
        }
        return {
            enable_filter: true,
            filter_cmp: "filter_date",
            date_from_cmp: form.date_from_cmp || start,
            date_to_cmp: form.date_to_cmp || end,
            label_filter: form.label_filter || _t("Comparison"),
        };
    }

    _injectIframeStyles(iframeDocument) {
        const styleId = "acc_reports_enterprise_simulation_iframe_style";
        const direction = this._direction();
        const textAlign = this._isRTL() ? "right" : "left";
        const oppositeAlign = this._isRTL() ? "left" : "right";
        const inlineStart = this._isRTL() ? "right" : "left";
        let style = iframeDocument.getElementById(styleId);
        if (!style) {
            style = iframeDocument.createElement("style");
            style.id = styleId;
            iframeDocument.head.appendChild(style);
        }
        style.textContent = `
            body.o_acc_reports_enterprise_simulation_iframe {
                background: #f5f7fb !important;
                margin: 0 !important;
                padding: 24px 0 48px !important;
                color: #243042;
                direction: ${direction} !important;
                font-family: "Tahoma", "Arial", "DejaVu Sans", sans-serif !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe,
            body.o_acc_reports_enterprise_simulation_iframe * {
                letter-spacing: 0 !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header,
            body.o_acc_reports_enterprise_simulation_iframe .page,
            body.o_acc_reports_enterprise_simulation_iframe .footer {
                max-width: 900px;
                margin-left: auto;
                margin-right: auto;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header {
                background: linear-gradient(180deg, #ffffff 0%, #fbfcfe 100%);
                border: 1px solid #dde3ec;
                box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
                border-radius: 18px;
                padding: 16px 24px;
                margin-bottom: 14px;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page {
                background: #ffffff;
                border: 1px solid #d8dde6;
                box-shadow: none;
                border-radius: 4px;
                padding: 24px 34px;
                margin-top: 18px;
                margin-bottom: 28px;
                direction: ${direction} !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header,
            body.o_acc_reports_enterprise_simulation_iframe .footer {
                display: none !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page {
                margin-top: 0;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page.o_acc_financial_page {
                background: transparent;
                border: 0;
                box-shadow: none;
                padding: 0;
                max-width: 860px;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page.o_trial_balance_page {
                background: transparent;
                border: 0;
                box-shadow: none;
                padding: 0;
                max-width: 1180px;
                margin-left: auto;
                margin-right: auto;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:first-child {
                flex: 0 0 auto;
                max-width: none;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:first-child > span {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 9px 14px;
                border-radius: 999px;
                background: #f4f7fb;
                color: #415168;
                font-size: 0.92rem;
                font-weight: 600;
                letter-spacing: 0.01em;
                box-shadow: inset 0 0 0 1px #dfe6ef;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:first-child > span::before {
                content: " ";
                width: 8px;
                height: 8px;
                border-radius: 999px;
                background: #c7a14d;
                box-shadow: 0 0 0 4px rgba(199, 161, 77, 0.12);
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:last-child {
                display: none !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:nth-child(2) {
                margin-left: auto;
                margin-right: auto;
                text-align: center !important;
                max-width: none;
                flex: 1 1 auto;
            }
            body.o_acc_reports_enterprise_simulation_iframe .header .row > div:nth-child(2) > span {
                display: inline-block;
                font-size: 1.25rem;
                font-weight: 700;
                line-height: 1.35;
                color: #1f2a3d;
                letter-spacing: 0.01em;
                white-space: nowrap;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page h2,
            body.o_acc_reports_enterprise_simulation_iframe .page h3 {
                color: #12223a;
                font-size: 20px;
                font-weight: 700;
                line-height: 1.35;
                margin: 0 0 22px;
                text-align: ${textAlign};
            }
            body.o_acc_reports_enterprise_simulation_iframe .page .row,
            body.o_acc_reports_enterprise_simulation_iframe > .row {
                direction: ${direction} !important;
                text-align: ${textAlign};
                max-width: 1100px;
                margin-left: auto;
                margin-right: auto;
            }
            body.o_acc_reports_enterprise_simulation_iframe > table.table-reports,
            body.o_acc_reports_enterprise_simulation_iframe > .table-reports {
                max-width: 1100px;
                margin-left: auto;
                margin-right: auto;
            }
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports,
            body.o_acc_reports_enterprise_simulation_iframe table.table-bordered {
                width: 100%;
                border-collapse: collapse !important;
                table-layout: auto;
                direction: ${direction} !important;
                color: #12223a;
                margin-top: 10px;
            }
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports th,
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports td,
            body.o_acc_reports_enterprise_simulation_iframe table.table-bordered th,
            body.o_acc_reports_enterprise_simulation_iframe table.table-bordered td {
                border: 0 !important;
                border-bottom: 1px solid #dde2e8 !important;
                padding: 5px 12px !important;
                line-height: 1.25;
                vertical-align: middle;
                font-size: 13px;
                text-align: ${textAlign};
            }
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports thead th,
            body.o_acc_reports_enterprise_simulation_iframe table.table-bordered thead th {
                color: #12223a;
                font-weight: 700;
                background: #fff;
            }
            body.o_acc_reports_enterprise_simulation_iframe .page table.table-reports tbody td {
                vertical-align: middle;
            }
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports tbody tr[style*="font-weight: bold"] td,
            body.o_acc_reports_enterprise_simulation_iframe table.table-reports tbody tr.o_total_row td,
            body.o_acc_reports_enterprise_simulation_iframe table.table-bordered tbody tr[style*="font-weight: bold"] td {
                background: #ebeced !important;
                border-bottom-color: #d8dadd !important;
                font-weight: 700;
            }
            body.o_acc_reports_enterprise_simulation_iframe .text-end,
            body.o_acc_reports_enterprise_simulation_iframe td.text-end,
            body.o_acc_reports_enterprise_simulation_iframe th.text-end {
                direction: ltr !important;
                text-align: ${oppositeAlign} !important;
                white-space: nowrap;
            }
            body.o_acc_reports_enterprise_simulation_iframe .text-center {
                text-align: ${textAlign} !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_preview_hidden_search {
                display: none !important;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_row_tools {
                display: inline-flex !important;
                position: relative;
                align-items: center;
                gap: 6px;
                margin-inline-start: 6px;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_action_btn {
                border: 0;
                background: transparent;
                color: #0f9cb6;
                width: 18px;
                height: 18px;
                padding: 0;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 4px;
                transition: background-color 0.15s ease, color 0.15s ease;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_action_btn:hover {
                background: #eef8fb;
                color: #0b7f95;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_action_dropdown {
                display: none;
                position: absolute;
                top: 24px;
                ${inlineStart}: 0;
                min-width: 156px;
                padding: 8px 0;
                background: #fff;
                border: 1px solid #d6dde7;
                border-radius: 4px;
                box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
                z-index: 30;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_row_tools.is-open .o_account_action_dropdown {
                display: block;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_action_item {
                display: block;
                width: 100%;
                border: 0;
                background: transparent;
                text-align: ${textAlign};
                padding: 9px 14px;
                color: #1f2a3d;
                font-size: 0.96rem;
            }
            body.o_acc_reports_enterprise_simulation_iframe .o_account_action_item:hover {
                background: #f6fafb;
            }
        `;
    }

    _normalizeSearchText(value) {
        return (value || "")
            .toString()
            .normalize("NFKD")
            .replace(/[\u064B-\u065F\u0670]/g, "")
            .replace(/[إأآا]/g, "ا")
            .replace(/ى/g, "ي")
            .replace(/ؤ/g, "و")
            .replace(/ئ/g, "ي")
            .replace(/ة/g, "ه")
            .replace(/\s+/g, " ")
            .trim()
            .toLocaleLowerCase();
    }

    _applySearchFilter() {
        if (!this.iframeDocument) {
            return;
        }
        const rows = this.iframeDocument.querySelectorAll("tbody tr");
        const needle = this._normalizeSearchText(this.uiState.searchTerm);
        const matchingRows = new Map();
        const relationKinds = ["report", "account", "partner", "agedPartner", "tb"];
        const matchingOwnIds = Object.fromEntries(relationKinds.map((kind) => [kind, new Set()]));
        const matchingParentIds = Object.fromEntries(relationKinds.map((kind) => [kind, new Set()]));
        const parentByChild = Object.fromEntries(relationKinds.map((kind) => [kind, new Map()]));
        const childrenByParent = Object.fromEntries(relationKinds.map((kind) => [kind, new Map()]));
        const rowKeys = new Map();

        const addChild = (kind, parentId, childId) => {
            if (!parentId || !childId) {
                return;
            }
            parentByChild[kind].set(childId, parentId);
            if (!childrenByParent[kind].has(parentId)) {
                childrenByParent[kind].set(parentId, new Set());
            }
            childrenByParent[kind].get(parentId).add(childId);
        };

        const getKeys = (row) => {
            const accountId = row.dataset.accountRowId || row.querySelector(".o_account_line")?.dataset.accountId || "";
            const partnerId = row.querySelector(".o_partner_line")?.dataset.partnerId || "";
            return {
                own: {
                    report: row.dataset.reportId || "",
                    account: accountId,
                    partner: partnerId,
                    agedPartner: row.dataset.agedPartnerId || "",
                    tb: row.dataset.tbLineKey || "",
                },
                parent: {
                    report: row.dataset.parentReportId || "",
                    account: row.dataset.parentAccountId || "",
                    partner: row.dataset.parentPartnerId || "",
                    agedPartner: row.dataset.parentAgedPartnerId || "",
                    tb: row.dataset.parentTbKey || "",
                },
            };
        };

        for (const row of rows) {
            row.classList.remove("o_preview_hidden_search");
            const keys = getKeys(row);
            rowKeys.set(row, keys);
            for (const kind of relationKinds) {
                addChild(kind, keys.parent[kind], keys.own[kind]);
            }
            if (!needle) {
                continue;
            }
            const haystack = this._normalizeSearchText(row.textContent);
            const matches = haystack.includes(needle);
            matchingRows.set(row, matches);
            if (!matches) {
                continue;
            }

            for (const kind of relationKinds) {
                if (keys.own[kind]) {
                    matchingOwnIds[kind].add(keys.own[kind]);
                }
                if (keys.parent[kind]) {
                    matchingParentIds[kind].add(keys.parent[kind]);
                }
            }
        }

        for (const kind of relationKinds) {
            const descendants = [...matchingOwnIds[kind]];
            for (const id of descendants) {
                for (const childId of childrenByParent[kind].get(id) || []) {
                    if (!matchingOwnIds[kind].has(childId)) {
                        matchingOwnIds[kind].add(childId);
                        descendants.push(childId);
                    }
                }
            }

            const ancestors = [...matchingParentIds[kind]];
            for (const id of ancestors) {
                const parentId = parentByChild[kind].get(id);
                if (parentId && !matchingParentIds[kind].has(parentId)) {
                    matchingParentIds[kind].add(parentId);
                    ancestors.push(parentId);
                }
            }
        }

        for (const row of rows) {
            if (!needle) {
                continue;
            }
            const keys = rowKeys.get(row);
            const visible = matchingRows.get(row) || relationKinds.some((kind) => (
                (keys.parent[kind] && matchingOwnIds[kind].has(keys.parent[kind])) ||
                (keys.own[kind] && matchingOwnIds[kind].has(keys.own[kind])) ||
                (keys.own[kind] && matchingParentIds[kind].has(keys.own[kind]))
            ));
            if (!visible) {
                row.classList.add("o_preview_hidden_search");
            }
        }
    }

    _applyIframeEnhancements() {
        if (!this.iframeDocument) {
            return;
        }
        this._injectIframeStyles(this.iframeDocument);
        this._applyCompanyLabelToIframe();
        this._applySearchFilter();
        this._bindIframeAccountActions();
    }

    _applyCompanyLabelToIframe() {
        if (!this.iframeDocument || !this.params.company_label) {
            return;
        }
        const companyLabel = this.iframeDocument.querySelector(".header .row > div:nth-child(2) > span");
        if (companyLabel) {
            companyLabel.textContent = this.params.company_label;
        }
    }

    _submitExportForm(action) {
        const form = document.createElement("form");
        form.method = "POST";
        form.action = action;
        form.target = "_blank";
        form.style.display = "none";

        const addField = (name, value) => {
            const input = document.createElement("input");
            input.type = "hidden";
            input.name = name;
            input.value = value;
            form.appendChild(input);
        };

        addField("report_name", this.params.report_name);
        addField("data", JSON.stringify(this.params.data || {}));
        addField("context", JSON.stringify(this.params.context || {}));
        addField("display_name", this.params.download_name || this.title || this.params.name || "");
        addField("search_term", this.uiState.searchTerm || "");
        if (window.odoo && odoo.csrf_token) {
            addField("csrf_token", odoo.csrf_token);
        }

        document.body.appendChild(form);
        form.submit();
        form.remove();
    }

    print() {
        this._submitExportForm("/acc_reports_enterprise_simulation/export_pdf");
    }

    exportXlsx() {
        this._submitExportForm("/acc_reports_enterprise_simulation/export_xlsx");
    }

    returnToPreviousReport() {
        if (this.params.return_action) {
            return this.action.doAction(this.params.return_action);
        }
    }

    async _reloadReport(updates) {
        const nextAction = await this.orm.call(
            "acc.report.preview.helper",
            "rerun_report_preview",
            [this.params.wizard_model, this.params.data?.form || {}, updates || {}]
        );
        nextAction.params.ui_state = {};
        if (this.params.return_action) {
            nextAction.params.return_action = this.params.return_action;
            nextAction.params.return_label = this.params.return_label;
        }
        this._setParams(nextAction.params || {}, { refresh: true });
        return true;
    }

    _choiceButton(title, label, field, choices) {
        return { type: "choice", title, label, field, choices };
    }

    _extractPeriodState(form) {
        const state = {};
        if ("date" in form) {
            state.date = form.date || "";
        }
        if ("date_from" in form) {
            state.date_from = form.date_from || "";
        }
        if ("date_to" in form) {
            state.date_to = form.date_to || "";
        }
        return state;
    }

    _setBasePeriod(nextForm) {
        this.uiState.basePeriod = this._extractPeriodState(nextForm || {});
    }

    _supportsNativeComparison(form) {
        return "enable_filter" in form || "comparison_context" in form;
    }

    _supportsPeriodComparison(form) {
        return ["account.balance.report", "account.tax.report.wizard"].includes(this.params.wizard_model)
            && ("date" in form || "date_from" in form || "date_to" in form);
    }

    _periodSignature(form) {
        if ("date" in form) {
            return `date:${form.date || ""}`;
        }
        return `range:${form.date_from || ""}|${form.date_to || ""}`;
    }

    _getPeriodComparisonUpdates(mode, form = this.uiState.basePeriod || {}) {
        const start = form.date_from || form.date || form.date_to || false;
        const end = form.date_to || form.date || form.date_from || false;
        if (mode === "no_comparison" || mode === "specific_date") {
            return { ...this._extractPeriodState(form) };
        }
        if (!end) {
            return {};
        }
        if ("date_from" in form || "date_to" in form) {
            if (mode === "previous_period") {
                const startDate = this._parseDate(form.date_from || form.date_to);
                const endDate = this._parseDate(form.date_to || form.date_from);
                const diffDays = Math.round((endDate - startDate) / 86400000) + 1;
                return {
                    date_from: this._shiftDays(form.date_from || form.date_to, -diffDays),
                    date_to: this._shiftDays(form.date_from || form.date_to, -1),
                };
            }
            if (mode === "same_period_last_year") {
                return {
                    date_from: start ? this._shiftYears(start, -1) : false,
                    date_to: this._shiftYears(end, -1),
                };
            }
        }
        if (mode === "previous_period") {
            return { date: this._shiftDays(end, -1) };
        }
        if (mode === "same_period_last_year") {
            return { date: this._shiftYears(end, -1) };
        }
        return { ...this._extractPeriodState(form) };
    }

    _getPeriodComparisonMode(form) {
        const current = this._periodSignature(form);
        const base = this._periodSignature(this.uiState.basePeriod || {});
        if (current === base) {
            return "no_comparison";
        }
        for (const mode of ["previous_period", "same_period_last_year"]) {
            if (this._periodSignature(this._getPeriodComparisonUpdates(mode)) === current) {
                return mode;
            }
        }
        return "specific_date";
    }

    _formatDate(date) {
        if (!date) {
            return "";
        }
        const parts = date.split("-");
        if (parts.length === 3) {
            return `${parts[1]}/${parts[2]}/${parts[0]}`;
        }
        return date;
    }

    _labelForDisplayAccount(value) {
        const map = {
            movement: _t("With Movement"),
            all: _t("All"),
            not_zero: _t("With Non-zero Balance"),
        };
        return map[value] || value;
    }

    _labelForResultSelection(value) {
        const map = {
            customer: _t("Customers"),
            supplier: _t("Vendors"),
            customer_supplier: _t("Partners"),
        };
        return map[value] || value;
    }

    _labelForAgedScope(value) {
        return value === "non_trade" ? _t("Non-trade Receivables") : _t("Trade Receivables");
    }

    _labelForAgingBasis(value) {
        return value === "invoice_date" ? _t("Invoice Date") : _t("Based on Due Date");
    }

    _entriesButtonLabel(form) {
        const targetMove = form.target_move === "posted" ? _t("Posted Entries") : _t("Draft Entries");
        if (form.cash_basis === undefined) {
            return targetMove;
        }
        const basis = form.cash_basis ? _t("Cash Basis") : _t("Accrual Basis");
        return _t("%s, %s", targetMove, basis);
    }

    _currentJournalIds() {
        const form = (this.params.data && this.params.data.form) || {};
        return [...(form.journal_ids || [])];
    }

    _selectedCompanyIds() {
        const form = (this.params.data && this.params.data.form) || {};
        return [...(this.params.selected_company_ids || form.selected_company_ids || [])].map((id) => Number(id));
    }

    _companyOptions() {
        return this.params.company_options || [];
    }

    _sameCompanySelection(companyIds) {
        const current = this._selectedCompanyIds().slice().sort((left, right) => left - right);
        const next = [...(companyIds || [])].map((id) => Number(id)).sort((left, right) => left - right);
        return current.length === next.length && current.every((id, index) => id === next[index]);
    }

    _isCompanySelected(companyId) {
        return this._sameCompanySelection([companyId]);
    }

    _isAllCompaniesSelected() {
        return this._sameCompanySelection(this._companyOptions().map((company) => company.id));
    }

    _companyButtonLabel() {
        const selectedIds = this._selectedCompanyIds();
        const options = this._companyOptions();
        if (selectedIds.length > 1 && selectedIds.length === options.length) {
            return _t("All");
        }
        if (selectedIds.length > 1) {
            return _t("Multiple Companies");
        }
        const company = options.find((option) => Number(option.id) === selectedIds[0]);
        return company ? company.name : (this.params.company_label || _t("Companies"));
    }

    _sortJournalIds(journalIds) {
        const order = new Map((this.params.journal_options || []).map((journal, index) => [journal.id, index]));
        return [...journalIds].sort((left, right) => (order.get(left) ?? 0) - (order.get(right) ?? 0));
    }

    _resetJournalDraftSelection() {
        this.uiState.journalDraftIds = this._currentJournalIds();
        return true;
    }

    _isJournalSelected(journalId) {
        return this.uiState.journalDraftIds.includes(journalId);
    }

    _toggleJournalSelection(journalId) {
        if (this._isJournalSelected(journalId)) {
            this.uiState.journalDraftIds = this.uiState.journalDraftIds.filter((id) => id !== journalId);
            return;
        }
        this.uiState.journalDraftIds = this._sortJournalIds([...this.uiState.journalDraftIds, journalId]);
    }

    _selectAllJournals() {
        this.uiState.journalDraftIds = (this.params.journal_options || []).map((journal) => journal.id);
    }

    _clearJournalSelection() {
        this.uiState.journalDraftIds = [];
    }

    applyJournalSelection() {
        if (!this.uiState.journalDraftIds.length) {
            return;
        }
        return this._reloadReport({ journal_ids: [...this.uiState.journalDraftIds] });
    }

    _currentAnalyticIds() {
        const form = (this.params.data && this.params.data.form) || {};
        return [...(form.analytic_account_ids || [])];
    }

    _resetAnalyticDraftSelection() {
        this.uiState.analyticDraftIds = this._currentAnalyticIds();
        return true;
    }

    _isAnalyticSelected(analyticId) {
        return this.uiState.analyticDraftIds.includes(analyticId);
    }

    _toggleAnalyticSelection(analyticId) {
        if (this._isAnalyticSelected(analyticId)) {
            this.uiState.analyticDraftIds = this.uiState.analyticDraftIds.filter((id) => id !== analyticId);
            return;
        }
        this.uiState.analyticDraftIds = [...this.uiState.analyticDraftIds, analyticId];
    }

    _selectAllAnalytics() {
        this.uiState.analyticDraftIds = (this.params.analytic_account_options || []).map((analytic) => analytic.id);
    }

    _clearAnalyticSelection() {
        this.uiState.analyticDraftIds = [];
    }

    applyAnalyticSelection() {
        return this._reloadReport({ analytic_account_ids: [...this.uiState.analyticDraftIds] });
    }

    _currentPartnerCategoryIds() {
        const form = (this.params.data && this.params.data.form) || {};
        return [...(form.partner_category_ids || [])];
    }

    _partnerCategoryOptions() {
        const form = (this.params.data && this.params.data.form) || {};
        return form.partner_category_options || [];
    }

    _resetPartnerCategoryDraftSelection() {
        this.uiState.partnerCategoryDraftIds = this._currentPartnerCategoryIds();
        return true;
    }

    _isPartnerCategorySelected(categoryId) {
        return this.uiState.partnerCategoryDraftIds.includes(categoryId);
    }

    _togglePartnerCategorySelection(categoryId) {
        if (this._isPartnerCategorySelected(categoryId)) {
            this.uiState.partnerCategoryDraftIds = this.uiState.partnerCategoryDraftIds.filter((id) => id !== categoryId);
            return;
        }
        this.uiState.partnerCategoryDraftIds = [...this.uiState.partnerCategoryDraftIds, categoryId];
    }

    _selectAllPartnerCategories() {
        this.uiState.partnerCategoryDraftIds = this._partnerCategoryOptions().map((category) => category.id);
    }

    _clearPartnerCategorySelection() {
        this.uiState.partnerCategoryDraftIds = [];
    }

    applyPartnerCategorySelection() {
        return this._reloadReport({ partner_category_ids: [...this.uiState.partnerCategoryDraftIds] });
    }

    _resetPeriodLengthDraft() {
        const form = (this.params.data && this.params.data.form) || {};
        this.uiState.periodLengthDraft = form.period_length || 30;
        return true;
    }

    _onPeriodLengthInput(ev) {
        this.uiState.periodLengthDraft = Number(ev.target.value || 0);
    }

    applyPeriodLength() {
        const periodLength = Math.max(1, Number(this.uiState.periodLengthDraft || 30));
        return this._reloadReport({ period_length: periodLength });
    }

    _getSmartButtons() {
        const form = (this.params.data && this.params.data.form) || {};
        const isAgedReport = this.params.data?.model === "account.aged.trial.balance";
        const buttons = [];
        if ((this.params.company_options || []).length > 1) {
            buttons.push({
                type: "companies_menu",
                title: _t("Companies"),
                label: this._companyButtonLabel(),
                icon: "fa fa-building-o",
            });
        }
        const date = form.date_to || form.date_from || form.date;
        if (date) {
            const fields = this._getDateFieldConfig(form);
            buttons.push({
                type: "date_menu",
                title: _t("Date"),
                label: this._formatDateButtonLabel(form),
                fields,
                primaryField: "date_to" in form ? "date_to" : fields[fields.length - 1]?.name,
                value: form.date_to || form.date || form.date_from,
                isRange: "date_from" in form && "date_to" in form,
                icon: "fa fa-calendar",
            });
        }
        if (this._supportsNativeComparison(form) || this._supportsPeriodComparison(form)) {
            buttons.push({
                type: "comparison_menu",
                title: _t("Comparison"),
                label: _t("Comparison"),
                icon: "fa fa-percent",
                withOrder: this._supportsNativeComparison(form),
            });
        }
        if (form.journal_ids && form.journal_ids.length) {
            const allJournalsCount = (this.params.journal_options || []).length;
            buttons.push({
                type: "journals_menu",
                title: _t("Journals"),
                label: form.journal_ids.length === allJournalsCount ? _t("All Journals") : _t("Journals"),
                icon: "fa fa-book",
            });
        }
        if (form.target_move) {
            buttons.push({
                type: "entries_menu",
                title: _t("Entries"),
                label: this._entriesButtonLabel(form),
                icon: "fa fa-sliders",
            });
        }
        if (form.period_length) {
            buttons.push({
                type: "period_length_menu",
                title: _t("Period Length"),
                label: _t("%s Days", form.period_length),
                icon: "fa fa-calendar",
            });
        }
        if (form.currency_unit && form.currency_unit_options) {
            buttons.push({
                ...this._choiceButton(
                    _t("Currency"),
                    form.currency_label,
                    "currency_unit",
                    form.currency_unit_options
                ),
                icon: "fa fa-money",
            });
        } else if (form.currency_label) {
            buttons.push({ label: form.currency_label, icon: "fa fa-money" });
        }
        if (form.tax_report_type && form.tax_report_type_options) {
            buttons.push({
                ...this._choiceButton(
                    _t("Report"),
                    _t("Report: %s", form.tax_report_type_label || form.tax_report_type),
                    "tax_report_type",
                    form.tax_report_type_options
                ),
                icon: "fa fa-book",
            });
        }
        if (isAgedReport && form.aging_based_on) {
            buttons.push({
                ...this._choiceButton(
                    _t("Aging Basis"),
                    this._labelForAgingBasis(form.aging_based_on),
                    "aging_based_on",
                    [
                        { value: "due_date", label: _t("Due Date") },
                        { value: "invoice_date", label: _t("Invoice Date") },
                    ]
                ),
                icon: "fa fa-file",
            });
        }
        if (isAgedReport && form.account_scope) {
            buttons.push({
                ...this._choiceButton(
                    _t("Account"),
                    this._labelForAgedScope(form.account_scope),
                    "account_scope",
                    [
                        { value: "trade", label: _t("Trade Receivables") },
                        { value: "non_trade", label: _t("Non-trade Receivables") },
                    ]
                ),
                icon: "fa fa-user",
            });
        }
        if (isAgedReport && form.partner_category_options) {
            const selectedCount = (form.partner_category_ids || []).length;
            buttons.push({
                type: "partner_categories_menu",
                title: _t("Partners"),
                label: selectedCount ? _t("Partners") : _t("Partners"),
                icon: "fa fa-folder-open",
            });
        }
        if (form.display_account) {
            buttons.push({
                ...this._choiceButton(
                    _t("Display Accounts"),
                    this._labelForDisplayAccount(form.display_account),
                    "display_account",
                    [
                        { value: "all", label: _t("All Accounts") },
                        { value: "movement", label: _t("Accounts with Movement") },
                        { value: "not_zero", label: _t("Accounts with Non-zero Balance") },
                    ]),
                icon: "fa fa-list-ul",
            });
        }
        if ("amount_currency" in form) {
            buttons.push({ type: "toggle", title: _t("Currency"), field: "amount_currency", label: form.amount_currency ? _t("In Currency") : _t("Base Currency"), icon: "fa fa-money" });
        }
        if ("reconciled" in form) {
            buttons.push({ type: "toggle", title: _t("Reconciled Entries"), field: "reconciled", label: form.reconciled ? _t("Reconciled Entries") : _t("All Partners"), icon: "fa fa-check-square-o" });
        }
        if (form.sort_selection) {
            buttons.push({
                ...this._choiceButton(
                    _t("Entries Order"),
                    form.sort_selection === "date" ? _t("Sort by Date") : _t("Sort by Entry Number"),
                    "sort_selection",
                    [
                        { value: "date", label: _t("Sort by Date") },
                        { value: "move_name", label: _t("Sort by Entry Number") },
                    ]),
                icon: "fa fa-sort",
            });
        }
        if (form.sortby) {
            buttons.push({
                ...this._choiceButton(
                    _t("Sort By"),
                    form.sortby === "sort_date" ? _t("Sort by Date") : _t("Sort by Journal and Partner"),
                    "sortby",
                    [
                        { value: "sort_date", label: _t("Sort by Date") },
                        { value: "sort_journal_partner", label: _t("Sort by Journal and Partner") },
                    ]),
                icon: "fa fa-sort",
            });
        }
        if (form.result_selection && !isAgedReport) {
            buttons.push({
                ...this._choiceButton(
                    _t("Partners"),
                    this._labelForResultSelection(form.result_selection),
                    "result_selection",
                    [
                        { value: "customer", label: _t("Customers") },
                        { value: "supplier", label: _t("Vendors") },
                        { value: "customer_supplier", label: _t("Partners") },
                    ]),
                icon: "fa fa-users",
            });
        }
        if (form.partner_ids && form.partner_ids.length) {
            buttons.push({ label: _t("Selected Partners"), icon: "fa fa-users" });
        }
        if ('analytic_account_ids' in form) {
            const allAnalyticsCount = (this.params.analytic_account_options || []).length;
            buttons.push({
                type: "analytic_accounts_menu",
                title: _t("Analytic Accounts"),
                label: form.analytic_account_ids.length === allAnalyticsCount
                    ? _t("All Analytic Accounts")
                    : form.analytic_account_ids.length
                        ? _t("Analytic Accounts")
                        : _t("Analytic Accounts"),
                icon: "fa fa-sitemap",
            });
        }
        return buttons;
    }

    _draftEntriesToggleLabel() {
        const form = (this.params.data && this.params.data.form) || {};
        return form.target_move === "posted" ? _t("Draft Entries") : _t("Posted Entries");
    }

    _unfoldAllLabel() {
        const form = (this.params.data && this.params.data.form) || {};
        return form.unfold_all ? _t("Fold All") : _t("Unfold All");
    }

    _fallbackReturnLabel() {
        return this.params.return_label || _t("Aged Receivable");
    }

    _smartButtonClasses(button) {
        return {
            "o_preview_chip": true,
            "o_preview_chip_active": !!button.type,
            [`o_preview_chip_${button.type}`]: !!button.type,
        };
    }

    _smartButtonKey(button) {
        return [
            button.type || "label",
            button.field || "",
            button.primaryField || "",
            button.title || "",
        ].join(":");
    }

    onSmartButtonClick(button) {
        const form = (this.params.data && this.params.data.form) || {};
        if (!button.type) {
            return;
        }
        if (button.type === "toggle") {
            return this._reloadReport({ [button.field]: !form[button.field] });
        }
    }

    onDatePresetSelected(button, preset) {
        if (preset === "specific_date") {
            return this.dialog.add(DateDialog, {
                title: _t("Custom Date"),
                fields: button.fields,
                values: (this.params.data && this.params.data.form) || {},
                onConfirm: (values) => {
                    this._setBasePeriod({ ...((this.params.data && this.params.data.form) || {}), ...values });
                    return this._reloadReport(values);
                },
            });
        }
        const updates = this._getDatePresetUpdates(button, preset);
        this._setBasePeriod({ ...((this.params.data && this.params.data.form) || {}), ...updates });
        return this._reloadReport(updates);
    }

    onDatePresetShift(button, preset, step) {
        const updates = this._shiftDatePresetValue(button, preset, step);
        this._setBasePeriod({ ...((this.params.data && this.params.data.form) || {}), ...updates });
        return this._reloadReport(updates);
    }

    onComparisonSelected(mode) {
        const form = (this.params.data && this.params.data.form) || {};
        if (this._supportsPeriodComparison(form)) {
            if (mode === "specific_date") {
                return this.dialog.add(DateDialog, {
                    title: _t("Custom Date"),
                    fields: this._getDateFieldConfig(form),
                    values: this._getPeriodComparisonUpdates("specific_date", form),
                    onConfirm: (values) => this._reloadReport(values),
                });
            }
            return this._reloadReport(this._getPeriodComparisonUpdates(mode));
        }
        if (mode === "specific_date") {
            const values = this._getComparisonUpdates("specific_date", form);
            return this.dialog.add(ComparisonDialog, {
                title: _t("Custom Date"),
                values,
                label: _t("Comparison"),
                onConfirm: (updates) => this._reloadReport(updates),
            });
        }
        return this._reloadReport(this._getComparisonUpdates(mode));
    }

    onComparisonOrderSelected(order) {
        return this._reloadReport({ comparison_order: order });
    }

    onChoiceSelected(button, value) {
        return this._reloadReport({ [button.field]: value });
    }

    onCompanySelected(companyIds) {
        if (!companyIds.length || this._sameCompanySelection(companyIds)) {
            return;
        }
        return this._reloadReport({ selected_company_ids: companyIds });
    }

    onEntriesSelected(mode) {
        if (mode === "toggle_draft_entries") {
            const form = (this.params.data && this.params.data.form) || {};
            const nextTargetMove = form.target_move === "posted" ? "all" : "posted";
            return this._reloadReport({ target_move: nextTargetMove });
        }
        if (mode === "toggle_hierarchy_subtotals") {
            const form = (this.params.data && this.params.data.form) || {};
            return this._reloadReport({
                hierarchy_subtotals: !form.hierarchy_subtotals,
                unfold_all: !form.hierarchy_subtotals ? form.unfold_all : false,
            });
        }
        if (mode === "unfold_all") {
            const form = (this.params.data && this.params.data.form) || {};
            const updates = { unfold_all: !form.unfold_all };
            if (form.hierarchy_subtotals !== undefined) {
                updates.hierarchy_subtotals = true;
            }
            return this._reloadReport(updates);
        }
        if (mode === "toggle_cash_basis") {
            const form = (this.params.data && this.params.data.form) || {};
            return this._reloadReport({ cash_basis: !form.cash_basis });
        }
        if (mode === "toggle_hide_zero_lines") {
            const form = (this.params.data && this.params.data.form) || {};
            return this._reloadReport({ hide_zero_lines: !form.hide_zero_lines });
        }
    }

    onSearchInput(ev) {
        this.uiState.searchTerm = ev.target.value || "";
        this._applyIframeEnhancements();
    }

    clearSearch() {
        this.uiState.searchTerm = "";
        this._applySearchFilter();
    }

    _closeIframeAccountMenus() {
        if (!this.iframeDocument) {
            return;
        }
        for (const menu of this.iframeDocument.querySelectorAll(".o_account_row_tools.is-open")) {
            menu.classList.remove("is-open");
        }
        for (const menu of this.iframeDocument.querySelectorAll(".o_pl_line_tools.is-open")) {
            menu.classList.remove("is-open");
        }
    }

    _bindIframeAccountActions() {
        if (!this.iframeDocument || this.iframeDocument.__accountPreviewActionsBound) {
            return;
        }
        this.iframeDocument.__accountPreviewActionsBound = true;
        this.iframeDocument.addEventListener("click", (ev) => this._onIframeAccountAction(ev));
    }

    _sourceReportTitle() {
        const titles = {
            "aged-partner-balance": _t("Aged Partner Balance"),
            "aged-payable": _t("Aged Payable"),
            "aged-receivable": _t("Aged Receivable"),
            "balance-sheet": _t("Balance Sheet"),
            "bank-book": _t("Bank Book"),
            "cash-book": _t("Cash Book"),
            "cash-flow-statement": _t("Cash Flow Statement"),
            "day-book": _t("All Journals"),
            "executive-summary": _t("Executive Summary"),
            "general-ledger": _t("General Ledger"),
            "journals-audit": _t("Journals Audit"),
            "partner-ledger": _t("Partner Ledger"),
            "profit-and-loss": _t("Profit and Loss"),
            "tax-report": _t("Tax Report"),
            "trial-balance": _t("Trial Balance"),
        };
        return titles[this.params.report_slug] || this.params.display_name || this.title || this.params.name || "";
    }

    _openDrilldownAction(action) {
        const sourceTitle = this._sourceReportTitle();
        if (sourceTitle && this.env.config?.setDisplayName) {
            this.env.config.setDisplayName(sourceTitle);
        }
        return this.action.doAction(action);
    }

    async _openAccountTarget(accountId, target) {
        const numericAccountId = Number(accountId);
        if (!numericAccountId) {
            return;
        }
        const action = await this.orm.call(
            "acc.report.preview.helper",
            "action_open_trial_balance_account_target",
            [this.params.data?.form || {}, numericAccountId, target]
        );
        if (action) {
            return this._openDrilldownAction(action);
        }
    }

    async _openTaxReportTarget(taxIdsValue, drilldownType, label) {
        const taxIds = [...new Set(
            String(taxIdsValue || "")
                .split(",")
                .map((value) => Number(value.trim()))
                .filter((value) => Number.isInteger(value) && value > 0)
        )];
        if (!taxIds.length || !["base", "tax"].includes(drilldownType)) {
            return;
        }
        const action = await this.orm.call(
            "acc.report.preview.helper",
            "action_open_tax_report_target",
            [this.params.data?.form || {}, taxIds, drilldownType, label || ""]
        );
        if (action) {
            return this._openDrilldownAction(action);
        }
    }

    _toggleFinancialReportLine(button) {
        const reportId = button?.dataset?.reportToggle;
        if (!reportId || !this.iframeDocument) {
            return;
        }
        const open = !button.classList.contains("is-open");
        button.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        const icon = button.querySelector(".fa");
        if (icon) {
            icon.classList.toggle("fa-caret-left", !open);
            icon.classList.toggle("fa-caret-down", open);
        }
        for (const row of this.iframeDocument.querySelectorAll("tr[data-parent-report-id]")) {
            if (row.dataset.parentReportId === reportId) {
                row.classList.toggle("o_acc_financial_folded_child", !open);
            }
        }
        this._applySearchFilter();
    }

    _toggleGeneralLedgerLine(button) {
        const accountId = button?.dataset?.accountToggle;
        if (!accountId || !this.iframeDocument) {
            return;
        }
        const open = !button.classList.contains("is-open");
        button.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        const icon = button.querySelector(".fa");
        if (icon) {
            icon.classList.toggle("fa-caret-left", !open);
            icon.classList.toggle("fa-caret-down", open);
        }
        for (const row of this.iframeDocument.querySelectorAll("tr[data-parent-account-id]")) {
            if (row.dataset.parentAccountId === accountId) {
                row.classList.toggle("o_gl_folded_child", !open);
            }
        }
        this._applySearchFilter();
    }

    _togglePartnerLedgerLine(button) {
        const partnerId = button?.dataset?.partnerToggle;
        if (!partnerId || !this.iframeDocument) {
            return;
        }
        const open = !button.classList.contains("is-open");
        button.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        const icon = button.querySelector(".fa");
        if (icon) {
            icon.classList.toggle("fa-caret-left", !open);
            icon.classList.toggle("fa-caret-down", open);
        }
        for (const row of this.iframeDocument.querySelectorAll("tr[data-parent-partner-id]")) {
            if (row.dataset.parentPartnerId === partnerId) {
                row.classList.toggle("o_pl_folded_child", !open);
            }
        }
        this._applySearchFilter();
    }

    _toggleAgedPartnerLine(button) {
        const partnerId = button?.dataset?.agedToggle;
        if (!partnerId || !this.iframeDocument) {
            return;
        }
        const open = !button.classList.contains("is-open");
        button.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        const icon = button.querySelector(".fa");
        if (icon) {
            icon.classList.toggle("fa-caret-left", !open);
            icon.classList.toggle("fa-caret-down", open);
        }
        for (const row of this.iframeDocument.querySelectorAll("tr[data-parent-aged-partner-id]")) {
            if (row.dataset.parentAgedPartnerId === partnerId) {
                row.classList.toggle("o_aged_folded_child", !open);
            }
        }
        this._applySearchFilter();
    }

    _toggleTrialBalanceLine(button) {
        const lineKey = button?.dataset?.tbToggle;
        if (!lineKey || !this.iframeDocument) {
            return;
        }
        const open = !button.classList.contains("is-open");
        button.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        const icon = button.querySelector(".fa");
        if (icon) {
            icon.classList.toggle("fa-caret-left", !open);
            icon.classList.toggle("fa-caret-down", open);
        }
        const rows = [...this.iframeDocument.querySelectorAll("tr[data-tb-line-key]")];
        const hideDescendants = (parentKey) => {
            for (const row of rows.filter((item) => item.dataset.parentTbKey === parentKey)) {
                row.classList.add("o_tb_folded_child");
                hideDescendants(row.dataset.tbLineKey);
            }
        };
        for (const row of rows.filter((item) => item.dataset.parentTbKey === lineKey)) {
            row.classList.toggle("o_tb_folded_child", !open);
            if (!open) {
                hideDescendants(row.dataset.tbLineKey);
            } else {
                const childToggle = row.querySelector(".o_tb_hierarchy_toggle");
                if (childToggle?.classList.contains("is-open")) {
                    for (const child of rows.filter((item) => item.dataset.parentTbKey === row.dataset.tbLineKey)) {
                        child.classList.remove("o_tb_folded_child");
                    }
                }
            }
        }
        this._applySearchFilter();
    }

    async _openPartnerTarget(partnerId, target) {
        const numericPartnerId = Number(partnerId);
        if (!numericPartnerId) {
            return;
        }
        const action = await this.orm.call(
            "acc.report.preview.helper",
            "action_open_partner_ledger_target",
            [this.params.data?.form || {}, numericPartnerId, target]
        );
        if (action) {
            return this._openDrilldownAction(action);
        }
    }

    async _openPartnerLedgerLineTarget(moveId, target) {
        const numericMoveId = Number(moveId);
        if (!numericMoveId) {
            return;
        }
        const action = await this.orm.call(
            "acc.report.preview.helper",
            "action_open_partner_ledger_line_target",
            [this.params.data?.form || {}, numericMoveId, target]
        );
        if (action) {
            return this._openDrilldownAction(action);
        }
    }

    async _openAgedPartnerTarget(partnerId, target) {
        const numericPartnerId = Number(partnerId);
        if (!numericPartnerId) {
            return;
        }
        const action = await this.orm.call(
            "acc.report.preview.helper",
            "action_open_aged_partner_target",
            [this.params.data?.form || {}, numericPartnerId, target]
        );
        if (action) {
            if (target === "partner_ledger" && action.params) {
                const returnParams = JSON.parse(JSON.stringify(this.params || {}));
                delete returnParams.return_action;
                delete returnParams.return_label;
                action.params.return_label = this.title || this.params.name || _t("Aged Receivable");
                action.params.return_action = {
                    type: "ir.actions.client",
                    tag: this.props.action?.tag || `report/${this.params.report_slug || "aged-receivable"}`,
                    name: this.params.name || this.title,
                    target: "current",
                    params: returnParams,
                };
            }
            return this._openDrilldownAction(action);
        }
    }

    _agedSortValue(row, sortKey) {
        const value = row?.dataset?.[`aged${sortKey.replace(/(^|_)([a-z])/g, (_, __, chr) => chr.toUpperCase())}`];
        if (["direction", "4", "3", "2", "1", "0", "total"].includes(sortKey)) {
            return Number(value || 0);
        }
        return (value || "").toString().toLocaleLowerCase();
    }

    _sortAgedTable(button) {
        if (!button || !this.iframeDocument) {
            return;
        }
        const table = button.closest("table");
        const tbody = table?.querySelector("tbody");
        const sortKey = button.dataset.agedSort;
        if (!tbody || !sortKey) {
            return;
        }
        const nextDirection = button.dataset.sortDirection === "asc" ? "desc" : "asc";
        for (const sortButton of table.querySelectorAll(".o_aged_sort_btn")) {
            sortButton.dataset.sortDirection = "";
            const icon = sortButton.querySelector(".o_aged_sort_icon");
            if (icon) {
                icon.textContent = "↕";
            }
        }
        button.dataset.sortDirection = nextDirection;
        const activeIcon = button.querySelector(".o_aged_sort_icon");
        if (activeIcon) {
            activeIcon.textContent = nextDirection === "asc" ? "↑" : "↓";
        }

        const groups = [...tbody.querySelectorAll(".o_aged_partner_summary")].map((summary, index) => ({
            summary,
            index,
            children: [...tbody.querySelectorAll(`tr[data-parent-aged-partner-id="${summary.dataset.agedPartnerId}"]`)],
        }));
        const numericSort = ["direction", "4", "3", "2", "1", "0", "total"].includes(sortKey);
        groups.sort((left, right) => {
            const leftValue = this._agedSortValue(left.summary, sortKey);
            const rightValue = this._agedSortValue(right.summary, sortKey);
            let result = 0;
            if (numericSort) {
                result = leftValue - rightValue;
            } else {
                result = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
            }
            if (result === 0) {
                result = left.index - right.index;
            }
            return nextDirection === "asc" ? result : -result;
        });
        for (const group of groups) {
            tbody.appendChild(group.summary);
            for (const child of group.children) {
                tbody.appendChild(child);
            }
        }
    }

    _onIframeAccountAction(ev) {
        const taxDrilldown = ev.target.closest(".o_tax_drilldown");
        const unfoldButton = ev.target.closest(".o_acc_financial_unfold_btn");
        const generalLedgerButton = ev.target.closest(".o_gl_unfold_btn");
        const partnerLedgerButton = ev.target.closest(".o_pl_unfold_btn");
        const agedPartnerButton = ev.target.closest(".o_aged_unfold");
        const trialBalanceButton = ev.target.closest(".o_tb_hierarchy_toggle");
        const partnerAction = ev.target.closest(".o_partner_action_item");
        const agedPartnerAction = ev.target.closest(".o_aged_partner_action_item");
        const agedSortButton = ev.target.closest(".o_aged_sort_btn");
        const partnerLedgerLineAction = ev.target.closest(".o_pl_line_action_item");
        const partnerLedgerLineMenu = ev.target.closest(".o_pl_line_action_menu");
        const actionItem = ev.target.closest(".o_account_action_item");
        const journalButton = ev.target.closest(".o_account_action_journal");
        const menuButton = ev.target.closest(".o_account_action_menu");

        if (taxDrilldown) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            const label = taxDrilldown.closest("tr")?.querySelector(".o_tax_label")?.textContent?.trim();
            return this._openTaxReportTarget(
                taxDrilldown.dataset.taxIds,
                taxDrilldown.dataset.taxDrilldownType,
                label
            );
        }

        if (unfoldButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            return this._toggleFinancialReportLine(unfoldButton);
        }

        if (generalLedgerButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            return this._toggleGeneralLedgerLine(generalLedgerButton);
        }

        if (partnerLedgerButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            return this._togglePartnerLedgerLine(partnerLedgerButton);
        }

        if (agedPartnerButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            return this._toggleAgedPartnerLine(agedPartnerButton);
        }

        if (trialBalanceButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            return this._toggleTrialBalanceLine(trialBalanceButton);
        }

        if (agedPartnerAction) {
            ev.preventDefault();
            const partnerLine = agedPartnerAction.closest(".o_aged_partner_summary");
            return this._openAgedPartnerTarget(partnerLine?.dataset.agedPartnerId, agedPartnerAction.dataset.action);
        }

        if (agedSortButton) {
            ev.preventDefault();
            return this._sortAgedTable(agedSortButton);
        }

        if (partnerAction) {
            ev.preventDefault();
            const partnerLine = partnerAction.closest(".o_partner_line");
            return this._openPartnerTarget(partnerLine?.dataset.partnerId, partnerAction.dataset.action);
        }

        if (partnerLedgerLineAction) {
            ev.preventDefault();
            const tools = partnerLedgerLineAction.closest(".o_pl_line_tools");
            this._closeIframeAccountMenus();
            return this._openPartnerLedgerLineTarget(tools?.dataset.moveId, partnerLedgerLineAction.dataset.action);
        }

        if (partnerLedgerLineMenu) {
            ev.preventDefault();
            const tools = partnerLedgerLineMenu.closest(".o_pl_line_tools");
            const isOpen = tools.classList.contains("is-open");
            this._closeIframeAccountMenus();
            if (!isOpen) {
                tools.classList.add("is-open");
            }
            return;
        }

        if (actionItem) {
            ev.preventDefault();
            const accountLine = actionItem.closest(".o_account_line");
            this._closeIframeAccountMenus();
            return this._openAccountTarget(accountLine?.dataset.accountId, actionItem.dataset.action);
        }

        if (journalButton) {
            ev.preventDefault();
            this._closeIframeAccountMenus();
            const accountLine = journalButton.closest(".o_account_line");
            return this._openAccountTarget(accountLine?.dataset.accountId, "journal_items");
        }

        if (menuButton) {
            ev.preventDefault();
            const tools = menuButton.closest(".o_account_row_tools");
            const isOpen = tools.classList.contains("is-open");
            this._closeIframeAccountMenus();
            if (!isOpen) {
                tools.classList.add("is-open");
            }
            return;
        }

        if (!ev.target.closest(".o_account_row_tools") && !ev.target.closest(".o_pl_line_tools")) {
            this._closeIframeAccountMenus();
        }
    }
}

AccountingReportPreviewClientAction.components = { Layout, Dropdown, DropdownItem };
AccountingReportPreviewClientAction.template = "acc_reports_enterprise_simulation.ReportClientAction";

const customerReportSlugs = [
    "trial-balance",
    "general-ledger",
    "partner-ledger",
    "profit-and-loss",
    "balance-sheet",
    "cash-flow-statement",
    "tax-report",
    "executive-summary",
    "aged-partner-balance",
    "aged-receivable",
    "aged-payable",
    "journals-audit",
    "day-book",
    "cash-book",
    "bank-book",
];

for (const slug of customerReportSlugs) {
    // Full tag is used when opening a report. The short alias lets Odoo restore
    // /odoo/report/<slug> after refresh while params come from session storage.
    registry.category("actions").add(`report/${slug}`, AccountingReportPreviewClientAction);
    registry.category("actions").add(slug, AccountingReportPreviewClientAction);
}

// Compatibility for already-open tabs and saved URLs using the former tag.
registry.category("actions").add(
    "accounting_reports.preview",
    AccountingReportPreviewClientAction
);
registry.category("actions").add(
    "acc_reports_enterprise_simulation.report_client_action",
    AccountingReportPreviewClientAction
);
