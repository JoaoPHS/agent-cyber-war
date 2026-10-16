"""
core/factions.py
================
Facções beligerantes e suas doutrinas de guerra cibernética.

A assimetria EUA x Rússia NÃO vem de "um lado é mais forte". O poder de fogo
agregado de ambas as facções é propositalmente equivalente. A diferença está
em *como* o dano é distribuído:

    EUA    -> doutrina "Cirúrgico": 1 alvo  por ciclo, dano concentrado (mult > 1)
    Rússia -> doutrina "Híbrido"  : N alvos por ciclo, dano diluído     (mult < 1)

Consequência tática (isso é o coração da simulação):
    * EUA consegue COLAPSAR um nó rápido -> ideal para decapitar alvos de
      alto valor estratégico, mas é focaça: se errar o alvo, gasta o turno.
    * Rússia enfraquece vários nós de uma vez -> difícil de defender (o
      adversário não sabe qual nó priorizar), mas nunca derruba nada rápido.

>>> EXPANSÃO — árvore de tecnologia
    A estrutura `Doutrina` é frozen (imutável) de propósito: crie uma função
    `evoluir(doutrina, nivel_tech) -> Doutrina` que retorne uma *nova* instância
    com `mult_dano`/`alcance` alterados. Exemplos de nós de tecnologia:
        * EUA    : "Zero-Day Arsenal"  -> +0.15 em mult_dano (precisão)
        * Rússia : "Botnet Federada"   -> +1 em alcance (mais alvos)
    Assinale no modelo quando aplicar (`modelo.aplicar_tech()`).

>>> EXPANSÃO — economia de processamento
    Adicione um campo `custo_cpu: float` em `Doutrina`. Ações com alto
    `alcance` (híbrido) custam mais ciclos de processamento. O agente passa a
    checar `modelo.processamento[faccao] >= doutrina.custo_cpu` antes de agir,
    o que cria escassez real: uma facção sob sanção computacional é forçada a
    ataques cirúrgicos mais baratos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Faction(str, Enum):
    """
    Facção beligerante.

    Herda de `str` para que `Faction.USA == "USA"` e a serialização direta
    para JSON/log funcionem sem conversão explícita.
    """

    USA = "USA"
    RUSSIA = "Russia"

    @property
    def inimiga(self) -> "Faction":
        """Retorna a facção adversária."""
        return Faction.RUSSIA if self is Faction.USA else Faction.USA

    @property
    def cor(self) -> str:
        """Código ANSI de cor (usado apenas na apresentação em terminal)."""
        return "\033[94m" if self is Faction.USA else "\033[91m"


@dataclass(frozen=True)
class Doutrina:
    """
    Modelo de combate de uma facção.

    Attributes
    ----------
    nome : str
        Rótulo exibido no relatório de turno.
    alcance : int
        Quantidade de nós inimigos atingidos em um único ciclo de ação.
    mult_dano : float
        Multiplicador aplicado ao dano de CADA alvo. `> 1` concentra,
        `< 1` dilui.
    descricao : str
        Texto explicativo para o log.
    """

    nome: str
    alcance: int
    mult_dano: float
    descricao: str


# --------------------------------------------------------------------------
# Tabela de doutrinas — o ponto único de balanceamento do MVP.
# --------------------------------------------------------------------------
DOUTRINAS: dict[Faction, Doutrina] = {
    Faction.USA: Doutrina(
        nome="Surgical",
        alcance=1,
        mult_dano=1.0,
        descricao="Precision: concentrated damage on a single critical node.",
    ),
    Faction.RUSSIA: Doutrina(
        nome="Hybrid",
        alcance=3,
        # 1/3 exato (e não 0.333) — ver `poder_fogo_agregado`.
        mult_dano=1 / 3,
        descricao="Spread: diluted damage across three different nodes.",
    ),
}


def poder_fogo_agregado(faccao: Faction) -> float:
    """
    Poder de fogo total de uma facção por ciclo de ação.

        poder_fogo_agregado = alcance * mult_dano

    É o invariante central do design: as duas facções devem ter o **mesmo**
    poder de fogo agregado, mudando apenas como ele é distribuído. Com os
    valores atuais, EUA e Rússia somam exatamente 1.0 — qualquer desvio
    desta igualdade é um bug de balanceamento, não uma escolha de design.
    """
    d = DOUTRINAS[faccao]
    return round(d.alcance * d.mult_dano, 3)


def doutrina_de(faccao: Faction) -> Doutrina:
    """Acesso seguro à doutrina de uma facção."""
    return DOUTRINAS[faccao]
