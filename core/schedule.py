"""
core/schedule.py
================
Substituto de `mesa.time.SimultaneousActivation`.

POR QUE REIMPLEMENTAR? (descoberta de compatibilidade)
------------------------------------------------------
O usuário do Mesa 2.x espera `mesa.time.RandomActivation` e
`mesa.time.SimultaneousActivation`. No Mesa 3.x **ambas foram removidas** — o
pacote `mesa.time` passou a expor apenas um sistema baseado em eventos
(`Schedule`, `Event`, `EventList`, `Priority`).

Este módulo preserva a semântica clássica de duas fases que a simulação
precisa, sem depender de API experimental:

    FASE 1  step()    -> todos os agentes DECIDEM sobre o mesmo snapshot
    FASE 2  advance() -> todos os agentes APLICAM suas decisões

POR QUE SIMULTÂNEO E NÃO ALEATÓRIO?
-----------------------------------
Com `RandomActivation` a ordem de ação vira vantagem: se os EUA sorteados
antes da Rússia, eles já enxergam o resultado do ataque inimigo no mesmo
turno. Num conflito isso é indesejável — ambos os lados devem observar o
mesmo estado e agir a partir dele. O modelo simultâneo elimina a viés de
ordem e torna o resultado reproduzível para um mesmo `rng`.

>>> EXPANSÃO — decisões assíncronas
    Para simular latência de rede (ataque híbrido que só surte efeito 2
    turnos depois), troque a aplicação imediata por uma fila de eventos:
    `model.schedule_event(AplicarDano(...), quando=model.time + latencia)`.
    O `schedule_event` nativo do Mesa 3 já suporta isso.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # evita import circular em tempo de execução
    from mesa import Agent, Model


class AtivacaoSimultanea:
    """
    Escalonador de duas fases (decidir -> aplicar).

    Uso típico dentro de `Model.step()`::

        self.schedule.step()
    """

    def __init__(self, model: "Model") -> None:
        self.model = model
        self.passos: int = 0

    @property
    def agents(self) -> list["Agent"]:
        """Snapshot atual dos agentes do modelo."""
        return list(self.model.agents)

    def step(self) -> None:
        """
        Executa um ciclo completo de decisão + aplicação.

        O snapshot é capturado **uma única vez** no início: um agente criado
        durante a fase de decisão só começa a agir no ciclo seguinte, o que
        mantém o ciclo determinístico.
        """
        agentes: list["Agent"] = list(self.model.agents)

        # Embaralhar usa o RNG do modelo -> continua reproduzível via seed.
        # A ordem não afeta o resultado (decisões são simultâneas), apenas
        # evita artefatos sistemáticos de iteração.
        self.model.random.shuffle(agentes)

        # FASE 1 — decisão sobre o mesmo snapshot do ambiente.
        for agente in agentes:
            agente.step()

        # FASE 2 — aplicação das decisões já registradas.
        for agente in agentes:
            agente.advance()

        self.passos += 1

    def __len__(self) -> int:
        return len(self.model.agents)
