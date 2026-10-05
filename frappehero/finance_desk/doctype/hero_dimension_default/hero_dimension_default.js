// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Dimension Default", {
	company(frm) {
		frm.set_query("account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
			},
		}));
	},
});
