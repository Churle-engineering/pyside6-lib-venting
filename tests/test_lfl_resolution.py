import unittest

from calculations import normalize_gas_key, resolve_lfl_curve_labels, resolve_toxic_gas_densities
from information import BATTERY_CHEMISTRY_DATA, CHEMICAL_PROPERTIES


class LFLResolutionTests(unittest.TestCase):
    def test_normalize_gas_key_handles_common_flammable_aliases(self):
        samples = {
            "CO (%)": "co",
            "Carbon Monoxide (ppm)": "co",
            "Hydrogen Gas (%)": "h2",
            "THC (%)": "total_hydrocarbons",
            "Total HC (v/v%)": "total_hydrocarbons",
            "total hydrocarbons": "total_hydrocarbons",
        }

        for label, expected in samples.items():
            self.assertEqual(normalize_gas_key(label), expected)

    def test_resolve_lfl_curve_labels_uses_canonical_gas_keys(self):
        labels = ["Carbon Monoxide (ppm)", "Hydrogen (ppm)", "Total Hydrocarbons (ppm)"]

        names, rows = resolve_lfl_curve_labels(labels)

        self.assertEqual(names, ["co", "h2", "total_hydrocarbons"])
        self.assertEqual(rows, [0, 1, 2])

    def test_toxic_density_resolution_uses_all_canonical_density_components(self):
        for chemistry in BATTERY_CHEMISTRY_DATA.values():
            composition = chemistry["tox_gas_composition"]
            labels, percentages, densities = resolve_toxic_gas_densities(composition)
            expected_labels = [
                label
                for label in composition
                if CHEMICAL_PROPERTIES.get(label, {}).get("density", 0) > 0
            ]

            self.assertEqual(labels, expected_labels)
            self.assertEqual(len(percentages), len(labels))
            self.assertEqual(len(densities), len(labels))

        nmc_labels, _, _ = resolve_toxic_gas_densities(
            BATTERY_CHEMISTRY_DATA["NMC"]["tox_gas_composition"]
        )
        self.assertIn("h2o", nmc_labels)


if __name__ == "__main__":
    unittest.main()
