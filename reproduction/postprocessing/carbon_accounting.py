# Made by Francesco Maldonato on 10/11/2026
"""Hourly carbon attribution of the community's energy flows (paper Section III-E, Eqs. 1, 2 and 6).

Input: one hourly DataFrame per scenario with these columns (energies in MWh per
hour, carbon intensities in gCO2eq/kWh == kgCO2eq/MWh):

    solar, wind        local generation
    imp, exp           grid import / export (from hourly net market sales)
    bess_ch, bess_dis  stationary battery charge / discharge, grid side
    bess_e             stationary battery stored energy at the end of the hour
    ev_ch, ev_dis      EV fleet charge / V2G discharge, grid side
    ev_e               EV fleet stored energy at the end of the hour
    ci_grid            external-grid carbon intensity

Method (one pass, t-1 -> t):
1. CI_mix(t) = (E_sol*CI_sol + E_wnd*CI_wnd + E_imp*CI_grid
                + E_BESS,dis*SOCI_BESS(t-1) + E_EV,dis*SOCI_EV(t-1)) / E_tot(t)
   where the discharges are the energies delivered to the DEMS node (grid side).
2. SOCI(t) = [SOCI(t-1) * (E_stored(t) - E_ch(t)*eta) + E_ch(t)*eta*CI_mix(t)] / E_stored(t)
   if the storage charges in t, else SOCI(t-1). Old energy keeps its intensity,
   new energy enters at CI_mix. This equals the paper's Eq. (SOCI) whenever charge,
   discharge and driving do not overlap in the same hour, and stays carbon-consistent
   for the aggregated EV fleet when some EVs drive while others charge.
3. KPIs: CO2_imp = sum E_imp*CI_grid, CO2_exp = sum E_exp*CI_mix,
   benefit = sum E_exp*(CI_grid - CI_mix), balance = CO2_imp - benefit.
"""
import numpy as np

CI_SOLAR = 43.0  # gCO2eq/kWh, NREL lifecycle median
CI_WIND = 13.0
ETA = 0.98  # charge efficiency of BESS and EVs

COLUMNS = ["solar", "wind", "imp", "exp", "bess_ch", "bess_dis", "bess_e", "ev_ch", "ev_dis", "ev_e", "ci_grid"]


def attribute(ts, bess_e0, ev_e0, soci0=None, eta_bess=None, eta_ev=None):
    """Return ts with hourly ci_mix, soci_bess, soci_ev columns added.

    eta_bess, eta_ev: charge efficiency of the battery and of the EVs (default ETA; the EV efficiency sweep changes it).

    bess_e0, ev_e0: stored energy before the first hour (MWh).
    soci0: initial SOCI of both storages; default = grid CI of the first hour.
    """
    x = {c: ts[c].to_numpy(float) for c in COLUMNS}
    n = len(ts)
    ci_mix, soci_b, soci_e = np.zeros(n), np.zeros(n), np.zeros(n)
    sb = se = x["ci_grid"][0] if soci0 is None else soci0
    for t in range(n):
        e_tot = x["solar"][t] + x["wind"][t] + x["imp"][t] + x["bess_dis"][t] + x["ev_dis"][t]
        if e_tot > 0:
            ci_mix[t] = (x["solar"][t] * CI_SOLAR + x["wind"][t] * CI_WIND + x["imp"][t] * x["ci_grid"][t]
                         + x["bess_dis"][t] * sb + x["ev_dis"][t] * se) / e_tot
        sb = _update_soci(sb, x["bess_ch"][t], x["bess_e"][t], ci_mix[t], ETA if eta_bess is None else eta_bess)
        se = _update_soci(se, x["ev_ch"][t], x["ev_e"][t], ci_mix[t], ETA if eta_ev is None else eta_ev)
        soci_b[t], soci_e[t] = sb, se
    return ts.assign(ci_mix=ci_mix, soci_bess=soci_b, soci_ev=soci_e)


def _update_soci(soci, e_ch, e_stored, ci_mix, eta=ETA):
    if e_ch <= 0 or e_stored <= 0:
        return soci
    new = min(e_ch * eta, e_stored)
    return (soci * (e_stored - new) + new * ci_mix) / e_stored


def kpis(ts):
    """Paper KPIs from an attributed frame (energies in MWh, emissions in tCO2eq)."""
    co2_imp = (ts.imp * ts.ci_grid).sum() / 1000
    co2_exp = (ts.exp * ts.ci_mix).sum() / 1000
    benefit = (ts.exp * (ts.ci_grid - ts.ci_mix)).sum() / 1000
    return {
        "Grid imported energy [MWh]": ts.imp.sum(),
        "Imported energy CO2eq [tCO2eq]": co2_imp,
        "Grid exported energy [MWh]": ts.exp.sum(),
        "Exported energy CO2eq [tCO2eq]": co2_exp,
        "Export CO2eq benefit [tCO2eq]": benefit,
        "Net attributed CO2eq balance [tCO2eq]": co2_imp - benefit,
        "Export carbon intensity [gCO2eq/kWh]": 1000 * co2_exp / ts.exp.sum(),
        "Mean SOCI BESS / EV [gCO2eq/kWh]": f"{ts.soci_bess.mean():.0f} / {ts.soci_ev.mean():.0f}",
    }

