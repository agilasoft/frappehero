// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.query_reports["Receivables Aging"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "as_of",
			label: __("As of"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
	],
};
