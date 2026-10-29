// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

const HOLD_STATE_LABELS = {
	on_hold: "On hold",
	is_on_hold: "On hold",
};

frappe.ui.form.on("Sales Invoice", {
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
