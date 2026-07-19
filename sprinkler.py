#sprinkler activation time arup compute calc
import math

from information import FIRE_PROPERTIES

def activation_time_Calc(sprinkler_data):

    radial_height = sprinkler_data['radial_distance'] / sprinkler_data['ceiling_height']
    growth_rate = FIRE_PROPERTIES['fire growth rate'][sprinkler_data['fire_growth_rate']]
    activation_temperature = sprinkler_data['sprinkler_activation_temperature']


    for t in range(0, 10000, 1):
        # --- fire growth rate calculation ---
            heat_release_rate = growth_rate * t**2
            
            # --- Ceiling Jet Temperature Calculation ---
            if radial_height <= 0.18:
                delta_celiing_jet_temperature = 16.9 * (heat_release_rate**(2/3)) / (sprinkler_data['ceiling_height']**(5/3))
            else:
                delta_celiing_jet_temperature = 5.38 * ((heat_release_rate/sprinkler_data['radial_distance'])**(2/3)) / (sprinkler_data['ceiling_height'])
            
            celing_jet_gas_temperature = sprinkler_data['ambient_temperature'] + delta_celiing_jet_temperature

            jet_velocity = 0.195 * (heat_release_rate**(1/3)) / (sprinkler_data['ceiling_height']**(1/2))
            
            delta_detector_temperature = (0.5 * jet_velocity * (celing_jet_gas_temperature - sprinkler_data['ambient_temperature'])) / (sprinkler_data['sprinkler_response_time_index']**(1/2))
            
            
            
            rti = time_constant * math.sqrt(jet_velocity)
            if t >= rti:
                break
            
            # Example time-varying conditions
    T_g = 20 + 180 * (1 - np.exp(-times / 50))
    u = 0.5 + 1.5 * (1 - np.exp(-times / 30))

    for i in range(len(times) - 1):

        dt = times[i + 1] - times[i]

        dTdt = (np.sqrt(u[i]) / RTI) * (T_g[i] - T_d)

        T_d += dTdt * dt

        if T_d >= T_activation:
            print(f"Activation time = {times[i+1]:.2f} s")
            break
    
    
    return rti

def ceiling_jet_temperature():
    
    return

