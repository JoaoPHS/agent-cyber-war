# USA vs Russia agent cyber war

Two sides, four agents, one cyber war. The USA and Russia have the same strength. They just spend it in different ways.

The USA tries to cut off one valuable target and stay on it until it falls. Russia spreads the hit across the network, so the score drops in several places at once. Short wars tend to favor that spread. Longer ones give the concentrated hits time to actually collapse something.

Run a match and you get a seed number at the top. That number is the whole fight. Same seed, same war. A new run without a seed is a new war.

## Play

```bash
python main.py
```

```bash
python main.py --seed 42
python main.py --turns 40
python main.py --lang pt-br
python main.py --no-color
python main.py --csv
```

`--seed` replays a match. `--turns` changes how long it can last (the default is 25). `--lang pt-br` tells the same war in Brazilian Portuguese; English is the default. `--csv` writes `metrics.csv`.

You need Python 3, plus [Mesa](https://mesa.readthedocs.io/) and NetworkX.

## What you are looking at

Each side owns three nodes: a reserve, a power grid, and a command center. On the board they show up as `USA-FederalReserve`, `USA-PowerGrid-East`, `USA-DefenseCommand`, and the Russian mirrors. A node has three numbers.

- **Integrity**, from 100 down to 0. At 0 it is gone.
- **Cryptography**, the lock. A harder lock is a harder hit. The chance is `45 / (45 + cryptography)`.
- **Strategic value**. Losing the command center hurts the score more than losing the grid.

The score is the sum of `(integrity / 100) × value` on that side's living nodes. If one side loses every node, the other wins immediately. If both are still standing at the turn limit, the higher score wins.

Each side has a defender and an attacker. Every operator gets 50 processing points per turn, and whatever they do not spend is thrown away.

| Action | Cost | What it does |
| --- | --- | --- |
| Attack | 50 | Spends the whole turn on a strike |
| Stanch | 30 | Heals a friendly node and leaves any implant in place |
| Clean | 30 | Pulls the implant out and barely heals. The host stays sealed for a few turns |
| Recon | 50 | Looks at a target's lock and the route one hop around it |
| Botnet | 50 | Russia only. Turns compromised nodes against their owner |

Shooting at a target you have not looked at yet still works. The chance is just worse, about 65% of a shot you have already scouted.

## The two doctrines

Firepower is the same on both sides. `reach × damage multiplier` comes out to 1 either way. The difference is the shape of the hit.

The USA is surgical. The attacker finishes the valuable node that is already hurt. The defender, when they are shooting, presses the next one. They do not both waste the turn on the healthiest host.

Russia is hybrid. One attack can touch up to three nodes, with a third of the damage on each. It rarely deletes a node in one blow. It makes the other side unsure what to save.

## Zombies

A successful Russian hit can leave an implant. That node is a door, not just a wound. Russia can step onto it and reach the living neighbors, even if the border bridge is already down. It is one hop, not the whole network.

The implant does not swing by itself. A Russian defender has to give up their turn and pay for the botnet. Then each zombie hurts itself, harder if it is still healthy.

The American defender does not clean the first scratch. They keep fighting until two implants are in place, which is also when the botnet can switch on. Cleaning removes the door. Stanching only props the node up, and the implant stays.

If a node collapses, its owner hits 50% harder for two turns. That retaliation works for both sides.

## Looking at a lot of matches

Three scripts next to `main.py` are for measuring, not for watching one war.

- `balance.py` runs many matches and shows who wins as the length changes.
- `verify.py` checks the budget, the paid botnet, and whether 25-turn games are still a fair fight.
- `mirror.py` gives both sides the same doctrine, so you can tell a rigged framework from a doctrine that is simply better.
