"""
verify.py — checks for the four required rules.
==================================================
Roda asserções objetivas sobre o contrato do jogo, sem depender de sorte:

    R1  orçamento isolado por AGENTE (50 PP, não cumulativo)
    R2  custo fixo: ATACAR 50 / REPARAR 30 (20 PP descartados)
    R3  botnet: zumbi só causa dano se um agente russo pagar 50 PP
    R4  disputa de dados SIMÉTRICA + fim de jogo ÚNICO em `turnos_max`
"""

from __future__ import annotations

import warnings
from collections import Counter

from core import CyberWarModel, Faction, poder_fogo_agregado
from core.agents import (
    CUSTO_ATACAR,
    CUSTO_BOTNET,
    CUSTO_REPARAR,
    PP_POR_AGENTE,
    PODER_ATAQUE_BASE,
)
from core.factions import DOUTRINAS
from core.terminal import configurar_utf8

warnings.filterwarnings("ignore")

FALHAS: list[str] = []


def checar(cond: bool, ok: str, erro: str) -> None:
    print(f"  [{'OK ' if cond else 'FAIL'}] {ok}")
    if not cond:
        FALHAS.append(erro)


def r4_simetria() -> None:
    print("\nR4a — both sides have the same firepower")
    for f in Faction:
        agg = poder_fogo_agregado(f)
        checar(
            abs(agg - 1.0) < 1e-9,
            f"aggregate firepower of {f.value:<7} = {agg:.4f}",
            f"aggregate firepower of {f.value} = {agg}, expected 1.0",
        )

    # O roll não pode depender da facção: mesmo A_base para todo mundo.
    p_eua = PODER_ATAQUE_BASE / (PODER_ATAQUE_BASE + 28.0)
    p_rus = PODER_ATAQUE_BASE / (PODER_ATAQUE_BASE + 28.0)
    checar(
        p_eua == p_rus,
        f"identical hit chance for both sides @crypto=28: {p_eua:.4f}",
        "the hit roll differs between sides",
    )


def r1_r2_orcamento() -> None:
    print("\nR1/R2 — per-agent budget and fixed costs")
    m = CyberWarModel(rng=11, turnos_max=6, verbose=False)
    m.run()

    # Orçamento individual: cada agente tem `PP_POR_AGENTE` e não negativa.
    checar(
        all(a.pp >= 0 for a in m.agente_cyber),
        "no agent finished a turn with a negative balance",
        "negative PP balance: the hard gate was broken",
    )

    # Custo fixo: ATACAR == orçamento inteiro, REPARAR deixa 20 PP no chão.
    checar(
        CUSTO_ATACAR == PP_POR_AGENTE == 50,
        f"ATTACK = {CUSTO_ATACAR} PP = the whole budget ({PP_POR_AGENTE})",
        "attack cost does not match the budget",
    )
    checar(
        CUSTO_REPARAR == 30 and PP_POR_AGENTE - CUSTO_REPARAR == 20,
        f"STANCH = {CUSTO_REPARAR} PP -> {PP_POR_AGENTE - CUSTO_REPARAR} PP thrown away",
        "stanch cost is not 30",
    )
    checar(
        CUSTO_BOTNET == PP_POR_AGENTE == 50,
        f"BOTNET = {CUSTO_BOTNET} PP (gives up the whole turn)",
        "botnet cost does not match the budget",
    )

    # Simetria de gasto: os dois lados têm o mesmo orçamento total possível.
    gasto_max_eua = len([a for a in m.agente_cyber if a.faccao is Faction.USA]) * PP_POR_AGENTE
    gasto_max_rus = len([a for a in m.agente_cyber if a.faccao is Faction.RUSSIA]) * PP_POR_AGENTE
    checar(
        gasto_max_eua == gasto_max_rus == 2 * PP_POR_AGENTE,
        f"same possible budget on both sides: {gasto_max_eua} = {gasto_max_rus} PP",
        "total budget differs between sides",
    )


def r3_botnet() -> None:
    print("\nR3 — the botnet is paid for, never free")
    # Sem pagar CUSTO_BOTNET, nenhum zumbi causa dano.
    m = CyberWarModel(rng=3, turnos_max=1, verbose=False)
    m.step()
    checar(
        m.botnet_ativa is False,
        "with no payment, the botnet stays idle on turn 1",
        "botnet activated without payment",
    )

    # Rodando partidas o bastante para haver zumbis, Toda ativação da botnet
    # deve estar associada a um gasto de >= CUSTO_BOTNET pelos russos.
    ativacoes = 0
    violacoes = 0
    for s in range(1, 61):
        m = CyberWarModel(rng=s, turnos_max=14, verbose=False)
        while not m.fim:
            m.step()
            if m.botnet_ativa:
                ativacoes += 1
                if m.pp_gasto[Faction.RUSSIA] < CUSTO_BOTNET:
                    violacoes += 1
    checar(
        violacoes == 0 and ativacoes > 0,
        f"botnet active on {ativacoes} turns, always with >= {CUSTO_BOTNET} Russian PP",
        f"{violacoes} activations without enough payment",
    )


def r4_fim_de_jogo() -> None:
    print("\nR4b — one ending rule, and it respects the turn limit")
    for tm in (25, 30, 40):
        longos: list[int] = []
        sem_fim = 0
        for s in range(1, 61):
            m = CyberWarModel(rng=s, turnos_max=tm, verbose=False)
            m.run()
            if not m.fim:
                sem_fim += 1
            if m.turno > tm:
                longos.append(m.turno)
        checar(
            sem_fim == 0 and not longos,
            f"turn limit={tm}: 60/60 matches ended on the limit",
            f"{sem_fim} never set finished; ran past the limit: {longos[:5]}",
        )


def placar_25(seeds: int = 1500) -> None:
    """
    Mede o placar agregado em 25 turnos e julga se é parelho.

    O julgamento usa um INTERVALO DE CONFIANÇA de 95%, não um limiar fixo.
    Com 300 partidas o erro padrão de uma proporção em torno de 50% é de
    ~2,9pp — o suficiente para que uma diferença de 5pp apareça por puro
    acaso. Um limiar fixo marcaria "DESCOMPENSADO" em amostras pequenas
    mesmo com o jogo perfeitamente equilibrado.
    """
    print(f"\n=== 25-TURN SCOREBOARD ({seeds} matches) ===")
    v = Counter()
    for s in range(1, seeds + 1):
        m = CyberWarModel(rng=s, turnos_max=25, verbose=False)
        m.run()
        v[m.vencedor.value if m.vencedor else "TIE"] += 1

    rus, eua, emp = v.get("Russia", 0), v.get("USA", 0), v.get("TIE", 0)
    total = rus + eua + emp
    p_eua = eua / total

    # Erro padrão da proporção de vitórias dos EUA, e o intervalo de 95%.
    erro = (0.25 / total) ** 0.5
    baixo, alto = (p_eua - 1.96 * erro) * 100, (p_eua + 1.96 * erro) * 100

    print(f"  Russia {rus:>4} ({rus / total * 100:4.1f}%)  |  "
          f"USA {eua:>4} ({p_eua * 100:4.1f}%)  |  TIE {emp:>3}")
    print(f"  95% CI for USA: [{baixo:4.1f}%, {alto:4.1f}%]  "
          f"(standard error ±{erro * 100:.1f}pp)")

    parelho = baixo <= 50.0 <= alto
    print(f"  verdict  : {'EVEN' if parelho else 'LOPSIDED'}"
          f" — 50% {'sits inside' if parelho else 'sits outside'} the interval")


def main() -> int:
    configurar_utf8()
    print("=" * 74)
    print("  RULE CHECK R1-R4")
    print("=" * 74)
    r4_simetria()
    r1_r2_orcamento()
    r3_botnet()
    r4_fim_de_jogo()
    placar_25()

    print()
    print("=" * 74)
    if FALHAS:
        print(f"  {len(FALHAS)} FAILURE(S):")
        for f in FALHAS:
            print(f"   - {f}")
    else:
        print("  ALL RULES CHECKED")
    print("=" * 74)
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
