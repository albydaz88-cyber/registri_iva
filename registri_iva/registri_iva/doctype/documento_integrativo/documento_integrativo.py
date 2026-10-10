import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt

from registri_iva.utils.tax_breakdown import TIPI_SENZA_IMPOSTA


class DocumentoIntegrativo(Document):
	def autoname(self):
		"""Numero/protocollo del documento integrativo = naming series del
		Sezionale scelto (es. AUTOFT/.YY./). Va fatto qui e non in validate():
		Frappe assegna il nome PRIMA di validate() quando autoname è
		'naming_series:', quindi impostare il campo più tardi produce
		'Naming Series mandatory'."""
		if not self.sezionale:
			frappe.throw(_("Seleziona un Sezionale IVA prima di salvare"))

		prefix = frappe.db.get_value("Sezionale IVA", self.sezionale, "naming_series_prefix")
		if not prefix:
			frappe.throw(
				_("Il Sezionale IVA {0} non ha un prefisso naming series configurato").format(
					self.sezionale
				)
			)
		self.naming_series = prefix
		self.name = make_autoname(self.naming_series)

	def validate(self):
		self.calcola_totali()

	def calcola_totali(self):
		"""Normalizza il segno e ricalcola sempre i totali.

		Un Documento Integrativo ha segno positivo, tranne quando integra una
		nota di credito (Purchase Invoice con is_return): in quel caso è
		interamente negativo. Qualunque sia il segno con cui arrivano le righe,
		qui lo si riporta a quello corretto."""
		segno = self._segno_documento()

		totale_imponibile = 0.0
		totale_imposta = 0.0
		for riga in self.aliquote:
			riga.imponibile = segno * abs(flt(riga.imponibile))
			if riga.tipo_imposta in TIPI_SENZA_IMPOSTA:
				riga.imposta = 0
			else:
				riga.imposta = segno * abs(flt(riga.imposta))
			totale_imponibile += riga.imponibile
			totale_imposta += riga.imposta

		self.totale_imponibile = totale_imponibile
		self.totale_imposta = totale_imposta
		# Campo read_only: va sempre ricalcolato, mai "se vuoto".
		self.totale_documento = totale_imponibile + totale_imposta

	def _segno_documento(self):
		if not self.purchase_invoice:
			return 1
		is_return = frappe.db.get_value("Purchase Invoice", self.purchase_invoice, "is_return")
		return -1 if is_return else 1
