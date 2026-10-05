// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hero Account Map", {
	setup(frm) {
		frm.set_query("target_company", () => ({
			filters: { name: ["!=", frm.doc.company || ""] },
		}));
	},
	refresh(frm) {
		frm.trigger("set_account_queries");
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Open Account Mapper"), () => {
			frappe.set_route("account-mapper", frm.doc.name);
		});
	},
	company(frm) {
		frm.trigger("set_account_queries");
	},
	mapping_type(frm) {
		frm.trigger("set_account_queries");
	},
	target_company(frm) {
		frm.trigger("set_account_queries");
	},
	set_account_queries(frm) {
		const target_company =
			frm.doc.mapping_type === "Another Company" ? frm.doc.target_company : frm.doc.company;
		frm.set_query("source_account", "lines", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("target_account", "lines", () => ({
			filters: { company: target_company, is_group: 0 },
		}));
	},
});
