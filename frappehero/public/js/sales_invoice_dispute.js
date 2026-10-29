// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

const HOLD_STATE_LABELS = {
	on_hold: "On hold",
	is_on_hold: "On hold",
};

// Same order as sales_invoice_dispute_fields(). The tab break comes first so
// the fields under it are not part of Details.
const DISPUTE_TAB_FIELDS = [
	"hero_dispute_tab",
	"hero_dispute_section",
	"hero_dispute",
	"hero_dispute_column",
	"hero_dispute_status",
	"hero_credit_section",
	"hero_credit_html",
	"hero_holds_section",
	"hero_holds_html",
];

frappe.ui.form.on("Sales Invoice", {
	before_load(frm) {
		const moved = dispute_section_is_in_the_header(frm);
		if (moved) {
			place_dispute_tab(frm);
		}
		const ordered = ordered_sales_invoice_fields(frm);
		const hide = header_column_breaks_to_hide(ordered);
		if (!moved && !hide.length) {
			return;
		}
		remake_layout(frm, ordered, hide);
	},

	refresh(frm) {
		load_dispute_tab(frm);
		if (frm.doc.docstatus !== 1) {
			return;
		}
		if (!frappe.user.has_role("System Manager") && !frappe.user.has_role("Accounts Manager")) {
			return;
		}
		if (frm.doc.hero_dispute_status === "Open" && frm.doc.hero_dispute) {
			frm.add_custom_button(
				__("Open Dispute"),
				() => frappe.set_route("Form", "Hero Dispute", frm.doc.hero_dispute),
				__("Dispute")
			);
			return;
		}
		frm.add_custom_button(__("Raise Dispute"), () => raise_dispute(frm), __("Dispute"));
	},

	customer(frm) {
		load_dispute_tab(frm);
	},

	company(frm) {
		load_dispute_tab(frm);
	},

	is_return(frm) {
		load_dispute_tab(frm);
	},

	return_against(frm) {
		load_dispute_tab(frm);
	},
});

function dispute_section_is_in_the_header(frm) {
	const map = frappe.meta.docfield_map["Sales Invoice"] || {};
	const section = map.hero_dispute_section;
	const dispute = map.hero_dispute;
	if (!section && !dispute) {
		return false;
	}
	const anchor = map.company || map.posting_date || map.is_return;
	const tab = map.hero_dispute_tab;
	if (!tab || tab.fieldtype !== "Tab Break") {
		return true;
	}
	if (anchor && section && field_idx(section) < field_idx(anchor)) {
		return true;
	}
	const layout = frm.doctype_layout;
	if (layout && layout.fields) {
		const names = layout.fields.map((row) => row.fieldname);
		const sectionAt = names.indexOf("hero_dispute_section");
		const companyAt = names.indexOf(anchor ? anchor.fieldname : "company");
		if (sectionAt >= 0 && companyAt >= 0 && sectionAt < companyAt) {
			return true;
		}
	}
	return false;
}

function place_dispute_tab(frm) {
	const map = frappe.meta.docfield_map["Sales Invoice"];
	if (!map) {
		return;
	}
	if (!map.hero_dispute_tab) {
		map.hero_dispute_tab = {
			doctype: "DocField",
			parent: "Sales Invoice",
			fieldname: "hero_dispute_tab",
			fieldtype: "Tab Break",
			label: __("Dispute"),
			idx: 0,
		};
	}
	map.hero_dispute_tab.fieldtype = "Tab Break";
	map.hero_dispute_tab.label = __("Dispute");
	if (map.hero_dispute_section) {
		map.hero_dispute_section.fieldtype = "Section Break";
		map.hero_dispute_section.collapsible = 0;
	}
	const skip = {};
	DISPUTE_TAB_FIELDS.forEach((name) => {
		skip[name] = true;
	});
	let maxIdx = 0;
	Object.keys(map).forEach((name) => {
		if (skip[name] || !map[name]) {
			return;
		}
		const idx = field_idx(map[name]);
		if (idx > maxIdx) {
			maxIdx = idx;
		}
	});
	let next = maxIdx + 1;
	DISPUTE_TAB_FIELDS.forEach((name) => {
		if (!map[name]) {
			return;
		}
		map[name].idx = next;
		next += 1;
	});
	reorder_doctype_layout(frm);
}

function reorder_doctype_layout(frm) {
	const layout = frm.doctype_layout;
	if (!layout || !layout.fields) {
		return;
	}
	const rows = layout.fields.slice();
	const names = rows.map((row) => row.fieldname);
	if (names.indexOf("hero_dispute") < 0 && names.indexOf("hero_dispute_section") < 0) {
		return;
	}
	if (names.indexOf("hero_dispute_tab") < 0) {
		rows.push({ fieldname: "hero_dispute_tab", label: __("Dispute") });
		names.push("hero_dispute_tab");
	}
	const byName = {};
	rows.forEach((row) => {
		byName[row.fieldname] = row;
	});
	layout.fields = dispute_tab_field_order(names)
		.map((name) => byName[name])
		.filter(Boolean);
}

function dispute_tab_field_order(fieldOrder) {
	const dispute = {};
	DISPUTE_TAB_FIELDS.forEach((name) => {
		dispute[name] = true;
	});
	const incoming = [];
	const present = {};
	(fieldOrder || []).forEach((name) => {
		if (!name) {
			return;
		}
		incoming.push(name);
		present[name] = true;
	});
	let hasBody = false;
	DISPUTE_TAB_FIELDS.forEach((name) => {
		if (name !== "hero_dispute_tab" && present[name]) {
			hasBody = true;
		}
	});
	if (!hasBody) {
		return incoming;
	}
	const rest = incoming.filter((name) => !dispute[name]);
	const body = DISPUTE_TAB_FIELDS.filter((name) => name === "hero_dispute_tab" || present[name]);
	return rest.concat(body);
}

function ordered_sales_invoice_fields(frm) {
	const map = frappe.meta.docfield_map["Sales Invoice"] || {};
	if (frm.doctype_layout && frm.doctype_layout.fields) {
		return frm.doctype_layout.fields
			.map((row) => map[row.fieldname])
			.filter(Boolean);
	}
	if (!frappe.meta.sort_docfields) {
		return [];
	}
	return frappe.meta.sort_docfields(map);
}

function header_column_breaks_to_hide(fields) {
	const hiddenBreaks = [];
	const visibleBreaks = [];
	let started = false;
	(fields || []).forEach((field) => {
		if (!field || started === "done") {
			return;
		}
		if (field.fieldname === "__newname") {
			return;
		}
		const fieldtype = field.fieldtype || "";
		if (fieldtype === "Tab Break") {
			if (started) {
				started = "done";
			}
			return;
		}
		if (fieldtype === "Section Break") {
			if (started) {
				started = "done";
				return;
			}
			started = true;
			return;
		}
		if (!fieldtype) {
			return;
		}
		started = true;
		if (fieldtype !== "Column Break" || !field.fieldname) {
			return;
		}
		if (field_hidden(field)) {
			hiddenBreaks.push(field.fieldname);
		} else {
			visibleBreaks.push(field.fieldname);
		}
	});
	const extras = visibleBreaks.length > 2 ? visibleBreaks.slice(0, visibleBreaks.length - 2) : [];
	return hiddenBreaks.concat(extras);
}

function field_hidden(df) {
	return df.hidden === 1 || df.hidden === true || df.hidden === "1";
}

function remake_layout(frm, ordered, hide) {
	if (!frm.layout || !frm.layout.make) {
		return;
	}
	const omit = {};
	(hide || []).forEach((name) => {
		omit[name] = true;
	});
	const body = (ordered || []).filter((df) => df && !omit[df.fieldname]);
	if (frm.layout.wrapper) {
		frm.layout.wrapper.remove();
	}
	frm.grids = [];
	frm.layout.tabs = [];
	frm.layout.sections = [];
	frm.layout.sections_dict = {};
	frm.layout.fields_list = [];
	frm.layout.fields_dict = {};
	frm.layout.section = null;
	frm.layout.column = null;
	frm.layout.fields = [
		{
			fieldtype: "Data",
			fieldname: "__newname",
			reqd: 1,
			hidden: 1,
			label: __("Name"),
			parent: "Sales Invoice",
		},
	].concat(body);
	frm.layout.make();
	frm.fields_dict = frm.layout.fields_dict;
	frm.fields = frm.layout.fields_list;

	const dashboardParent = $('<div class="form-dashboard">');
	let dashboardAdded = false;
	if (frm.layout.tabs && frm.layout.tabs.length) {
		frm.layout.tabs.every((tab) => {
			if (tab.df && tab.df.show_dashboard) {
				tab.wrapper.prepend(dashboardParent);
				dashboardAdded = true;
				return false;
			}
			return true;
		});
		if (!dashboardAdded) {
			frm.layout.tabs[0].wrapper.prepend(dashboardParent);
		}
	} else if (frm.layout.wrapper) {
		frm.layout.wrapper.find(".form-page").prepend(dashboardParent);
	}
	frm.dashboard = new frappe.ui.form.Dashboard(dashboardParent, frm);
}

function field_idx(df) {
	return parseInt(df && df.idx, 10) || 0;
}

function raise_dispute(frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				reqd: 1,
			},
		],
		async (values) => {
			const dispute = await frappe.call({
				method: "frappehero.dispute_desk.api.raise_dispute",
				args: {
					reference_doctype: "Sales Invoice",
					reference_name: frm.doc.name,
					sales_invoice: frm.doc.name,
					company: frm.doc.company,
					customer: frm.doc.customer,
					reason: values.reason,
					source_module: "ERPNext",
				},
			});
			await frm.reload_doc();
			frappe.show_alert({
				message: __("Dispute opened. Holds, collection, and dunning on this invoice were released."),
				indicator: "green",
			});
			if (dispute.message && dispute.message.name) {
				frappe.set_route("Form", "Hero Dispute", dispute.message.name);
			}
		},
		__("Raise Dispute"),
		__("Raise")
	);
}

async function load_dispute_tab(frm) {
	if (!frm.get_field("hero_credit_html") && !frm.get_field("hero_holds_html")) {
		return;
	}
	frm.__hero_dispute_token = (frm.__hero_dispute_token || 0) + 1;
	const token = frm.__hero_dispute_token;
	if (frm.is_new() && !frm.doc.customer) {
		render_dispute_tab(frm, { customer_known: 0, holds: [] });
		return;
	}
	render_dispute_tab(frm, null);
	try {
		const payload = await frappehero.call("frappehero.dispute_desk.api.invoice_dispute_tab", {
			sales_invoice: frm.is_new() ? "" : frm.doc.name,
			customer: frm.doc.customer,
			company: frm.doc.company,
			is_return: frm.doc.is_return ? 1 : 0,
			return_against: frm.doc.return_against,
		});
		if (token !== frm.__hero_dispute_token) {
			return;
		}
		render_dispute_tab(frm, payload || { customer_known: 0, holds: [] });
	} catch (error) {
		if (token !== frm.__hero_dispute_token) {
			return;
		}
		const failed = `<div class="fh-empty">${__("Credit and holds could not be loaded.")}</div>`;
		const credit = frm.get_field("hero_credit_html");
		const holds = frm.get_field("hero_holds_html");
		if (credit) {
			credit.$wrapper.html(failed);
		}
		if (holds) {
			holds.$wrapper.html("");
		}
	}
}

function render_dispute_tab(frm, payload) {
	const credit = frm.get_field("hero_credit_html");
	const holds = frm.get_field("hero_holds_html");
	if (!payload) {
		const waiting = `<div class="fh-empty">${__("Loading credit and holds.")}</div>`;
		if (credit) {
			credit.$wrapper.html(waiting);
		}
		if (holds) {
			holds.$wrapper.html("");
		}
		return;
	}
	if (credit) {
		credit.$wrapper.html(credit_html(payload));
	}
	if (holds) {
		holds.$wrapper.html(holds_html(payload.holds));
	}
}

function credit_html(credit) {
	if (!credit.customer_known) {
		return `<div class="fh-empty">${__("Choose a customer to see credit for this company.")}</div>`;
	}
	if (!credit.company_known) {
		return `<div class="fh-empty">${__("Choose a company to see the credit limit.")}</div>`;
	}
	const currency = credit.currency;
	const rows = [];
	if (credit.limit_set) {
		rows.push(text_rule(__("Credit Limit"), money(credit.credit_limit, currency)));
		rows.push(text_rule(__("Outstanding"), money(credit.outstanding, currency)));
		rows.push(text_rule(__("Available Credit"), money(credit.available, currency)));
	} else {
		rows.push(text_rule(__("Credit Limit"), __("No credit limit for this company.")));
		rows.push(text_rule(__("Outstanding"), money(credit.outstanding, currency)));
	}
	if (credit.bypass_credit_limit_check) {
		rows.push(
			text_rule(
				__("Bypass at Sales Order"),
				__("Credit limit is not checked on the sales order. It is checked on the invoice.")
			)
		);
	}
	if (credit.is_return) {
		const against = credit.return_against
			? doc_link("Sales Invoice", credit.return_against)
			: frappehero.esc(__("Not set"));
		rows.push(rule(__("This Credit Note"), `${frappehero.esc(__("Against"))} ${against}`));
	}
	rows.push(rule(__("Credit Notes"), credit_note_list(credit.credit_notes)));
	return rows.join("");
}

function credit_note_list(notes) {
	if (!notes || !notes.length) {
		return frappehero.esc(__("No credit notes against this invoice."));
	}
	return notes
		.map((note) => {
			const when = note.posting_date ? frappe.datetime.str_to_user(note.posting_date) : "";
			const amount = frappehero.esc(money(note.grand_total, note.currency));
			return `${doc_link("Sales Invoice", note.name)} ${frappehero.esc(when)} ${amount}`;
		})
		.join("<br>");
}

function holds_html(holds) {
	if (!holds || !holds.length) {
		return `<div class="fh-empty">${__("No holds on this invoice.")}</div>`;
	}
	const body = holds
		.map((row) => {
			const source = source_cell(row);
			const state = HOLD_STATE_LABELS[row.state] ? __(HOLD_STATE_LABELS[row.state]) : row.state || "";
			const status = row.active ? __("Active") : __("Released");
			const dispute = row.dispute ? doc_link("Hero Dispute", row.dispute) : "";
			return `<tr><td>${source}</td><td>${frappehero.esc(state)}</td><td>${frappehero.esc(status)}</td><td>${dispute}</td></tr>`;
		})
		.join("");
	return `<table class="fh-matrix"><thead><tr><th>${__("Source")}</th><th>${__("Hold")}</th><th>${__("Status")}</th><th>${__("Dispute")}</th></tr></thead><tbody>${body}</tbody></table>`;
}

function source_cell(row) {
	const doctype = row.source_doctype || "";
	if (!row.source_name) {
		return frappehero.esc(doctype || __("Hold"));
	}
	const link = doc_link(doctype || "Sales Invoice", row.source_name);
	if (!doctype) {
		return link;
	}
	return `${frappehero.esc(doctype)} ${link}`;
}

function doc_link(doctype, name) {
	if (!name) {
		return "";
	}
	const route = frappe.router.slug(doctype || "DocType");
	const href = `/app/${route}/${encodeURIComponent(name)}`;
	return `<a href="${href}">${frappehero.esc(name)}</a>`;
}

function rule(label, valueHtml) {
	return `<div class="fh-rule"><span class="fh-muted">${frappehero.esc(label)}</span><span>${valueHtml}</span></div>`;
}

function text_rule(label, text) {
	return rule(label, frappehero.esc(text));
}

function money(value, currency) {
	if (value == null || value === "") {
		return "";
	}
	return frappe.format(value, { fieldtype: "Currency", options: currency || "" });
}
