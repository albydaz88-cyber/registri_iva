frappe.ui.form.on("Sezionale IVA", {
	onload(frm) {
		// Una volta sola al caricamento: NON su "refresh", che scatta ad ogni
		// repaint del form e, combinato con refresh_field, aveva effetti
		// collaterali sul rendering delle altre sezioni della pagina.
		popola_prefissi(frm);
	},
});

function popola_prefissi(frm) {
	frappe.call({
		method: "registri_iva.registri_iva.doctype.sezionale_iva.sezionale_iva.get_prefissi_options",
		args: { txt: "" },
		callback(r) {
			if (!r || !r.message) return;
			const opzioni = r.message.map((x) => (Array.isArray(x) ? x[0] : x));
			const campo = frm.get_field("naming_series_prefix");
			if (campo) {
				campo.df.options = opzioni.join("\n");
			}
		},
	});
}
