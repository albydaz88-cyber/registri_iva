from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = [line.strip() for line in f if line.strip()]

setup(
	name="registri_iva",
	version="0.0.1",
	description="Registri IVA italiani (acquisti, vendite, corrispettivi) con sezionali e autofatture intra-UE per ERPNext",
	author="Il tuo nome",
	author_email="you@example.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
