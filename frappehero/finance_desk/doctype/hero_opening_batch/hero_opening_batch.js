// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Opening Batch", {
	company(frm) {
		frm.set_query("matched_account", "lines", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
			},
		}));
	},
});
