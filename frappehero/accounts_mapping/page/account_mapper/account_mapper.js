// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["account-mapper"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Account Mapper"),
		single_column: true,
	});
	wrapper.mapper = new frappehero.AccountMapper(page);
};

frappe.pages["account-mapper"].on_page_show = function (wrapper) {
	if (wrapper.mapper) {
		wrapper.mapper.show();
	}
};

frappehero.AccountMapper = class AccountMapper {
	constructor(page) {
		this.page = page;
		this.filters = { search: "", status: "unmapped", root_types: [], account_types: [], include_disabled: 0 };
		this.company = null;
		this.mapName = null;
		this.selectedAccount = null;
		this.checked = new Set();
		this.expanded = new Set();
		this.seededFor = null;
		this.state = null;
		this.targetControl = null;
		this.rootTypes = ["Asset", "Liability", "Equity", "Income", "Expense"];
		this.page.main.addClass("fh-page");
		this.page.set_primary_action(__("New Map"), () => this.openMapDialog(), "add");
		this.page.set_secondary_action(__("Suggest matches"), () => this.openSuggestions());
		this.page.add_menu_item(__("Unmapped Accounts report"), () => {
			const route = ["query-report", "Unmapped Accounts"];
			if (this.mapName) {
				frappe.route_options = { map: this.mapName };
			}
			frappe.set_route(route);
		});
		this.page.main.html(`
			<div class="fh-app">
				<div class="fh-filters">
					<select class="fh-company"></select>
					<select class="fh-map"></select>
					<button type="button" class="fh-btn-danger" data-action="delete-map">${__("Delete map")}</button>
					<input type="search" class="fh-search" placeholder="${__("Search name, number, type")}">
					<select class="fh-status">
						<option value="unmapped">${__("Unmapped")}</option>
						<option value="partial">${__("Partial")}</option>
						<option value="mapped">${__("Mapped")}</option>
						<option value="all">${__("All accounts")}</option>
					</select>
					<select class="fh-account-type"><option value="">${__("All account types")}</option></select>
					<label class="fh-check"><input type="checkbox" class="fh-disabled"> ${__("Include disabled")}</label>
				</div>
				<div class="fh-roots"></div>
				<div class="fh-coverage"></div>
				<div class="fh-tree-layout">
					<div class="fh-tree-wrap"></div>
					<section class="fh-detail"></section>
				</div>
			</div>
		`);
		this.coverageEl = this.page.main.find(".fh-coverage");
		this.treeEl = this.page.main.find(".fh-tree-wrap");
		this.detailEl = this.page.main.find(".fh-detail");
		this.page.main.find(".fh-roots").html(
			`<button type="button" class="fh-on" data-action="root" data-root="">${__("All")}</button>` +
				this.rootTypes
					.map((root) => `<button type="button" data-action="root" data-root="${root}">${__(root)}</button>`)
					.join("")
		);
		const root = this.page.main.find(".fh-app").get(0);
		root.addEventListener("click", (event) => this.onClick(event));
		root.addEventListener("change", (event) => this.onChange(event));
		root.addEventListener("input", (event) => this.onInput(event));
	}

	show() {
		const routeName = frappe.get_route()[1];
		if (routeName) {
			this.mapName = decodeURIComponent(routeName);
		}
		this.refresh();
	}

	async refresh() {
		this.page.main.addClass("fh-loading");
		try {
			this.state = await frappehero.call("frappehero.accounts_mapping.api.get_mapper_state", {
				company: this.company,
				map_name: this.mapName,
				filters: this.filters,
			});
			this.company = this.state.company || this.company;
			this.mapName = this.state.map ? this.state.map.name : null;
			if (this.seededFor !== this.mapName) {
				this.expanded = new Set();
				this.seed(this.state.tree || [], 0);
				this.seededFor = this.mapName;
				this.checked = new Set();
				this.selectedAccount = null;
			}
			this.syncFilterControls();
			this.render();
		} finally {
			this.page.main.removeClass("fh-loading");
		}
	}

	seed(nodes, depth) {
		(nodes || []).forEach((node) => {
			if (depth < 1 && (node.children || []).length) {
				this.expanded.add(node.name);
			}
			this.seed(node.children || [], depth + 1);
		});
	}

	syncFilterControls() {
		const company = this.page.main.find(".fh-company").get(0);
		const companies = this.state.companies || [];
		const companySignature = companies.join("|");
		if (company.dataset.signature !== companySignature) {
			company.innerHTML = companies
				.map((name) => `<option value="${frappehero.esc(name)}">${frappehero.esc(name)}</option>`)
				.join("");
			company.dataset.signature = companySignature;
		}
		if (this.company) {
			company.value = this.company;
		}
		this.page.main.find(".fh-status").val(this.filters.status || "unmapped");
		const mapSelect = this.page.main.find(".fh-map").get(0);
		const maps = this.state.maps || [];
		const mapSignature = maps.map((row) => row.name).join("|");
		if (mapSelect.dataset.signature !== mapSignature) {
			mapSelect.innerHTML =
				maps
					.map((row) => `<option value="${frappehero.esc(row.name)}">${frappehero.esc(row.name)}</option>`)
					.join("") || `<option value="">${__("No maps yet")}</option>`;
			mapSelect.dataset.signature = mapSignature;
		}
		if (this.mapName) {
			mapSelect.value = this.mapName;
		}
		const typeSelect = this.page.main.find(".fh-account-type").get(0);
		const types = this.state.account_types || [];
		const typeSignature = types.join("|");
		if (typeSelect.dataset.signature !== typeSignature) {
			const current = typeSelect.value;
			typeSelect.innerHTML =
				`<option value="">${__("All account types")}</option>` +
				types.map((name) => `<option value="${frappehero.esc(name)}">${frappehero.esc(name)}</option>`).join("");
			typeSelect.dataset.signature = typeSignature;
			if (types.includes(current)) {
				typeSelect.value = current;
			}
		}
	}

	render() {
		const coverage = this.state.coverage || { mapped: 0, partial: 0, unmapped: 0, total: 0, percent: 0 };
		const total = coverage.total || 0;
		const width = (count) => (total ? Math.round((count / total) * 1000) / 10 : 0);
		const map = this.state.map;
		this.coverageEl.html(`
			<strong>${map ? frappehero.esc(map.name) : __("No account map")}</strong>
			<span class="fh-muted">${map ? frappehero.esc(map.mapping_type) : ""} ${
				map && map.target_company ? "→ " + frappehero.esc(map.target_company) : ""
			}</span>
			${map && map.description ? `<div class="fh-muted">${frappehero.esc(map.description)}</div>` : ""}
			<div class="fh-bar">
				<i class="mapped" style="width:${width(coverage.mapped)}%"></i>
				<i class="partial" style="width:${width(coverage.partial)}%"></i>
				<i class="unmapped" style="width:${width(coverage.unmapped)}%"></i>
			</div>
			<div class="fh-legend">
				<span><i class="fh-dot fh-dot-mapped"></i>${__("{0} mapped", [String(coverage.mapped)])}</span>
				<span><i class="fh-dot fh-dot-partial"></i>${__("{0} partial", [String(coverage.partial)])}</span>
				<span><i class="fh-dot fh-dot-unmapped"></i>${__("{0} unmapped", [String(coverage.unmapped)])}</span>
				<span class="fh-muted">${__("{0}% of ledger accounts", [String(coverage.percent)])}</span>
			</div>
		`);
		const tree = this.state.tree || [];
		this.treeEl.html(
			tree.length
				? `<div class="fh-section-head" style="padding:8px">
						<button type="button" class="fh-btn-quiet" data-action="expand-all">${__("Expand all")}</button>
						<button type="button" class="fh-btn-quiet" data-action="collapse-all">${__("Collapse all")}</button>
						<span class="fh-muted fh-bulk-count">${__("{0} selected", [String(this.checked.size)])}</span>
					</div>${this.renderNodes(tree, 0)}`
				: `<div class="fh-empty">${
						map
							? __("Nothing matches these filters. Try All accounts, or clear the search.")
							: __("Create a map for this company to start matching accounts.")
					}</div>`
		);
		this.renderDetail();
	}

	renderNodes(nodes, depth) {
		return (nodes || []).map((node) => this.renderNode(node, depth)).join("");
	}

	renderNode(node, depth) {
		const children = node.children || [];
		const open = this.expanded.has(node.name);
		const label = `${node.account_number ? node.account_number + " · " : ""}${node.account_name || node.name}`;
		const meta = node.is_group
			? `${node.mapped_leaves || 0}/${node.total_leaves || 0}`
			: node.account_type || node.status;
		return `
			<div class="fh-node">
				<div class="fh-row ${this.selectedAccount === node.name ? "fh-row-selected" : ""}" style="padding-left:${8 + depth * 16}px" data-action="select-account" data-name="${frappehero.esc(node.name)}">
					${
						children.length
							? `<button type="button" class="fh-chevron" data-action="toggle-account" data-name="${frappehero.esc(node.name)}">${open ? "▾" : "▸"}</button>`
							: `<span class="fh-chevron-spacer"></span>`
					}
					${
						node.is_group
							? `<span class="fh-chevron-spacer"></span>`
							: `<input type="checkbox" data-action="check-account" data-name="${frappehero.esc(node.name)}" ${this.checked.has(node.name) ? "checked" : ""}>`
					}
					<span class="fh-dot fh-dot-${frappehero.esc(node.status || "unmapped")}"></span>
					<span class="fh-row-label">${frappehero.esc(label)}</span>
					<span class="fh-muted">${frappehero.esc(meta)}</span>
				</div>
				${open ? this.renderNodes(children, depth + 1) : ""}
			</div>
		`;
	}

	findAccount(name, nodes) {
		for (const node of nodes || []) {
			if (node.name === name) {
				return node;
			}
			const child = this.findAccount(name, node.children || []);
			if (child) {
				return child;
			}
		}
		return null;
	}

	renderDetail() {
		const map = this.state.map;
		const account = this.findAccount(this.selectedAccount, this.state.tree || []);
		if (!map) {
			this.detailEl.html(`<div class="fh-empty"><button type="button" class="fh-btn" data-action="new-map">${__("New Map")}</button></div>`);
			return;
		}
		if (!account || account.is_group) {
			this.detailEl.html(`
				<div class="fh-empty">
					<p>${__("Select a ledger account to map it. Tick several accounts to give them the same target.")}</p>
					<p class="fh-muted">${__("{0} selected", [String(this.checked.size)])}</p>
				</div>
			`);
			this.targetControl = null;
			return;
		}
		const line = account.line || {};
		const type = map.mapping_type;
		let fields = "";
		if (type === "Another Company") {
			fields = `<div class="fh-target"></div>`;
		} else if (type === "External Code") {
			fields = `
				<label>${__("External Code")}<input type="text" class="fh-external-code" value="${frappehero.esc(line.external_code || "")}"></label>
				<label>${__("External Name")}<input type="text" class="fh-external-name" value="${frappehero.esc(line.external_name || "")}"></label>
			`;
		} else {
			fields = `<label>${__("Reporting Group")}<input type="text" class="fh-reporting-group" value="${frappehero.esc(line.reporting_group || "")}"></label>`;
		}
		this.detailEl.html(`
			<div class="fh-muted">${frappehero.esc(account.root_type || "")} ${frappehero.esc(account.account_type || "")}</div>
			<h2 style="margin:4px 0 8px">${frappehero.esc(account.account_name || account.name)}</h2>
			<div><span class="fh-pill">${frappehero.esc(account.status)}</span></div>
			<div class="fh-form">
				${fields}
				<label>${__("Notes")}<textarea class="fh-notes">${frappehero.esc(line.notes || "")}</textarea></label>
				<div class="fh-actions">
					<button type="button" class="fh-btn" data-action="save-mapping">${__("Save")}</button>
					<button type="button" class="fh-btn" data-action="save-bulk">${__("Apply to {0} selected", [String(this.checked.size)])}</button>
					<button type="button" class="fh-btn-danger" data-action="clear-mapping">${__("Clear")}</button>
				</div>
			</div>
		`);
		this.targetControl = null;
		if (type === "Another Company") {
			this.targetControl = frappe.ui.form.make_control({
				parent: this.detailEl.find(".fh-target"),
				df: {
					fieldtype: "Link",
					fieldname: "target_account",
					options: "Account",
					label: __("Target Account"),
					ignore_user_permissions: 1,
					get_query: () => ({
						filters: { company: map.target_company, is_group: 0 },
					}),
				},
				render_input: true,
			});
			this.targetControl.set_value(line.target_account || "");
		}
	}

	readForm() {
		const type = this.state.map.mapping_type;
		const notes = this.detailEl.find(".fh-notes").val() || "";
		if (type === "Another Company") {
			return { target_account: this.targetControl ? this.targetControl.get_value() : "", notes };
		}
		if (type === "External Code") {
			return {
				external_code: this.detailEl.find(".fh-external-code").val() || "",
				external_name: this.detailEl.find(".fh-external-name").val() || "",
				notes,
			};
		}
		return { reporting_group: this.detailEl.find(".fh-reporting-group").val() || "", notes };
	}

	formIsComplete(values) {
		const type = this.state.map.mapping_type;
		if (type === "Another Company") {
			return !!values.target_account;
		}
		if (type === "External Code") {
			return !!String(values.external_code || "").trim();
		}
		return !!String(values.reporting_group || "").trim();
	}

	onInput(event) {
		if (!event.target.matches(".fh-search")) {
			return;
		}
		clearTimeout(this.searchTimer);
		this.searchTimer = setTimeout(() => {
			this.filters.search = event.target.value || "";
			this.refresh();
		}, 250);
	}

	onChange(event) {
		if (event.target.matches(".fh-company")) {
			this.company = event.target.value;
			this.mapName = null;
			this.seededFor = null;
			this.refresh();
		} else if (event.target.matches(".fh-map")) {
			this.mapName = event.target.value;
			this.seededFor = null;
			this.refresh();
		} else if (event.target.matches(".fh-status")) {
			this.filters.status = event.target.value;
			this.refresh();
		} else if (event.target.matches(".fh-account-type")) {
			this.filters.account_types = event.target.value ? [event.target.value] : [];
			this.refresh();
		} else if (event.target.matches(".fh-disabled")) {
			this.filters.include_disabled = event.target.checked ? 1 : 0;
			this.refresh();
		} else if (event.target.matches("[data-action='check-account']")) {
			const name = event.target.dataset.name;
			if (event.target.checked) {
				this.checked.add(name);
			} else {
				this.checked.delete(name);
			}
			const label = this.treeEl.find(".fh-bulk-count");
			label.text(__("{0} selected", [String(this.checked.size)]));
			const bulk = this.detailEl.find("[data-action='save-bulk']");
			if (bulk.length) {
				bulk.text(__("Apply to {0} selected", [String(this.checked.size)]));
			}
		}
	}

	onClick(event) {
		const target = event.target.closest("[data-action]");
		if (!target || target.matches("[data-action='check-account']")) {
			return;
		}
		const action = target.dataset.action;
		if (action === "toggle-account") {
			const name = target.dataset.name;
			if (this.expanded.has(name)) {
				this.expanded.delete(name);
			} else {
				this.expanded.add(name);
			}
			this.render();
		} else if (action === "select-account") {
			this.selectedAccount = target.dataset.name;
			this.treeEl.find(".fh-row").removeClass("fh-row-selected");
			target.classList.add("fh-row-selected");
			this.renderDetail();
		} else if (action === "root") {
			const rootType = target.dataset.root;
			this.page.main.find(".fh-roots button").removeClass("fh-on");
			if (!rootType) {
				this.filters.root_types = [];
				target.classList.add("fh-on");
			} else {
				const active = new Set(this.filters.root_types);
				if (active.has(rootType)) {
					active.delete(rootType);
				} else {
					active.add(rootType);
				}
				this.filters.root_types = this.rootTypes.filter((name) => active.has(name));
				if (!this.filters.root_types.length) {
					this.page.main.find('.fh-roots button[data-root=""]').addClass("fh-on");
				} else {
					this.filters.root_types.forEach((name) => {
						this.page.main.find(`.fh-roots button[data-root="${name}"]`).addClass("fh-on");
					});
				}
			}
			this.refresh();
		} else if (action === "expand-all" || action === "collapse-all") {
			this.expanded = new Set();
			if (action === "expand-all") {
				const walk = (nodes) =>
					(nodes || []).forEach((node) => {
						if ((node.children || []).length) {
							this.expanded.add(node.name);
						}
						walk(node.children);
					});
				walk(this.state.tree || []);
			}
			this.render();
		} else if (action === "new-map") {
			this.openMapDialog();
		} else if (action === "delete-map") {
			this.deleteMap();
		} else if (action === "save-mapping") {
			this.saveMapping(false);
		} else if (action === "save-bulk") {
			this.saveMapping(true);
		} else if (action === "clear-mapping") {
			this.clearMapping();
		}
	}

	async saveMapping(bulk) {
		if (!this.state.map) {
			return;
		}
		const values = this.readForm();
		if (!this.formIsComplete(values)) {
			frappe.msgprint(__("Fill in the target before saving."));
			return;
		}
		const sources = bulk ? Array.from(this.checked) : [this.selectedAccount];
		const rows = sources.filter(Boolean).map((source) => ({ source_account: source, ...values }));
		if (!rows.length) {
			frappe.msgprint(__("Select at least one ledger account."));
			return;
		}
		await frappehero.call("frappehero.accounts_mapping.api.set_mappings", {
			map_name: this.state.map.name,
			rows,
		});
		frappe.show_alert({ message: __("Mapping saved"), indicator: "green" });
		this.checked = new Set();
		this.refresh();
	}

	async clearMapping() {
		const sources = this.checked.size ? Array.from(this.checked) : [this.selectedAccount];
		await frappehero.call("frappehero.accounts_mapping.api.clear_mappings", {
			map_name: this.state.map.name,
			source_accounts: sources.filter(Boolean),
		});
		this.checked = new Set();
		this.refresh();
	}

	openMapDialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("New account map"),
			fields: [
				{ fieldtype: "Data", fieldname: "map_name", label: __("Map Name"), reqd: 1 },
				{
					fieldtype: "Select",
					fieldname: "mapping_type",
					label: __("Mapping Type"),
					options: "Another Company\nExternal Code\nReporting Group",
					reqd: 1,
					default: "Another Company",
				},
				{
					fieldtype: "Link",
					fieldname: "target_company",
					label: __("Target Company"),
					options: "Company",
					depends_on: "eval:doc.mapping_type=='Another Company'",
					mandatory_depends_on: "eval:doc.mapping_type=='Another Company'",
					get_query: () => ({ filters: { name: ["!=", this.company || ""] } }),
				},
				{ fieldtype: "Small Text", fieldname: "description", label: __("Description") },
			],
			primary_action_label: __("Create"),
			primary_action: async (values) => {
				if (!this.company) {
					frappe.msgprint(__("Choose a company first."));
					return;
				}
				const created = await frappehero.call("frappehero.accounts_mapping.api.create_map", {
					map_name: values.map_name,
					company: this.company,
					mapping_type: values.mapping_type,
					target_company: values.target_company,
					description: values.description,
				});
				dialog.hide();
				this.mapName = created.name;
				this.seededFor = null;
				this.filters.status = "unmapped";
				this.refresh();
			},
		});
		dialog.show();
	}

	deleteMap() {
		if (!this.mapName) {
			return;
		}
		frappe.confirm(__("Delete this account map and its lines?"), async () => {
			await frappehero.call("frappehero.accounts_mapping.api.delete_map", { name: this.mapName });
			this.mapName = null;
			this.seededFor = null;
			this.refresh();
		});
	}

	async openSuggestions() {
		if (!this.mapName) {
			frappe.msgprint(__("Create a map first."));
			return;
		}
		const rows = await frappehero.call("frappehero.accounts_mapping.api.suggest", { map_name: this.mapName });
		if (!rows || !rows.length) {
			frappe.msgprint(
				__("No unambiguous matches. An account number that appears once, or a matching account name, is required.")
			);
			return;
		}
		const shown = rows.slice(0, 200);
		const dialog = new frappe.ui.Dialog({
			title: __("Suggested matches"),
			fields: [{ fieldtype: "HTML", fieldname: "results" }],
			primary_action_label: __("Apply selected"),
			primary_action: async () => {
				const picked = [];
				dialog.fields_dict.results.$wrapper.find("input:checked").each(function () {
					picked.push(rows[Number($(this).val())]);
				});
				if (!picked.length) {
					frappe.msgprint(__("Select at least one suggestion."));
					return;
				}
				await frappehero.call("frappehero.accounts_mapping.api.set_mappings", {
					map_name: this.mapName,
					rows: picked.map((row) => ({
						source_account: row.source_account,
						target_account: row.target_account,
						external_code: row.external_code,
						external_name: row.external_name,
						reporting_group: row.reporting_group,
					})),
				});
				dialog.hide();
				frappe.show_alert({ message: __("Suggestions applied"), indicator: "green" });
				this.refresh();
			},
		});
		dialog.fields_dict.results.$wrapper.html(
			`<div class="fh-muted" style="margin-bottom:8px">${__("{0} suggestions. Showing {1}.", [
				String(rows.length),
				String(shown.length),
			])}</div>` +
				shown
					.map((row, index) => {
						const target = row.target_account || row.external_code || row.reporting_group;
						return `
							<label class="fh-pick">
								<input type="checkbox" value="${index}" checked>
								<span>
									<strong>${frappehero.esc(row.account_name || row.source_account)}</strong>
									<div class="fh-muted">${frappehero.esc(target)} · ${frappehero.esc(row.reason)}</div>
								</span>
							</label>`;
					})
					.join("")
		);
		dialog.show();
	}
};
