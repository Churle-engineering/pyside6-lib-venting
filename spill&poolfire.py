# spill and pool fire calculations

import math
import numpy as np
R = 8.314  # Universal gas constant in J/(mol*K)
from information import POOL_SPREAD_DATA, POOL_PROPERTIES


def max_pool_area(dike, pool_depth, user_selected_fuel, wind_speed, orifice_diameter, delta_P, ambient_temperature, volumetric_flow_rate, user_surface, user_weather):
    
    
    cross_section = math.pi * (orifice_diameter / 2) ** 2
    liquid_vapour_pressure = POOL_SPREAD_DATA[user_selected_fuel]['liquid vapour pressure']
    molar_mass = POOL_SPREAD_DATA[user_selected_fuel]['molar mass']
    fuel_density = POOL_SPREAD_DATA[user_selected_fuel]['density']
    area_max = (POOL_PROPERTIES['discharge_coefficients'][dike] * cross_section * R * ambient_temperature * math.sqrt(2 * fuel_density * delta_P)) / (18.3 * 10**-3 * wind_speed**0.78 * liquid_vapour_pressure * molar_mass) #m2
    if area_max > dike:
        area_max = dike
    
    area_permeability = (1.7715 * volumetric_flow_rate * POOL_SPREAD_DATA[user_selected_fuel]['kinematic viscosity']) / (9.81 * POOL_PROPERTIES['intrinsic_permeability'][user_surface] * POOL_PROPERTIES['relative_permeability'][user_weather])
    
    area_combined = area_max * (1 - (area_max/(area_max+area_permeability)))
    
    return area_max, area_permeability, area_combined


def operator_intervention(area_max, area_combined, area_dike, t_oi, ground_description, average_evaporation_rate):
    
    
    area_oi = area_combined * (1 - 0.5 ** ((t_oi * average_evaporation_rate)/ (area_max * POOL_PROPERTIES['average_pool_height'][ground_description]) ))
    return area_oi

def calc_pool_diameter(self, area_dike):
    # Placeholder for pool size calculation logic
    # Implement the actual calculation based on pool_parameters
    
    pool_diameter = math.sqrt( 4 * area_dike / math.pi)
    

    return pool_diameter


def pool_fire_hrr(pool_diameter, area_dike, user_selected_fuel):
    # Placeholder for pool fire heat release rate calculation
    mass_burn_rate = POOL_SPREAD_DATA[user_selected_fuel]['mass burning rate']
    heat_of_combustion = POOL_SPREAD_DATA[user_selected_fuel]['heat of combustion']
    empirical_constant = POOL_SPREAD_DATA[user_selected_fuel]['empirical constant']
    hrr = mass_burn_rate * heat_of_combustion * ( 1 - math.exp(-1 * empirical_constant * pool_diameter)) * area_dike
    return hrr


def pool_fire_burn_duration(pool_volume, pool_diameter, area_dike, user_selected_fuel):
    # Placeholder for pool fire burn duration calculation
    # Implement the actual calculation based on pool_size and fuel_properties
    
    mass_burn_rate = POOL_SPREAD_DATA[user_selected_fuel]['mass burning rate']
    fuel_density = POOL_SPREAD_DATA[user_selected_fuel]['density']
    regression_rate = mass_burn_rate / fuel_density
    
    burn_duration = 4 * pool_volume / (math.pi * pool_diameter**2 * regression_rate)
    return burn_duration


def pool_fire_flame_height(pool_diameter, hrr, user_selected_fuel):
    # Placeholder for pool fire flame height calculation
    # Implement the actual calculation based on pool_size and heat_release_rate
    mass_burn_rate = POOL_SPREAD_DATA[user_selected_fuel]['mass burning rate']
    air_density = 1.18  # kg/m^3, assumed constant for air at room temperature and pressure
    flame_height_heskestad = 0.235 * (hrr ** (2/5)) - (1.02 * pool_diameter)
    flame_height_thomas = 42 * pool_diameter * (mass_burn_rate / air_density * math.sqrt(9.81 * pool_diameter)) ** 0.61
    
    return flame_height_heskestad, flame_height_thomas