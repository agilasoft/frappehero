app_name = "frappehero"
app_title = "Frappe Hero"
app_publisher = "Agilasoft"
app_description = "Group users and the documents they may use, map accounts, and review access, defaults, shares, dimensions, tax, opening entries, and invoice disputes."
app_email = "dev@agilasoft.com"
app_license = "mit"

required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "frappehero",
		"logo": "/assets/frappehero/images/logo.svg",
		"title": "Frappe Hero",
		"route": "/app/frappe-hero",
		"has_permission": "frappehero.api.has_app_permission",
	}
]

app_include_css = "/assets/frappehero/css/frappehero.css"
app_include_js = "/assets/frappehero/js/frappehero.js"

doctype_list_js = {
	"Hero Permission Group": "public/js/hero_permission_group_list.js",
}

doctype_js = {
	"Sales Invoice": "public/js/sales_invoice_dispute.js",
}

after_install = "frappehero.install.after_install"
after_migrate = "frappehero.install.after_migrate"

doc_events = {
	"User Permission": {
		"validate": "frappehero.permissions.lock_hero_fields",
	},
	"GL Entry": {
		"validate": "frappehero.finance_desk.gl.apply_dimension_defaults",
	},
}

scheduler_events = {
	"daily": ["frappehero.access_desk.tasks.daily"],
}

# Permission Studio writes User Permissions. The ownership fields are read-only
# in the desk and are restored on validate unless the sync flag is set.
