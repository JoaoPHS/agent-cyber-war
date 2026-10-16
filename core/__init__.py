"""
core
====
Pacote com a arquitetura do simulador de guerra cibernética.

Estrutura
---------
factions.py : Facções (EUA/Rússia) e as doutrinas que criam a assimetria.
nodes.py    : `CyberNode` — ativos de infraestrutura crítica (estado do ambiente).
schedule.py : `AtivacaoSimultanea` — substituto do scheduler removido no Mesa 3.x.
agents.py   : `CyberAgent` — tomadores de decisão com mecânica estocástica.
model.py    : `CyberWarModel` — o modelo que orquestra a partida.
"""

from .agents import AcaoAtaque, AcaoBotnet, AcaoDefesa, AcaoRecon, CyberAgent
from .factions import DOUTRINAS, Doutrina, Faction, doutrina_de, poder_fogo_agregado
from .model import TURNOS_MAX_PADRAO, CyberWarModel
from .nodes import CyberNode
from .schedule import AtivacaoSimultanea

__all__ = [
    "AcaoAtaque",
    "AcaoBotnet",
    "AcaoDefesa",
    "AcaoRecon",
    "AtivacaoSimultanea",
    "CyberAgent",
    "CyberNode",
    "CyberWarModel",
    "Doutrina",
    "DOUTRINAS",
    "Faction",
    "TURNOS_MAX_PADRAO",
    "doutrina_de",
    "poder_fogo_agregado",
]
