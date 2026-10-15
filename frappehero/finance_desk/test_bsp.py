# Copyright (c) 2026, Agilasoft and contributors
# For license information, please see license.txt

import json
import unittest

from frappehero.finance_desk.bsp import (
	choose_bulletins,
	clean_lookback,
	dates_with_bsp_rows,
	parse_bulletin,
	parse_range,
	parse_title_date,
	plan_rates,
	read_list_page,
)

BULLETIN = """
1 UNITED STATES DOLLAR USD 0.858222 1.000000 61.6540
2 JAPAN YEN JPY 0.005390 0.006280 0.3872
9 BAHRAIN DINAR* BHD 2.276752 2.652872 163.5602
10 KUWAIT DINAR KWD N/A N/A N/A
11 NOWHERE NNN 1.000000 1.000000 0
16 EUROPEAN MONETARY UNION EURO EUR 1.000000 1.165200 71.8392
20 GOLD XAU 1.000000 1.000000 1500.25
21 SILVER XAG 1.000000 1.000000 18.40
BSP Reference Rate: PHP 61.600
SDR Rate: $ 1.36668 /SDR
"""


class TestBulletin(unittest.TestCase):
	def test_parses_peso_equivalents_and_the_reference_rate(self):
		rows = parse_bulletin(BULLETIN, "2026-05-29")
		by_code = {row["currency"]: row["rate"] for row in rows}
		self.assertEqual(by_code["JPY"], 0.3872)
		self.assertEqual(by_code["EUR"], 71.8392)
		self.assertAlmostEqual(by_code["BHD"], 163.5602)
		self.assertEqual(by_code["USD"], 61.6)
		self.assertNotIn("KWD", by_code)
		self.assertNotIn("NNN", by_code)
		self.assertNotIn("XAU", by_code)
		self.assertNotIn("XAG", by_code)
		self.assertNotIn("SDR", by_code)
		self.assertNotIn("XDR", by_code)
		self.assertTrue(all(row["date"] == "2026-05-29" for row in rows))
		self.assertNotIn(61.654, by_code.values())

	def test_usd_without_a_reference_line_is_left_out(self):
		text = "1 UNITED STATES DOLLAR USD 0.858222 1.000000 61.6540\n"
		self.assertEqual(parse_bulletin(text, "2026-05-29"), [])

	def test_title_dates(self):
		self.assertEqual(parse_title_date("29May2026"), "2026-05-29")
		self.assertEqual(parse_title_date("1Jan2017"), "2017-01-01")
		self.assertIsNone(parse_title_date("not-a-date"))
		self.assertIsNone(parse_title_date("32May2026"))


class TestList(unittest.TestCase):
	def test_choose_stops_at_the_older_page(self):
		page = read_list_page(
			{
				"d": {
					"results": [
						{
							"Title": "29May2026",
							"AttachmentFiles": {"results": [{"ServerRelativeUrl": "/rerb/29May2026.pdf"}]},
						},
						{
							"Title": "30May2026",
							"AttachmentFiles": {"results": [{"ServerRelativeUrl": "/rerb/30May2026.pdf"}]},
						},
						{
							"Title": "01Jan2017",
							"AttachmentFiles": {"results": [{"ServerRelativeUrl": "/rerb/old.pdf"}]},
						},
						{"Title": "not-a-date", "AttachmentFiles": {"results": [{"ServerRelativeUrl": "/rerb/bad.pdf"}]}},
						{"Title": "28May2026", "AttachmentFiles": {"results": []}},
					],
					"__next": "https://www.bsp.gov.ph/next",
				}
			}
		)
		chosen = choose_bulletins(page, "2026-05-27", "2026-05-29")
		self.assertEqual([row["date"] for row in chosen["bulletins"]], ["2026-05-29"])
		self.assertEqual(chosen["bulletins"][0]["url"], "/rerb/29May2026.pdf")
		self.assertTrue(chosen["stop"])
		self.assertIsNone(chosen["next"])


class TestPlan(unittest.TestCase):
	def test_create_update_and_skip(self):
		rates = parse_bulletin(BULLETIN, "2026-05-29") + [
			{"date": "2026-05-29", "currency": "ZZZ", "rate": 1.5}
		]
		existing = [
			{
				"name": "CX-USD",
				"date": "2026-05-29",
				"from_currency": "USD",
				"to_currency": "PHP",
				"exchange_rate": 61.0,
				"hero_bsp": 1,
			},
			{
				"name": "CX-EUR",
				"date": "2026-05-29",
				"from_currency": "EUR",
				"to_currency": "PHP",
				"exchange_rate": 70,
				"hero_bsp": 0,
			},
			{
				"name": "CX-PHP-JPY",
				"date": "2026-05-29",
				"from_currency": "PHP",
				"to_currency": "JPY",
				"exchange_rate": 2,
				"hero_bsp": 0,
			},
		]
		plan = plan_rates(rates, existing, ["USD", "EUR", "JPY", "PHP", "BHD"], write_inverse=1)
		by_pair = {(row["from_currency"], row["to_currency"]): row for row in plan["rows"]}
		self.assertEqual(by_pair[("USD", "PHP")]["action"], "update")
		self.assertEqual(by_pair[("USD", "PHP")]["exchange_rate"], 61.6)
		self.assertEqual(by_pair[("USD", "PHP")]["name"], "CX-USD")
		self.assertEqual(by_pair[("PHP", "USD")]["action"], "create")
		self.assertEqual(by_pair[("PHP", "USD")]["exchange_rate"], round(1 / 61.6, 9))
		self.assertEqual(by_pair[("EUR", "PHP")]["action"], "skip")
		self.assertEqual(by_pair[("EUR", "PHP")]["reason"], "Manual rate")
		self.assertEqual(by_pair[("PHP", "EUR")]["action"], "create")
		self.assertEqual(by_pair[("JPY", "PHP")]["action"], "create")
		self.assertEqual(by_pair[("JPY", "PHP")]["for_buying"], 1)
		self.assertEqual(by_pair[("JPY", "PHP")]["for_selling"], 1)
		self.assertEqual(by_pair[("PHP", "JPY")]["action"], "skip")
		self.assertEqual(by_pair[("PHP", "JPY")]["reason"], "Manual rate")
		self.assertEqual(by_pair[("ZZZ", "PHP")]["action"], "skip")
		self.assertEqual(by_pair[("ZZZ", "PHP")]["reason"], "Currency is not enabled")
		self.assertIn("ZZZ", plan["missing_currencies"])
		self.assertNotIn("KWD", by_pair)
		self.assertEqual(plan["counts"]["update"], 1)

	def test_an_owned_rate_that_matches_is_already_stored(self):
		plan = plan_rates(
			[{"date": "2026-05-29", "currency": "USD", "rate": 61.6}],
			[
				{
					"name": "CX-USD",
					"date": "2026-05-29",
					"from_currency": "USD",
					"to_currency": "PHP",
					"exchange_rate": 61.6,
					"hero_bsp": 1,
				}
			],
			["USD", "PHP"],
			write_inverse=0,
		)
		self.assertEqual(plan["rows"][0]["action"], "skip")
		self.assertEqual(plan["rows"][0]["reason"], "Already stored")

	def test_inverse_rows_follow_the_same_ownership_rules(self):
		plan = plan_rates(
			[{"date": "2026-05-29", "currency": "USD", "rate": 61.6}],
			[
				{
					"name": "CX-INV",
					"date": "2026-05-29",
					"from_currency": "PHP",
					"to_currency": "USD",
					"exchange_rate": 0.01,
					"hero_bsp": 1,
				}
			],
			["USD", "PHP"],
			write_inverse=1,
		)
		inverse = next(row for row in plan["rows"] if row["from_currency"] == "PHP")
		self.assertEqual(inverse["action"], "update")
		self.assertEqual(inverse["name"], "CX-INV")

	def test_stored_dates_and_range(self):
		stored = dates_with_bsp_rows(
			[
				{"date": "2026-05-29", "hero_bsp": 1},
				{"date": "2026-05-28", "hero_bsp": 0},
			]
		)
		self.assertEqual(stored, {"2026-05-29"})
		self.assertEqual(parse_range("2026-05-01", "2026-05-31"), ("2026-05-01", "2026-05-31"))
		with self.assertRaises(ValueError):
			parse_range("2026-05-31", "2026-05-01")
		with self.assertRaises(ValueError):
			parse_range("2026-05-01", "2026-07-01")
		self.assertEqual(clean_lookback(""), 5)
		self.assertEqual(clean_lookback("12"), 12)
		with self.assertRaises(ValueError):
			clean_lookback(0)


class TestClient(unittest.TestCase):
	def test_discover_follows_the_next_page_until_the_range_ends(self):
		from frappehero.finance_desk.bsp_client import BspError, discover, fetch_rates

		calls = []

		def get(url, accept=None):
			calls.append((url, accept))
			if len(calls) == 1:
				return json.dumps(
					{
						"d": {
							"results": [
								{
									"Title": "29May2026",
									"AttachmentFiles": {
										"results": [{"ServerRelativeUrl": "/Lists/RERB/Attachments/1/29May2026.pdf"}]
									},
								}
							],
							"__next": "https://www.bsp.gov.ph/next",
						}
					}
				)
			return json.dumps(
				{
					"d": {
						"results": [
							{
								"Title": "01Jan2017",
								"AttachmentFiles": {"results": [{"ServerRelativeUrl": "/old.pdf"}]},
							}
						]
					}
				}
			)

		found = discover("2026-05-27", "2026-05-29", get)
		self.assertEqual(
			found,
			[
				{
					"date": "2026-05-29",
					"url": "https://www.bsp.gov.ph/Lists/RERB/Attachments/1/29May2026.pdf",
				}
			],
		)
		self.assertEqual(calls[1][0], "https://www.bsp.gov.ph/next")
		self.assertIn("application/json", calls[0][1])

		def stored_get(url, accept=None):
			if "getByTitle" not in url:
				raise AssertionError(url)
			return json.dumps(
				{
					"d": {
						"results": [
							{
								"Title": "29May2026",
								"AttachmentFiles": {
									"results": [{"ServerRelativeUrl": "/Lists/RERB/Attachments/1/29May2026.pdf"}]
								},
							}
						]
					}
				}
			)

		skipped = fetch_rates("2026-05-29", "2026-05-29", get=stored_get, stored_dates=["2026-05-29"])
		self.assertEqual(skipped["skipped"], ["2026-05-29"])
		self.assertEqual(skipped["rates"], [])

		with self.assertRaises(BspError):
			discover("2026-05-29", "2026-05-29", lambda url, accept=None: "<html>denied</html>")
