"""
core/agents.py
==============
`CyberAgent` — unidade ofensiva/defensiva controlada pela simulação.

O agente executa um ciclo DECISÃO -> APLICAÇÃO por turno, herdado da
semântica de duas fases de `AtivacaoSimultanea`:

    step()    -> avalia o estado, escolhe UMA ação do menu e resolve o
                 resultado ESTOCÁSTICO. **Não muta o ambiente aqui.**
    advance() -> materializa a intenção registrada em `self._intencoes`
                 e DEBITA o custo da ação do orçamento individual.

Manter a mutação fora de `step()` é o que garante que os dois lados do
conflito enxerguem exatamente o mesmo estado ao decidir.

ORÇAMENTO DE PROCESSAMENTO (PP) — SIMETRIA RÍGIDA
-------------------------------------------------
Cada agente possui **individualmente** `PP_POR_AGENTE` Pontos de
Processamento por turno. O orçamento **não acumula**: é repostonão
integramente a cada `step()`. Não existe pool compartilhado por facção —
o PP é propriedade do agente, e o modelo apenas agrega os valores para
o relatório.

O menu de ações tem custo FIXO e é idêntico para as duas facções:

    ATACAR   -> `CUSTO_ATACAR`  (consome 100% do orçamento)
    ESTANCAR -> `CUSTO_REPARAR` (sobe integridade; o implante fica)
    LIMPAR   -> `CUSTO_LIMPAR`  (tira o implante; quase não cura)
    RECON    -> `CUSTO_RECON`   (revela fechadura e a rota de um salto)
    BOTNET   -> `CUSTO_BOTNET`  (substitui a ação normal; só Rússia)

A rigidez é literal: `step()` só agenda uma ação se `custo <= self.pp`.
Como `CUSTO_ATACAR == PP_POR_AGENTE`, **atacar impede qualquer outra
ação no mesmo turno — para ambas as facções, sem exceção**. Não há
"estouro silencioso" nem turno perdido: se a ação não cabe no
orçamento, ela simplesmente não é escolhida e o agente cai para a
próxima opção do menu.

MECÂNICA ESTOCÁSTICA — disputa de dados SIMÉTRICA
--------------------------------------------------
        P(sucesso) = A_base / (A_base + D_base)

    A_base = `PODER_ATAQUE_BASE`  (idêntico para toda a facção)
    D_base = criptografia CRUA do nó alvo (idêntica para todo atacante)

Os pesos base são **estruturalmente iguais** para EUA e Rússia: nenhum
modificador de doutrina entra nesta fórmula. A doutrina e a retaliação
[M4] atuam apenas **depois do roll**, sobre o DANO. Atacar um nó que a
facção ainda não reconheceu multiplica a chance por `PENALIDADE_CEGO`.
Esta separação é o que impede que uma facção seja punida duas vezes
(menos dano **e** menos chance de acertar).

O dano, quando a invasão passa, cresce com a margem de vantagem e flutua
aleatoriamente — dois inimigos idênticos nunca causam o mesmo dano.

>>> EXPANSÃO — árvore de tecnologia
    `poder_ataque` e o bônus de doutrina são pontos naturais de upgrade.
    Adicione `self.nivel_tech` e aplique multiplicadores progressivos
    (ex.: `poder * (1 + 0.1 * self.nivel_tech)`).

>>> EXPANSÃO — economia de processamento
    O orçamento já é por agente. Para criar escassez real, troque
    `PP_POR_AGENTE` por uma propriedade do modelo
    (`modelo.processamento[faccao]`) e deduza infraestrutura destruída:
    perder nós reduz a capacidade de atacar, acelerando o colapso de
    quem já está enfraquecido.
"""

from __future__ import annotations

from dataclasses import dataclass

from mesa import Agent

from .factions import Faction, doutrina_de
from .nodes import CyberNode

# --- Parâmetros de combate --------------------------------------------------
# Todos os "magic numbers" vivem aqui, num bloco só, para facilitar
# experimentação (e para serem substituídos por uma tabela de tech no futuro).

# Limites do orçamento e do gatilho defensivo.
#
# `LIMIAR_CRITICO` é o parâmetro mais sensível do jogo — e por isso foi
# calibrado por medição, não por palpite. Ver `economia.py`.
#
# A economia do conflito é esta:
#     reparo  30 PP  ->  `BONUS_DEFESA_INTEGRIDADE` de integridade
#     ataque  50 PP  ->  ~12 de dano esperado
# Ou seja, o reparo rende ~1,5 por PP contra ~0,24 do ataque: é ~6x mais
# eficiente. Consequência direta: assim que uma facção entra em modo
# defensivo, ela desfaz o dano com folga — e o resultado passa a depender
# de QUEM DISPARA O LIMIAR PRIMEIRO.
#
# Com o limiar em 40 a defesa disparava fora de hora e a taxa de vitória
# ficava caótica. Com estancar separado de limpar, reconhecimento e a porta
# do zumbi, o limiar em 35.5 devolve o cruzamento para perto de 25 turnos.
LIMIAR_CRITICO = 35.5        # abaixo disso o agente defensor entra em ação
PODER_ATAQUE_BASE = 45.0     # peso base de ATAQUE — idêntico p/ toda a facção
DOSE_DANO = 0.55             # fração do poder de ataque convertida em dano
VAR_DANO = (0.75, 1.25)      # faixa de flutuação estocástica do dano
BONUS_DEFESA_INTEGRIDADE = 44.0   # integridade restaurada ao estancar
BONUS_LIMPEZA = 8.0               # cura mínima ao tirar o implante
BONUS_DEFESA_CRIPTO = 12.0        # criptografia adicionada por ação defensiva
FAIXA_DEFESA = (0.85, 1.15)       # variância do efeito defensivo
PENALIDADE_CEGO = 0.65            # multiplicador da chance se o alvo é desconhecido

# --- Orçamento de Pontos de Processamento (PP) ------------------------------
# SIMETRIA PURA: custos idênticos para EUA e Rússia. O que muda entre as
# facções é COMO o dano é distribuído (doutrina), nunca QUANTO custa agir.

PP_POR_AGENTE = 50   # orçamento individual por turno — NÃO acumula
CUSTO_ATACAR = 50    # consome o orçamento inteiro -> nada mais no turno
CUSTO_REPARAR = 30   # estancar: sobram 20 PP, que são DESPREZADOS no fim do turno
CUSTO_LIMPAR = 30    # tirar o implante custa o mesmo que estancar
CUSTO_RECON = 50     # um turno inteiro olhando fechadura e rota
CUSTO_BOTNET = 50    # abandona a ação normal para acionar a botnet

# [N1] Botnet: um agente russo só ativa os zumbis se abrir mão da própria
# ação. Com `CUSTO_BOTNET == PP_POR_AGENTE`, ativar a botnet é tão caro
# quanto atacar — nunca é um "bônus grátis".
LIMIAR_BOTNET = 2    # nº mínimo de zumbis para a opção entrar no menu
DURACAO_IMUNIDADE = 5  # turnos em que o host limpo não aceita outro implante
DANO_ZUMBI = 8.0     # dano-base de cada zumbi por ativação (garantido)
VAR_ZUMBI = (0.85, 1.15)  # variância do dano de zumbi

# [M4] Retaliação "Dead Man's Switch" — SIMÉTRICA: dispara para a facção que
# PERDER um nó, seja ela quem for. Uma mecânica que só uma facção pudesse
# acionar seria uma alavanca de mão única, e não um balanceamento.
MULT_RETALIACAO_DANO = 1.50  # +50% de dano
DURACAO_RETALIACAO = 2       # turnos de duração do bônus

# Papéis táticos — ver `CyberAgent.papel`.
PAPEL_DEFENSOR = "defensor"
PAPEL_OFENSIVO = "ofensivo"


# --------------------------------------------------------------------------
# Intenções — o "registro de ordens de batalha" gerado na fase de decisão.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class AcaoAtaque:
    """Dano destinado a um alvo específico, já resolvido estocasticamente."""

    alvo: CyberNode
    dano: float


@dataclass(frozen=True)
class AcaoDefesa:
    """Ordem de defesa para um nó aliado. `limpar` tira o implante."""

    alvo: CyberNode
    restaurar: float = 0.0
    reforcar: float = 0.0
    limpar: bool = False


@dataclass(frozen=True)
class AcaoRecon:
    """Um turno olhando a fechadura de um alvo e a rota dos vizinhos vivos."""

    alvo: CyberNode


@dataclass(frozen=True)
class AcaoBotnet:
    """
    Ordem para acionar a botnet [N1].

    Os nós zumbificados atacam a **própria facção** que os detém — é assim
    que uma botnet funciona: infraestrutura comprometida virada contra o
    dono. A ação custa `CUSTO_BOTNET` e substitui o ataque/reparo do agente
    no turno. `zumbis` é uma cópia congelada da lista no momento da decisão,
    para que a fase de aplicação opere sobre o mesmo conjunto que a IA viu.
    """

    zumbis: tuple[CyberNode, ...] = ()


class CyberAgent(Agent):
    """
    Agente cibernético alinhado a uma facção.

    Attributes
    ----------
    nome : str
        Identificador legível para os logs.
    faccao : Faction
        Alinhamento político/doutrinário do agente.
    poder_ataque : float
        Potência de fogo bruta. Entra **apenas** no cálculo do dano; a
        acurácia usa o peso base simétrico `PODER_ATAQUE_BASE`.
    pp : int
        Pontos de Processamento **individuais** disponíveis neste turno.
        Reposto a cada `step()`. Nunca negativo: a rigidez do menu impede
        agendar uma ação que não cabe no saldo.
    """

    def __init__(
        self,
        model,
        nome: str,
        faccao: Faction,
        poder_ataque: float = PODER_ATAQUE_BASE,
        papel: str = PAPEL_OFENSIVO,
    ) -> None:
        # O Mesa 3.x registra o agente automaticamente em `model.agents`
        # dentro do `Agent.__init__` — não há `unique_id` manual a criar.
        super().__init__(model)

        self.nome = nome
        self.faccao = faccao
        self.poder_ataque = poder_ataque

        # --- Papel tático --------------------------------------------------
        # Por que existe papel e não "todos decidem igual": com decisão
        # idêntica, um nó em perigo convertia TODOS os agentes da facção em
        # reparadores e zerava o ataque por turnos seguidos. Isso castigava
        # quase só quem concentra dano (o dano espalhado raramente derruba
        # um nó abaixo do limiar), criando uma espiral de morte assimétrica.
        # Um defensor + um ofensivo por facção mantém a pressão ofensiva
        # viva mesmo sob ataque — e o arranjo é idêntico dos dois lados.
        self.papel = papel

        # --- Orçamento individual -----------------------------------------
        # Propriedade do AGENTE, não da facção. Reposto em `step()`.
        self.pp: int = PP_POR_AGENTE

        # Custo da ação escolhida e seu rótulo — consumidos por `advance()`
        # para débito e relatório. `0` significa "nenhuma ação agendada".
        self._custo_acao: int = 0
        self._rotulo_acao: str = self.model.t("tag.idle")

        # Intenções decididas na fase 1, aplicadas na fase 2.
        # Uma lista (e não um item) é o que permite à doutrina híbrida da
        # Rússia atingir VÁRIOS nós no mesmo ciclo, como exige o design.
        self._intencoes: list[AcaoAtaque | AcaoDefesa | AcaoBotnet] = []

        # Histórico simples, útil para inspeção/debug e para expansões futuras
        # (aprendizado por reforço, por exemplo).
        self.ataques_realizados = 0
        self.sucessos = 0

        # Ação executada no turno anterior (auditoria). Ver `advance()`.
        self.ultima_acao: str = self.model.t("tag.idle")
        self.ultimo_custo: int = 0

    # -- consultas ---------------------------------------------------------

    @property
    def doutrina(self):
        """Doutrina da facção deste agente (fonte única do bônus assimétrico)."""
        return doutrina_de(self.faccao)

    def __repr__(self) -> str:  # pragma: no cover - apenas conveniência
        return f"<CyberAgent {self.nome} [{self.faccao.value}] PP={self.pp}>"

    # -- FASE 1: decisão ---------------------------------------------------

    def step(self) -> None:
        """
        Escolhe UMA ação do menu, respeitando o orçamento individual.

        Menu em ordem de prioridade — cada ramo testa o custo contra o
        saldo ANTES de agendar:

            1. ESTANCAR (30 PP) — defensor, se a facção está em risco
            2. LIMPAR   (30 PP) — defensor, se há implante aliado e nada crítico
            3. BOTNET   (50 PP) — só Rússia, só com >= `LIMIAR_BOTNET` zumbis
            4. RECON    (50 PP) — defensor, se ainda há alvo no escuro
            5. ATACAR   (50 PP) — se há alvo alcançável (cego se não reconhecido)
            6. ESTANCAR (30 PP) — fallback, para não ficar ocioso
            7. OCioso   ( 0 PP) — nenhuma ação coube no orçamento

        O ramo 1 é restrito ao `PAPEL_DEFENSOR`: só um agente por facção
        abandona o ataque para defender, de modo que a facção nunca perde a
        pressão ofensiva por completo — ver `CyberAgent.__init__`.
        """
        self._intencoes = []
        self._custo_acao = 0
        self._rotulo_acao = self.model.t("tag.idle")

        # --- [R1] Reposição do orçamento individual -----------------------
        # Não cumulativo: todo turno começa com o valor integral.
        self.pp = PP_POR_AGENTE

        modelo = self.model
        aliados = modelo.nos_da_faccao(self.faccao)

        # Sem aliados = sem o que defender; e sem inimigos, não há o que
        # atacar — ambos os casos deixam o agente ocioso neste turno.
        if not aliados:
            return

        # 1) ESTANCAR — exclusiva do papel defensor. Nó crítico vem antes
        #    de limpar: manter o host de pé deixa o implante lá.
        if self.papel == PAPEL_DEFENSOR and self._faccao_em_risco(aliados):
            if self._pode_pagar(CUSTO_REPARAR):
                self._agendar_defesa(aliados)
            return

        # 1b) LIMPAR — com um implante só, o defensor continua na luta.
        #     A partir de `LIMIAR_BOTNET` zumbis a porta já sustenta a botnet,
        #     e o defensor gasta o turno expulsando o mais valioso.
        if (
            self.papel == PAPEL_DEFENSOR
            and self._contar_zumbis(aliados) >= LIMIAR_BOTNET
            and self._pode_pagar(CUSTO_LIMPAR)
        ):
            self._agendar_limpar(aliados)
            return

        # 2) BOTNET [N1] — exclusiva do papel defensor, e SÓ quando não há
        #    nada a defender.
        #
        #    Por que está encaixada aqui, e não como uma opção comparada ao
        #    ataque: se a IA escolhesse entre "atacar" e "acionar botnet"
        #    comparando dano esperado, o limiar entre as duas curvas seria
        #    íngreme — um ajuste mínimo nos parâmetros ligaria ou desligaria
        #    a botnet de um turno para o outro, deslocando a taxa de vitória
        #    em dezenas de pontos percentuais.
        #
        #    Encaixada no tempo ocioso do defensor, a mecânica vira
        #    CONTÍNUA e comparável por construção: quando a facção está
        #    segura, os EUA recebem um SEGUNDO ataque e a Rússia recebe um
        #    ataque + a botnet. O equilíbrio passa a depender só de
        #    `DANO_ZUMBI` valer mais ou menos o que vale um ataque — não de
        #    um limiar.
        zumbis = tuple(modelo.zumbis_vivos())
        if (
            self.papel == PAPEL_DEFENSOR
            and not self._faccao_em_risco(aliados)
            and self.faccao is Faction.RUSSIA
            and len(zumbis) >= LIMIAR_BOTNET
            and self._pode_pagar(CUSTO_BOTNET)
        ):
            self._intencoes = [AcaoBotnet(zumbis)]
            self._custo_acao = CUSTO_BOTNET
            self._rotulo_acao = self.model.t("tag.botnet")
            return

        # 2b) RECON — o defensor gasta o turno olhando. O ofensivo atira
        #     mesmo no escuro e paga a penalidade de chance.
        if self.papel == PAPEL_DEFENSOR and self._pode_pagar(CUSTO_RECON):
            alvo_recon = self._alvo_de_recon()
            if alvo_recon is not None:
                self._intencoes = [AcaoRecon(alvo_recon)]
                self._custo_acao = CUSTO_RECON
                self._rotulo_acao = self.model.t("tag.scouted")
                return

        # 3) ATACAR: gate duro — precisa dos 50 PP inteiros, senão a ação
        #    nem é considerada. Como o custo iguala o orçamento, atacar
        #    descarta qualquer outra ação no turno.
        alvos = self._selecionar_alvos()
        if alvos and self._pode_pagar(CUSTO_ATACAR):
            self._intencoes = self._resolver_ataque(alvos)
            self._custo_acao = CUSTO_ATACAR
            self._rotulo_acao = (
                self.model.t("tag.attacked") if self._intencoes else self.model.t("tag.attack_missed")
            )
            return

        # 4) FALLBACK defensivo: ainda cabe um reparo, então não fica parado.
        if self._pode_pagar(CUSTO_REPARAR):
            self._agendar_defesa(aliados)

    def _pode_pagar(self, custo: int) -> bool:
        """Gate rígido de orçamento. Nenhuma ação é agendada sem saldo."""
        return self.pp >= custo

    def _agendar_defesa(self, aliados: list[CyberNode]) -> None:
        """Agenda uma ação defensiva e registra seu custo fixo."""
        ordem = self._decidir_defesa(aliados)
        if ordem is not None:
            self._intencoes = [ordem]
            self._custo_acao = CUSTO_REPARAR
            self._rotulo_acao = (
                self.model.t("tag.stanched") if ordem.restaurar > 0.0 else self.model.t("tag.reinforced")
            )

    def _contar_zumbis(self, aliados: list[CyberNode]) -> int:
        """Quantos nós aliados vivos ainda carregam implante."""
        return sum(1 for n in aliados if n.zumbificado and not n.destruido)

    def _agendar_limpar(self, aliados: list[CyberNode]) -> None:
        """Tira o implante do zumbi mais valioso. A cura é só um resto."""
        vivos = [n for n in aliados if n.zumbificado and not n.destruido]
        if not vivos:
            return
        alvo = max(vivos, key=lambda n: (n.valor_estrategico, -n.integridade))
        variacao = self.random.uniform(*FAIXA_DEFESA)
        self._intencoes = [AcaoDefesa(alvo=alvo, restaurar=BONUS_LIMPEZA * variacao, limpar=True)]
        self._custo_acao = CUSTO_LIMPAR
        self._rotulo_acao = self.model.t("tag.cleaned")

    def _alvo_de_recon(self) -> CyberNode | None:
        """O inimigo alcançável de maior valor que esta facção ainda não viu."""
        desconhecidos = [
            n for n in self._inimigos_alcancaveis()
            if not self.model.conhece(self.faccao, n)
        ]
        if not desconhecidos:
            return None
        return max(desconhecidos, key=lambda n: n.valor_estrategico)

    def _faccao_em_risco(self, aliados: list[CyberNode]) -> bool:
        """True se algum nó aliado estiver na faixa crítica de integridade."""
        return any(not n.destruido and n.integridade <= LIMIAR_CRITICO for n in aliados)

    def _decidir_defesa(self, aliados: list[CyberNode]) -> AcaoDefesa | None:
        """
        Escolhe o que reparar: integridade ou criptografia.

        Heurística simples e legível:
            * existe nó abaixo de 50% -> restaura o mais crítico
            * senão                    -> reforça a criptografia do nó mais valioso
        """
        vivos = [n for n in aliados if not n.destruido]
        if not vivos:
            return None

        criticos = [n for n in vivos if n.integridade < 50.0]
        if criticos:
            alvo = min(criticos, key=lambda n: n.integridade)
            variacao = self.random.uniform(*FAIXA_DEFESA)
            reparo = BONUS_DEFESA_INTEGRIDADE * variacao
            return AcaoDefesa(alvo=alvo, restaurar=reparo)

        alvo = max(vivos, key=lambda n: n.valor_estrategico)
        variacao = self.random.uniform(*FAIXA_DEFESA)
        reforco = BONUS_DEFESA_CRIPTO * variacao
        return AcaoDefesa(alvo=alvo, reforcar=reforco)

    def _selecionar_alvos(self) -> list[CyberNode]:
        """
        Escolhe os nós inimigos-alvo, respeitando a topologia do grafo.

        A regra usa `modelo.grafo` (networkx) para restringir os alvos aos nós
        **alcançáveis** por uma rota de nós vivos. Sem essa rota, não há
        ataque — um alvo isolado por colapsos fica fora do menu.
        """
        doutrina = self.doutrina
        inimigos = self._inimigos_alcancaveis()

        if not inimigos:
            return []

        # Cirúrgico fecha o alvo de maior valor que já está mais ferido.
        # O ofensivo faz esse golpe. O defensor, quando ataca, pressiona o
        # próximo alvo — os dois não gastam o turno no mesmo host.
        # Híbrido espalha e começa pelos mais vulneráveis.
        if doutrina.alcance == 1:
            inimigos.sort(key=lambda n: (-n.valor_estrategico, n.integridade))
            if self.papel != PAPEL_OFENSIVO and len(inimigos) > 1:
                inimigos = inimigos[1:] + inimigos[:1]
        else:
            inimigos.sort(key=lambda n: n.integridade)

        # O alcance nunca pode exceder o número de alvos disponíveis.
        return inimigos[: doutrina.alcance]

    def _inimigos_alcancaveis(self) -> list[CyberNode]:
        """Inimigos vivos com rota a partir da rede própria ou de um zumbi-porta."""
        modelo = self.model
        return [
            n
            for n in modelo.nos_alcancaveis(self.faccao)
            if n.faccao is not self.faccao and not n.destruido
        ]

    def _resolver_ataque(self, alvos: list[CyberNode]) -> list[AcaoAtaque]:
        """
        Resolve a disputa estocástica de CADA alvo e devolve as intenções.

        A chance por alvo é `A_base / (A_base + D_base)` com pesos
        **idênticos para as duas facções** — ver documentação do módulo.
        Como o roll é independente por alvo, um ataque híbrido da Rússia pode
        acertar parte dos alvos e errar o resto: é assim que a assimetria se
        manifesta na prática, sem nunca tocar na acurácia.

        Returns
        -------
        list[AcaoAtaque]
            Uma intenção por alvo que caiu. Pode ser vazia (turno perdido).
        """
        modelo = self.model
        intencoes: list[AcaoAtaque] = []

        for alvo in alvos:
            # ------------------------------------------------------------------
            # ROLL SIMÉTRICO — pesos base iguais para ambas as facções
            # ------------------------------------------------------------------
            # `PODER_ATAQUE_BASE` é constante global e `alvo.criptografia` é a
            # barreira crua: nenhum dos dois varia com doutrina. Os
            # modificadores assimétricos ([M4] retaliação, doutrina) entram
            # DEPOIS, apenas sobre o dano.
            p_base = PODER_ATAQUE_BASE / (PODER_ATAQUE_BASE + alvo.criptografia)
            cego = not modelo.conhece(self.faccao, alvo)
            p_sucesso = p_base * PENALIDADE_CEGO if cego else p_base

            self.ataques_realizados += 1

            if self.random.random() < p_sucesso:
                self.sucessos += 1

                # Dano: cresce com a margem de vitória e flutua estocasticamente.
                # `mult_dano_efetivo` é a ÚNICA porta de entrada da assimetria.
                margem = 0.6 + 0.4 * p_base
                ruido = self.random.uniform(*VAR_DANO)
                mult = modelo.mult_dano_efetivo(alvo, self.faccao)
                dano = self.poder_ataque * DOSE_DANO * margem * ruido * mult

                intencoes.append(AcaoAtaque(alvo=alvo, dano=dano))

        return intencoes

    # -- FASE 2: aplicação --------------------------------------------------

    def advance(self) -> None:
        """
        Materializa TODAS as intenções registradas em `step()` e debita o PP.

        Iterar a lista é o que dá sentido à doutrina híbrida: o agente russo
        aplica dano a `alcance` nós distintos num mesmo ciclo, cada um com
        dano diluído (`mult_dano < 1`). O agente estadunidense, com
        `alcance == 1`, itera uma única vez com dano concentrado.

        O débito é incondicional e anterior à aplicação: como `step()` só
        agendou ações que cabiam no saldo, `self.pp` nunca fica negativo, e
        os 20 PP remanescentes de um reparo são simplesmente descartados.
        """
        intencoes = self._intencoes
        self._intencoes = []

        # --- Débito rígido do orçamento individual -------------------------
        custo = self._custo_acao
        self._custo_acao = 0
        self.pp -= custo
        self.model.registrar_gasto(self.faccao, custo)

        rotulo = self._rotulo_acao
        self._rotulo_acao = self.model.t("tag.idle")

        # Histórico persistente da última ação — o `_rotulo_acao` é zerado
        # acima, então sem isto não haveria como auditar o que cada agente
        # fez depois que o turno terminou (relatórios, testes, diagnóstico).
        self.ultima_acao = rotulo
        self.ultimo_custo = custo

        for intencao in intencoes:
            if isinstance(intencao, AcaoAtaque):
                self._aplicar_ataque(intencao)
            elif isinstance(intencao, AcaoDefesa):
                self._aplicar_defesa(intencao)
            elif isinstance(intencao, AcaoBotnet):
                self._aplicar_botnet(intencao)
            elif isinstance(intencao, AcaoRecon):
                self._aplicar_recon(intencao)

        # Relatório de gasto — deixa o consumo visível e auditável por turno.
        self.model.registrar_evento(self.model.t(
            "event.spent", name=self.nome, tag=rotulo, cost=custo, left=self.pp,
        ))

    def _aplicar_ataque(self, intencao: AcaoAtaque) -> None:
        dano_aplicado = intencao.alvo.receber_dano(intencao.dano)

        # Registra ANTES do early-return de baixo: se o alvo já estava morto,
        # o dano aplicado é 0 e o pedido INTEIRO foi desperdiçado — e é
        # justamente essa perda que o relatório precisa tornar visível.
        self.model.registrar_dano(
            self.faccao, aplicado=dano_aplicado, pedido=intencao.dano
        )

        # Efeito zero é possível e esperado com ativação simultânea: o
        # alvo podia estar de pé na fase de decisão e ter caído na fase
        # de aplicação.
        if dano_aplicado <= 0.0:
            return

        self.model.registrar_evento(self.model.t(
            "event.hit",
            name=self.model.ver(intencao.alvo.nome),
            damage=dano_aplicado,
        ))
        # Acertar revela a fechadura daquele nó. A vizinhança continua no escuro
        # até um reconhecimento.
        self.model.revelar(self.faccao, intencao.alvo)

        # [N1] Toda infecção bem-sucedida da Rússia sobre um nó dos EUA o
        # converte em zumbi. Ele só passa a agir se um agente russo pagar
        # `CUSTO_BOTNET` para acioná-lo.
        if self.faccao is Faction.RUSSIA:
            self.model.registrar_infeccao(intencao.alvo)

        # [M4] o colapso de um nó puxa o Dead Man's Switch da facção dona.
        if intencao.alvo.destruido:
            self.model.registrar_colapso(intencao.alvo)

    def _aplicar_defesa(self, intencao: AcaoDefesa) -> None:
        if intencao.limpar:
            cura = intencao.alvo.limpar(intencao.restaurar)
            intencao.alvo.imune_ate = self.model.turno + DURACAO_IMUNIDADE
            self.model.registrar_evento(self.model.t(
                "event.cleaned",
                name=self.model.ver(intencao.alvo.nome),
                heal=cura,
                turns=DURACAO_IMUNIDADE,
            ))
            return
        if intencao.restaurar > 0.0:
            recuperado = intencao.alvo.restaurar(intencao.restaurar)
            if recuperado > 0.0:
                self.model.registrar_evento(self.model.t(
                    "event.stanched",
                    name=self.model.ver(intencao.alvo.nome),
                    heal=recuperado,
                ))
        if intencao.reforcar > 0.0:
            somado = intencao.alvo.reforcar(intencao.reforcar)
            if somado > 0.0:
                self.model.registrar_evento(self.model.t(
                    "event.reinforced",
                    name=self.model.ver(intencao.alvo.nome),
                    crypto=somado,
                ))

    def _aplicar_botnet(self, acao: AcaoBotnet) -> None:
        """
        [N1] Aciona a botnet: cada zumbi causa dano garantido ao nó da
        **própria facção** que o detém.

        O roll não é usado de propósito — o ativo já está comprometido, então
        a "chance de sucesso" é 100%. O que regula o poder da mecânica é o
        custo: o agente russo abriu mão de um ataque inteiro (50 PP) para
        isto, então a botnet é uma ALTERNATIVA ao ataque, nunca um extra
        grátis.
        """
        modelo = self.model

        # Marca a ativação para o relatório do turno.
        modelo.botnet_ativa = True

        for zumbi in acao.zumbis:
            # Zumbi ainda infectado: o dano escala com a integridade restante.
            # Estancar não tira o implante. Só `CyberNode.limpar` fecha a porta.
            carga = zumbi.integridade / 100.0
            dano = DANO_ZUMBI * carga * self.random.uniform(*VAR_ZUMBI)
            aplicado = zumbi.receber_dano(dano)

            # O dano é da botnet russa e entra na mesma telemetria do ataque
            # direto — assim o relatório mostra o total real que a Rússia
            # converteu em dano, não só o que passou pelo roll.
            modelo.registrar_dano(
                Faction.RUSSIA, aplicado=aplicado, pedido=dano
            )

            if aplicado <= 0.0:
                continue

            modelo.registrar_evento(modelo.t(
                "event.botnet",
                name=modelo.ver(zumbi.nome),
                damage=aplicado,
            ))

            if zumbi.destruido:
                modelo.registrar_colapso(zumbi)

    def _aplicar_recon(self, acao: AcaoRecon) -> None:
        """Revela a fechadura do alvo e a rota até os vizinhos ainda vivos."""
        novos = self.model.revelar(self.faccao, acao.alvo, vizinhos=True)
        nomes = [self.model.ver(nome) for nome in novos] if novos else [self.model.ver(acao.alvo.nome)]
        self.model.registrar_evento(self.model.t("event.scouted", names=", ".join(nomes)))
