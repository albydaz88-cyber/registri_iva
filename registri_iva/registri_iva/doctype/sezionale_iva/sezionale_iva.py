import frappe
from frappe import _
from frappe.model.document import Document


class SezionaleIVA(Document):
	def validate(self):
		self.validate_naming_series_exists()

	def validate_naming_series_exists(self):
		"""Avvisa (senza bloccare) se il prefisso non risulta tra le naming
		series configurate: un sezionale può legittimamente puntare a una serie
		appena aggiunta in 'Setup Series for transactions'."""
		prefix = (self.naming_series_prefix or "").strip()
		if not prefix:
			return

		if prefix not in get_prefissi_disponibili():
			frappe.msgprint(
				_(
					"Il prefisso '{0}' non risulta tra le naming series configurate per "
					"Sales/Purchase Invoice. Se è una serie nuova, aggiungila prima in "
					"Setup > Settings > Naming Series."
				).format(prefix),
				alert=True,
				indicator="orange",
			)


def get_prefissi_disponibili():
	"""Prefissi naming series noti al sistema, presi dai doctype transazionali
	(Sales/Purchase/POS Invoice). Nota: NON si può leggere la tabella interna
	'Series' di Frappe con frappe.get_all — non è un DocType vero e proprio,
	la chiamata fallisce sempre con 'DocType Series not found'."""
	prefissi = set()

	for doctype in ("Sales Invoice", "Purchase Invoice", "POS Invoice"):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue
		field = meta.get_field("naming_series")
		if field and field.options:
			prefissi.update(p.strip() for p in field.options.split("\n") if p.strip())

	return sorted(prefissi)


@frappe.whitelist()
def get_prefissi_options(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
	"""Sorgente dati per il campo Autocomplete 'Prefisso Naming Series'.
	Non deve mai far fallire l'apertura del form: in caso di errore imprevisto
	torna una lista vuota invece di propagare l'eccezione al client."""
	try:
		txt = (txt or "").lower()
		return [[p] for p in get_prefissi_disponibili() if txt in p.lower()]
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Sezionale IVA: get_prefissi_options")
		return []
