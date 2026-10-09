"""Provisional spill and pool-fire correlations from the supplied fuel table."""

import math

from information import POOL_PROPERTIES, POOL_SPREAD_DATA

R = 8314.5 #J/kmol.K


def _positive(value, name):
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite number greater than 0.")


def max_pool_area(bund_area, fuel, wind_speed, orifice_diameter, delta_p,
                  ambient_temperature, volumetric_flow_rate, surface, weather,
                  orifice_condition):
    """Return evaporation-limited, permeability and combined areas in m2."""
    properties = POOL_SPREAD_DATA[fuel]
    for name, value in (
        ("Bund area", bund_area),
        ("Wind speed", wind_speed),
        ("Orifice diameter", orifice_diameter),
        ("Pressure differential", delta_p),
        ("Ambient temperature", ambient_temperature),
        ("Volumetric flow rate", volumetric_flow_rate),
        ("Kinematic viscosity", properties.get("kinematic_viscosity")),
    ):
        if value is None:
            raise ValueError(f"Fuel '{fuel}' has no kinematic viscosity in the fuel property data.")
        _positive(value, name)
    permeability = POOL_PROPERTIES["relative_permeability"][weather]
    if not math.isfinite(permeability) or permeability <= 0:
        raise ValueError(f"Surface weather '{weather}' has no usable permeability.")

    cross_section = math.pi * (orifice_diameter / 2) ** 2
    area_max = (POOL_PROPERTIES["discharge_coefficients"][orifice_condition]
        * cross_section * R * ambient_temperature
        * math.sqrt(2 * properties["density"] * delta_p)
        / (18.3e-3 * wind_speed ** 0.78* properties["liquid vapour pressure"] * properties["molar mass"] ** 0.667)
    )
    
    area_max = min(area_max, bund_area)
    
    _positive(area_max, "Evaporation-limited area")
    
    area_permeability = (1.7715 * volumetric_flow_rate * properties["kinematic_viscosity"] /
                         (9.81 * POOL_PROPERTIES["intrinsic_permeability"][surface] * permeability)
    )
    
    area_combined = area_max * (1 - (area_max / (area_max + area_permeability)))
    
    for area in (area_max, area_permeability, area_combined):
        if not math.isfinite(area):
            raise ValueError("The spill calculation produced a non-finite area.")
    _positive(area_combined, "Combined pool area")
    return area_max, area_permeability, area_combined


def operator_intervention(area_max, area_combined, t_oi,
                          ground_description, average_evaporation_rate, *, pool_depth=None):
    """Return the intervention-adjusted pool area in m2."""
    if not math.isfinite(t_oi) or t_oi < 0:
        raise ValueError("Operator intervention time must be finite and non-negative.")
    _positive(average_evaporation_rate, "Average evaporation rate")
    height = (POOL_PROPERTIES["average_pool_height"][ground_description]
              if pool_depth is None else pool_depth)
    _positive(height, "Pool depth")
    return area_combined * (1 - 0.5 ** ((t_oi * average_evaporation_rate * 5400) / (area_max * height)))


def calc_pool_diameter(area):
    _positive(area, "Pool area")
    return math.sqrt(4 * area / math.pi)


def pool_fire_hrr(pool_diameter, area, fuel):
    properties = POOL_SPREAD_DATA[fuel]
    return (
        properties["mass burning rate"] * properties["heat of combustion"]
        * (1 - math.exp(-properties["empirical constant"] * pool_diameter))
        * area
    )


def pool_fire_burn_duration(pool_volume, area, fuel):
    _positive(pool_volume, "Pool volume")
    _positive(area, "Pool area")
    properties = POOL_SPREAD_DATA[fuel]
    regression_rate = properties["mass burning rate"] / properties["density"]
    return pool_volume / (area * regression_rate)


def pool_fire_flame_height(pool_diameter, hrr, fuel):
    mass_burn_rate = POOL_SPREAD_DATA[fuel]["mass burning rate"]
    air_density = 1.18
    heskestad = max(0.0, 0.235 * hrr ** (2 / 5) - 1.02 * pool_diameter)
    thomas = (
        42 * pool_diameter
        * (mass_burn_rate / (air_density * math.sqrt(9.81 * pool_diameter))) ** 0.61
    )
    return heskestad, thomas

# ----- calcualtion ----

def calculate_pool_assessment(*, bund_area, fuel, wind_speed, orifice_diameter,
                              delta_p, ambient_temperature, volumetric_flow_rate,
                              surface, weather, orifice_condition, ground_description,
                              pool_depth=None, intervention_time=None,
                              include_fire=False):
    """Calculate a single spill, with optional intervention and pool fire."""
    fuel_properties = POOL_SPREAD_DATA.get(fuel, {})
    required_properties = [
        "density", "liquid vapour pressure", "molar mass", "kinematic_viscosity",
    ]
    if include_fire:
        required_properties.extend((
            "mass burning rate", "heat of combustion", "empirical constant",
        ))
    missing_properties = [key for key in required_properties if key not in fuel_properties]
    if missing_properties:
        raise ValueError(
            f"Calculation is unavailable for fuel '{fuel}'; missing verified property data: "
            f"{', '.join(missing_properties)}."
        )

    area_max, area_permeability, area_combined = max_pool_area(
        bund_area, fuel, wind_speed, orifice_diameter, delta_p,
        ambient_temperature, volumetric_flow_rate, surface, weather,
        orifice_condition,
    )
    if intervention_time is not None or include_fire:
        if pool_depth is None:
            pool_depth = POOL_PROPERTIES["average_pool_height"][ground_description]
        _positive(pool_depth, "Pool depth")
    area = area_combined
    if intervention_time is not None:
        intervention_rate = (
            area_max * 18.3e-3 * wind_speed ** 0.78
            * fuel_properties["liquid vapour pressure"] * fuel_properties["molar mass"] ** 0.667
            / (R * ambient_temperature * fuel_properties["density"])
        )
        area = operator_intervention(
            area_max, area_combined, intervention_time,
            ground_description, intervention_rate, pool_depth=pool_depth,
        )
    result = {
        "area_max_m2": area_max,
        "area_permeability_m2": area_permeability,
        "area_combined_m2": area_combined,
        "pool_area_m2": area,
    }
    if intervention_time is not None or include_fire:
        result["pool_depth_m"] = pool_depth
    if intervention_time is not None:
        result["area_intervention_m2"] = area
    if include_fire:
        if area <= 0:
            raise ValueError("Pool fire requires a positive pool area.")
        diameter = calc_pool_diameter(area)
        volume = area * pool_depth
        hrr = pool_fire_hrr(diameter, area, fuel)
        heskestad, thomas = pool_fire_flame_height(diameter, hrr, fuel)
        result.update({
            "pool_diameter_m": diameter,
            "pool_volume_m3": volume,
            "heat_release_rate": hrr,
            "burn_duration_s": pool_fire_burn_duration(volume, area, fuel),
            "flame_height_heskestad_m": heskestad,
            "flame_height_thomas_m": thomas,
        })
        if not all(math.isfinite(value) for value in result.values()):
            raise ValueError("The pool fire calculation produced a non-finite result.")
    return result
