# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

"""Build docs/cheque-leaf-guide.pdf.

Requires fpdf2, which is used only to produce the guide:

    pip install fpdf2
    python docs/build_cheque_leaf_guide.py
"""

from pathlib import Path

from fpdf import FPDF

BLUE = (36, 144, 239)
INK = (28, 32, 36)
MUTED = (84, 94, 107)
LINE = (214, 221, 229)
WASH = (238, 246, 253)
WHITE = (255, 255, 255)

OUTPUT = Path(__file__).resolve().parent / "cheque-leaf-guide.pdf"


class Guide(FPDF):
	def header(self):
		if self.page_no() == 1:
			return
		self.set_fill_color(*BLUE)
		self.rect(0, 0, 210, 11, "F")
		self.set_font("Helvetica", "", 9)
		self.set_text_color(*WHITE)
		self.set_xy(16, 3)
		self.cell(120, 5, "Frappe Hero", align="L")
		self.cell(58, 5, "Cheque Leaf", align="R")
		self.set_xy(self.l_margin, self.t_margin)

	def footer(self):
		self.set_draw_color(*LINE)
		self.set_line_width(0.2)
		self.line(16, 282, 194, 282)
		self.set_y(-12)
		self.set_font("Helvetica", "", 8)
		self.set_text_color(*MUTED)
		self.cell(90, 6, "Agilasoft", align="L")
		self.cell(88, 6, str(self.page_no()), align="R")


def ensure(pdf, height):
	if pdf.get_y() + height > pdf.page_break_trigger:
		pdf.add_page()


def heading(pdf, text):
	ensure(pdf, 18)
	if pdf.get_y() > pdf.t_margin + 1:
		pdf.ln(2.5)
	pdf.set_x(pdf.l_margin)
	pdf.set_font("Helvetica", "B", 13)
	pdf.set_text_color(*INK)
	pdf.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
	y = pdf.get_y()
	pdf.set_draw_color(*BLUE)
	pdf.set_line_width(0.6)
	pdf.line(16, y, 36, y)
	pdf.ln(3.5)


def paragraph(pdf, text):
	pdf.set_font("Helvetica", "", 10.5)
	pdf.set_text_color(*INK)
	pdf.multi_cell(0, 5.3, text)
	pdf.ln(1.6)


def bullet(pdf, text):
	ensure(pdf, 10)
	y = pdf.get_y() + 1.7
	pdf.set_fill_color(*BLUE)
	pdf.rect(pdf.l_margin, y, 1.5, 1.5, "F")
	pdf.set_xy(pdf.l_margin + 5, pdf.get_y())
	pdf.set_font("Helvetica", "", 10.5)
	pdf.set_text_color(*INK)
	pdf.multi_cell(pdf.epw - 5, 5.2, text)
	pdf.ln(1.1)


def callout(pdf, title, text):
	pdf.set_font("Helvetica", "", 10.5)
	inner = pdf.epw - 8
	body_h = pdf.multi_cell(inner, 5.2, text, dry_run=True, output="HEIGHT")
	box_h = 8 + body_h + 4
	ensure(pdf, box_h + 2)
	x = pdf.l_margin
	y = pdf.get_y()
	pdf.set_fill_color(*WASH)
	pdf.set_draw_color(*BLUE)
	pdf.set_line_width(0.4)
	pdf.rect(x, y, pdf.epw, box_h, "FD")
	pdf.set_xy(x + 4, y + 2.5)
	pdf.set_font("Helvetica", "B", 10)
	pdf.set_text_color(*BLUE)
	pdf.cell(inner, 5, title, new_x="LMARGIN", new_y="NEXT")
	pdf.set_x(x + 4)
	pdf.set_font("Helvetica", "", 10.5)
	pdf.set_text_color(*INK)
	pdf.multi_cell(inner, 5.2, text)
	pdf.set_y(y + box_h + 3)


def table(pdf, headers, rows, widths):
	line_h = 5.2
	pdf.set_font("Helvetica", "", 9.5)

	def row_height(cells, font_style):
		pdf.set_font("Helvetica", font_style, 9.5)
		heights = []
		for cell, width in zip(cells, widths):
			heights.append(pdf.multi_cell(width - 4, line_h, cell, dry_run=True, output="HEIGHT") + 3)
		return max(heights)

	heights = [row_height(headers, "B")]
	for row in rows:
		heights.append(row_height(row, ""))
	if pdf.get_y() + sum(heights) > pdf.page_break_trigger:
		pdf.add_page()

	def paint(cells, font_style, fill, ink):
		height = row_height(cells, font_style)
		x = pdf.l_margin
		y = pdf.get_y()
		pdf.set_fill_color(*fill)
		pdf.rect(x, y, sum(widths), height, "F")
		pdf.set_text_color(*ink)
		pdf.set_font("Helvetica", font_style, 9.5)
		cursor = x
		for cell, width in zip(cells, widths):
			pdf.set_xy(cursor + 2, y + 1.5)
			pdf.multi_cell(width - 4, line_h, cell)
			cursor += width
		pdf.set_y(y + height)

	paint(headers, "B", BLUE, WHITE)
	for index, row in enumerate(rows):
		fill = WASH if index % 2 == 0 else WHITE
		paint(row, "", fill, INK)
	pdf.ln(3)


def build():
	pdf = Guide(format="A4", unit="mm")
	pdf.set_auto_page_break(auto=True, margin=18)
	pdf.set_margins(16, 20, 16)
	pdf.add_page()

	pdf.set_fill_color(*BLUE)
	pdf.rect(0, 0, 210, 46, "F")
	pdf.set_xy(16, 12)
	pdf.set_font("Helvetica", "", 11)
	pdf.set_text_color(*WHITE)
	pdf.cell(0, 6, "Frappe Hero  ·  Finance Desk", new_x="LMARGIN", new_y="NEXT")
	pdf.set_x(16)
	pdf.set_font("Helvetica", "B", 26)
	pdf.cell(0, 12, "Cheque Leaf", new_x="LMARGIN", new_y="NEXT")
	pdf.set_x(16)
	pdf.set_font("Helvetica", "", 12)
	pdf.cell(0, 7, "Cheque numbers for each company bank account", new_x="LMARGIN", new_y="NEXT")
	pdf.set_y(54)

	paragraph(
		pdf,
		"A Cheque Leaf is the set of cheque numbers for one company bank account. "
		"A Payment Entry with Payment Type Pay takes the next free number from that set "
		"and writes it to Cheque/Reference No.",
	)
	paragraph(
		pdf,
		"Open it from Finance Desk, then Cheque Leaf. The same list is under Cheque Leaves.",
	)

	heading(pdf, "Who does what")
	bullet(pdf, "Accounts Manager and System Manager create the leaves and choose the default book for a bank account.")
	bullet(pdf, "Accounts User pays with a leaf. Editing the number set stays with Accounts Manager.")
	bullet(pdf, "A bank account with no active leaf still accepts a reference number typed by hand.")

	heading(pdf, "Create a leaf")
	paragraph(pdf, "Finance Desk, Cheque Leaf, New leaf. You can also add a Hero Cheque Leaf directly.")
	bullet(pdf, "Leaf Name is the document name. Use the bank and the range, for example BDO Current 1001-1050.")
	bullet(pdf, "Bank Account must be a company bank account. Company and Bank fill in from that account.")
	bullet(pdf, "Status starts at Draft while you are still setting the numbers. Active means Pay entries may use the leaf. Closed means the book is finished.")
	bullet(pdf, "Default for this bank account is the book Pay entries use when more than one leaf is active. Only an active leaf keeps this tick. Closing the leaf clears it.")
	paragraph(
		pdf,
		"A leaf holds up to 500 numbers in one range. Split a larger book into two leaves.",
	)

	heading(pdf, "Build the number set")
	paragraph(pdf, "Saving adds the range to the rows already on the leaf. A number that is already there is left as it is.")
	bullet(pdf, "Prefix is printed before the number. Include a dash yourself if you want one, for example CHQ-.")
	bullet(pdf, "Padding is the zero-fill width. 6 turns 12 into 000012. 0 leaves the number as it is. Padding runs from 0 to 12.")
	bullet(pdf, "From Number and To Number are the first and last numbers. Set both, or leave the range blank and type the set yourself. Numbers start at 1.")
	bullet(pdf, "Add numbers takes one cheque number per line. Those lines are saved onto the set, then the box clears. Use it for numbers outside the range.")
	bullet(pdf, "Rebuild available numbers, when ticked, replaces the free numbers from the range and the pasted lines on the next save. Assigned, used, and cancelled numbers stay.")
	paragraph(
		pdf,
		"The same cheque number cannot sit on two leaves for the same bank account.",
	)

	ensure(pdf, 78)
	heading(pdf, "Each number has a status")
	table(
		pdf,
		["Status", "Meaning"],
		[
			["Available", "Free for the next payment."],
			["Assigned", "Reserved on a draft Payment Entry."],
			["Used", "The payment was submitted."],
			["Cancelled", "Spoiled, or the submitted payment was cancelled."],
		],
		[40, 138],
	)
	paragraph(
		pdf,
		"To spoil a spare number, set that row from Available to Cancelled and put the reason in Remarks. "
		"A number that is Assigned or Used keeps its number and stays on the leaf. "
		"A cancelled number that was never issued can be set back to Available.",
	)

	heading(pdf, "Tell the mode of payment to use a leaf")
	paragraph(
		pdf,
		"On Mode of Payment, tick Uses Cheque Leaf. Pay entries with that mode take a number from the bank account's Cheque Leaf.",
	)
	paragraph(
		pdf,
		"A mode whose name contains the word cheque or check does this without the tick. "
		"Cheque and Manager's Check qualify. Wire Transfer does not. The word Checking does not qualify, because it is a different word.",
	)

	heading(pdf, "Pay")
	bullet(pdf, "New Payment Entry. Payment Type: Pay.")
	bullet(pdf, "Set the company bank account that owns the leaf, and the cheque mode of payment.")
	bullet(pdf, "The Cheque Leaf section offers the default active leaf, or the only active leaf, and the next free number.")
	bullet(pdf, "Assign Cheque Number, under the Cheque menu, picks a specific free number from that leaf.")
	bullet(pdf, "Save. The number is reserved and copied to Cheque/Reference No. When Cheque/Reference Date is still empty, the posting date is used.")
	paragraph(
		pdf,
		"If several active leaves exist and none is the default, choose the leaf before saving. "
		"A payment that is not Pay does not take a number. Switching away from Pay, or switching to a mode that does not use a leaf, releases a draft reservation.",
	)

	callout(
		pdf,
		"Example",
		"Leaf BDO Current 1001-1050 is Active and the default for bank account BDO Current. "
		"The range is 1001 to 1050, with no prefix and no padding. "
		"A Pay entry for that bank account, mode Cheque, is offered 1001. "
		"Save reserves 1001. Submit marks it used. The next Pay entry is offered 1002.",
	)

	ensure(pdf, 86)
	heading(pdf, "After you save")
	table(
		pdf,
		["What you do", "What happens to the number"],
		[
			["Save the draft", "Assigned. It is held for this payment."],
			["Submit", "Used."],
			["Cancel the submitted payment", "Cancelled. The number was issued once and is not reused."],
			["Delete the draft", "Available again."],
			["Amend", "The new draft takes the next free number. The voided number stays on the cancelled payment."],
		],
		[62, 116],
	)
	paragraph(
		pdf,
		"Cheque State on the payment shows Assigned, Used, or Cancelled. "
		"The leaf row also stores the payment, the party, and the posting date.",
	)

	heading(pdf, "The desk")
	paragraph(
		pdf,
		"Finance Desk, then Cheque Leaf, lists every leaf you can see. Filter by company, bank account, and status (Draft, Active, or Closed). "
		"Filter the set by numbers left, exhausted, or empty. Search matches the leaf name, the bank account, and the bank.",
	)
	paragraph(
		pdf,
		"The counts along the top are the leaves on screen and how many numbers are available, assigned, used, and cancelled. "
		"Open a name to edit that leaf.",
	)

	heading(pdf, "Rules the form will enforce")
	bullet(pdf, "Bank Account is required, and it is a company bank account.")
	bullet(pdf, "An active leaf needs at least one cheque number.")
	bullet(pdf, "The range is blank, or both ends are set. The last number is the same as the first, or higher. The span is at most 500.")
	bullet(pdf, "A Pay entry whose mode uses a leaf needs an active leaf on that company bank account.")
	bullet(pdf, "The cheque number on the payment has to be one of the free numbers on the leaf you chose, or the number this draft already holds.")

	pdf.output(OUTPUT)
	return OUTPUT


if __name__ == "__main__":
	path = build()
	print(path)
