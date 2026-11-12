// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

frappe.provide("frappehero");
if (!frappehero.call) {
	frappehero.esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
	frappehero.call = (method, args) => frappe.call({ method, args: args || {} }).then((response) => response.message);
}

frappe.pages["proof-of-payment"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Proof of Payment"),
		single_column: true,
	});
	wrapper.proofOfPayment = new frappehero.ProofOfPayment(page);
};

frappe.pages["proof-of-payment"].on_page_show = function (wrapper) {
	if (wrapper.proofOfPayment) {
		wrapper.proofOfPayment.loadPending();
	}
};

frappe.pages["proof-of-payment"].on_page_hide = function (wrapper) {
	if (wrapper.proofOfPayment) {
		wrapper.proofOfPayment.stopScan();
	}
};

frappehero.ProofOfPayment = class ProofOfPayment {
	constructor(page) {
		this.page = page;
		this.payment = null;
		this.pending = [];
		this.busy = false;
		this.scanning = false;
		this.stream = null;
		this.scanFormats = ["qr_code", "code_128"];
		this.page.main.addClass("fh-page");
		this.page.main.html(`
			<div class="fh-app fh-proof">
				<p class="fh-muted">${__("Scan a Payment Entry, or type its name. Then add the proof.")}</p>
				<div class="fh-proof-scan">
					<label class="fh-proof-label">
						${__("Payment Entry")}
						<input type="text" class="fh-proof-id" autocomplete="off" enterkeyhint="search" placeholder="${__("ACC-PAY-2026-00001")}">
					</label>
					<div class="fh-proof-actions">
						<button type="button" class="fh-btn" data-action="lookup">${__("Look up")}</button>
						<button type="button" class="fh-btn" data-action="scan">${__("Scan")}</button>
					</div>
				</div>
				<section class="fh-proof-detail"></section>
				<section class="fh-proof-pending">
					<h2>${__("Pending upload")}</h2>
					<div class="fh-proof-cards"></div>
				</section>
				<div class="fh-proof-camera" hidden>
					<p class="fh-proof-camera-hint">${__("Point the camera at the Payment Entry code.")}</p>
					<video playsinline autoplay muted></video>
					<button type="button" class="fh-btn" data-action="close-scan">${__("Close camera")}</button>
				</div>
				<input type="file" class="fh-proof-photo" accept="image/jpeg,image/png,image/webp,application/pdf" capture="environment" hidden>
				<input type="file" class="fh-proof-file" accept="image/jpeg,image/png,image/webp,application/pdf" hidden>
			</div>
		`);
		const root = this.page.main.find(".fh-proof").get(0);
		this.root = root;
		this.input = root.querySelector(".fh-proof-id");
		this.detailEl = root.querySelector(".fh-proof-detail");
		this.cardsEl = root.querySelector(".fh-proof-cards");
		this.cameraEl = root.querySelector(".fh-proof-camera");
		this.video = root.querySelector("video");
		this.photoInput = root.querySelector(".fh-proof-photo");
		this.fileInput = root.querySelector(".fh-proof-file");
		root.addEventListener("click", (event) => this.onClick(event));
		this.input.addEventListener("keydown", (event) => {
			if (event.key === "Enter") {
				event.preventDefault();
				this.lookup(this.input.value);
			}
		});
		this.photoInput.addEventListener("change", () => this.onFile(this.photoInput));
		this.fileInput.addEventListener("change", () => this.onFile(this.fileInput));
		this.prepareScan();
		this.loadPending();
	}

	prepareScan() {
		const button = this.root.querySelector("[data-action=scan]");
		if (!button) {
			return;
		}
		if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
			button.remove();
			return;
		}
		if (typeof BarcodeDetector.getSupportedFormats !== "function") {
			return;
		}
		BarcodeDetector.getSupportedFormats()
			.then((formats) => {
				const wanted = ["qr_code", "code_128"].filter((format) => formats.includes(format));
				if (!wanted.length) {
					button.remove();
					return;
				}
				this.scanFormats = wanted;
			})
			.catch(() => {
				button.remove();
			});
	}

	onClick(event) {
		const button = event.target.closest("[data-action]");
		if (!button || this.busy) {
			return;
		}
		const action = button.dataset.action;
		if (action === "lookup") {
			this.lookup(this.input.value);
		} else if (action === "scan") {
			this.startScan();
		} else if (action === "close-scan") {
			this.stopScan();
		} else if (action === "open") {
			this.input.value = button.dataset.name || "";
			this.lookup(button.dataset.name);
		} else if (action === "photo") {
			this.photoInput.click();
		} else if (action === "file") {
			this.fileInput.click();
		}
	}

	async loadPending() {
		try {
			this.pending = (await frappehero.call("frappehero.finance_desk.proof.list_pending")) || [];
			this.renderPending();
		} catch (error) {
			// The desk already shows the server message.
		}
	}

	async lookup(raw) {
		const name = String(raw || "").trim();
		if (!name) {
			frappe.msgprint(__("Enter a Payment Entry."));
			return;
		}
		if (this.busy) {
			return;
		}
		this.busy = true;
		try {
			this.payment = await frappehero.call("frappehero.finance_desk.proof.get_payment", { name });
			this.renderDetail();
			this.detailEl.scrollIntoView({ block: "nearest" });
		} catch (error) {
			// The desk already shows the server message.
		} finally {
			this.busy = false;
		}
	}

	async onFile(input) {
		const file = input.files && input.files[0];
		input.value = "";
		if (!file || !this.payment) {
			return;
		}
		const error = this.fileError(file);
		if (error) {
			frappe.msgprint(error);
			return;
		}
		if (this.busy) {
			return;
		}
		this.busy = true;
		try {
			const filedata = await this.readFile(file);
			this.payment = await frappehero.call("frappehero.finance_desk.proof.attach_proof", {
				name: this.payment.name,
				filename: file.name,
				filedata,
			});
			frappe.show_alert({ message: __("Proof saved"), indicator: "green" });
			this.renderDetail();
			await this.loadPending();
		} catch (error) {
			if (!error || !error.exc) {
				frappe.msgprint(__("That file could not be read."));
			}
		} finally {
			this.busy = false;
		}
	}

	fileError(file) {
		const name = String(file.name || "").split(/[/\\]/).pop();
		const extension = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
		if (!["jpg", "jpeg", "png", "webp", "pdf"].includes(extension)) {
			return __("Use a JPEG, PNG, WebP, or PDF.");
		}
		if (!file.size) {
			return __("That file is empty.");
		}
		if (file.size > 10 * 1024 * 1024) {
			return __("The file must be 10 MB or smaller.");
		}
		return "";
	}

	readFile(file) {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result);
			reader.onerror = () => reject(reader.error);
			reader.readAsDataURL(file);
		});
	}

	async startScan() {
		if (this.scanning) {
			return;
		}
		this.cameraEl.hidden = false;
		try {
			this.stream = await navigator.mediaDevices.getUserMedia({
				video: { facingMode: { ideal: "environment" } },
				audio: false,
			});
		} catch (error) {
			this.stopScan();
			frappe.msgprint(__("The camera is not available. Type the Payment Entry instead."));
			return;
		}
		this.video.srcObject = this.stream;
		try {
			await this.video.play();
		} catch (error) {
			this.stopScan();
			frappe.msgprint(__("The camera is not available. Type the Payment Entry instead."));
			return;
		}
		try {
			this.detector = new BarcodeDetector({ formats: this.scanFormats });
		} catch (error) {
			try {
				this.detector = new BarcodeDetector({ formats: ["qr_code"] });
			} catch (ignored) {
				this.stopScan();
				frappe.msgprint(__("This browser cannot scan a code. Type the Payment Entry instead."));
				return;
			}
		}
		this.scanning = true;
		this.detect();
	}

	async detect() {
		if (!this.scanning) {
			return;
		}
		try {
			const codes = await this.detector.detect(this.video);
			const value = codes && codes[0] && codes[0].rawValue;
			if (value) {
				this.stopScan();
				this.input.value = value;
				this.lookup(value);
				return;
			}
		} catch (error) {
			// One missed frame leaves the camera open.
		}
		this.scanTimer = setTimeout(() => this.detect(), 250);
	}

	stopScan() {
		this.scanning = false;
		clearTimeout(this.scanTimer);
		if (this.stream) {
			this.stream.getTracks().forEach((track) => track.stop());
			this.stream = null;
		}
		if (this.video) {
			this.video.srcObject = null;
		}
		if (this.cameraEl) {
			this.cameraEl.hidden = true;
		}
	}

	renderPending() {
		if (!this.pending.length) {
			this.cardsEl.innerHTML = `<p class="fh-empty">${__("Nothing is waiting on you.")}</p>`;
			return;
		}
		this.cardsEl.innerHTML = this.pending
			.map((row) => {
				const party = row.party ? frappehero.esc(row.party) : "";
				const date = this.when(row.posting_date);
				const meta = [party, date ? frappehero.esc(date) : ""].filter(Boolean).join(" · ");
				return `
					<button type="button" class="fh-card" data-action="open" data-name="${frappehero.esc(row.name)}">
						<span class="fh-card-text">
							<strong>${frappehero.esc(row.name)}</strong>
							<span class="fh-muted">${meta}</span>
						</span>
						<span class="fh-pill">${this.money(row.amount, row.currency)}</span>
					</button>
				`;
			})
			.join("");
	}

	renderDetail() {
		const payment = this.payment;
		if (!payment) {
			this.detailEl.innerHTML = "";
			return;
		}
		const references = payment.references || [];
		const referenceHtml = references.length
			? references
					.map((row) => {
						const invoice = row.invoice_currency
							? `<span class="fh-muted">${this.money(row.invoice_amount, row.invoice_currency)}</span>`
							: "";
						return `
							<div class="fh-rule">
								<span>
									${frappehero.esc(row.reference_name)}
									<span class="fh-muted">${frappehero.esc(row.reference_doctype)}</span>
									${invoice}
								</span>
								<span>${this.money(row.allocated_amount, payment.allocated_currency)}</span>
							</div>
						`;
					})
					.join("")
			: `<p class="fh-empty">${__("No references.")}</p>`;
		const proof = this.proofLink(payment.proof_of_payment);
		const uploaded = payment.proof_uploaded_by
			? `<p class="fh-muted">${frappehero.esc(
					__("Uploaded by {0}", [payment.proof_uploaded_by]) +
						(payment.proof_uploaded_on ? " · " + this.when(payment.proof_uploaded_on) : "")
			  )}</p>`
			: "";
		const upload = payment.can_upload
			? `
				<div class="fh-proof-actions">
					<button type="button" class="fh-btn" data-action="photo">${__("Take photo")}</button>
					<button type="button" class="fh-btn" data-action="file">${__("Choose file")}</button>
				</div>
				<p class="fh-muted">${
					payment.proof_of_payment
						? __("A new file replaces this one. JPEG, PNG, WebP, or PDF. 10 MB or smaller.")
						: __("JPEG, PNG, WebP, or PDF. 10 MB or smaller.")
				}</p>
			`
			: `<p class="fh-muted">${
					Number(payment.docstatus) === 2
						? __("This payment is cancelled.")
						: __("This payment is not assigned to you.")
			  }</p>`;
		this.detailEl.innerHTML = `
			<h2>${frappehero.esc(payment.name)}</h2>
			<p class="fh-proof-amount">${this.money(payment.amount, payment.currency)}</p>
			<div class="fh-rule"><span>${__("Party")}</span><span>${frappehero.esc(payment.party_name || payment.party)}${
				payment.party_type ? `<span class="fh-muted">${frappehero.esc(payment.party_type)}</span>` : ""
			}</span></div>
			<div class="fh-rule"><span>${__("Posting Date")}</span><span>${frappehero.esc(this.when(payment.posting_date))}</span></div>
			<div class="fh-rule"><span>${__("Payment Type")}</span><span>${frappehero.esc(payment.payment_type)}</span></div>
			<div class="fh-rule"><span>${__("Status")}</span><span>${frappehero.esc(this.statusLabel(payment.docstatus))}</span></div>
			${payment.mode_of_payment ? `<div class="fh-rule"><span>${__("Mode of Payment")}</span><span>${frappehero.esc(payment.mode_of_payment)}</span></div>` : ""}
			${
				payment.reference_no
					? `<div class="fh-rule"><span>${__("Reference")}</span><span>${frappehero.esc(payment.reference_no)}${
							payment.reference_date ? " · " + frappehero.esc(this.when(payment.reference_date)) : ""
					  }</span></div>`
					: ""
			}
			${payment.company ? `<div class="fh-rule"><span>${__("Company")}</span><span>${frappehero.esc(payment.company)}</span></div>` : ""}
			<h3>${__("References")}</h3>
			${referenceHtml}
			<h3>${__("Proof")}</h3>
			${proof}
			${uploaded}
			${upload}
		`;
	}

	proofLink(url) {
		const value = String(url || "");
		if (value.startsWith("/files/") || value.startsWith("/private/files/")) {
			return `<p><a href="${frappehero.esc(value)}" target="_blank" rel="noopener">${__("View proof")}</a></p>`;
		}
		return "";
	}

	money(amount, currency) {
		const number = Number(amount || 0);
		const formatted = currency
			? frappe.format(number, { fieldtype: "Currency", options: currency })
			: frappe.format(number, { fieldtype: "Float" });
		return frappehero.esc(formatted);
	}

	when(value) {
		if (!value) {
			return "";
		}
		return frappe.datetime.str_to_user(String(value));
	}

	statusLabel(docstatus) {
		const status = Number(docstatus);
		if (status === 2) {
			return __("Cancelled");
		}
		if (status === 1) {
			return __("Submitted");
		}
		return __("Draft");
	}
};
