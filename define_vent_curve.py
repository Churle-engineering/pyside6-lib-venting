import numpy as np
import matplotlib

try:
    matplotlib.use("QtAgg")
except Exception:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt


def plot_rise_exp_decay(A, m1, tau, eps=1e-2, n=1000, ax=None,
                        show_area=False, title=None, show_popup=True):
    """
    Plot a linear-rise + exponential-decay pulse with fixed area A.

    y(t) = m1 * t                      for 0 <= t <= tp   (linear rise)
         = h * exp(-(t - tp)/tau)      for t > tp         (exp decay tail)

    The peak height h is FORCED by the area constraint (Option B):
        A = h^2/(2*m1) + h*tau   ->   h = sqrt(m1^2 tau^2 + 2 m1 A) - m1 tau

    Parameters
    ----------
    A     : float               total area (volume) under the curve
    m1    : float               rising gradient (> 0)
    tau   : float or list       decay time constant(s) to compare
    eps   : float or list       tail cut-off fraction(s) of the peak (e.g. 0.01)
    n     : int                 samples per curve
    ax    : matplotlib axis     optional existing axis to draw on
    show_area: bool             shade the area under each curve
    title : str                 optional custom plot title

    Returns
    -------
    ax    : the matplotlib axis
    info  : list of dicts (h, tp, tau, eps, te) for each curve drawn
    """
    taus = np.atleast_1d(tau).astype(float)
    epss = np.atleast_1d(eps).astype(float)

    if ax is None:
        fig, ax = plt.subplots(figsize=(9, 5.5))

    info = []
    # one combination per (tau, eps) pair, broadcast if lengths differ
    combos = [(t, e) for t in taus for e in epss]

    colors = [matplotlib.colors.to_hex(c) for c in plt.cm.viridis(np.linspace(0, 0.85, len(combos)))]

    for (t_tau, t_eps), c in zip(combos, colors):
        # peak height forced by the area constraint
        h  = np.sqrt(m1**2 * t_tau**2 + 2 * m1 * A) - m1 * t_tau
        tp = h / m1
        te = tp + t_tau * np.log(1.0 / t_eps)    # practical cut-off

        t = np.linspace(0, te, n)
        y = np.where(t <= tp, m1 * t, h * np.exp(-(t - tp) / t_tau))

        label = f"$\\tau$={t_tau:g}, $\\epsilon$={t_eps:g}  (h={h:.2f}, $t_e$={te:.2f})"
        ax.plot(t, y, color=c, lw=2, label=label)
        ax.scatter([tp], [h], color=c, s=25, zorder=5)   # mark the peak

        if show_area:
            ax.fill_between(t, y, color=c, alpha=0.12)

        info.append({"h": h, "tp": tp, "tau": t_tau, "eps": t_eps, "te": te})

    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("time  $t$")
    ax.set_ylabel("$y(t)$")
    ax.set_title(title or f"Linear rise + exponential decay  (A={A:g}, $m_1$={m1:g})")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, framealpha=0.9)

    if show_popup:
        try:
            plt.show(block=True)
        except Exception:
            pass

    return ax, info


if __name__ == "__main__":
    # Compare several tau values (same eps) and a couple of eps values
    ax, info = plot_rise_exp_decay(
        A=100.0, m1=5.0,
        tau=[2, 5, 10],      # try different decay time constants
        eps=0.01,            # 1% cut-off
        show_area=True,
    )
    plt.tight_layout()
    plt.savefig("rise_decay_tau.png", dpi=130)

    # Second figure: fix tau, vary eps to see how the cut-off point moves
    fig2, ax2 = plt.subplots(figsize=(9, 5.5))
    plot_rise_exp_decay(A=100.0, m1=5.0, tau=5,
                        eps=[0.1, 0.01, 0.001], ax=ax2,
                        title="Effect of $\\epsilon$ (tail cut-off) at fixed $\\tau$=5")
    plt.tight_layout()
    plt.savefig("rise_decay_eps.png", dpi=130)

    for d in info:
        print(d)
