"""
balance.py — verificador de balanceamento.
==========================================
Roda muitas partidas por configuração e mostra como o conflito está distribuído.
É a ferramenta para responder "as partidas estão disputadas?" com dado, não com
impressão.

Uso
---
    python balance.py                    # varredura padrão, 300 partidas/ponto
    python balance.py --games 1000       # larger sample
    python balance.py --turns 25 39 60   # specific points on the curve
    python balance.py --detail 7         # replay seed 7 with the full report
"""

from __future__ import annotations

import argparse
import statistics
import warnings
from collections import Counter

from core import (
    TURNOS_MAX_PADRAO,
    CyberWarModel,
    Faction,
    poder_fogo_agregado,
)
from core.terminal import configurar_utf8

warnings.filterwarnings("ignore")  # silencia o FutureWarning do Mesa sobre `seed`

# Pontos da curva. O padrão é 25 (TURNOS_MAX_PADRAO) — é ali que a vitória
# por pontuação decide a maioria das partidas.
PADRAO_TURNOS = (15, 20, 25, 30, 35, 40, 50)


def _rotulo(vencedor) -> str:
    return vencedor.value if vencedor else "TIE"


def rodar_lote(turnos_max: int, jogos: int, base_seed: int = 1) -> dict:
    """
    Executa `jogos` partidas para um determinado limite de turnos.

    Cada partida usa a seed `base_seed + i`, de modo que a amostra cobre
    trajetórias distintas e o resultado é reproduzível.
    """
    vitorias: Counter[str] = Counter()
    motivos: Counter[str] = Counter()
    turnos: list[int] = []
    margens: list[float] = []

    for i in range(jogos):
        modelo = CyberWarModel(rng=base_seed + i, turnos_max=turnos_max, verbose=False)
        modelo.run()

        vitorias[_rotulo(modelo.vencedor)] += 1
        motivos["COLLAPSE" if modelo.fim_codigo == "collapse" else "SCORE"] += 1
        turnos.append(modelo.turno)
        margens.append(
            abs(modelo.pontuacao(Faction.USA) - modelo.pontuacao(Faction.RUSSIA))
        )

    return {
        "vitorias": vitorias,
        "motivos": motivos,
        "turno_medio": statistics.mean(turnos),
        "margem_media": statistics.mean(margens),
        "jogos": jogos,
    }


def imprimir_curva(turnos_lista: list[int], jogos: int) -> None:
    print("=" * 78)
    print("  BALANCE CURVE — wins by match length")
    print("=" * 78)
    print(f"  Sample: {jogos} matches per point · deterministic seeds")
    print()
    print(f"  {'turns':>7}  {'RUSSIA':>14} {'USA':>14} {'TIE':>4}   winner")
    print("  " + "-" * 74)

    for turnos in turnos_lista:
        r = rodar_lote(turnos, jogos)
        v = r["vitorias"]
        total = r["jogos"]
        rus, eua, emp = v.get("Russia", 0), v.get("USA", 0), v.get("TIE", 0)

        if rus > eua:
            folga = (rus - eua) / total * 100
            chamada = f"RUSSIA +{folga:.1f}pp"
        elif eua > rus:
            folga = (eua - rus) / total * 100
            chamada = f"USA +{folga:.1f}pp"
        else:
            chamada = "exact tie"

        # Ponto de cruzamento recebe destaque.
        marca = " <== even" if abs(rus - eua) / total < 0.03 else ""
        print(
            f"  {turnos:>7}  {rus:>5} ({rus/total*100:4.1f}%) "
            f"{eua:>5} ({eua/total*100:4.1f}%) {emp:>4}   {chamada}{marca}"
        )

    print()
    print("  Short matches are decided by SCORE (spread damage). Long matches")
    print("  are decided by COLLAPSE (concentrated damage has time to finish")
    print("  a node). The even point is where the two curves cross.")
    print("=" * 78)


def imprimir_anatomia(turnos: int, jogos: int) -> None:
    print()
    print("=" * 78)
    print(f"  HOW MATCHES END — turn limit={turnos}")
    print("=" * 78)
    r = rodar_lote(turnos, jogos)
    motivos = r["motivos"]
    total = r["jogos"]

    for motivo, qtd in motivos.most_common():
        print(f"  {motivo:<10} {qtd:>5} ({qtd/total*100:5.1f}%)")
    print(f"  Average ending turn : {r['turno_medio']:.1f}")
    print(f"  Average final margin: {r['margem_media']:.2f} strategic health")


def main(argv: list[str] | None = None) -> int:
    configurar_utf8()  # acentos no terminal (Windows)
    parser = argparse.ArgumentParser(description="Check how even the simulation is.")
    parser.add_argument("--games", type=int, default=300, help="Matches per point (default 300).")
    parser.add_argument("--turns", type=int, nargs="+", default=None,
                        help="Curve points. Default: the built-in sweep.")
    parser.add_argument("--detail", type=int, metavar="SEED", default=None,
                        help="Replay one seed with the full report.")
    args = parser.parse_args(argv)

    if args.detail is not None:
        print(f"  Full report for seed {args.detail} "
              f"(turn limit={TURNOS_MAX_PADRAO})\n")
        modelo = CyberWarModel(rng=args.detail, turnos_max=TURNOS_MAX_PADRAO, verbose=True)
        modelo.run()
        return 0

    turnos_lista = args.turns if args.turns else list(PADRAO_TURNOS)
    imprimir_curva(turnos_lista, args.games)
    imprimir_anatomia(TURNOS_MAX_PADRAO, args.games)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
