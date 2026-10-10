"""Codice tipo documento (TD01, TD04, ...) per il Registro IVA."""

import json
import xml.etree.ElementTree as ET

import frappe

from registri_iva.utils.tax_breakdown import _body_da_json

TIPOLOGIA = "Tipologia di documento e-Invoice"
CAMPO_ORIGINALE = "custom_tipo_documento_originale"


def codici_tipologia():
	"""{name: codice}: tabella piccola, una query per report."""
	return {r.name: r.codice for r in frappe.get_all(TIPOLOGIA, fields=["name", "codice"])}


def tipo_da_json(dati):
	"""TipoDocumento dal JSON dati_fattura (stesso body che legge tax_breakdown)."""
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
	dg = (body.get("dati_generali") or {}).get("dati_generali_documento") or {}
	return (dg.get("tipo_documento") or "").strip().upper() or None


def tipo_da_xml(contenuto):
	"""TipoDocumento dall'XML grezzo, indifferente a namespace/prefisso (p:, ns3:, ...)."""
	if isinstance(contenuto, str):
		contenuto = contenuto.encode("utf-8")
	try:
		root = ET.fromstring(contenuto)
	except ET.ParseError:  # p7m, file corrotto
		return None
	for el in root.iter():
		if el.tag.rsplit("}", 1)[-1] == "TipoDocumento":
			return (el.text or "").strip().upper() or None
	return None


def _tipo_da_allegato(nome_sdi):
	nome_file = frappe.db.get_value(
		"File",
		{
			"attached_to_doctype": "Fattura Fornitori SDI",
			"attached_to_name": nome_sdi,
			"file_name": ["like", "%.xml"],
		},
		"name",
	)
	if not nome_file:
		return None
	try:
		return tipo_da_xml(frappe.get_doc("File", nome_file).get_content())
	except Exception:
		return None


def tipi_acquisti(nomi_pi, usa_campo_manuale=True):
	"""{nome PI: codice TDxx}. Ordine: 1) JSON dati_fattura, 2) XML allegato,
	3) campo manuale. Una query per tutte le PI del report."""
	if not nomi_pi:
		return {}

	risultato, senza_json = {}, []
	for r in frappe.get_all(
		"Fattura Fornitori SDI",
		filters={"fattura": ["in", list(nomi_pi)]},
		fields=["name", "fattura", "dati_fattura"],
	):
		tipo = tipo_da_json(r.dati_fattura)
		if tipo:
			risultato[r.fattura] = tipo
		else:
			senza_json.append(r)

	for r in senza_json:
		tipo = _tipo_da_allegato(r.name)
		if tipo:
			risultato[r.fattura] = tipo

	mancanti = [n for n in nomi_pi if n not in risultato]
	if usa_campo_manuale and mancanti and frappe.get_meta("Purchase Invoice").has_field(CAMPO_ORIGINALE):
		codici = codici_tipologia()
		for r in frappe.get_all(
			"Purchase Invoice", filters={"name": ["in", mancanti]}, fields=["name", CAMPO_ORIGINALE]
		):
			valore = r.get(CAMPO_ORIGINALE)
			if valore:
				risultato[r.name] = codici.get(valore, valore)
	return risultato


def backfill_tipo_documento_originale():
	"""Una tantum, sulle PI già importate:
	bench --site SITO execute registri_iva.utils.tipo_documento.backfill_tipo_documento_originale
	(NON come patch: al momento dei patch il Custom Field non esiste ancora)."""
	righe = frappe.get_all("Purchase Invoice", filters={"docstatus": ["<", 2]}, fields=["name", CAMPO_ORIGINALE])
	da_fare = [r.name for r in righe if not r.get(CAMPO_ORIGINALE)]
	n = 0
	for nome, tipo in tipi_acquisti(da_fare, usa_campo_manuale=False).items():
		if frappe.db.exists(TIPOLOGIA, tipo):
			frappe.db.set_value("Purchase Invoice", nome, CAMPO_ORIGINALE, tipo, update_modified=False)
			n += 1
	frappe.db.commit()
	print(f"Compilate {n} Purchase Invoice")