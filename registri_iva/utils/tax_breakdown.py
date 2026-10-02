"""
Scomposizione delle righe tasse (Purchase/Sales Taxes and Charges) per aliquota
o tipo imposta. Modulo condiviso tra:
- l'hook che genera il Documento Integrativo dalla Purchase Invoice TD17/18/19
- il report "Registro Sezionali IVA", che lo richiama live su ogni PI/SI
  interrogata (nessun dato duplicato in una tabella intermedia).
"""

import re

import frappe
from frappe.utils import flt

TIPI_SENZA_IMPOSTA = {"Esente", "Non Imponibile", "Non Soggetta", "Non Imponibile/Esente (verificare)"}

# italian_invoice.utilities.fatture_passive.prepare_invoice_taxes genera, per le
# righe con natura N6.x, due righe di tassa "gemelle" con importo opposto.
RC_CREDITO_RE = re.compile(r"RC credito", re.IGNORECASE)
RC_DEBITO_RE = re.compile(r"RC debito", re.IGNORECASE)


def tax_breakdown(doc, detrazione, lato="credito"):
	"""Scompone le righe tasse del documento (doc.taxes) per tipo imposta,
	restituendo una lista di dict: tipo_imposta, aliquota, imponibile, imposta.

	lato: "credito" -> registro acquisti (faccia a credito dell'IVA)
	      "debito"  -> documento integrativo / registro vendite (faccia a debito)

	Nel template reverse charge italiano la stessa imposta compare due volte
	sulla Purchase Invoice: una riga ADD (IVA su acquisti, a credito) e una riga
	DEDUCT (IVA su vendite, a debito) di pari importo, che si compensano nel
	grand total. NON vanno sommate: farlo raddoppia l'imposta. La riga DEDUCT
	non è "IVA non detraibile" (concetto diverso).
	"""
	righe_add = []
	righe_deduct = []

	for tax in doc.get("taxes") or []:
		descrizione = tax.description or ""
		if RC_DEBITO_RE.search(descrizione):
			righe_deduct.append(tax)
			continue
		if RC_CREDITO_RE.search(descrizione):
			righe_add.append(tax)
			continue

		if getattr(tax, "add_deduct_tax", None) == "Deduct":
			righe_deduct.append(tax)
		else:
			righe_add.append(tax)

	e_reverse_charge = bool(righe_deduct) and _sono_speculari(righe_add, righe_deduct)

	if e_reverse_charge:
		righe_da_usare = righe_deduct if lato == "debito" else righe_add
	else:
		righe_da_usare = righe_add

	# Purchase Invoice: Purchase Taxes and Charges è un riepilogo per
	# aliquota/conto, non per riga — due articoli con nature DIVERSE (es.
	# N2.2 e N3.2) ma stessa aliquota 0% collassano nella stessa riga tassa,
	# perdendo la distinzione. La natura va quindi letta dagli ITEM (granulare
	# per riga), non dalla tax row: qui costruiamo l'aggregato per poterla
	# usare al posto della riga tassa aggregata più sotto.
	nature_da_item = {}
	if doc.doctype == "Purchase Invoice":
		for item in doc.get("items") or []:
			codice = (item.get("custom_motivo_esenzione_iva") or "").strip()
			if not codice:
				continue
			imponibile = flt(item.get("base_net_amount") or item.get("net_amount") or 0)
			if not imponibile:
				continue
			nature_da_item[codice] = nature_da_item.get(codice, 0) + imponibile

	risultato = {}
	for tax in righe_da_usare:
		rate = flt(tax.rate)
		tax_amount = abs(flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None)))
		base_amount = _base_amount_da_riga(tax)
		descrizione = tax.description or ""
		# Per Purchase Invoice la natura si legge solo dagli item (sopra): si
		# ignora quella eventualmente sulla tax row per non rischiare di
		# contare due volte lo stesso imponibile.
		natura = "" if doc.doctype == "Purchase Invoice" else (getattr(tax, "custom_motivo_esenzione_iva", None) or "").strip()

		if base_amount == 0 and tax_amount == 0 and not natura:
			continue

		ha_imposta = True  # salvo i casi sotto che la azzerano esplicitamente

		if e_reverse_charge:
			# Riga già instradata come faccia credito/debito del reverse
			# charge (vedi sopra): qui si mostra sempre l'aliquota applicata
			# (es. "22%"), mai il codice natura, su richiesta esplicita.
			tipo = f"{int(rate)}%" if rate == int(rate) else f"{rate}%"
		elif natura:
			# Solo Sales Invoice arriva qui con natura valorizzata (vedi
			# sopra): lì il JS di validazione la richiede per riga tassa,
			# quindi è affidabile anche a questo livello.
			tipo = _label_natura(natura)
			base_amount = base_amount or flt(getattr(tax, "total", 0))
			ha_imposta = natura.upper().startswith("N6")
		elif rate in (22, 10, 5, 4):
			tipo = f"{int(rate)}%"
		elif rate == 0:
			if doc.doctype == "Purchase Invoice" and nature_da_item:
				# Questa riga aggregata a aliquota 0 è già rappresentata,
				# articolo per articolo, da nature_da_item sotto: salterla qui
				# evita di contarla una seconda volta in modo generico.
				continue
			# Nessun dato di natura disponibile (fattura più vecchia, o non
			# ancora passata dall'importer aggiornato): fallback sulla
			# descrizione testuale, meno affidabile.
			descrizione_lower = descrizione.lower()
			if "esent" in descrizione_lower:
				tipo = "Esente"
			elif "non impon" in descrizione_lower:
				tipo = "Non Imponibile"
			elif "non sogget" in descrizione_lower:
				tipo = "Non Soggetta"
			elif "fuori campo" in descrizione_lower or "esclus" in descrizione_lower:
				tipo = "Fuori Campo IVA"
			else:
				tipo = "Non Imponibile/Esente (verificare)"
			base_amount = base_amount or flt(getattr(tax, "total", 0))
			ha_imposta = False
		else:
			tipo = f"{rate}%"

		chiave = (tipo, rate, natura)
		riga = risultato.setdefault(
			chiave,
			{"tipo_imposta": tipo, "aliquota": rate, "imponibile": 0, "imposta": 0,
			 "reverse_charge": e_reverse_charge, "natura_iva": natura or None},
		)
		riga["imponibile"] += base_amount
		if ha_imposta:
			riga["imposta"] += tax_amount

	# Righe natura lette dagli item (Purchase Invoice, vedi sopra). N6.x
	# (inversione contabile) è l'unica famiglia con imposta autoliquidata; se
	# presente a livello item verrebbe comunque già gestita dalla coppia
	# RC credito/debito sulla tax row, quindi qui è sempre a imposta zero.
	for codice, imponibile in nature_da_item.items():
		tipo = _label_natura(codice)
		chiave = (tipo, 0.0, codice)
		riga = risultato.setdefault(
			chiave,
			{"tipo_imposta": tipo, "aliquota": 0.0, "imponibile": 0, "imposta": 0,
			 "reverse_charge": False, "natura_iva": codice},
		)
		riga["imponibile"] += imponibile

	if not e_reverse_charge and detrazione and lato == "credito":
		for tax in righe_deduct:
			importo = abs(flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None)))
			if not importo:
				continue
			chiave = ("Non Detraibile", flt(tax.rate), None)
			riga = risultato.setdefault(
				chiave,
				{"tipo_imposta": "Non Detraibile", "aliquota": flt(tax.rate), "imponibile": 0, "imposta": 0,
				 "reverse_charge": False, "natura_iva": None},
			)
			riga["imponibile"] += _base_amount_da_riga(tax)
			riga["imposta"] += importo

	return list(risultato.values())


def _label_natura(codice):
	"""'N2.2' -> 'N2.2 - Non soggette – altri casi', leggendo la descrizione da
	Motivo esenzione IVA (già pre-popolata da italian_invoice/install.py con i
	codici N1-N7). Cache per evitare una query per riga su fatture con molte
	righe della stessa natura."""
	descrizione = frappe.get_cached_value("Motivo esenzione IVA", codice, "descrizione")
	return f"{codice} - {descrizione}" if descrizione else codice


def _sono_speculari(righe_add, righe_deduct):
	if not righe_add or not righe_deduct:
		return False

	def chiavi(righe):
		out = []
		for t in righe:
			importo = abs(flt(getattr(t, "tax_amount", None) or getattr(t, "base_tax_amount", None)))
			out.append((flt(t.rate), round(importo, 2)))
		return sorted(out)

	return all(k in chiavi(righe_add) for k in chiavi(righe_deduct))


def _base_amount_da_riga(tax):
	import json

	base_amount = 0
	item_wise = getattr(tax, "item_wise_tax_detail", None)
	if item_wise:
		try:
			parsed = json.loads(item_wise)
			for _item_code, tax_data in parsed.items():
				if isinstance(tax_data, list) and len(tax_data) >= 2:
					base_amount += flt(tax_data[1])
		except (ValueError, TypeError):
			pass

	tax_amount = flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None))
	rate = flt(tax.rate)
	if base_amount == 0 and tax_amount != 0 and rate != 0:
		base_amount = tax_amount / (rate / 100)

	return base_amount
