"""
Scomposizione delle righe IVA di un documento per aliquota o tipo imposta.
Modulo condiviso tra:
- l'hook che genera il Documento Integrativo dalla Purchase Invoice (TD16/17/18/19)
- il report "Registro Sezionali IVA", che lo richiama live su ogni PI/SI
  interrogata (nessun dato duplicato in una tabella intermedia).

Fonte dei dati
--------------
- Purchase Invoice importata da XML SDI: si usa il riepilogo IVA (DatiRiepilogo)
  della "Fattura Fornitori SDI" collegata. Sono gli importi del fornitore, esatti
  al centesimo, e non dipendono da come ERPNext arrotonda, azzera `rate` sulle
  righe "Actual" o ripartisce l'imposta sugli articoli. Per le nature N6.x
  (inversione contabile interna) l'imposta autoliquidata non e' nell'XML (e' 0):
  si legge dalla coppia di righe "RC credito" / "RC debito" della Purchase Invoice.
- Purchase Invoice senza XML collegato (inserite a mano, autofatture
  TD17/18/19/20/21) e Sales Invoice: si ricostruisce dalle righe tasse del
  documento, come prima.
"""

import json
import re

import frappe
from frappe.utils import flt

TIPI_SENZA_IMPOSTA = {"Esente", "Non Imponibile", "Non Soggetta", "Non Imponibile/Esente (verificare)"}

# italian_invoice.utilities.fatture_passive.prepare_invoice_taxes genera, per le
# righe con natura N6.x, due righe di tassa "gemelle" con importo opposto.
RC_CREDITO_RE = re.compile(r"RC credito", re.IGNORECASE)
RC_DEBITO_RE = re.compile(r"RC debito", re.IGNORECASE)

# Righe di una Purchase Invoice che NON sono IVA (arrotondamento SDI, bollo,
# ritenuta d'acconto): create da sdi_manual_import, vanno ignorate quando si
# ricostruisce il registro dalle righe tasse.
RIGHE_NON_IVA_RE = re.compile(r"^\s*(differenza di arrotondamento|bollo|ritenuta)", re.IGNORECASE)

# Autofatture/integrazioni inserite a mano: il registro le ricostruisce SEMPRE dal
# template fiscale della Purchase Invoice, mai dall'XML. TD16 non e' in elenco: una
# PI importata con natura N6 riceve TD16 ma ha l'XML del fornitore e va letta da li'.
TIPI_DOCUMENTO_AUTOFATTURA = {"TD17", "TD18", "TD19", "TD20", "TD21"}

# Aliquota usata per l'inversione contabile quando non si riesce a ricavarla dalle
# righe "RC credito/debito" (stessa scelta di italian_invoice._get_reverse_charge_rate).
ALIQUOTA_RC_DEFAULT = 22.0

# "Totale Documento" del report per le Purchase Invoice da XML:
#   True  -> ImportoTotaleDocumento dichiarato dal fornitore (comprende ad es. il
#            bollo addebitato in testata e gli arrotondamenti del fornitore)
#   False -> sempre imponibile + imposta delle righe IVA
# Nelle fatture in inversione contabile si usa comunque imponibile + imposta
# (valore dell'operazione ai fini del registro).
USA_TOTALE_XML = True


def tax_breakdown(doc, detrazione, lato="credito", usa_xml=True):
	"""Scompone le imposte del documento, restituendo una lista di dict:
	tipo_imposta, aliquota, imponibile, imposta, reverse_charge, natura_iva.

	lato: "credito" -> registro acquisti (faccia a credito dell'IVA)
	      "debito"  -> documento integrativo / registro vendite (faccia a debito)
	usa_xml: se False non legge mai l'XML SDI (solo righe tasse del documento).
	"""
	if usa_xml and _usa_riepilogo_xml(doc):
		righe = _breakdown_da_xml(doc, lato)
		if righe:
			return righe

	return _breakdown_da_righe_tasse(doc, detrazione, lato)


def totale_documento(doc, righe):
	"""Totale del documento per il registro. `righe` e' il risultato di tax_breakdown()."""
	calcolato = sum(flt(r["imponibile"]) + flt(r["imposta"]) for r in righe)

	if not USA_TOTALE_XML or not righe or any(r.get("reverse_charge") for r in righe):
		return calcolato
	if not _usa_riepilogo_xml(doc):
		return calcolato

	xml = _leggi_xml(doc)
	if not xml or not xml["riepiloghi"] or not xml["totale"]:
		return calcolato

	return xml["totale"] * _segno_documento(doc, xml["riepiloghi"])


# ---------------------------------------------------------------------------
# Lettura dell'XML SDI
# ---------------------------------------------------------------------------


def _usa_riepilogo_xml(doc):
	if doc.doctype != "Purchase Invoice":
		return False
	tipo = (doc.get("custom_tipo_di_documento") or "").strip().upper()
	return tipo not in TIPI_DOCUMENTO_AUTOFATTURA


def _leggi_xml(doc):
	"""Riepilogo IVA e totale dell'XML della fattura SDI collegata alla PI.
	Restituisce None se la PI non ha un XML collegato o se non e' leggibile:
	chi chiama ripiega allora sulle righe tasse."""
	dati = frappe.db.get_value("Fattura Fornitori SDI", {"fattura": doc.name}, "dati_fattura")
	if not dati:
		return None

	try:
		if isinstance(dati, str):
			dati = json.loads(dati)
	except (TypeError, ValueError):
		return None
	if not isinstance(dati, dict):
		return None

	body = _body_da_json(dati)
	if not body:
		return None

	beni_servizi = body.get("dati_beni_servizi") or {}
	riepiloghi = _come_lista(beni_servizi.get("dati_riepilogo"))
	dati_documento = (body.get("dati_generali") or {}).get("dati_generali_documento") or {}

	totale = None
	if dati_documento.get("importo_totale_documento") not in (None, ""):
		try:
			totale = float(dati_documento["importo_totale_documento"])
		except (TypeError, ValueError):
			totale = None

	return {"riepiloghi": [r for r in riepiloghi if isinstance(r, dict)], "totale": totale}


def _body_da_json(dati):
	"""Primo FatturaElettronicaBody: e' quello da cui l'importer crea la PI."""
	body = None
	try:
		from italian_invoice.utilities.fatture import JSON_PATHS, get_value_from_json_paths
	except ImportError:
		JSON_PATHS = get_value_from_json_paths = None

	if get_value_from_json_paths:
		body = get_value_from_json_paths(dati, JSON_PATHS["fattura_body"])
	if not body:
		body = dati.get("fattura_elettronica_body")

	if isinstance(body, list):
		body = body[0] if body else None
	return body if isinstance(body, dict) else None


def _come_lista(valore):
	if not valore:
		return []
	return valore if isinstance(valore, list) else [valore]


def _natura(riepilogo):
	return (riepilogo.get("natura") or "").strip().upper()


def _segno_documento(doc, riepiloghi):
	"""-1 per le note di credito. Nell'XML una nota di credito (TD04) ha importi
	positivi: nel registro devono comparire in negativo, come nella Purchase Invoice.
	Se il fornitore ha mandato una nota di credito con importi gia' negativi
	(tipo documento TD01, rilevata dall'importer) non si ribalta una seconda volta."""
	if not doc.get("is_return"):
		return 1
	somma = sum(flt(r.get("imponibile_importo")) + flt(r.get("imposta")) for r in riepiloghi)
	return -1 if somma > 0 else 1


def _label_aliquota(aliquota):
	return f"{aliquota:g}%"


def _breakdown_da_xml(doc, lato):
	xml = _leggi_xml(doc)
	if not xml or not xml["riepiloghi"]:
		return None

	riepiloghi = xml["riepiloghi"]
	segno = _segno_documento(doc, riepiloghi)
	numero_rc = sum(1 for r in riepiloghi if _natura(r).startswith("N6"))

	risultato = {}
	for r in riepiloghi:
		aliquota = flt(r.get("aliquota_iva"))
		natura = _natura(r)
		imponibile = flt(r.get("imponibile_importo")) * segno
		imposta = flt(r.get("imposta")) * segno
		reverse_charge = natura.startswith("N6")

		if reverse_charge:
			# Inversione contabile interna: il fornitore indica imposta 0, l'IVA
			# integrata dal cessionario e' sulle righe RC della Purchase Invoice.
			# Si mostra l'aliquota applicata (es. "22%"), non il codice natura.
			imposta, aliquota = _imposta_reverse_charge(doc, natura, lato, imponibile, numero_rc)
			tipo = _label_aliquota(aliquota)
		elif natura:
			tipo = _label_natura(natura)
		else:
			tipo = _label_aliquota(aliquota)

		# Riga a importi zero (es. N2.2 con le condizioni di vendita): nessun
		# rilievo fiscale, non va a registro.
		if not imponibile and not imposta:
			continue

		riga = risultato.setdefault(
			(tipo, aliquota, natura),
			{
				"tipo_imposta": tipo,
				"aliquota": aliquota,
				"imponibile": 0,
				"imposta": 0,
				"reverse_charge": reverse_charge,
				"natura_iva": natura or None,
			},
		)
		riga["imponibile"] += imponibile
		riga["imposta"] += imposta

	return list(risultato.values()) or None


def _imposta_reverse_charge(doc, natura, lato, imponibile, numero_rc):
	"""(imposta, aliquota) dell'inversione contabile per la natura indicata."""
	if lato == "debito":
		regex_ordine = (RC_DEBITO_RE, RC_CREDITO_RE)
	else:
		regex_ordine = (RC_CREDITO_RE, RC_DEBITO_RE)
	segno = 1 if imponibile >= 0 else -1

	for regex in regex_ordine:
		righe = [t for t in doc.get("taxes") or [] if regex.search(t.description or "")]
		mirate = [t for t in righe if f"({natura})" in (t.description or "").upper()]
		if not mirate and numero_rc == 1:
			mirate = righe
		if mirate:
			imposta = sum(abs(_importo_tassa(t)) for t in mirate)
			return segno * imposta, _aliquota_da_riga(mirate[0]) or ALIQUOTA_RC_DEFAULT

	return round(imponibile * ALIQUOTA_RC_DEFAULT / 100, 2), ALIQUOTA_RC_DEFAULT


# ---------------------------------------------------------------------------
# Ricostruzione dalle righe tasse del documento
# ---------------------------------------------------------------------------


def _breakdown_da_righe_tasse(doc, detrazione, lato):
	"""Nel template reverse charge italiano la stessa imposta compare due volte
	sulla Purchase Invoice: una riga ADD (IVA su acquisti, a credito) e una riga
	DEDUCT (IVA su vendite, a debito) di pari importo, che si compensano nel
	grand total. NON vanno sommate: farlo raddoppia l'imposta. La riga DEDUCT
	non e' "IVA non detraibile" (concetto diverso)."""
	e_purchase = doc.doctype == "Purchase Invoice"

	righe_add = []
	righe_deduct = []

	for tax in doc.get("taxes") or []:
		if e_purchase and _riga_non_iva(tax):
			continue

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

	# Purchase Invoice: Purchase Taxes and Charges e' un riepilogo per
	# aliquota/conto, non per riga - due articoli con nature DIVERSE (es.
	# N2.2 e N3.2) ma stessa aliquota 0% collassano nella stessa riga tassa,
	# perdendo la distinzione. La natura va quindi letta dagli ITEM (granulare
	# per riga), non dalla tax row: qui costruiamo l'aggregato per poterla
	# usare al posto della riga tassa aggregata piu' sotto.
	nature_da_item = {}
	if e_purchase:
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
		rate = _aliquota_da_riga(tax)
		tax_amount = abs(_importo_tassa(tax))
		base_amount = _base_amount_da_riga(tax, rate)
		descrizione = tax.description or ""
		# Per Purchase Invoice la natura si legge solo dagli item (sopra): si
		# ignora quella eventualmente sulla tax row per non rischiare di
		# contare due volte lo stesso imponibile.
		natura = "" if e_purchase else (getattr(tax, "custom_motivo_esenzione_iva", None) or "").strip()

		if base_amount == 0 and tax_amount == 0 and not natura:
			continue

		ha_imposta = True  # salvo i casi sotto che la azzerano esplicitamente

		if e_reverse_charge:
			# Riga gia' instradata come faccia credito/debito del reverse
			# charge (vedi sopra): qui si mostra sempre l'aliquota applicata
			# (es. "22%"), mai il codice natura, su richiesta esplicita.
			tipo = _label_aliquota(rate)
		elif natura:
			# Solo Sales Invoice arriva qui con natura valorizzata (vedi
			# sopra): li' il JS di validazione la richiede per riga tassa,
			# quindi e' affidabile anche a questo livello.
			tipo = _label_natura(natura)
			base_amount = base_amount or flt(getattr(tax, "total", 0))
			ha_imposta = natura.upper().startswith("N6")
		elif rate in (22, 10, 5, 4):
			tipo = _label_aliquota(rate)
		elif rate == 0:
			if e_purchase and nature_da_item:
				# Questa riga aggregata a aliquota 0 e' gia' rappresentata,
				# articolo per articolo, da nature_da_item sotto: saltarla qui
				# evita di contarla una seconda volta in modo generico.
				continue
			# Nessun dato di natura disponibile (fattura piu' vecchia, o non
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
			tipo = _label_aliquota(rate)

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
	# (inversione contabile) e' l'unica famiglia con imposta autoliquidata; se
	# presente a livello item verrebbe comunque gia' gestita dalla coppia
	# RC credito/debito sulla tax row, quindi qui e' sempre a imposta zero.
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
			importo = abs(_importo_tassa(tax))
			if not importo:
				continue
			rate = _aliquota_da_riga(tax)
			chiave = ("Non Detraibile", rate, None)
			riga = risultato.setdefault(
				chiave,
				{"tipo_imposta": "Non Detraibile", "aliquota": rate, "imponibile": 0, "imposta": 0,
				 "reverse_charge": False, "natura_iva": None},
			)
			riga["imponibile"] += _base_amount_da_riga(tax, rate)
			riga["imposta"] += importo

	return list(risultato.values())


def _importo_tassa(tax):
	return flt(getattr(tax, "tax_amount", None) or getattr(tax, "base_tax_amount", None))


def _riga_non_iva(tax):
	"""True per le righe di una Purchase Invoice che non sono IVA: differenza di
	arrotondamento SDI, bollo, ritenuta d'acconto e in genere spese su conti non
	IVA senza aliquota."""
	descrizione = tax.description or ""
	if RIGHE_NON_IVA_RE.search(descrizione):
		return True

	account = tax.get("account_head")
	if not account or "iva" in descrizione.lower() or _aliquota_da_riga(tax):
		return False

	tipo_conto = frappe.get_cached_value("Account", account, "account_type")
	return tipo_conto != "Tax"


def _aliquota_da_riga(tax):
	"""Aliquota di una riga IVA. ERPNext azzera `rate` sulle righe "Actual" a ogni
	save/submit: si ripiega sulla descrizione ("IVA 22.0% ...") e poi sul conto IVA."""
	rate = flt(tax.rate)
	if rate:
		return rate

	trovato = re.search(r"(\d+(?:[.,]\d+)?)\s*%", tax.description or "")
	if trovato:
		return flt(trovato.group(1).replace(",", "."))

	account = tax.get("account_head")
	if account:
		return flt(frappe.get_cached_value("Account", account, "tax_rate"))
	return 0.0


def _label_natura(codice):
	"""'N2.2' -> 'N2.2 - Non soggette - altri casi', leggendo la descrizione da
	Motivo esenzione IVA (gia' pre-popolata da italian_invoice/install.py con i
	codici N1-N7). Cache per evitare una query per riga su fatture con molte
	righe della stessa natura."""
	try:
		descrizione = frappe.get_cached_value("Motivo esenzione IVA", codice, "descrizione")
	except frappe.DoesNotExistError:
		descrizione = None
	return f"{codice} - {descrizione}" if descrizione else codice


def _sono_speculari(righe_add, righe_deduct):
	if not righe_add or not righe_deduct:
		return False

	def chiavi(righe):
		out = []
		for t in righe:
			importo = abs(_importo_tassa(t))
			out.append((_aliquota_da_riga(t), round(importo, 2)))
		return sorted(out)

	return all(k in chiavi(righe_add) for k in chiavi(righe_deduct))


def _base_amount_da_riga(tax, rate=None):
	"""Imponibile di una riga IVA.

	In ERPNext 16 il dettaglio per articolo e' nella tabella figlia
	`item_wise_tax_details` (non piu' nel JSON `item_wise_tax_detail`, che peraltro
	conteneva l'IMPOSTA per articolo e non l'imponibile). Se il dettaglio non c'e' si
	risale dall'imposta: imposta / aliquota."""
	base_amount = 0
	for dettaglio in tax.get("item_wise_tax_details") or []:
		base_amount += flt(dettaglio.get("taxable_amount"))

	if rate is None:
		rate = _aliquota_da_riga(tax)
	tax_amount = _importo_tassa(tax)
	if base_amount == 0 and tax_amount != 0 and rate != 0:
		base_amount = tax_amount / (rate / 100)

	return base_amount
