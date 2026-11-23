// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

// Sales Invoice, Purchase Invoice, and Payment Entry keep workflow state and
// status in separate fields. The desk pill is one status: the workflow state
// while the document is draft, and the ERPNext status after that. Colors for
// Paid, Overdue, and the other submitted statuses match the ERPNext list.

const DOCTYPES = ["Sales Invoice", "Purchase Invoice", "Payment Entry"];

const WORKFLOW_STYLE_COLORS = {
	Success: "green",
	Warning: "orange",
	Danger: "red",
	Primary: "blue",
	Inverse: "black",
	Info: "light-blue",
};

const SALES_INVOICE_COLORS = {
	Draft: "red",
	Unpaid: "orange",
	Paid: "green",
	Return: "gray",
	"Credit Note Issued": "gray",
	"Unpaid and Discounted": "orange",
	"Partly Paid and Discounted": "yellow",
	"Overdue and Discounted": "red",
	Overdue: "red",
	"Partly Paid": "yellow",
	"Internal Transfer": "darkgrey",
};

const PURCHASE_INVOICE_COLORS = {
	Unpaid: "orange",
	Paid: "green",
	Return: "gray",
	Overdue: "red",
	"Partly Paid": "yellow",
	"Internal Transfer": "darkgrey",
	"Debit Note Issued": "gray",
};

const STATUS_COLORS = {
	"Sales Invoice": SALES_INVOICE_COLORS,
	"Purchase Invoice": PURCHASE_INVOICE_COLORS,
};

// A workflow often writes one of these into Status for every draft. The
// document's own workflow state is the status to show.
const GENERIC_DRAFT_STATUSES = new Set(["draft", "pending", "pending for approval", "pending approval"]);

function docstatusOf(doc) {
	const value = doc && doc.docstatus;
	if (value === undefined || value === null || value === "") {
		return 0;
	}
	const number = Number(value);
	return Number.isFinite(number) ? number : 0;
}

function flag(value) {
	if (value === true) {
		return 1;
	}
	if (value === false || value == null || value === "") {
		return 0;
	}
	const number = Number(value);
	return Number.isFinite(number) ? number : 0;
}

function text(value) {
	return String(value == null ? "" : value).trim();
}

function isGenericDraftStatus(value) {
	return GENERIC_DRAFT_STATUSES.has(text(value).toLowerCase());
}

function workflowStateOf(doc, stateField) {
	const field = text(stateField);
	if (!field) {
		return null;
	}
	const configured = text(doc[field]);
	const dedicated = text(doc.workflow_state);
	if (field === "status" && isGenericDraftStatus(configured) && dedicated && dedicated !== configured) {
		return { field: "workflow_state", state: dedicated };
	}
	if (!configured) {
		return null;
	}
	return { field: field, state: configured };
}

function presentedIndicator(doc, options) {
	const settings = options || {};
	const doctype = settings.doctype || (doc && doc.doctype);
	if (!doc || !DOCTYPES.includes(doctype) || doc.__unsaved || !text(settings.stateField)) {
		return null;
	}
	const translate = settings.translate || ((label) => label);
	const docstatus = docstatusOf(doc);
	const resolved = workflowStateOf(doc, settings.stateField);

	if (docstatus === 0 && resolved) {
		const style = settings.stateStyle ? settings.stateStyle(resolved.state) : "";
		return [
			translate(resolved.state, doctype),
			WORKFLOW_STYLE_COLORS[style] || "gray",
			resolved.field + ",=," + resolved.state,
		];
	}
	if (docstatus === 2) {
		return [translate("Cancelled", doctype), "red", "docstatus,=,2"];
	}
	if (docstatus === 0) {
		return [translate("Draft", doctype), "red", "docstatus,=,0"];
	}

	if (doctype === "Purchase Invoice") {
		const hold = purchaseIndicator(doc, doctype, translate, settings);
		if (hold) {
			return hold;
		}
	}

	const colors = STATUS_COLORS[doctype];
	const status = text(doc.status);
	if (colors && status && colors[status]) {
		return [translate(status, doctype), colors[status], "status,=," + status];
	}
	if (docstatus === 1) {
		return [translate("Submitted", doctype), "blue", "docstatus,=,1"];
	}
	return null;
}

function purchaseIndicator(doc, doctype, translate, settings) {
	const status = text(doc.status);
	if (status === "Debit Note Issued") {
		return [translate(status, doctype), "gray", "status,=," + status];
	}
	const outstanding = Number(doc.outstanding_amount);
	if (!(Number.isFinite(outstanding) && outstanding > 0 && docstatusOf(doc) === 1 && flag(doc.on_hold))) {
		return null;
	}
	if (!text(doc.release_date)) {
		return [translate("On Hold", doctype), "darkgrey"];
	}
	if (settings.isReleaseInFuture && settings.isReleaseInFuture(doc.release_date)) {
		return [translate("Temporarily on Hold", doctype), "darkgrey"];
	}
	return null;
}

function hasField(desk, doctype, fieldname) {
	if (!desk.meta || typeof desk.meta.has_field !== "function") {
		return false;
	}
	return Boolean(desk.meta.has_field(doctype, fieldname));
}

function stateFieldName(desk, doctype) {
	try {
		if (!desk.workflow || typeof desk.workflow.get_state_fieldname !== "function") {
			return "";
		}
		return text(desk.workflow.get_state_fieldname(doctype));
	} catch (error) {
		return "";
	}
}

function workflowStyle(state) {
	const root = typeof window !== "undefined" ? window : typeof global !== "undefined" ? global : null;
	const table = root && root.locals && root.locals["Workflow State"];
	const row = table && table[state];
	return (row && row.style) || "";
}

function releaseIsInFuture(desk, date) {
	if (!desk.datetime || typeof desk.datetime.get_diff !== "function" || typeof desk.datetime.nowdate !== "function") {
		return false;
	}
	return desk.datetime.get_diff(date, desk.datetime.nowdate()) > 0;
}

function translateLabel(label, doctype) {
	if (typeof __ === "function") {
		return __(label, null, doctype);
	}
	return label;
}

function indicatorOptions(desk, doctype) {
	return {
		doctype: doctype,
		stateField: stateFieldName(desk, doctype),
		stateStyle: workflowStyle,
		translate: translateLabel,
		isReleaseInFuture: (date) => releaseIsInFuture(desk, date),
	};
}

function paintStatus(control, label, value) {
	if (!control) {
		return;
	}
	if (control.disp_area && typeof control.disp_area.text === "function") {
		control.disp_area.text(label);
	}
	const input = control.$input;
	if (!input || typeof input.val !== "function") {
		return;
	}
	const isSelect = typeof input.is === "function" && input.is("select");
	if (isSelect && typeof input.get === "function") {
		const element = input.get(0);
		const options = element && element.options ? Array.from(element.options) : [];
		if (element && !options.some((option) => option.value === value)) {
			element.add(new Option(label, value));
		}
	}
	input.val(isSelect ? value : label);
}

function showStateOnStatus(frm, desk) {
	if (!frm || !frm.doc || !frm.fields_dict || !frm.fields_dict.status) {
		return;
	}
	const doctype = frm.doctype || frm.doc.doctype;
	const resolved = workflowStateOf(frm.doc, stateFieldName(desk, doctype));
	if (docstatusOf(frm.doc) !== 0 || !resolved || resolved.state === text(frm.doc.status)) {
		return;
	}
	paintStatus(frm.fields_dict.status, translateLabel(resolved.state, doctype), resolved.state);
}

function install(desk) {
	if (!desk || desk.__heroDocumentStatus || typeof desk.get_indicator !== "function") {
		return;
	}
	desk.__heroDocumentStatus = true;
	const original = desk.get_indicator;
	const indicator = function (doc, doctype, showWorkflowState) {
		const name = doctype || (doc && doc.doctype);
		const presented = presentedIndicator(doc, indicatorOptions(desk, name));
		if (!presented) {
			return original.call(this, doc, doctype, showWorkflowState);
		}
		return presented;
	};
	indicator._heroDocumentStatus = true;
	desk.get_indicator = indicator;

	if (desk.ui && desk.ui.form && typeof desk.ui.form.on === "function") {
		DOCTYPES.forEach((doctype) => {
			desk.ui.form.on(doctype, {
				refresh(frm) {
					showStateOnStatus(frm, desk);
				},
			});
		});
	}

	const ListView = desk.views && desk.views.ListView;
	if (!ListView || !ListView.prototype || typeof ListView.prototype.set_fields !== "function") {
		return;
	}
	const originalFields = ListView.prototype.set_fields;
	ListView.prototype.set_fields = async function () {
		const result = await originalFields.apply(this, arguments);
		if (!DOCTYPES.includes(this.doctype) || typeof this._add_field !== "function") {
			return result;
		}
		const configured = stateFieldName(desk, this.doctype);
		if (!configured) {
			return result;
		}
		this._add_field(configured);
		if (configured !== "workflow_state" && hasField(desk, this.doctype, "workflow_state")) {
			this._add_field("workflow_state");
		}
		return result;
	};
}

function boot() {
	if (typeof frappe === "undefined") {
		return;
	}
	const start = () => install(frappe);
	if (frappe.views && frappe.views.ListView) {
		start();
	}
	if (typeof frappe.ready === "function") {
		frappe.ready(start);
	} else if (!(frappe.views && frappe.views.ListView)) {
		start();
	}
}

boot();

if (typeof module !== "undefined" && module.exports) {
	module.exports = {
		DOCTYPES,
		presentedIndicator,
		workflowStateOf,
		paintStatus,
		showStateOnStatus,
		install,
	};
}
