// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.query_reports["Unmapped Accounts"] = {
	filters: [
		{
			fieldname: "map",
			label: __("Account Map"),
			fieldtype: "Link",
			options: "Hero Account Map",
			reqd: 1,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "unmapped\npartial\nmapped\nall",
			default: "unmapped",
		},
		{
			fieldname: "root_type",
			label: __("Root Type"),
			fieldtype: "Select",
			options: "\nAsset\nLiability\nEquity\nIncome\nExpense",
		},
		{
			fieldname: "account_type",
			label: __("Account Type"),
			fieldtype: "Data",
			description: __("Exact account type, such as Bank or Receivable."),
		},
		{
			fieldname: "search",
			label: __("Search"),
			fieldtype: "Data",
		},
		{
			fieldname: "include_disabled",
			label: __("Include Disabled"),
			fieldtype: "Check",
		},
	],
};
