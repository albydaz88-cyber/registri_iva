import unittest

import frappe

from registri_iva.utils.tax_breakdown import tax_breakdown


def _pi(is_return=0):
	"""Purchase Invoice finta con template Reverse Charge ADD/DEDUCT, 22% su 1000."""
	return frappe._dict(
		doctype="Purchase Invoice",
		name="PI-TEST",
		is_return=is_return,
		custom_tipo_di_documento="TD17",   # niente lettura XML: usa le righe tasse
		items=[],
		taxes=[
			frappe._dict(name="t1", rate=22, tax_amount=220, add_deduct_tax="Add",
				account_head="IVA acquisti", description="IVA 22% RC credito"),
			frappe._dict(name="t2", rate=22, tax_amount=-220, add_deduct_tax="Deduct",
				account_head="IVA vendite", description="IVA 22% RC debito"),
		],
		item_wise_tax_details=[
			{"tax_row": "t1", "taxable_amount": 1000, "amount": 220},
			{"tax_row": "t2", "taxable_amount": -1000, "amount": -220},
		],
	)


class TestSegnoAutofattura(unittest.TestCase):
	def test_lato_debito_positivo(self):
		righe = tax_breakdown(_pi(), detrazione=True, lato="debito")
		self.assertEqual(righe[0]["imponibile"], 1000)
		self.assertEqual(righe[0]["imposta"], 220)

	def test_lato_credito_positivo(self):
		righe = tax_breakdown(_pi(), detrazione=True, lato="credito")
		self.assertEqual(righe[0]["imponibile"], 1000)
		self.assertEqual(righe[0]["imposta"], 220)

	def test_nota_di_credito_negativa(self):
		righe = tax_breakdown(_pi(is_return=1), detrazione=True, lato="debito")
		self.assertEqual(righe[0]["imponibile"], -1000)
		self.assertEqual(righe[0]["imposta"], -220)