"""
core/model.py
=============
`CyberWarModel` — orquestra a partida.

Responsabilidades:
  * montar o ambiente (nós de infraestrutura crítica) e o **grafo de rede**;
  * instanciar os agentes cibernéticos de cada facção;
  * rodar o loop de turnos com ativação simultânea;
  * aplicar a regra de parada ÚNICA (Colapso Sistêmico ou limite de turnos);
  * coletar métricas via `DataCollector` (pronto para visualização futura).

GRAFO DE REDE
-------------
A topologia é um `networkx.Graph` cujos nós são os **nomes** dos `CyberNode`.
Duas famílias de arestas:
    * "interno"    — links dentro de uma mesma facção (LAN / backbone);
    * "transfronteiriço" — rotas de ataque entre EUA e Rússia.

O grafo não é enfeite: ele **restringe quais alvos um agente pode alcançar**
(veja `CyberAgent._selecionar_alvos`). Sem rota, não há ataque.

ORÇAMENTO DE PROCESSAMENTO
--------------------------
O PP é propriedade de **cada agente** (`CyberAgent.pp`), não da facção.
O modelo NÃO mantém um pool que vete ações — ele apenas agrega os gastos
para o relatório. A rigidez orçamentária vive em `CyberAgent.step()`.

>>> EXPANSÃO — propagação lateral
    Arestas podem carregar pesos (`latencia`, `confiabilidade`). Uma infecção
    bem-sucedida poderia então se propagar para vizinhos com probabilidade
    que decai com a distância no grafo — use BFS limitado a partir do nó
    atingido.

>>> EXPANSÃO — economia de processamento
    Hoje o orçamento é fixo e igual para todos (`PP_POR_AGENTE`). Para criar
    escassez real, derive o orçamento da infraestrutura viva da facção
    (`sum(n.valor_estrategico for n nos próprios)`), de modo que perder nós
    reduza a capacidade de agir e acelere o colapso de quem já está em
    desvantagem.
"""

from __future__ import annotations

import networkx as nx
from mesa import Model
from mesa.datacollection import DataCollector

from .i18n import nome_visivel, normalizar, traduzir
from .agents import (
    DURACAO_RETALIACAO,
    MULT_RETALIACAO_DANO,
    PAPEL_DEFENSOR,
    PAPEL_OFENSIVO,
    PP_POR_AGENTE,
    CyberAgent,
)
from .factions import Faction, doutrina_de
from .nodes import CyberNode
from .schedule import AtivacaoSimultanea

# --- Configuração da partida ----------------------------------------------
# Ponto único de verdade do cenário. Troque aqui para testar outros desenhos
# de conflito sem tocar em nenhuma lógica.

# Duração padrão da partida. Ao atingir `turnos_max` sem que nenhum lado tenha
# colapsado, o vencedor é quem tiver maior pontuação estratégica (`pontuacao`).
#
# =================== NOTA DE BALANCEAMENTO ===================
# O sistema de orçamento por AGENTE (50 PP, custos fixos) tornou os pesos de
# combate estruturalmente simétricos:
#     * o ROLL usa pesos idênticos para as duas facções;
#     * o PODER DE FOGO AGREGADO é igual: EUA 1.0 x 1 alvo = 1.0 e
#       Rússia 0.333 x 3 alvos = 1.0;
#     * custos de ação idênticos (50 atacar / 30 reparar).
#
# Verificado com `mirror.py`: com as duas facções iguais (ambas Surgical)
# a taxa de vitória dos EUA fica em torno de 50% — o framework é justo. A
# assimetria que sobra é doutrinária, não estrutural.
#
# A calibragem final NÃO foi feita nos pesos de combate (o invariante
# acima permanece intacto), mas na ECONOMIA de reparo:
#     reparo  30 PP  ->  44 de integridade   ~= 1,47 por PP
#     ataque  50 PP  ->  ~12 de dano esperado ~= 0,24 por PP
# O reparo rende ~6x mais que o ataque, então quem entra em modo defensivo
# desfaz o dano com folga — e o resultado depende de QUEM DISPARA O LIMIAR
# PRIMEIRO (`LIMIAR_CRITICO`, em core/agents.py).
#
# `python balance.py` mostra o vencedor alternando com a duração da partida,
# com o padrão de 25 turnos no ponto de cruzamento. O gatilho é
# `LIMIAR_CRITICO` = 35.5.
# Use `python balance.py` and `python verify.py` before changing the numbers.
# =============================================================
TURNOS_MAX_PADRAO = 25

AGENTES_POR_FACCAO = 2      # exigido: >= 2 por facção
NOS_POR_FACCAO = 3          # exigido: >= 2 por facção

# Cenário nominal: (nome, facção, criptografia, valor estratégico)
# A criptografia varia para criar alvos "caros" e "baratos" de invadir.
# Os dois lados são espelhados — qualquer assimetria vem da doutrina, nunca
# da disposição dos ativos.
CENARIO: list[tuple[str, Faction, float, float]] = [
    # --- USA ---
    ("USA-FederalReserve",  Faction.USA,    28.0, 3.0),
    ("USA-PowerGrid-East",  Faction.USA,    18.0, 2.5),
    ("USA-DefenseCommand",  Faction.USA,    34.0, 3.0),
    # --- Russia ---
    ("RUS-MoscowExchange",  Faction.RUSSIA, 28.0, 3.0),
    ("RUS-PowerGrid-West",  Faction.RUSSIA, 18.0, 2.5),
    ("RUS-CommandCenter",   Faction.RUSSIA, 34.0, 3.0),
]

# Papéis táticos: cada facção tem exatamente UM defensor e UM ofensivo.
# O arranjo é espelhado — ver `CyberAgent.__init__` para o porquê de existir.
AGENTES: list[tuple[str, Faction, float, str]] = [
    ("USA-Cypher-01", Faction.USA,    45.0, PAPEL_DEFENSOR),
    ("USA-Cypher-02", Faction.USA,    45.0, PAPEL_OFENSIVO),
    ("RUS-Viper-01",  Faction.RUSSIA, 45.0, PAPEL_DEFENSOR),
    ("RUS-Viper-02",  Faction.RUSSIA, 45.0, PAPEL_OFENSIVO),
]


class CyberWarModel(Model):
    """
    Modelo principal do conflito cibernético EUA x Rússia.

    Parameters
    ----------
    rng : int | None
        Seed reprodutível. Passe o mesmo valor para obter exatamente a mesma
        sequência de eventos estocásticos.
    turnos_max : int
        Limite duro de turnos. Atingido o limite sem colapso, vence quem
        tiver maior pontuação estratégica (ver `pontuacao`).
    verbose : bool
        Se True, imprime o relatório de integridade a cada turno.
    idioma : str
        `en` (padrão) ou `pt-br`. Só muda o texto da partida.
    """

    def __init__(
        self,
        rng: int | None = 42,
        turnos_max: int = TURNOS_MAX_PADRAO,
        verbose: bool = True,
        idioma: str = "en",
    ) -> None:
        # Mesa 3.x: `seed=` está deprecado; use `rng=`.
        super().__init__(rng=rng)

        self.turnos_max = turnos_max
        self.verbose = verbose
        self.idioma = normalizar(idioma)

        self.turno: int = 0
        self.fim: bool = False
        self.vencedor: Faction | None = None
        self.fim_codigo: str = ""
        self._fim_faccao: Faction | None = None

        # Buffer de eventos do turno corrente, consumido pelo relatório.
        self._eventos: list[str] = []

        # --- Orçamento de processamento -----------------------------------
        # Só AGREGADO de relatório. A decisão de gastar é de cada agente
        # (`CyberAgent.pp`) — o modelo nunca veta uma ação por saldo.
        self.pp_gasto: dict[Faction, int] = {f: 0 for f in Faction}

        # --- Telemetria de combate ----------------------------------------
        # Acumulados por turno, zerados em `step()`. Permitem auditar se as
        # duas facções estão CONVERTENDO o mesmo orçamento no mesmo dano —
        # ver `registrar_dano` para a diferença entre aplicado e desperdiçado.
        self.dano_causado: dict[Faction, float] = {f: 0.0 for f in Faction}
        self.dano_desperdicado: dict[Faction, float] = {f: 0.0 for f in Faction}

        # --- Estado do balanceamento dinâmico -----------------------------
        # Tudo aqui é ESTADO GLOBAL do conflito, não propriedade de um agente.
        #
        # [M4] Turnos restantes do bônus de retaliação. SIMÉTRICO: dispara
        #      para QUALQUER facção que perder um nó.
        self.retaliacao: dict[Faction, int] = {f: 0 for f in Faction}
        self._retaliacao_este_turno: dict[Faction, bool] = {f: False for f in Faction}

        # [N1] Botnet. `botnet_ativa` é um flag de relatório, zerado a cada
        # turno: os zumbis só causam dano quando um agente russo paga
        # `CUSTO_BOTNET` para acioná-los. A porta que o implante abre na
        # rede vale enquanto `zumbificado` for True, sem pagar de novo.
        self.botnet_ativa: bool = False

        # Inteligência por facção: nomes de nós cuja criptografia e vizinhança
        # já foram vistas. Atacar fora desta lista sofre penalidade de cegueira.
        self.intel: dict[Faction, set[str]] = {f: set() for f in Faction}

        # --- Ambiente ----------------------------------------------------
        self.nos: list[CyberNode] = [
            CyberNode(nome=nome, faccao=faccao, criptografia=crypto, valor_estrategico=valor)
            for nome, faccao, crypto, valor in CENARIO
        ]
        self.grafo: nx.Graph = self._construir_grafo()

        # --- Agentes -----------------------------------------------------
        self.agente_cyber: list[CyberAgent] = [
            CyberAgent(model=self, nome=nome, faccao=faccao, poder_ataque=poder, papel=papel)
            for nome, faccao, poder, papel in AGENTES
        ]

        # --- Escalonamento ----------------------------------------------
        # Substituto de mesa.time.SimultaneousActivation (ver core/schedule.py).
        self.schedule = AtivacaoSimultanea(self)

        # --- Métricas ----------------------------------------------------
        # DataCollector do Mesa: base pronta para plotar curvas depois.
        self.datacollector = DataCollector(
            model_reporters={
                "health_USA": lambda m: m.pontuacao(Faction.USA),
                "health_Russia": lambda m: m.pontuacao(Faction.RUSSIA),
                "nodes_destroyed": lambda m: len([n for n in m.nos if n.destruido]),
                "turn": lambda m: m.turno,
                "pp_spent_USA": lambda m: m.pp_gasto[Faction.USA],
                "pp_spent_Russia": lambda m: m.pp_gasto[Faction.RUSSIA],
                "zombies": lambda m: len(m.zumbis_vivos()),
                "botnet": lambda m: int(m.botnet_ativa),
            }
        )
        self.datacollector.collect(self)

        if self.verbose:
            self._imprimir_abertura()

    # ------------------------------------------------------------------
    # Construção do ambiente
    # ------------------------------------------------------------------
    def _construir_grafo(self) -> nx.Graph:
        """
        Monta a topologia de rede.

        Arestas "interno" ligam os nós de cada facção em cadeia (backbone).
        Uma aresta "transfronteiriça" por par de facções cria uma rota de
        ataque. Um nó colapsado sai do caminho: sem ponte viva, o alvo
        do outro lado fica inalcançável.
        """
        grafo = nx.Graph()

        for faccao in Faction:
            proprios = [n.nome for n in self.nos_da_faccao(faccao)]
            for a, b in zip(proprios, proprios[1:]):
                grafo.add_edge(a, b, tipo="interno")

        # Rotas de ataque: EUA <-> Rússia.
        eua = [n.nome for n in self.nos_da_faccao(Faction.USA)]
        rus = [n.nome for n in self.nos_da_faccao(Faction.RUSSIA)]
        grafo.add_edge(eua[0], rus[0], tipo="transfronteirico")
        grafo.add_edge(eua[1], rus[1], tipo="transfronteirico")

        return grafo

    # ------------------------------------------------------------------
    # API usada pelos agentes
    # ------------------------------------------------------------------
    def nos_da_faccao(self, faccao: Faction) -> list[CyberNode]:
        """Todos os nós detidos por `faccao` (inclui os destruídos)."""
        return [n for n in self.nos if n.faccao is faccao]

    def nos_alcancaveis(self, faccao: Faction) -> list[CyberNode]:
        """
        Nós alcançáveis a partir da rede viva de `faccao`.

        O caminho só atravessa nós operacionais. Um colapso deixa de ser
        origem de rota e também deixa de servir de ponte. Um zumbi inimigo
        é uma porta de um salto: o atacante alcança esse nó e os vizinhos
        vivos dele, mesmo com a ponte de fronteira caída.
        """
        vivos = [n.nome for n in self.nos if not n.destruido and n.nome in self.grafo]
        rede = self.grafo.subgraph(vivos)
        nomes_alcancaveis: set[str] = set()
        for no in self.nos_da_faccao(faccao):
            if not no.destruido and no.nome in rede:
                nomes_alcancaveis |= nx.node_connected_component(rede, no.nome)
        for no in self.nos:
            if (
                no.zumbificado
                and not no.destruido
                and no.faccao is not faccao
                and no.nome in rede
            ):
                nomes_alcancaveis.add(no.nome)
                nomes_alcancaveis |= set(rede.neighbors(no.nome))

        return [n for n in self.nos if n.nome in nomes_alcancaveis]

    def conhece(self, faccao: Faction, no: CyberNode) -> bool:
        """True se `faccao` já viu a fechadura deste nó."""
        return no.nome in self.intel[faccao]

    def revelar(self, faccao: Faction, alvo: CyberNode, vizinhos: bool = False) -> list[str]:
        """
        Marca `alvo` como visto por `faccao`.

        Com `vizinhos=True` (reconhecimento), a vizinhança viva entra junto:
        olhar um nó confirma a rota de um salto.
        """
        nomes = {alvo.nome}
        if vizinhos and not alvo.destruido and alvo.nome in self.grafo:
            vivos = [n.nome for n in self.nos if not n.destruido and n.nome in self.grafo]
            rede = self.grafo.subgraph(vivos)
            if alvo.nome in rede:
                nomes |= set(rede.neighbors(alvo.nome))
        novos = sorted(nomes - self.intel[faccao])
        self.intel[faccao] |= nomes
        return novos

    def t(self, chave: str, **valores) -> str:
        """Texto da partida no idioma escolhido."""
        return traduzir(self.idioma, chave, **valores)

    def ver(self, nome: str) -> str:
        """Nome do nó como a partida deve mostrá-lo."""
        return nome_visivel(self.idioma, nome)

    def lado(self, faccao: Faction) -> str:
        """Rótulo curto do lado, no idioma da partida."""
        chave = "side.usa" if faccao is Faction.USA else "side.russia"
        return self.t(chave)

    def registrar_evento(self, texto: str) -> None:
        """Acumula um evento do turno para o relatório."""
        self._eventos.append(texto)

    def registrar_gasto(self, faccao: Faction, valor: int) -> None:
        """
        Acumula o gasto de PP de `faccao` **neste turno**, só para o relatório.

        Esta função não veta nem limita nada: a rigidez orçamentária é
        imposta por `CyberAgent.step()`, que só agenda ações que cabem no
        saldo do agente. Aqui apenas registramos o consumo agregado, para que
        o relatório mostre que ambos os lados gastaram recursos.

        Parameters
        ----------
        faccao : Faction
            Facção que gastou os PP.
        valor : int
            Quantidade de PP gasta pela ação.
        """
        self.pp_gasto[faccao] += valor

    def registrar_dano(self, faccao: Faction, aplicado: float, pedido: float) -> None:
        """
        Acumula o dano de `faccao` no turno, separando o que pegou do que
        foi desperdiçado em overkill.

        Overkill é a diferença entre o dano PEDIDO e o dano APLICADO: atingir
        um nó com 5 de integridade usando um golpe de 20 joga 15 no lixo. Ele
        existe porque `receber_dano` satura em 0 (não há dano negativo).

        Medir isto separadamente é o que permite enxergar a assimetria
        estrutural entre as doutrinas: a híbrida espalha dano e quase nunca
        desperdiça, enquanto a cirúrgica concentra e desperdiça sempre que
        escolhe um alvo já moribundo.
        """
        self.dano_causado[faccao] += aplicado
        self.dano_desperdicado[faccao] += max(0.0, pedido - aplicado)

    # ------------------------------------------------------------------
    # Matemática do combate
    # ------------------------------------------------------------------
    def mult_dano_efetivo(self, alvo: CyberNode, faccao: Faction) -> float:
        """
        Multiplicador de dano de um ataque de `faccao` contra `alvo`.

        **Esta é a única porta de entrada da assimetria.** O ROLL de acerto é
        estruturalmente igual para as duas facções (ver
        `CyberAgent._resolver_ataque`); tudo que diferencia EUA e Rússia —
        a doutrina e a retaliação [M4] — atua aqui, sobre o resultado.

        A doutrina distribui o DANO, nunca a ACURÁCIA: se `mult_dano`
        entrasse também na chance de acerto, a facção híbrida seria punida
        em dobro (menos dano **e** menos chance de acertar).

        `alvo` fica na assinatura por causa do `>>> EXPANSÃO` de módulos de
        defesa específicos (IDS, honeypots), que reduziriam o dano recebido.
        """
        mult = doutrina_de(faccao).mult_dano

        # [M4] Retaliação simétrica: a facção que PERDEU um nó dispara o
        # Dead Man's Switch e causa +50% de dano por `DURACAO_RETALIACAO`
        # turnos. Aplicar só a uma facção seria uma alavanca de mão única.
        if self.retaliacao.get(faccao, 0) > 0:
            mult *= MULT_RETALIACAO_DANO

        return mult

    def status_faccao(self, faccao: Faction) -> str:
        """Resumo curto dos efeitos ativos sobre a facção, para o relatório."""
        partes: list[str] = []
        if self.retaliacao.get(faccao, 0) > 0:
            partes.append(self.t("status.retaliation", turns=self.retaliacao[faccao]))
        zumbis = [n for n in self.zumbis_vivos() if n.faccao is faccao]
        if zumbis:
            n = len(zumbis)
            partes.append(self.t(
                "status.botnet",
                state=self.t("botnet.active" if self.botnet_ativa else "botnet.idle"),
                n=n,
                word=self.t("word.zombie" if n == 1 else "word.zombies"),
            ))
        return " · ".join(partes) if partes else "—"

    def zumbis_vivos(self) -> list[CyberNode]:
        """
        [N1] Nós comprometidos ainda operacionais — o combustível da botnet.

        Um zumbi destruído não tem o que oferecer, então é descartado da
        lista. Enquanto a botnet não for paga e ativada por um agente russo,
        estes nós continuam apenas **inativos**, drenando o lado que os detém
        apenas como alvos potenciais.
        """
        return [n for n in self.nos if n.zumbificado and not n.destruido]

    def registrar_infeccao(self, alvo: CyberNode) -> None:
        """
        [N1] Marca `alvo` como zumbificado.

        Chamado toda vez que um agente russo consegue dano real sobre um nó.
        A infecção fica até uma limpeza. Enquanto dura, o nó é porta para
        dentro da rede dele. O dano da botnet só sai se um agente russo
        pagar `CUSTO_BOTNET`.
        """
        if alvo.zumbificado or self.turno <= alvo.imune_ate:
            return
        alvo.zumbificado = True
        self.registrar_evento(self.t("event.zombie", name=self.ver(alvo.nome)))

    # ------------------------------------------------------------------
    # Registro de efeitos (chamado pelos agentes durante a aplicação)
    # ------------------------------------------------------------------
    def registrar_colapso(self, alvo: CyberNode) -> None:
        """
        Puxa o Dead Man's Switch quando um nó é destruído [M4].

        **SIMÉTRICO**: dispara para a facção dona do nó que caiu, seja ela
        quem for. Uma retaliação que só uma das facções pudesse acionar seria
        uma alavanca de mão única — quem já está ganhando receberia mais
        dano, invertendo o sentido da palavra "retaliação".

        Se outro nó colapsar durante o bônus, a duração é reforçada até
        `DURACAO_RETALIACAO`, sem acumular multiplicadores.
        """
        faccao = alvo.faccao

        self.retaliacao[faccao] = max(self.retaliacao[faccao], DURACAO_RETALIACAO)
        self._retaliacao_este_turno[faccao] = True
        self.registrar_evento(
            self.t(
                "event.switch",
                name=self.ver(alvo.nome),
                side=self.lado(faccao),
                turns=DURACAO_RETALIACAO,
            )
        )

    def _atualizar_retaliacao(self) -> None:
        """
        [M4] Decrementa o contador da retaliação de cada facção.

        O decremento é suprimido no turno em que o gatilho foi puxado, para
        que o bônus dure exatamente `DURACAO_RETALIACAO` turnos COMPLETOS de
        combate, e não `DURACAO_RETALIACAO - 1`.
        """
        for faccao in Faction:
            if self.retaliacao[faccao] > 0 and not self._retaliacao_este_turno[faccao]:
                self.retaliacao[faccao] -= 1
            self._retaliacao_este_turno[faccao] = False

    # ------------------------------------------------------------------
    # Loop principal
    # ------------------------------------------------------------------
    def step(self) -> None:
        """
        Executa um turno completo, se a partida ainda não terminou.

        Ordem das fases — importante para a coerência causal das mecânicas:

            1. limpa os marcadores de turno (eventos, PP gasto, botnet);
            2. decide e aplica as ações (ativação simultânea), cada agente
               gastando do **seu próprio** orçamento de PP;
            3. decrementa a retaliação ([M4]);
            4. aplica a regra ÚNICA de fim de jogo (`_verificar_fim`);
            5. coleta métricas.
        """
        if self.fim:
            return

        self._eventos = []
        self.turno += 1

        # Zera os marcadores de turno; os agentes os repovoam em `advance()`.
        self.pp_gasto = {f: 0 for f in Faction}
        self.dano_causado = {f: 0.0 for f in Faction}
        self.dano_desperdicado = {f: 0.0 for f in Faction}
        self.botnet_ativa = False

        # Ativação simultânea: decidir (todos) -> aplicar (todos).
        self.schedule.step()

        self._atualizar_retaliacao()     # [M4] -> contagem regressiva por facção

        self._verificar_fim()
        self.datacollector.collect(self)

        if self.verbose:
            self._imprimir_turno()

    def run(self) -> None:
        """Roda a partida até o limite de turnos ou até o Colapso Sistêmico."""
        while not self.fim:
            self.step()

        if self.verbose:
            self._imprimir_resultado()

    # ------------------------------------------------------------------
    # Regra de fim de jogo — ÚNICA fonte de verdade
    # ------------------------------------------------------------------
    def _verificar_fim(self) -> None:
        """
        Encerra a partida por Colapso Sistêmico ou por limite de turnos.

        Há **uma só** função decidindo o fim, e ela SEMPRE seta `self.fim`.
        Duas verificações independentes (uma para colapso, outra para
        pontuação) já causaram um bug em que a partida ignorava o limite e
        rodava dezenas de turnos além do previsto — mantidas separadas, elas
        se sobrescreviam silenciosamente.

        Ordem:
            1. Colapso — todos os nós de uma facção destruídos. Vence a outra.
            2. Limite de turnos — vence quem tiver maior pontuação
               estratégica (`pontuacao`).
        """
        if self.fim:
            return

        # 1) Colapso Sistêmico
        for faccao in Faction:
            restantes = [n for n in self.nos_da_faccao(faccao) if not n.destruido]
            if not restantes:
                self.fim = True
                self.fim_codigo = "collapse"
                self.vencedor = faccao.inimiga
                self._fim_faccao = faccao
                return

        # 2) Limite de turnos -> decisão por pontuação
        if self.turno >= self.turnos_max:
            self.fim = True
            eua = self.pontuacao(Faction.USA)
            rus = self.pontuacao(Faction.RUSSIA)
            if abs(eua - rus) < 1e-9:
                self.fim_codigo = "tie"
                self.vencedor = None
            else:
                self.fim_codigo = "limit"
                self.vencedor = Faction.USA if eua > rus else Faction.RUSSIA

    def pontuacao(self, faccao: Faction) -> float:
        """
        Saúde estratégica agregada da facção.

            soma( (integridade/100) * valor_estrategico ) sobre os nós próprios

        É a métrica que decide a vitória quando o tempo se esgota sem que
        nenhum lado tenha colapsado — assim perder um nó valioso pesa mais
        que perder vários baratos.
        """
        return round(sum(n.saude_ponderada for n in self.nos_da_faccao(faccao)), 2)

    @property
    def motivo_fim(self) -> str:
        """Por que a partida acabou, no idioma escolhido."""
        if self.fim_codigo == "collapse":
            return self.t("end.collapse", side=self.lado(self._fim_faccao))
        if self.fim_codigo == "tie":
            return self.t("end.tie", turn=self.turno)
        if self.fim_codigo == "limit":
            return self.t("end.limit", turns=self.turnos_max)
        return ""

    # ------------------------------------------------------------------
    # Relatório em terminal
    # ------------------------------------------------------------------
    def _imprimir_abertura(self) -> None:
        print("=" * 74)
        print(f"  {self.t('title')}")
        print("=" * 74)
        print(f"  {self.t('banner.turns')} : {self.turnos_max}")
        print(f"  {self.t('banner.seed')} : {getattr(self, '_seed', None)} "
              f"({self.t('banner.seed_note')})")
        print("-" * 74)
        for faccao in Faction:
            d = doutrina_de(faccao)
            forma = "usa" if faccao is Faction.USA else "russia"
            print(f"  {self.lado(faccao):<8} "
                  f"{self.t('banner.doctrine', name=self.t('doctrine.' + forma), reach=d.alcance, mult=d.mult_dano, shape=self.t('shape.' + forma))}")
        print("-" * 74)
        print(f"  {self.t('banner.budget', pp=PP_POR_AGENTE)}")
        print(f"  {self.t('banner.menu')}")
        print(f"    {self.t('action.attack'):<7} 50 PP  {self.t('banner.attack')}")
        print(f"    {self.t('action.stanch'):<7} 30 PP  {self.t('banner.stanch')}")
        print(f"    {self.t('action.clean'):<7} 30 PP  {self.t('banner.clean')}")
        print(f"    {self.t('action.recon'):<7} 50 PP  {self.t('banner.recon')}")
        print(f"    {self.t('action.botnet'):<7} 50 PP  {self.t('banner.botnet')}")
        print("-" * 74)
        print(f"  {self.t('banner.chance')}")
        print(f"    {self.t('plain.blind')}")
        print("=" * 74)

    def _imprimir_turno(self) -> None:
        print(f"\n>>> {self.t('turn.header', turn=self.turno)}")
        for faccao in Faction:
            print(f"  {self.lado(faccao)}")
            for no in self.nos_da_faccao(faccao):
                estado = self.t("state.collapsed") if no.destruido else f"{no.integridade_pct:3d}%"
                marca = self.t("mark.zombie") if no.zumbificado and not no.destruido else ""
                print(
                    f"    - {self.ver(no.nome):<22} {self.t('field.integrity')}={estado:>10}  "
                    f"{self.t('field.crypto')}={no.criptografia:5.1f}  "
                    f"{self.t('field.value')}={no.valor_estrategico}{marca}"
                )
            efeitos = self.status_faccao(faccao)
            if efeitos != "—":
                print(f"    >> {efeitos}")
        print(
            f"  {self.t('turn.pp')}  "
            f"{self.lado(Faction.USA)} {self.pp_gasto[Faction.USA]:3d} | "
            f"{self.lado(Faction.RUSSIA)} {self.pp_gasto[Faction.RUSSIA]:3d}  "
            f"{self.t('turn.budget', pp=PP_POR_AGENTE)}"
        )
        print(f"  {self.t('turn.score')}  {self.lado(Faction.USA)}: {self.pontuacao(Faction.USA):5.2f} | "
              f"{self.lado(Faction.RUSSIA)}: {self.pontuacao(Faction.RUSSIA):5.2f}")

        if self._eventos:
            print(f"  {self.t('plain.events')}")
            for evento in sorted(self._eventos):
                print(f"    * {evento}")

    def _imprimir_resultado(self) -> None:
        print("\n" + "=" * 74)
        print(f"  {self.t('end.title')}")
        print("=" * 74)
        print(f"  {self.t('end.reason')} : {self.motivo_fim}")
        print(f"  {self.t('end.turns')} : {self.turno}")
        if self.vencedor is None:
            print(f"  {self.t('end.result')}: {self.t('plain.tie')}")
        else:
            print(f"  {self.t('end.winner')} : {self.lado(self.vencedor)}")
        print(f"  {self.t('plain.score')}  {self.lado(Faction.USA)}: {self.pontuacao(Faction.USA):5.2f} | "
              f"{self.lado(Faction.RUSSIA)}: {self.pontuacao(Faction.RUSSIA):5.2f}")
        print("=" * 74)
