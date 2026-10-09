import math
#view factor calculation based on arupcompute documentation


DEFAULT_INPUTS = {
    "emmissive_power": 100,  # heat flux in kW/m2.
    "distance_to_receptor": 3,         # Distance from the emitter in meters
    "length_of_radiating_panel": 5,         # Length of the panel in meters
    "width_of_radiating_panel": 2,         # Width of the panel in meters
    "perp_distance_to_receptor": 2.5,  # Perpendicular distance from the emitter to the receptor in meters
    "temp_of_emitter": 1000,  # Emitter surface temperature in kelvin
    "emissivity": 0.9,  # must be between 0 and 1
    }


def heat_flux_of_emitter(emmissive_power: float, perp_distance_to_receptor: float,
                         length_of_radiating_panel: float, width_of_radiating_panel: float,
                         ) -> dict:
    """Return the view factor and received heat flux for one radiating panel."""
    #setup
    a_t = perp_distance_to_receptor + length_of_radiating_panel
    half_width_of_raidating_panel = width_of_radiating_panel / 2
    
    #equations
    A_t = a_t / perp_distance_to_receptor
    B_t = half_width_of_raidating_panel / perp_distance_to_receptor
    
    area_3 = (a_t - length_of_radiating_panel) / perp_distance_to_receptor
    base_3 = half_width_of_raidating_panel / perp_distance_to_receptor
    
    theta_1 = (1 / (2 * math.pi) ) * ((A_t/(math.sqrt(1 + A_t**2)) * math.atan((B_t / (math.sqrt(1 + A_t**2))))) + (B_t/(math.sqrt(1 + B_t**2)) * math.atan((A_t / (math.sqrt(1 + B_t**2))))))
        
    theta_2 = (1 / (2 * math.pi) ) * ((area_3/(math.sqrt(1 + area_3**2)) * math.atan((base_3 / (math.sqrt(1 + area_3**2))))) + (base_3/(math.sqrt(1 + base_3**2)) * math.atan((area_3 / (math.sqrt(1 + base_3**2))))))
    
    theta = 2 * (theta_1 - theta_2)
    
    recieved_heat_flux = emmissive_power * theta
    
    return {"view_factor": theta, "received_heat_flux": recieved_heat_flux}


def temp_of_emitter(temp_of_emitter: float, length_of_radiating_panel: float,
                         perp_distance_to_receptor: float, width_of_radiating_panel: float,
                         emissivity: float) -> dict:
    
    stef_boltz = 5.67e-11
    
    half_width_of_raidating_panel = width_of_radiating_panel / 2
    
    area_T = (perp_distance_to_receptor + length_of_radiating_panel) / perp_distance_to_receptor
    base_T = half_width_of_raidating_panel / perp_distance_to_receptor
    
    theta_T = (1 / (2 * math.pi) ) * ((area_T/(math.sqrt(1 + area_T**2)) * math.atan((base_T / (math.sqrt(1 + area_T**2))))) + (base_T/(math.sqrt(1 + base_T**2)) * math.atan((area_T / (math.sqrt(1 + base_T**2))))))
    
    area_3 = ((perp_distance_to_receptor + length_of_radiating_panel) - length_of_radiating_panel) / perp_distance_to_receptor
    base_3 = half_width_of_raidating_panel / perp_distance_to_receptor
    theta_3 = (1 / (2 * math.pi) ) * ((area_3/(math.sqrt(1 + area_3**2)) * math.atan((base_3 / (math.sqrt(1 + area_3**2))))) + (base_3/(math.sqrt(1 + base_3**2)) * math.atan((area_3 / (math.sqrt(1 + base_3**2))))))
    
    theta_final = 2 * (theta_T - theta_3)

    recieved_heat_flux = emissivity * stef_boltz * temp_of_emitter**4 * theta_final

    return {"view_factor": theta_final, "received_heat_flux": recieved_heat_flux}



