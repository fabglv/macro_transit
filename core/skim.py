"""How far every zone is from every other: free-flow minutes, checked, with the diagonal filled.

Free-flow, not congested: the distribution has to decide who travels where before there is
traffic to delay them. Two things need care:

- **the diagonal is empty** - a skim says nothing about a trip that starts and ends in one zone.
  Left at zero, every zone would be infinitely attractive to itself, so it is given a share of the
  trip to the nearest other zone (`INTRAZONAL_SHARE`).
- **some pairs may be unreachable** - counted rather than quietly turned into zeros.
"""
import numpy as np


def with_intrazonal(minutes, share):
    """The skim with each zone's time to itself made `share` of its time to the nearest other
    zone it reaches - what skim_zones does, done again in the demand step, where INTRAZONAL_SHARE
    belongs (a gravity model choice, not a property of the zones)."""
    out = minutes.copy()
    reachable = np.isfinite(out) & (out > 0)
    np.fill_diagonal(reachable, False)
    off = np.where(reachable, out, np.nan)
    has = reachable.any(axis=1)
    nearest = np.full(len(out), np.nan)
    nearest[has] = np.nanmin(off[has], axis=1)
    np.fill_diagonal(out, np.nan_to_num(nearest * share))
    return out


def skim_zones(project, zone_list, n_internal, intrazonal_share, label="internal",
               strict=True):
    """Free-flow minutes and km between every pair of zones in `zone_list`.

    Zones numbered above `n_internal` are external. With `strict`, a zone cut off from more than
    half the others stops the run: its trips would vanish from the assignment. Without it, the
    stranded zones are only reported.
    Returns minutes (diagonal filled), km, and the zone order of the skim.
    """
    from aequilibrae.paths import NetworkSkimming

    zone_list = np.asarray(zone_list)
    project.network.build_graphs(modes=["c"])
    graph = project.network.graphs["c"]
    graph.prepare_graph(zone_list)
    graph.set_graph("travel_time")
    graph.set_skimming(["travel_time", "distance"])
    graph.set_blocked_centroid_flows(True)   # no routing *through* a zone's connector
    skimming = NetworkSkimming(graph)
    skimming.execute()
    skims = skimming.results.skims
    minutes = np.array(skims.matrix["travel_time"], dtype=float).copy()
    km = np.array(skims.matrix["distance"], dtype=float) / 1000
    order = np.array(skims.index).astype(int)
    # Everything downstream indexes this matrix by position, so its order has to be the zone
    # order. A silent mismatch here would pair each zone's trips with another zone's times.
    if not np.array_equal(order, zone_list):
        raise ValueError("the skim is not in zone order; every cost lookup would be wrong")
    internal = zone_list <= n_internal
    extra = f", {(~internal).sum()} {label}" if (~internal).any() else ""
    print(f"skim: {minutes.shape[0]} x {minutes.shape[1]} zones ({internal.sum()} internal"
          f"{extra}), index checked against the zone table")

    reachable = np.isfinite(minutes) & (minutes > 0)
    np.fill_diagonal(reachable, False)
    stranded = reachable.sum(axis=1) == 0
    unserved = (~reachable).sum() - len(minutes)
    print(f"pairs the network cannot serve: {unserved:,} of {minutes.size:,} "
          f"({100 * unserved / minutes.size:.2f}%)")
    print(f"zones reaching nowhere: {stranded.sum()}"
          + (f" - {', '.join(map(str, order[stranded]))}" if stranded.any() else ""))
    cannot_leave = (~reachable).sum(axis=1) - 1
    cannot_enter = (~reachable).sum(axis=0) - 1
    for k in np.where((cannot_leave > len(minutes) / 2) | (cannot_enter > len(minutes) / 2))[0]:
        print(f"  zone {order[k]}: cannot reach {cannot_leave[k]} zones, "
              f"cannot be reached from {cannot_enter[k]}")
        if strict:
            raise RuntimeError(f"zone {order[k]} is cut off from most of the network; its trips "
                               f"would vanish from the assignment")

    off = np.where(reachable, minutes, np.nan)
    nearest = np.full(len(minutes), np.nan)
    nearest[~stranded] = np.nanmin(off[~stranded], axis=1)
    np.fill_diagonal(minutes, np.nan_to_num(nearest * intrazonal_share))

    block = minutes[np.ix_(internal, internal)]
    inner = block[np.isfinite(block) & ~np.eye(len(block), dtype=bool) & (block > 0)]
    print("\nfree-flow travel time between internal zones, minutes:")
    for name, q in [("10th", 10), ("median", 50), ("90th", 90), ("longest", 100)]:
        print(f"  {name:>8}  {np.percentile(inner, q):6.1f}")
    print(f"nearest other zone: median {np.nanmedian(nearest):.1f} min, "
          f"furthest {np.nanmax(nearest):.1f} min")
    print(f"intrazonal cost: median {np.median(np.diag(minutes)[internal & ~stranded]):.1f} min")
    return minutes, km, order
