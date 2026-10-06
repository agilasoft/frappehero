// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Dispute", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Open") {
			return;
		}
		frm.add_custom_button(__("Resolve"), () => set_status(frm, "Resolved"), __("Dispute"));
		frm.add_custom_button(__("Cancel"), () => set_status(frm, "Cancelled"), __("Dispute"));
	},
	customer(frm) {
		frm.set_query("sales_invoice", () => ({
			filters: {
				customer: frm.doc.customer,
				company: frm.doc.company,
				docstatus: 1,
			},
		}));
	},
	company(frm) {
		frm.set_query("sales_invoice", () => ({
			filters: {
				customer: frm.doc.customer,
				company: frm.doc.company,
				docstatus: 1,
			},
		}));
	},
});

function set_status(frm, status) {
	frappe.call({
		method: "frappehero.dispute_desk.api.set_dispute_status",
		args: { name: frm.doc.name, status },
	}).then(() => frm.reload_doc());
}
