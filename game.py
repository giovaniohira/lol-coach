"""Live Client Data + lembretes a partir do estado real da partida."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

LIVE = "https://127.0.0.1:2999/liveclientdata/allgamedata"
CTX = ssl._create_unverified_context()

DRAGON_FIRST = 5 * 60
DRAGON_RESPAWN = 5 * 60
ELDER_RESPAWN = 6 * 60
GRUBS_SPAWN = 8 * 60
GRUBS_DESPAWN = 14 * 60 + 45
HERALD_SPAWN = 15 * 60
HERALD_DESPAWN = 19 * 60 + 45
BARON_FIRST = 20 * 60
BARON_RESPAWN = 6 * 60
MINIONS = 90
CANNON_FIRST = 150  # 2:30, depois a cada 90s
CANNON_EVERY = 90
LANING_END = 20 * 60
STALL_LANE = 8
STALL_JG = 12


def poll() -> dict | None:
    try:
        with urllib.request.urlopen(LIVE, context=CTX, timeout=0.8) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def game_time(data: dict) -> float:
    return float(data.get("gameData", {}).get("gameTime") or 0)


def is_rift(data: dict) -> bool:
    gd = data.get("gameData") or {}
    return gd.get("mapNumber") == 11 or gd.get("mapName") == "Map11"


def events(data: dict) -> list[dict]:
    return list((data.get("events") or {}).get("Events") or [])


def clock(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60}:{t % 60:02d}"


def _names(p: dict) -> set[str]:
    return {n.lower() for n in (p.get("riotId"), p.get("riotIdGameName"), p.get("summonerName")) if n}


def me_row(data: dict) -> dict | None:
    ap = data.get("activePlayer") or {}
    mine = _names(ap)
    for p in data.get("allPlayers") or []:
        if _names(p) & mine:
            return p
    return None


def _items(p: dict) -> list[str]:
    out = []
    for it in p.get("items") or []:
        name = it.get("displayName")
        if name and name != "Empty":
            out.append(name)
    return out


def compact(data: dict) -> dict:
    """Estado curto pra mandar no LLM — o que está acontecendo agora, não teoria."""
    ap = data.get("activePlayer") or {}
    stats = ap.get("championStats") or {}
    me = me_row(data) or {}
    t = game_time(data)
    hp, hpmax = stats.get("currentHealth") or 0, stats.get("maxHealth") or 0
    allies, enemies = [], []
    my_team = me.get("team")
    for p in data.get("allPlayers") or []:
        row = {
            "champ": p.get("championName"),
            "lane": p.get("position") or None,
            "lv": p.get("level"),
            "dead": p.get("isDead"),
            "respawn": round(p.get("respawnTimer") or 0, 1) if p.get("isDead") else 0,
            "kda": f"{(s := p.get('scores') or {}).get('kills', 0)}/{s.get('deaths', 0)}/{s.get('assists', 0)}",
            "cs": (p.get("scores") or {}).get("creepScore"),
            "items": _items(p),
            "spells": [
                (p.get("summonerSpells") or {}).get("summonerSpellOne", {}).get("displayName"),
                (p.get("summonerSpells") or {}).get("summonerSpellTwo", {}).get("displayName"),
            ],
        }
        (allies if p.get("team") == my_team else enemies).append(row)
    ev = events(data)
    recent = [e for e in ev if t - float(e.get("EventTime") or 0) <= 90]
    r = ap.get("abilities") or {}
    return {
        "tempo": clock(t),
        "modo": (data.get("gameData") or {}).get("gameMode"),
        "eu": {
            "champ": me.get("championName"),
            "lane": me.get("position"),
            "lv": ap.get("level") or me.get("level"),
            "ouro": int(ap.get("currentGold") or 0),
            "hp": f"{int(hp)}/{int(hpmax)}",
            "hp_pct": round(100 * hp / hpmax) if hpmax else None,
            "morto": bool(me.get("isDead")),
            "ult": (r.get("R") or {}).get("displayName"),
            "ult_lv": (r.get("R") or {}).get("abilityLevel") or 0,
            "runa": ((ap.get("fullRunes") or {}).get("keystone") or {}).get("displayName"),
        },
        "aliados": allies,
        "inimigos": enemies,
        "eventos_90s": [
            {k: e[k] for k in e if k in ("EventName", "EventTime", "KillerName", "VictimName", "DragonType", "Stolen", "TurretKilled")}
            for e in recent
        ],
        "objetivos": {k: v for k, v in describe_objectives(data).items()},
        "sumidos": WATCH.labels(data),
        "proxima_cannon": (lambda eta: None if eta is None else ("agora" if eta <= 1 else f"em {clock(eta)}"))(cannon_eta(t)),
    }


def describe_objectives(data: dict) -> dict[str, str]:
    if not is_rift(data):
        return {}
    t = game_time(data)
    ev = events(data)
    out: dict[str, str] = {}
    for name, eta, up in _objective_etas(t, ev):
        if up and eta <= 0:
            extra = ""
            if name == "grubs":
                extra = f" (saem {clock(GRUBS_DESPAWN)})"
            elif name == "arauto":
                extra = f" (sai {clock(HERALD_DESPAWN)})"
            out[name] = "no mapa" + extra
        elif eta > 0:
            out[name] = f"em {clock(eta)}"
    return out


def _last_time(ev: list[dict], name: str) -> float | None:
    times = [float(e["EventTime"]) for e in ev if e.get("EventName") == name]
    return max(times) if times else None


def _objective_etas(t: float, ev: list[dict]) -> list[tuple[str, float, bool]]:
    """(nome, segundos_ate_spawn, ja_esta_no_mapa). eta<=0 e up=True = vivo agora."""
    rows = []
    dragons = [e for e in ev if e.get("EventName") == "DragonKill"]
    last_d = _last_time(ev, "DragonKill")
    elder = any(str(e.get("DragonType") or "").lower() == "elder" for e in dragons)
    delay = ELDER_RESPAWN if elder or len(dragons) >= 4 else DRAGON_RESPAWN
    if last_d is None:
        eta = DRAGON_FIRST - t
        rows.append(("dragão", eta, eta <= 0))
    else:
        eta = last_d + delay - t
        rows.append(("dragão" if not (elder or len(dragons) >= 4) else "elder", eta, eta <= 0))

    hordes = sum(1 for e in ev if e.get("EventName") == "HordeKill")
    if hordes < 3 and t < GRUBS_DESPAWN:
        eta = GRUBS_SPAWN - t
        rows.append(("grubs", eta, t >= GRUBS_SPAWN))

    if _last_time(ev, "HeraldKill") is None and t < HERALD_DESPAWN:
        eta = HERALD_SPAWN - t
        rows.append(("arauto", eta, t >= HERALD_SPAWN))

    last_b = _last_time(ev, "BaronKill")
    if t < BARON_FIRST:
        rows.append(("barão", BARON_FIRST - t, False))
    elif last_b is None:
        rows.append(("barão", 0, True))
    else:
        eta = last_b + BARON_RESPAWN - t
        rows.append(("barão", eta, eta <= 0))
    return rows


def cannon_eta(t: float) -> float | None:
    if t < MINIONS:
        return None
    if t < CANNON_FIRST:
        return CANNON_FIRST - t
    rem = (t - CANNON_FIRST) % CANNON_EVERY
    return 0.0 if rem < 1 else CANNON_EVERY - rem


class CsWatch:
    """CS parou de subir = saiu da lane/jungle. Não é fog of war; é o sinal que o client dá."""

    def __init__(self):
        self.last: dict[str, tuple[int, float, str, bool]] = {}
        self.farmed: set[str] = set()

    def observe(self, data: dict) -> None:
        t = game_time(data)
        me = me_row(data) or {}
        my_team = me.get("team")
        for p in data.get("allPlayers") or []:
            if p.get("team") == my_team:
                continue
            key = p.get("championName") or p.get("summonerName") or "?"
            cs = int((p.get("scores") or {}).get("creepScore") or 0)
            lane = (p.get("position") or "").upper()
            dead = bool(p.get("isDead"))
            prev = self.last.get(key)
            if dead:
                self.last[key] = (cs, t, lane, True)
                continue
            if prev is None:
                if cs > 0:
                    self.farmed.add(key)
                self.last[key] = (cs, t, lane, False)
            elif cs > prev[0]:
                self.farmed.add(key)
                self.last[key] = (cs, t, lane, False)
            else:
                self.last[key] = (prev[0], prev[1], lane or prev[2], False)

    def missing(self, data: dict, min_stall: float = STALL_LANE) -> list[dict]:
        t = game_time(data)
        out = []
        for key, (cs, t0, lane, dead) in self.last.items():
            if dead or key not in self.farmed:
                continue
            stall = t - t0
            if stall >= min_stall:
                out.append({"champ": key, "lane": lane, "stall": int(stall), "cs": cs})
        return out

    def labels(self, data: dict) -> list[str]:
        self.observe(data)
        return [f"{m['champ']} ({m['lane'] or '?'}, {m['stall']}s sem CS)" for m in self.missing(data)]


WATCH = CsWatch()


class Reminders:
    """Hábitos + relógio do mapa. Sem LLM — tem que sair na hora."""

    def __init__(self, tab_every: float = 45, map_every: float = 28, watch: CsWatch | None = None):
        self.tab_every = tab_every
        self.map_every = map_every
        self.seen_ids: set[int] = set()
        self.obj_said: set[str] = set()
        self.last_tab = -999.0
        self.last_map = -999.0
        self.last_gold = -999.0
        self.last_gank = -999.0
        self.wave_said: set[str] = set()
        self.was_dead = False
        self.watch = watch or WATCH

    def next(self, data: dict) -> list[str]:
        t = game_time(data)
        me = me_row(data) or {}
        ap = data.get("activePlayer") or {}
        lines: list[str] = []

        for e in events(data):
            eid = e.get("EventID")
            if eid in self.seen_ids:
                continue
            self.seen_ids.add(eid)
            line = self._event_line(e, me, data)
            if line:
                lines.append(line)

        dead = bool(me.get("isDead"))
        if dead and not self.was_dead:
            rs = int(me.get("respawnTimer") or 0)
            lines.append(f"Morto. TAB e minimapa. Volta e deixa a wave bater, não choca. Respawn {rs}.")
        self.was_dead = dead

        self.watch.observe(data)
        if is_rift(data) and not dead:
            lines.extend(self._gank_lines(t, me))
            lines.extend(self._wave_lines(t, ap))

        if is_rift(data):
            lines.extend(self._objective_lines(t, events(data)))

        gold = float(ap.get("currentGold") or 0)
        stats = ap.get("championStats") or {}
        hp, hpmax = stats.get("currentHealth") or 0, stats.get("maxHealth") or 0
        hp_pct = (hp / hpmax) if hpmax else 1
        if (
            not dead
            and t - self.last_gold > 90
            and gold >= 1300
            and (gold >= 1800 or hp_pct < 0.4)
        ):
            self.last_gold = t
            lines.append("Ouro pra item. Back se a wave deixar.")

        if t >= MINIONS and not dead:
            if t - self.last_tab >= self.tab_every:
                self.last_tab = t
                lines.append("TAB.")
            elif t - self.last_map >= self.map_every:
                self.last_map = t
                lines.append("Minimapa.")

        return lines

    def _objective_lines(self, t: float, ev: list[dict]) -> list[str]:
        labels = {
            "dragão": "Dragão",
            "elder": "Elder",
            "grubs": "Grubs, lado de cima",
            "arauto": "Arauto",
            "barão": "Barão",
        }
        setup = {
            "dragão": "Prioridade bot e visão no pit.",
            "elder": "Grupo. Não dê Elder de graça.",
            "grubs": "Se a wave permitir, contest.",
            "arauto": "Setup no pit de cima.",
            "barão": "Não fique sozinho. Visão no pit.",
        }
        out = []
        for name, eta, up in _objective_etas(t, ev):
            for sec in (60, 30):
                key = f"{name}:{sec}"
                if 0 < eta <= sec and key not in self.obj_said:
                    self.obj_said.add(key)
                    if eta <= 30:
                        self.obj_said.add(f"{name}:30")
                    out.append(f"{labels[name]} em {int(eta)} segundos. {setup[name]}")
                    break
            key_up = f"{name}:up"
            if up and eta <= 0 and key_up not in self.obj_said and name in ("dragão", "elder", "barão"):
                # só anuncia spawn de objetivo grande uma vez; grubs/arauto já entram no 60/30
                if f"{name}:30" in self.obj_said or f"{name}:60" in self.obj_said:
                    self.obj_said.add(key_up)
        return out

    def _event_line(self, e: dict, me: dict, data: dict) -> str | None:
        name = e.get("EventName")
        mine = _names(me) | _names(data.get("activePlayer") or {})
        killer = (e.get("KillerName") or "").lower()
        us = killer in mine
        if name == "MinionsSpawning":
            return "Minions. Wave."
        if name == "FirstBlood":
            return "First blood seu. Congela e traduz em wave." if us else "First blood deles. Joga mais curto."
        if name == "DragonKill":
            kind = e.get("DragonType") or "dragão"
            steal = str(e.get("Stolen") or "").lower() == "true"
            if steal:
                return f"Steal de {kind}."
            return f"{kind} nosso." if us else f"{kind} deles. Próximo em 5 minutos. TAB."
        if name == "HordeKill" and us:
            return "Grub seu."
        if name == "HeraldKill":
            return "Arauto nosso. Empurra a wave livre." if us else "Arauto deles. Não chuta a wave cega."
        if name == "BaronKill":
            return "Barão nosso. Empurra junto." if us else "Barão deles. Não lute agora. Defende."
        if name == "Ace":
            team = e.get("AcingTeam")
            ours = team and team == me.get("team")
            return "Ace. Empurra ou pega objetivo." if ours else "Levaram ace. Reseta, não x1."
        if name == "InhibKilled":
            return "Inibidor. Empurra a super, TAB nos respawns."
        if name == "InhibRespawningSoon":
            return "Inibidor respawna já. Não overstay."
        if name == "TurretKilled" and us:
            return "Torre. Empurra a próxima wave, não chase."
        if name == "ChampionKill":
            victim = (e.get("VictimName") or "").lower()
            if victim in mine:
                return None
            assisters = [(a or "").lower() for a in (e.get("Assisters") or [])]
            if us or any(a in mine for a in assisters):
                return "Matou. Empurra uma e reseta a wave. Não chase no rio."
        return None

    def _gank_lines(self, t: float, me: dict) -> list[str]:
        if t < 120 or t > LANING_END:
            return []
        my_lane = (me.get("position") or "").upper()
        if my_lane == "JUNGLE":
            return []
        out: list[str] = []
        if 135 <= t <= 170 and "lv3jg" not in self.obj_said:
            self.obj_said.add("lv3jg")
            out.append("Janela de gank level 3. Joga mais curto, olha o rio.")
        if t - self.last_gank < 22:
            return out
        # ponytail: missing() só precisa do relógio; o CS já está no watch
        miss = self.watch.missing({"gameData": {"gameTime": t}}, STALL_LANE)
        jg = [m for m in miss if m["lane"] == "JUNGLE" and m["stall"] >= STALL_JG]
        laner = [m for m in miss if my_lane and m["lane"] == my_lane]
        if not laner and my_lane in ("BOTTOM", "UTILITY"):
            laner = [m for m in miss if m["lane"] in ("BOTTOM", "UTILITY") and m["stall"] >= 10]
        if jg and laner:
            self.last_gank = t
            out.append(f"{jg[0]['champ']} e {laner[0]['champ']} sumiram. Recua — gank alto.")
        elif laner:
            self.last_gank = t
            out.append(f"{laner[0]['champ']} sumiu da lane. Minimapa, pode estar vindo ou roam.")
        elif jg:
            self.last_gank = t
            out.append(f"Jungler {jg[0]['champ']} parou de farmar. Não ultrapassa o river.")
        return out

    def _wave_lines(self, t: float, ap: dict) -> list[str]:
        eta = cannon_eta(t)
        if eta is None:
            return []
        gold = float(ap.get("currentGold") or 0)
        wave_id = round((t + eta) / CANNON_EVERY)
        for sec, key in ((25, "cannon25"), (6, "cannon6")):
            mark = f"{key}:{wave_id}"
            if 0 <= eta <= sec and mark not in self.wave_said:
                self.wave_said.add(mark)
                if gold >= 1100:
                    return ["Cannon e ouro. Crash na torre e reseta — back."]
                if sec == 6:
                    return ["Cannon. Choca e reseta, ou segura freeze."]
                return ["Cannon em breve. Decide: crash e reset, ou freeze."]
        return []
