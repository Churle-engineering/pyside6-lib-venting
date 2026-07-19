import unittest

from calculations import resolve_lfl_curve_labels


class LFLResolutionTests(unittest.TestCase):
    def test_resolve_lfl_curve_labels_uses_canonical_gas_keys(self):
        labels = ["Carbon Monoxide (ppm)", "Hydrogen (ppm)", "Total Hydrocarbons (ppm)"]

        names, rows = resolve_lfl_curve_labels(labels)

        self.assertEqual(names, ["co", "h2", "total_hydrocarbons"])
        self.assertEqual(rows, [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
