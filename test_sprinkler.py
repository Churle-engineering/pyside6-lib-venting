import unittest

from sprinkler import activation_time_Calc


class SprinklerTimingTests(unittest.TestCase):
    INPUTS = {
        "ceiling_height": 3.0,
        "radial_distance": 2.0,
        "sprinkler_response_time_index": 50.0,
        "sprinkler_activation_temperature": 68.0,
        "ambient_temperature": 20.0,
        "fire_growth_rate": "fast",
    }

    def test_activation_time_converges_as_timestep_is_refined(self):
        coarse = activation_time_Calc({**self.INPUTS, "time_step_s": 0.2})
        fine = activation_time_Calc({**self.INPUTS, "time_step_s": 0.05})

        self.assertIsNotNone(coarse["activation_time_s"])
        self.assertIsNotNone(fine["activation_time_s"])
        self.assertAlmostEqual(coarse["activation_time_s"], fine["activation_time_s"], places=2)

    def test_activation_at_ambient_temperature_occurs_at_zero(self):
        result = activation_time_Calc({
            **self.INPUTS,
            "sprinkler_activation_temperature": self.INPUTS["ambient_temperature"],
        })

        self.assertEqual(result["activation_time_s"], 0.0)

    def test_invalid_timestep_is_rejected(self):
        for time_step in (0.0, -1.0, float("inf")):
            with self.subTest(time_step=time_step), self.assertRaisesRegex(ValueError, "time step"):
                activation_time_Calc({**self.INPUTS, "time_step_s": time_step})


if __name__ == "__main__":
    unittest.main()