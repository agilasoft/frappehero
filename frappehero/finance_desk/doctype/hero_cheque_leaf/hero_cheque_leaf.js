// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Cheque Leaf", {
	setup(frm) {
		frm.set_query("bank_account", () => {
			const filters = { is_company_account: 1 };
			if (frm.doc.company) {
				filters.company = frm.doc.company;
			}
			return { filters };
		});
	},
});
