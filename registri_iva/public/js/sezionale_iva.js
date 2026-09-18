frappe.ui.form.on("Sezionale IVA", {
	refresh(frm) {
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
			frm.set_df_property("naming_series_prefix", "options", opzioni);
			frm.refresh_field("naming_series_prefix");
		},
	});
}
