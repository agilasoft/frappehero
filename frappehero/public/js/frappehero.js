// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");

frappehero.esc = function (value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
};

frappehero.initials = function (label) {
	const parts = String(label || "?")
		.trim()
		.split(/\s+/)
		.slice(0, 2);
	const letters = parts.map((part) => part.charAt(0).toUpperCase()).join("");
	return letters || "?";
};

frappehero.safe_color = function (value) {
	return /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#2490ef";
};

frappehero.call = function (method, args) {
	return frappe.call({ method, args: args || {} }).then((response) => response.message);
};
