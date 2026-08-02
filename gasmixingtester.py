import numpy as np
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt


# ==================================================
# ROOM / COMPARTMENT SETUP
# ==================================================

n_compartments = 9

# Room layout:
#
# +-----+-----+-----+
# |  6  |  7  |  8  |  ceiling layer
# +-----+-----+-----+
# |  3  |  4  |  5  |  middle layer
# +-----+-----+-----+
# |  0  |  1  |  2  |  floor layer
# +-----+-----+-----+

V = np.full(n_compartments, 20.0)  # compartment volumes, m3


# ==================================================
# GAS SPECIES SETUP
# ==================================================

species = np.array([
    "H2",
    "CO",
    "CH4",
    "C2H4"
])

n_species = len(species)

# Battery offgas volume fractions
gas_fractions = np.array([
    0.35,  # H2
    0.25,  # CO
    0.15,  # CH4
    0.25   # C2H4
])

# Check fractions sum to 1
gas_fractions = gas_fractions / gas_fractions.sum()


# ==================================================
# TRANSPORT MATRIX
# ==================================================

A = np.zeros((n_compartments, n_compartments))

Q_horizontal = 0.5  # m3/s
Q_up = 1.5          # m3/s, buoyancy-driven upward movement
Q_down = 0.2        # m3/s, reduced downward movement

connections = [
    # horizontal floor
    (0, 1), (1, 2),

    # horizontal middle
    (3, 4), (4, 5),

    # horizontal ceiling
    (6, 7), (7, 8),

    # vertical lower to middle
    (0, 3), (1, 4), (2, 5),

    # vertical middle to upper
    (3, 6), (4, 7), (5, 8)
]


def add_exchange(A, i, j, q_ij, q_ji, V):
    """
    Adds exchange between compartments i and j.

    q_ij = volumetric flow/mixing rate from i to j, m3/s
    q_ji = volumetric flow/mixing rate from j to i, m3/s
    """

    # Loss from i to j
    A[i, i] -= q_ij / V[i]

    # Gain into j from i
    A[j, i] += q_ij / V[j]

    # Loss from j to i
    A[j, j] -= q_ji / V[j]

    # Gain into i from j
    A[i, j] += q_ji / V[i]


for i, j in connections:

    # Vertical connection if index difference is 3
    if abs(j - i) == 3:

        # Here, j is above i for this layout
        lower = min(i, j)
        upper = max(i, j)

        add_exchange(
            A=A,
            i=lower,
            j=upper,
            q_ij=Q_up,
            q_ji=Q_down,
            V=V
        )

    else:
        # Symmetric horizontal turbulent mixing
        add_exchange(
            A=A,
            i=i,
            j=j,
            q_ij=Q_horizontal,
            q_ji=Q_horizontal,
            V=V
        )


# ==================================================
# VENTILATION
# ==================================================

Q_supply = 0.3   # m3/s
Q_exhaust = 0.3  # m3/s

supply_compartment = 0
exhaust_compartment = 8

# Clean supply air entering compartment 0.
# Since incoming concentration is zero, this acts as dilution/removal.
A[supply_compartment, supply_compartment] -= Q_supply / V[supply_compartment]

# Exhaust removes gas from compartment 8.
A[exhaust_compartment, exhaust_compartment] -= Q_exhaust / V[exhaust_compartment]


# ==================================================
# BATTERY OFFGAS SOURCE
# ==================================================

release_compartment = 1


def total_release_rate(t):
    """
    Total volumetric offgas release rate, m3/s.

    Example:
    Battery releases 0.02 m3/s of total vent gas for 60 seconds.
    """

    if 0 <= t <= 60:
        return 0.02
    else:
        return 0.0


def source_term(t):
    """
    Returns source term S with shape:

        S.shape = (n_species, n_compartments)

    Units:
        concentration generation rate, 1/s
        because release_rate / compartment_volume gives:
        (m3/s) / m3 = 1/s
    """

    S = np.zeros((n_species, n_compartments))

    release_rate = total_release_rate(t)  # total m3/s

    species_release_rates = release_rate * gas_fractions

    S[:, release_compartment] = (
        species_release_rates / V[release_compartment]
    )

    return S


# ==================================================
# ODE FUNCTION
# ==================================================

def room_model(t, y):
    """
    ODE function for solve_ivp.

    solve_ivp requires y to be 1D, so internally:

        y -> C with shape (n_species, n_compartments)

    The transport equation is:

        dCdt = C @ A.T + S

    because each row of C is one species, while A acts on compartments.
    """

    C = y.reshape(n_species, n_compartments)

    dCdt = C @ A.T + source_term(t)

    return dCdt.reshape(-1)


# ==================================================
# INITIAL CONDITIONS
# ==================================================

C0 = np.zeros((n_species, n_compartments))

y0 = C0.reshape(-1)


# ==================================================
# SOLVE
# ==================================================

t_span = (0, 600)
t_eval = np.linspace(0, 600, 601)

sol = solve_ivp(
    fun=room_model,
    t_span=t_span,
    y0=y0,
    t_eval=t_eval,
    method="RK45"
)


# Reshape result into:
#
# C_time.shape = (n_times, n_species, n_compartments)

C_time = sol.y.T.reshape(len(sol.t), n_species, n_compartments)


# ==================================================
# POST-PROCESSING
# ==================================================

# Example: extract H2 concentration
idx_H2 = np.where(species == "H2")[0][0]

H2 = C_time[:, idx_H2, :]  # shape = (n_times, n_compartments)

# Maximum H2 concentration in each compartment
max_H2_by_compartment = H2.max(axis=0)

# Maximum H2 concentration anywhere in room at each time
max_H2_at_each_time = H2.max(axis=1)

print("Maximum H2 concentration by compartment:")
for i, value in enumerate(max_H2_by_compartment):
    print(f"Compartment {i}: {value:.4f} m3/m3")


# ==================================================
# LFL CALCULATION USING LE CHATELIER
# ==================================================

# LFL values as volume fraction, not percent
# Example values only - check against the data source you want to use
LFL = np.array([
    0.04,   # H2
    0.125,  # CO
    0.05,   # CH4
    0.027   # C2H4 / ethylene
])

# Total fuel concentration in each compartment over time
fuel_conc = C_time.sum(axis=1)  # shape = (n_times, n_compartments)

# Species mole/volume fractions within fuel mixture
# Avoid divide-by-zero using where
fuel_species_fraction = np.divide(
    C_time,
    fuel_conc[:, np.newaxis, :],
    out=np.zeros_like(C_time),
    where=fuel_conc[:, np.newaxis, :] > 0
)

# Le Chatelier mixture LFL:
#
# LFL_mix = 1 / sum(y_i / LFL_i)

LFL_mix = np.divide(
    1.0,
    np.sum(fuel_species_fraction / LFL[np.newaxis, :, np.newaxis], axis=1),
    out=np.full_like(fuel_conc, np.inf),
    where=fuel_conc > 0
)

percent_LFL = 100 * fuel_conc / LFL_mix

max_percent_LFL_by_compartment = percent_LFL.max(axis=0)

print("\nMaximum %LFL by compartment:")
for i, value in enumerate(max_percent_LFL_by_compartment):
    print(f"Compartment {i}: {value:.1f}% LFL")


# ==================================================
# PLOTS
# ==================================================

plt.figure(figsize=(10, 6))

for i in range(n_compartments):
    plt.plot(
        sol.t,
        H2[:, i],
        label=f"Compartment {i}"
    )

plt.xlabel("Time (s)")
plt.ylabel("H2 concentration (m3/m3)")
plt.title("Hydrogen Concentration by Compartment")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()


plt.figure(figsize=(10, 6))

for i in range(n_compartments):
    plt.plot(
        sol.t,
        percent_LFL[:, i],
        label=f"Compartment {i}"
    )

plt.xlabel("Time (s)")
plt.ylabel("% LFL")
plt.title("Flammability Level by Compartment")
plt.axhline(100, color="red", linestyle="--", label="100% LFL")
plt.axhline(25, color="orange", linestyle="--", label="25% LFL")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()