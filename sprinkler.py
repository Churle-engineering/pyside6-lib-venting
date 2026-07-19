# sprinkler activation time arup compute calc
import math

from information import FIRE_PROPERTIES


def _ceiling_jet_properties(heat_release_rate, ceiling_height, radial_distance, ambient_temperature):
    """Return ceiling jet gas temperature and velocity using Alpert-type correlations."""
    radial_height = radial_distance / ceiling_height

    if radial_height <= 0.18:
        delta_ceiling_jet_temperature = 16.9 * (heat_release_rate ** (2.0 / 3.0)) / (ceiling_height ** (5.0 / 3.0))
        jet_velocity = 0.96 * ((heat_release_rate / ceiling_height) ** (1.0 / 3.0))
    else:
        delta_ceiling_jet_temperature = 5.38 * ((heat_release_rate / radial_distance) ** (2.0 / 3.0)) / ceiling_height
        jet_velocity = 0.195 * (heat_release_rate ** (1.0 / 3.0)) / (ceiling_height ** 0.5)

    ceiling_jet_gas_temperature = ambient_temperature + delta_ceiling_jet_temperature
    return ceiling_jet_gas_temperature, max(jet_velocity, 1e-9)


def activation_time_Calc(sprinkler_data):
    """Compute sprinkler activation time with a simple RTI detector response model.

    Expected keys in sprinkler_data:
    - ceiling_height (m)
    - radial_distance (m)
    - sprinkler_response_time_index ((m*s)^0.5)
    - sprinkler_activation_temperature (degC)
    - ambient_temperature (degC)
    - fire_growth_rate (key in FIRE_PROPERTIES['fire growth rate'])
    Optional:
    - max_time_s (defaults to 10000)
    - time_step_s (defaults to 1.0)
    """
    growth_rate_key = sprinkler_data["fire_growth_rate"]
    growth_rate = float(FIRE_PROPERTIES["fire growth rate"][growth_rate_key])
    ceiling_height = float(sprinkler_data["ceiling_height"])
    radial_distance = float(sprinkler_data["radial_distance"])
    rti = float(sprinkler_data["sprinkler_response_time_index"])
    activation_temperature = float(sprinkler_data["sprinkler_activation_temperature"])
    ambient_temperature = float(sprinkler_data["ambient_temperature"])
    max_time_s = float(sprinkler_data.get("max_time_s", 10000.0))
    time_step_s = float(sprinkler_data.get("time_step_s", 1.0))

    detector_temperature = ambient_temperature
    t = 0.0
    activation_time = None
    heat_release_rate = 0.0
    jet_velocity = 0.0
    ceiling_jet_gas_temperature = ambient_temperature

    while t <= max_time_s:
        heat_release_rate = growth_rate * (t ** 2)
        ceiling_jet_gas_temperature, jet_velocity = _ceiling_jet_properties(
            heat_release_rate,
            ceiling_height,
            radial_distance,
            ambient_temperature,
        )

        dtdt = (math.sqrt(jet_velocity) / rti) * (ceiling_jet_gas_temperature - detector_temperature)
        detector_temperature += dtdt * time_step_s

        if detector_temperature >= activation_temperature:
            activation_time = t
            break

        t += time_step_s

    return {
        "activation_time_s": activation_time,
        "detector_temperature_c": detector_temperature,
        "ceiling_jet_temperature_c": ceiling_jet_gas_temperature,
        "jet_velocity_mps": jet_velocity,
        "heat_release_rate_kw": heat_release_rate,
    }

