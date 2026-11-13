// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Collection Call", {
	setup(frm) {
		if (frm.is_new() && !frm.doc.collector) {
			frm.set_value("collector", frappe.session.user);
		}
	},
	refresh(frm) {
		if (frm.is_new() || !frm.doc.customer || !frm.doc.company) {
			return;
		}
		frm.add_custom_button(__("Collection Call"), () => {
			frappe.route_options = { company: frm.doc.company, customer: frm.doc.customer };
			frappe.set_route("collection-call");
		});
	},
});
