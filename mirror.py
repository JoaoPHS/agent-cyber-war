"""
mirror.py — framework symmetry test.
====================================
Makes both sides mechanically identical and measures the win rate.
This separates "the framework is unfair" from "the doctrine is unfair".

    Case 1  USA and Russia match (reach 1, mult 1.0)  -> should land near 50/50
    Case 2  Russia is hybrid (reach 3, mult 1/3)       -> measures the asymmetry
    Case 3  Mirror of case 2 (USA gets the hybrid doctrine)

Usage
-----
    python mirror.py --seeds 300
"""

from __future__ import annotations

import argparse
import warnings
from collections import Counter

import core.agents as mod_agents
from core import CyberWarModel, Doutrina, Faction, DOUTRINAS
from core.terminal import configurar_utf8

warnings.filterwarnings("ignore")

CIRURGICO = DOUTRINAS[Faction.USA]      # alcance 1
HIBRIDO = DOUTRINAS[Faction.RUSSIA]     # alcance 3, mult 1/3


def aplicar(usa: Doutrina, rus: Doutrina) -> None:
    DOUTRINAS[Faction.USA] = usa
    DOUTRINAS[Faction.RUSSIA] = rus


def rodar(seeds: int, turnos: int) -> Counter:
    v = Counter()
    for s in range(1, seeds + 1):
        m = CyberWarModel(rng=s, turnos_max=turnos, verbose=False)
        m.run()
        v[m.vencedor.value if m.vencedor else "TIE"] += 1
    return v


def main() -> int:
    configurar_utf8()
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=300)
    p.add_argument("--turns", type=int, default=25)
    p.add_argument("--no-botnet", action="store_true",
                   help="turn the botnet off so the doctrine is the only difference")
    a = p.parse_args()

    if a.no_botnet:
        mod_agents.LIMIAR_BOTNET = 10_000  # nunca satisfaz -> botnet inalcançável

    original = dict(DOUTRINAS)

    casos = [
        ("1. Pure mirror (both Surgical)", CIRURGICO, CIRURGICO),
        ("2. Asymmetric (USA Surgical, RUS Hybrid)", CIRURGICO, HIBRIDO),
        ("3. Flipped mirror (USA Hybrid, RUS Surgical)", HIBRIDO, CIRURGICO),
    ]

    print("=" * 78)
    print(f"  FRAMEWORK SYMMETRY TEST — {a.seeds} seeds, "
          f"{a.turns} turns"
          + ("  [botnet OFF]" if a.no_botnet else ""))
    print("=" * 78)
    for rotulo, usa, rus in casos:
        aplicar(usa, rus)
        v = rodar(a.seeds, a.turns)
        eua, emp = v.get("USA", 0), v.get("TIE", 0)
        p_eua = eua / a.seeds * 100
        print(f"  {rotulo:<48} USA {p_eua:5.1f}%")

    DOUTRINAS.update(original)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
