"""The gravity model: trips between two zones in proportion to what the origin produces, what the
destination attracts, and a deterrence function of the travel time between them.

`EXPO` gives `exp(-beta x minutes)`: a large beta keeps everyone close to home, a small one
spreads them across the city. Rather than pick beta blind, the model picks an **average trip
length** - a quantity that can be argued about - and solves for the beta that produces it.

Any pair the network cannot serve gets a very large cost rather than a missing one, so it
receives almost exactly zero trips instead of dividing by nothing.
"""
import numpy as np
import pandas as pd


class Gravity:
    """A doubly-constrained gravity model over one block of zones.

    `cost` is the zone-by-zone minutes; `vectors` has `productions` and `attractions` indexed by
    zone number, in the cost's order. Attractions are rescaled to the production total: only
    their ratios survive.
    """

    def __init__(self, cost, vectors, deterrence="EXPO", beta_floor=0.001, beta_ceiling=1.0):
        self.cost = cost
        far = np.nanmax(cost[np.isfinite(cost)]) * 10
        self.impedance = np.where(np.isfinite(cost), cost, far)
        self.vectors = vectors.copy()
        self.vectors["attractions"] *= (self.vectors["productions"].sum()
                                        / self.vectors["attractions"].sum())
        self.deterrence = deterrence
        self.beta_floor, self.beta_ceiling = beta_floor, beta_ceiling
        self.beta = None

    def matrix(self, beta):
        """One run of the gravity model at a given deterrence parameter."""
        from aequilibrae.distribution import GravityApplication, SyntheticGravityModel
        from aequilibrae.matrix import AequilibraeMatrix

        impedance = AequilibraeMatrix()
        impedance.create_empty(zones=len(self.vectors), matrix_names=["time"], memory_only=True)
        impedance.index[:] = self.vectors.index.to_numpy()
        impedance.matrices[:, :, 0] = self.impedance
        impedance.computational_view(["time"])
        shape = SyntheticGravityModel()
        shape.function = self.deterrence
        shape.beta = float(beta)
        run = GravityApplication(impedance=impedance, vectors=self.vectors,
                                 row_field="productions", column_field="attractions",
                                 model=shape, nan_as_zero=True)
        run.apply()
        return np.array(run.output.matrix["gravity"], dtype=float)

    def mean_trip_minutes(self, trips):
        """Trip-weighted average travel time, over the pairs the network can actually serve."""
        usable = np.isfinite(self.cost) & (trips > 0)
        return float((trips[usable] * self.cost[usable]).sum() / trips[usable].sum())

    def solve(self, mean_trip_min):
        """The matrix whose average trip is `mean_trip_min`, by bisection on beta.

        At the strong end the deterrence is so steep that AequilibraE's balancing may stop short
        of convergence (it warns); that end only bounds the range reported and is never the
        matrix used.
        """
        longest = self.mean_trip_minutes(self.matrix(self.beta_floor))
        shortest = self.mean_trip_minutes(self.matrix(self.beta_ceiling))
        print(f"average trip lengths this network and attraction pattern can produce: "
              f"{shortest:.1f} to {longest:.1f} min")
        target = min(max(mean_trip_min, shortest), longest)
        if target != mean_trip_min:
            print(f"  ** {mean_trip_min:.1f} min is outside that range; using {target:.1f} min "
                  f"instead")

        # More deterrence means shorter trips, so the search is monotone.
        low, high = self.beta_floor, self.beta_ceiling
        for _ in range(24):
            mid = (low + high) / 2
            if self.mean_trip_minutes(self.matrix(mid)) > target:
                low = mid          # trips still too long, deter more
            else:
                high = mid
        self.beta = (low + high) / 2
        demand = self.matrix(self.beta)
        print(f"\ndeterrence {self.deterrence} with beta = {self.beta:.4f}")
        print(f"  asked for {target:.1f} min, achieved {self.mean_trip_minutes(demand):.1f} min")
        if self.beta < 0.01:
            print("  ** beta this small means travel time barely affects where people go.")
        print(f"vehicle trips in the matrix: {demand.sum():,.0f} "
              f"(productions asked for {self.vectors['productions'].sum():,.0f})")
        return demand

    def check(self, demand, bands=((0, 5), (5, 10), (10, 20), (20, 30), (30, 45), (45, 1e9))):
        """Is the matrix sensible? Intrazonal share, trip lengths, and both margins."""
        print(f"cells with any trips: {(demand > 0.01).sum():,} of {demand.size:,}")
        print(f"intrazonal share: {100 * np.trace(demand) / demand.sum():.1f}% of the trips")
        print("where the trips go, by travel time:")
        served = np.isfinite(self.cost)
        for lo, hi in bands:
            mask = served & (self.cost >= lo) & (self.cost < hi)
            share = 100 * demand[mask].sum() / demand.sum()
            label = f"{lo}-{hi} min" if hi < 1e9 else f"over {lo} min"
            print(f"  {label:>12}  {share:5.1f}%  of trips   {'#' * int(share / 2)}")
        print(f"row sums against productions: correlation "
              f"{np.corrcoef(demand.sum(axis=1), self.vectors['productions'])[0, 1]:.4f}")
        print(f"column sums against attractions: correlation "
              f"{np.corrcoef(demand.sum(axis=0), self.vectors['attractions'])[0, 1]:.4f}")


def busiest_pairs(demand, cost, zones, names, n=10):
    """The n busiest zone pairs, by name. `zones` is the matrix's zone order."""
    top = np.dstack(np.unravel_index(np.argsort(demand, axis=None)[-n:][::-1], demand.shape))[0]
    print(f"\nthe {n} busiest zone pairs:")
    for i, j in top:
        print(f"  {names.get(zones[i], zones[i])!s:<30} -> {names.get(zones[j], zones[j])!s:<30} "
              f"{demand[i, j]:6.0f} trips {cost[i, j]:5.1f} min")


def stayers(demand, vectors, cost, label_of, extra=None, n=8):
    """Zones keeping more than a quarter of their trips at home, which a too-strong deterrence
    or a zone with no other way out produces."""
    own = np.diag(demand)
    share = np.divide(own, demand.sum(axis=1), out=np.zeros_like(own),
                      where=demand.sum(axis=1) > 0)
    found = np.where(share > 0.25)[0]
    print(f"zones keeping more than a quarter of their trips at home: {len(found)}")
    for k in found[np.argsort(-share[found])][:n]:
        out = cost[k].copy()
        out[k] = np.inf
        z = vectors.index[k]
        print(f"    {label_of(z)} {100 * share[k]:3.0f}% at home, nearest zone "
              f"{np.nanmin(out[np.isfinite(out)]):5.1f} min; produces "
              f"{vectors['productions'].iloc[k]:,.0f}, attracts "
              f"{vectors['attractions'].iloc[k]:,.0f}" + (f"; {extra(z)}" if extra else ""))
    return pd.Series(share, index=vectors.index)
