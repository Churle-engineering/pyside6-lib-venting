import math
import numpy as np



input = {
    "emmissive_power": 3,  # Emitter temperature in Kelvin
    "distance_to_receptor": 2,         # Distance from the emitter in meters
    "length_of_radiating_panel": 2,         # Length of the panel in meters
    "width_of_radiating_panel": 2,         # Width of the panel in meters
    }

def heat_flux_of_emitter(emitter_temp: float, distance: float) -> float:
    
    
    emmissive_power = input["emmissive_power"]
    distance_to_receptor = input["distance_to_receptor"]
    length_of_radiating_panel = input["length_of_radiating_panel"]
    width_of_radiating_panel = input["width_of_radiating_panel"]
    
    a_t = distance_to_receptor + length_of_radiating_panel
    half_width_of_raidating_panel = width_of_radiating_panel / 2
    A_t = a_t / distance_to_receptor
    B_t = half_width_of_raidating_panel / distance_to_receptor
    
    area_3 = (a_t - length_of_radiating_panel) / distance_to_receptor
    base_3 = half_width_of_raidating_panel / distance_to_receptor
    
    theta_1 = (1 / (2 * math.pi) ) * ((A_t/(math.sqrt(1 + A_t**2)) * math.atan((B_t / (math.sqrt(1 + A_t**2))))) + (B_t/(math.sqrt(1 + B_t**2)) * math.atan((A_t / (math.sqrt(1 + B_t**2))))))
    
    theta_2 = (1 / (2 * math.pi) ) * ((area_3/(math.sqrt(1 + area_3**2)) * math.atan((base_3 / (math.sqrt(1 + area_3**2))))) + (base_3/(math.sqrt(1 + base_3**2)) * math.atan((area_3 / (math.sqrt(1 + base_3**2))))))
    
    theta = 2 * (theta_1 - theta_2)
    
    recieved_heat_flux = emmissive_power * theta
    return recieved_heat_flux

