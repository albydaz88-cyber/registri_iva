import frappe
from frappe.model.document import Document


class SezionaleIVA(Document):
	def validate(self):
		self.validate_naming_series_exists()

	def validate_naming_series_exists(self):
		"""Verifica che il prefisso indicato esista davvero tra le naming series
		configurate in 'Setup Series for transactions' (tabella Series di Frappe)."""
		prefix = (self.naming_series_prefix or "").strip()
		if not prefix:
			return

		# Frappe salva le serie usate nella tabella "Series" con il prefisso
		# ripulito dai placeholder (.YY., #### ecc.) come chiave (name).
		# Verifichiamo invece contro le Property Setter / DocType option
		# "naming_series" di Sales Invoice e Purchase Invoice, che è la fonte
		# più affidabile di "prefissi validi" lato utente.
		valid_prefixes = set()
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			meta = frappe.get_meta(doctype)
			field = meta.get_field("naming_series")
			if field and field.options:
				valid_prefixes.update(
					[p.strip() for p in field.options.split("\n") if p.strip()]
				)

		if valid_prefixes and prefix not in valid_prefixes:
			frappe.msgprint(
				frappe.tostring(
					"Attenzione: '{0}' non risulta tra le naming series configurate "
					"in Setup > Settings > Naming Series per Sales/Purchase Invoice. "
					"Se è un sezionale nuovo (es. AUTOFT/.YY./), aggiungilo prima lì, "
					"altrimenti la numerazione automatica di 'Registrazione IVA' non sarà coerente."
				).format(prefix),
				alert=True,
				indicator="orange",
			)
