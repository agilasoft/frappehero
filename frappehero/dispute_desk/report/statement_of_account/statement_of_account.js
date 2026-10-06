// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.query_reports["Statement of Account"] = {
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
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],
	onload(report) {
		frappehero_split_disputed_print(report);
	},
};

function frappehero_split_disputed_print(report) {
	if (report._disputed_print) {
		return;
	}
	report._disputed_print = true;
	const prepare = report.prepare_report_data.bind(report);
	report.prepare_report_data = function (payload) {
		prepare(payload);
		const all = this.data || [];
		this.disputed_rows = all.filter((row) => row.section === "Disputed Transactions");
		this.data = all.filter((row) => row.section !== "Disputed Transactions" && !row.is_section);
	};
}
