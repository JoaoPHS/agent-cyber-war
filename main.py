"""
main.py — ponto de entrada do MVP.
==================================
Roda uma partida de CyberWarModel e imprime a integridade turno a turno.

Uso
---
    python main.py                 # partida nova, seed sorteada
    python main.py --turns 40      # outro limite de turnos
    python main.py --lang pt-br    # a mesma partida, em português
    python main.py --seed 7        # repete a sequência da seed 7
    python main.py --no-color      # saída sem ANSI (terminais antigos)
    python main.py --csv           # exporta as métricas para metrics.csv
"""

from __future__ import annotations

import argparse
import os
import sys

from core import (
    TURNOS_MAX_PADRAO,
    CyberWarModel,
    Faction,
    doutrina_de,
    poder_fogo_agregado,
)
from core.agents import (
    CUSTO_ATACAR,
    CUSTO_BOTNET,
    CUSTO_LIMPAR,
    CUSTO_RECON,
    CUSTO_REPARAR,
    PP_POR_AGENTE,
)
from core.i18n import normalizar, traduzir
from core.terminal import Pintura, configurar_utf8, habilitar_ansi


def _aplicar_cores(
    modelo: CyberWarModel,
    pintura: Pintura,
    verbose_turnos: bool = True,
) -> None:
    """
    Sobrescreve o relatório padrão do modelo com uma versão colorida.

    Mantida fora de `CyberWarModel` de propósito: o modelo continua puro e
    reutilizável em testes, batch runs ou num dashboard Mesa, sem amarras de
    UI. Se preferir, basta `verbose=True` para usar o relatório do modelo.

    `verbose_turnos` controla SÓ o relatório turno a turno. O banner de
    abertura e o resultado final são impressos sempre — `--no-verbose`
    servia para enxugar a saída, não para apagar o desfecho da partida.
    """
    cores = {Faction.USA: pintura.eua, Faction.RUSSIA: pintura.russia}

    def _abertura() -> None:
        d_eua = doutrina_de(Faction.USA)
        d_rus = doutrina_de(Faction.RUSSIA)
        tr = modelo.t

        print("=" * 78)
        print(pintura.negrito(f"  {tr('title')}"))
        print("=" * 78)
        print(f"  {tr('banner.turns'):<15}: {modelo.turnos_max}")
        print(f"  {tr('banner.seed'):<15}: {getattr(modelo, '_seed', None)}")
        print(f"  {tr('banner.roster_label'):<15}: "
              f"{tr('banner.roster', nodes=len(modelo.nos), agents=len(modelo.agente_cyber))}")
        print("-" * 78)
        print(f"  {cores[Faction.USA](f'{modelo.lado(Faction.USA):<6}')} "
              f"{tr('banner.doctrine', name=tr('doctrine.usa'), reach=d_eua.alcance, mult=d_eua.mult_dano, shape=tr('shape.usa'))}")
        print(f"  {cores[Faction.RUSSIA](f'{modelo.lado(Faction.RUSSIA):<6}')} "
              f"{tr('banner.doctrine', name=tr('doctrine.russia'), reach=d_rus.alcance, mult=d_rus.mult_dano, shape=tr('shape.russia'))}")
        for faccao in Faction:
            print(f"              {modelo.lado(faccao):<8} "
                  f"{tr('banner.firepower', power=poder_fogo_agregado(faccao))}")
        print("-" * 78)
        print(f"  {tr('banner.budget', pp=PP_POR_AGENTE)}")
        print(f"  {tr('banner.menu')}")
        print(f"    {tr('action.attack'):<8} {CUSTO_ATACAR} PP   {tr('banner.attack')}")
        print(f"    {tr('action.stanch'):<8} {CUSTO_REPARAR} PP   {tr('banner.stanch')}")
        print(f"    {tr('action.clean'):<8} {CUSTO_LIMPAR} PP   {tr('banner.clean')}")
        print(f"    {tr('action.recon'):<8} {CUSTO_RECON} PP   {tr('banner.recon')}")
        print(f"    {tr('action.botnet'):<8} {CUSTO_BOTNET} PP   {tr('banner.botnet')}")
        print("-" * 78)
        print(f"  {tr('banner.chance')}")
        print(f"    {tr('banner.blind')}")
        print(f"  {tr('banner.balance')}")
        print(f"    {tr('banner.m4')}")
        print(f"    {tr('banner.n1a')}")
        print(f"    {tr('banner.n1b')}")
        print(f"    {tr('banner.n1c')}")
        print("=" * 78)

    def _turno() -> None:
        tr = modelo.t
        print()
        print(pintura.negrito(f">>> {tr('turn.header', turn=modelo.turno)}") + " " + "-" * 56)
        for faccao in Faction:
            nome = cores[faccao](f"{modelo.lado(faccao):<8}")
            print(f"  {nome}")
            for no in modelo.nos_da_faccao(faccao):
                if no.destruido:
                    estado = pintura.alerta(tr("state.collapsed"))
                else:
                    estado = f"{no.integridade_pct:3d}%"
                marca = tr("mark.zombie") if no.zumbificado and not no.destruido else ""
                print(
                    f"    - {modelo.ver(no.nome):<22} {tr('field.integrity')}={estado:>10}   "
                    f"{tr('field.crypto')}={no.criptografia:5.1f}   {tr('field.value')}={no.valor_estrategico}"
                    f"{pintura.alerta(marca) if marca else ''}"
                )
            efeitos = modelo.status_faccao(faccao)
            if efeitos != "—":
                print(f"    {pintura.alerta('>> ' + efeitos)}")

        print(
            f"  {tr('turn.pp')}  "
            f"{cores[Faction.USA](f'{modelo.lado(Faction.USA)} {modelo.pp_gasto[Faction.USA]:3d}')} | "
            f"{cores[Faction.RUSSIA](f'{modelo.lado(Faction.RUSSIA)} {modelo.pp_gasto[Faction.RUSSIA]:3d}')}   "
            f"{tr('turn.budget', pp=PP_POR_AGENTE)}"
        )

        eua = modelo.pontuacao(Faction.USA)
        rus = modelo.pontuacao(Faction.RUSSIA)
        print(
            f"  {tr('turn.score')}  "
            f"{cores[Faction.USA](f'{modelo.lado(Faction.USA)} {eua:5.2f}')} | "
            f"{cores[Faction.RUSSIA](f'{modelo.lado(Faction.RUSSIA)} {rus:5.2f}')}"
        )

        if modelo._eventos:
            print(f"  {tr('turn.events')}")
            for evento in sorted(modelo._eventos):
                print(f"    * {evento}")

    def _resultado() -> None:
        tr = modelo.t
        print()
        print("=" * 74)
        print(pintura.negrito(f"  {tr('end.title')}"))
        print("=" * 74)
        print(f"  {tr('end.reason')} : {pintura.alerta(modelo.motivo_fim)}")
        print(f"  {tr('end.turns')} : {modelo.turno}")

        eua = modelo.pontuacao(Faction.USA)
        rus = modelo.pontuacao(Faction.RUSSIA)
        print(f"  {tr('end.score')}  {cores[Faction.USA](f'{modelo.lado(Faction.USA)} {eua:5.2f}')} | "
              f"{cores[Faction.RUSSIA](f'{modelo.lado(Faction.RUSSIA)} {rus:5.2f}')}")

        if modelo.vencedor is None:
            print(f"  {tr('end.result')} : {pintura.alerta(tr('end.tie_label'))}")
        else:
            cor = cores[modelo.vencedor]
            print(f"  {tr('end.winner')} : {cor(pintura.negrito(modelo.lado(modelo.vencedor)))}")
        print("=" * 74)

    modelo._imprimir_abertura = _abertura   # type: ignore[method-assign]
    modelo._imprimir_resultado = _resultado # type: ignore[method-assign]
    if verbose_turnos:
        modelo._imprimir_turno = _turno     # type: ignore[method-assign]
    else:
        # `--no-verbose`: suprime só o relatório por turno. `run()` ainda
        # chama `_imprimir_resultado` no fim, então o desfecho continua
        # visível — é o que a ajuda da flag promete.
        modelo._imprimir_turno = lambda: None  # type: ignore[method-assign]


def _exportar_csv(modelo: CyberWarModel, caminho: str) -> None:
    """Grava as métricas do DataCollector num CSV para análise posterior."""
    df = modelo.datacollector.get_model_vars_dataframe()
    df.to_csv(caminho, index_label=modelo.t("csv.step"))
    print(f"\n  {modelo.t('csv.written', path=os.path.abspath(caminho))}")


def _idioma_pedido(argv: list[str] | None) -> str:
    """Lê --lang antes do parser, para a própria ajuda sair no idioma certo."""
    args = list(sys.argv[1:] if argv is None else argv)
    for i, arg in enumerate(args):
        if arg in ("--lang", "--idioma") and i + 1 < len(args):
            return normalizar(args[i + 1])
        if arg.startswith("--lang=") or arg.startswith("--idioma="):
            return normalizar(arg.split("=", 1)[1])
    return "en"


def _parser(idioma: str) -> argparse.ArgumentParser:
    def ajuda(chave: str, **valores) -> str:
        return traduzir(idioma, chave, **valores)

    parser = argparse.ArgumentParser(description=ajuda("help.description"))
    parser.add_argument("--turns", type=int, default=None,
                        help=ajuda("help.turns", default=TURNOS_MAX_PADRAO))
    parser.add_argument("--seed", type=int, default=None, help=ajuda("help.seed"))
    parser.add_argument("--lang", "--idioma", default="en", metavar="LANG",
                        choices=("en", "pt", "pt-br", "pt_br"),
                        help=ajuda("help.lang"))
    parser.add_argument("--no-color", action="store_true", help=ajuda("help.no_color"))
    parser.add_argument("--no-verbose", action="store_true", help=ajuda("help.no_verbose"))
    parser.add_argument("--csv", action="store_true", help=ajuda("help.csv"))
    return parser


def main(argv: list[str] | None = None) -> int:
    configurar_utf8()  # antes de qualquer print, senão os acentos viram '?'
    args = _parser(_idioma_pedido(argv)).parse_args(argv)

    usar_ansi = (not args.no_color) and sys.stdout.isatty() and habilitar_ansi()
    pintura = Pintura(usar_ansi)

    # Construímos silenciosamente para poder instalar os relatórios coloridos
    # ANTES do primeiro print — senão o banner de abertura sairia sem cor.
    modelo = CyberWarModel(
        rng=args.seed,
        turnos_max=args.turns if args.turns is not None else TURNOS_MAX_PADRAO,
        verbose=False,
        idioma=normalizar(args.lang),
    )
    _aplicar_cores(modelo, pintura, verbose_turnos=not args.no_verbose)

    # Banner e resultado sempre; `verbose` do modelo fica True para que
    # `run()` imprima o desfecho no fim (ver `_aplicar_cores`).
    modelo._imprimir_abertura()
    modelo.verbose = True
    modelo.run()

    if args.csv:
        _exportar_csv(modelo, "metrics.csv")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
