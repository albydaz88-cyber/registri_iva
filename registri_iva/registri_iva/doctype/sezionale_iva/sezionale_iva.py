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
	"""Tutti i prefissi naming series noti al sistema: quelli configurati sui
	doctype transazionali più quelli già usati almeno una volta (tabella Series)."""
	prefissi = set()

	for doctype in ("Sales Invoice", "Purchase Invoice", "POS Invoice"):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue
		field = meta.get_field("naming_series")
		if field and field.options:
			prefissi.update(p.strip() for p in field.options.split("\n") if p.strip())

	# Serie già in uso (il name della tabella Series è il prefisso "risolto",
	# es. PINV/26/ : utile come riferimento ma non è il pattern con .YY.)
	try:
		for row in frappe.get_all("Series", fields=["name"], limit=500):
			if row.get("name"):
				prefissi.add(row["name"])
	except Exception:
		pass

	return sorted(prefissi)


@frappe.whitelist()
def get_prefissi_options(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
	"""Sorgente dati per il campo Autocomplete 'Prefisso Naming Series'."""
	txt = (txt or "").lower()
	return [[p] for p in get_prefissi_disponibili() if txt in p.lower()]
