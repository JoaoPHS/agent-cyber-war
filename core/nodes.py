"""
core/nodes.py
=============
`CyberNode` — ativo de infraestrutura crítica.

IMPORTANTE SOBRE O DESIGN:
    CyberNode NÃO é um `mesa.Agent`. Ela representa **estado do ambiente**
    (o grafo de rede), não um tomador de decisão. Manter a separação
    agente/ambiente é o que torna o modelo extensível: no futuro os nós podem
    ganhar comportamento autônomo (firewalls que se reconfiguram, honeypots)
    promovendo esta classe a `Agent` sem tocar na lógica dos invasores.

    Uma `dataclass` é intencional: é trivialmente serializável, comparável e
    fácil de inspecionar no debugger.

>>> EXPANSÃO — grafo de rede com topologia real
    `CyberNode` guarda apenas atributos próprios. As arestas (quem alcança
    quem) vivem em `CyberWarModel.grafo` (networkx). Para modelar latência,
    custo de pivô ou propagação lateral, adicione atributos como `camadas`
    ou `segmento_rede` e use-os como restrição de movimento.
"""

from __future__ import annotations

from dataclasses import dataclass

from .factions import Faction

# Limites do domínio. Centralizados aqui para evitar "magic numbers" soltos.
INTEGRIDADE_MAX = 100.0
INTEGRIDADE_MIN = 0.0

# Valor inicial de criptografia — serve de barreira contra invasões.
CRIPTOGRAFIA_PADRAO = 20.0


@dataclass
class CyberNode:
    """
    Nó de rede representando um ativo de infraestrutura crítica.

    Attributes
    ----------
    nome : str
        Identificador único do ativo (também é o nó no grafo networkx).
    faccao : Faction
        Quem detém o ativo.
    integridade : float
        Saúde operacional, 0..100. Em 0 o ativo colapsa.
    criptografia : float
        Barreira defensiva. Quanto maior, menor a probabilidade de invasão.
    valor_estrategico : float
        Relevância para a vitória. Pesa na pontuação de saúde da facção —
        perder um nó de valor 3.0 dói mais que perder três de valor 0.5.
    zumbificado : bool
        True quando o ativo foi comprometido por um ataque russo bem-sucedido.
        Enquanto o implante estiver lá, o nó é uma porta: o atacante entra
        na rede por ele mesmo sem a ponte de fronteira. Também entra na
        botnet se um agente russo pagar para acioná-la. Estancar a
        integridade não tira o implante; isso é a ação de limpar.
    """

    nome: str
    faccao: Faction
    integridade: float = 100.0
    criptografia: float = CRIPTOGRAFIA_PADRAO
    valor_estrategico: float = 1.0
    zumbificado: bool = False
    imune_ate: int = 0

    def __post_init__(self) -> None:
        """Garante invariantes do domínio mesmo com valores vindos de fora."""
        self.integridade = min(INTEGRIDADE_MAX, max(INTEGRIDADE_MIN, self.integridade))
        self.criptografia = max(0.0, self.criptografia)
        self.valor_estrategico = max(0.0, self.valor_estrategico)

    # -- consultas ---------------------------------------------------------

    @property
    def destruido(self) -> bool:
        """True quando o ativo atingiu colapso total."""
        return self.integridade <= INTEGRIDADE_MIN

    @property
    def integridade_pct(self) -> int:
        """Integridade arredondada, para exibição em tabela."""
        return int(round(self.integridade))

    @property
    def saude_ponderada(self) -> float:
        """
        Contribuição do nó para a pontuação estratégica da facção.

            saude_ponderada = (integridade / 100) * valor_estrategico

        É a métrica usada para decidir quem está vencendo quando o tempo
        se esgota (nenhum colapso total ocorreu).
        """
        return (self.integridade / INTEGRIDADE_MAX) * self.valor_estrategico

    # -- mutações de estado ------------------------------------------------

    def receber_dano(self, dano: float) -> float:
        """
        Aplica dano à integridade.

        Returns
        -------
        float
            Dano *efetivamente* aplicado (para log), pois a integridade é
            clampada em 0 — um overkill não gera dano negativo.
        """
        if self.destruido or dano <= 0.0:
            return 0.0

        antes = self.integridade
        self.integridade = max(INTEGRIDADE_MIN, self.integridade - dano)
        return antes - self.integridade

    def restaurar(self, quantidade: float) -> float:
        """Recupera integridade e deixa o implante onde está."""
        if self.destruido or quantidade <= 0.0:
            return 0.0

        antes = self.integridade
        self.integridade = min(INTEGRIDADE_MAX, self.integridade + quantidade)
        return self.integridade - antes

    def limpar(self, cura: float = 0.0) -> float:
        """
        Remove o implante e devolve só um resto de integridade.

        Sem zumbi não há o que limpar. O host deixa de ser porta e sai da botnet.
        """
        if self.destruido or not self.zumbificado:
            return 0.0

        self.zumbificado = False
        if cura <= 0.0:
            return 0.0

        antes = self.integridade
        self.integridade = min(INTEGRIDADE_MAX, self.integridade + cura)
        return self.integridade - antes

    def reforcar(self, quantidade: float) -> float:
        """Aumenta a criptografia (ação de defesa). Retorna o quanto somou."""
        if quantidade <= 0.0:
            return 0.0

        antes = self.criptografia
        self.criptografia += quantidade
        return self.criptografia - antes
