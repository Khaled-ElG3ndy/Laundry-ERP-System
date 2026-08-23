/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { getReportUrl } from "@web/webclient/actions/reports/utils";

const reportHandlers = registry.category("ir.actions.report handlers");

let wkhtmltopdfStatusPromise;

reportHandlers.add("report_pdf_inline_preview", async (action, options, env) => {
    if (action.report_type !== "qweb-pdf") {
        return false;
    }

    const previewWindow = window.open("", "_blank", "noopener");
    if (!previewWindow) {
        env.services.notification.add(
            _t("The browser blocked the PDF preview tab. Please allow pop-ups for this site."),
            {
                sticky: true,
                title: _t("Report"),
            }
        );
        return false;
    }

    wkhtmltopdfStatusPromise ||= env.services.rpc("/report/check_wkhtmltopdf");
    const status = await wkhtmltopdfStatusPromise;
    if (!["ok", "upgrade"].includes(status)) {
        previewWindow.close();
        return false;
    }

    const reportUrl = getReportUrl(action, "pdf", {
        ...env.services.user.context,
        ...(action.context || {}),
    });
    previewWindow.location = reportUrl;

    if (action.close_on_report_download) {
        await env.services.action.doAction(
            { type: "ir.actions.act_window_close" },
            { onClose: options.onClose }
        );
    } else if (options.onClose) {
        options.onClose();
    }

    return true;
});
