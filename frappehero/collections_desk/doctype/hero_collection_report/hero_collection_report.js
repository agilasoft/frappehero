// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Collection Report", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		if (frm.doc.status === "Open") {
			frm.add_custom_button(__("Close"), () => {
				frm.set_value("status", "Closed");
				frm.save();
			});
		}
		if (frm.doc.customer && frm.doc.company) {
			frm.add_custom_button(__("Collection Call"), () => {
				frappe.route_options = { company: frm.doc.company, customer: frm.doc.customer };
				frappe.set_route("collection-call");
			});
		}
	},
});
