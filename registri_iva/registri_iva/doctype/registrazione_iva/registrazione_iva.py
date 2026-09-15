import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# Tipi imposta che non generano importo IVA (solo imponibile)
TIPI_SENZA_IMPOSTA = {"Esente", "Non Imponibile", "Non Soggetta", "Non Imponibile/Esente (verificare)"}


class RegistrazioneIVA(Document):
	def validate(self):
		self.set_naming_series_from_sezionale()
		self.validate_company_matches_sezionale()
		self.calcola_totali()

	def set_naming_series_from_sezionale(self):
		"""La naming series del documento è sempre quella definita sul Sezionale
		scelto: l'utente non la imposta mai a mano, evitando disallineamenti."""
		if not self.sezionale:
			frappe.throw(_("Seleziona un Sezionale IVA"))

		prefix = frappe.db.get_value("Sezionale IVA", self.sezionale, "naming_series_prefix")
		if not prefix:
			frappe.throw(
				_("Il Sezionale IVA {0} non ha un prefisso naming series configurato").format(
					self.sezionale
				)
			)
		self.naming_series = prefix

	def validate_company_matches_sezionale(self):
		sezionale_company = frappe.db.get_value("Sezionale IVA", self.sezionale, "company")
		if sezionale_company and self.company and sezionale_company != self.company:
			frappe.throw(
				_("Il Sezionale IVA {0} appartiene alla company {1}, non a {2}").format(
					self.sezionale, sezionale_company, self.company
				)
			)

	def calcola_totali(self):
		totale_imponibile = 0.0
		totale_imposta = 0.0
		for riga in self.aliquote:
			totale_imponibile += flt(riga.imponibile)
			if riga.tipo_imposta not in TIPI_SENZA_IMPOSTA:
				totale_imposta += flt(riga.imposta)
			else:
				# per coerenza visiva azzeriamo l'imposta sui tipi che non la prevedono
				riga.imposta = 0

		self.totale_imponibile = totale_imponibile
		self.totale_imposta = totale_imposta
		if not self.totale_documento:
			self.totale_documento = totale_imponibile + totale_imposta

	def on_cancel(self):
		# Se questa registrazione è "madre" di una gemella collegata (es. la riga
		# acquisti che ha generato l'autofattura in vendite), annulla anche quella,
		# a meno che non sia già stata annullata dal chiamante.
		if self.registrazione_collegata:
			collegata = frappe.get_doc("Registrazione IVA", self.registrazione_collegata)
			if collegata.docstatus == 1:
				collegata.flags.ignore_linked_doctypes = True
				collegata.cancel()
