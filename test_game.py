"""assert nos timers e lembretes — quebra se o relógio do mapa mentir."""

from game import CsWatch, Reminders, cannon_eta, compact, describe_objectives, game_time


def rift(t: float, ev=None, gold=0.0, dead=False, extra=None) -> dict:
    me = {
        "championName": "Ahri",
        "summonerName": "Você",
        "riotId": "Você#BR1",
        "team": "ORDER",
        "position": "MIDDLE",
        "isDead": dead,
        "respawnTimer": 18 if dead else 0,
        "level": 6,
        "items": [{"displayName": "Lost Chapter"}],
        "scores": {"kills": 2, "deaths": 1, "assists": 1, "creepScore": 50},
        "summonerSpells": {
            "summonerSpellOne": {"displayName": "Flash"},
            "summonerSpellTwo": {"displayName": "Ignite"},
        },
    }
    return {
        "activePlayer": {
            "currentGold": gold,
            "level": 6,
            "summonerName": "Você",
            "riotId": "Você#BR1",
            "championStats": {"currentHealth": 400 if gold else 1200, "maxHealth": 1400},
            "abilities": {"R": {"displayName": "Tibbers", "abilityLevel": 1}},
            "fullRunes": {"keystone": {"displayName": "Electrocute"}},
        },
        "allPlayers": [me] + list(extra or []),
        "events": {"Events": ev or [{"EventID": 0, "EventName": "GameStart", "EventTime": 0}]},
        "gameData": {"gameMode": "CLASSIC", "gameTime": t, "mapName": "Map11", "mapNumber": 11},
    }


def foe(champ: str, lane: str, cs: int, name: str = "E") -> dict:
    return {
        "championName": champ,
        "summonerName": name,
        "team": "CHAOS",
        "position": lane,
        "isDead": False,
        "respawnTimer": 0,
        "level": 5,
        "items": [],
        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": cs},
        "summonerSpells": {
            "summonerSpellOne": {"displayName": "Flash"},
            "summonerSpellTwo": {"displayName": "Smite" if lane == "JUNGLE" else "Ignite"},
        },
    }


def test_first_dragon_clock():
    d = describe_objectives(rift(4 * 60 + 30))
    assert d["dragão"] == "em 0:30", d
    assert "grubs" in describe_objectives(rift(7 * 60))


def test_dragon_respawn_after_kill():
    ev = [
        {"EventID": 0, "EventName": "GameStart", "EventTime": 0},
        {"EventID": 1, "EventName": "DragonKill", "EventTime": 400, "DragonType": "Fire", "KillerName": "Você"},
    ]
    d = describe_objectives(rift(500, ev))
    assert d["dragão"] == "em 3:20", d  # 400+300-500 = 200s


def test_grubs_gone_after_three_hordes():
    ev = [{"EventID": i, "EventName": "HordeKill", "EventTime": 500 + i} for i in range(3)]
    d = describe_objectives(rift(8 * 60 + 30, ev))
    assert "grubs" not in d, d


def test_baron_at_20():
    d = describe_objectives(rift(19 * 60))
    assert d["barão"] == "em 1:00", d
    assert describe_objectives(rift(20 * 60 + 5))["barão"] == "no mapa"


def test_no_objectives_on_aram():
    data = rift(300)
    data["gameData"] = {"gameMode": "ARAM", "gameTime": 300, "mapName": "Map12", "mapNumber": 12}
    assert describe_objectives(data) == {}


def test_dragon_30s_reminder_once():
    r = Reminders()
    lines = r.next(rift(5 * 60 - 25))
    assert any("Dragão" in x and "25" in x for x in lines), lines
    again = r.next(rift(5 * 60 - 20))
    assert not any("Dragão" in x for x in again), again


def test_death_calls_tab():
    r = Reminders()
    r.next(rift(200, dead=False))
    lines = r.next(rift(201, dead=True))
    assert any("Morto" in x and "TAB" in x for x in lines), lines


def test_compact_uses_live_gold_not_theory():
    c = compact(rift(600, gold=1850))
    assert c["eu"]["ouro"] == 1850
    assert c["eu"]["champ"] == "Ahri"
    assert game_time(rift(90)) == 90


def test_cannon_clock():
    assert cannon_eta(80) is None
    assert abs(cannon_eta(125) - 25) < 0.01
    assert cannon_eta(150) == 0


def test_cannon_reset_call():
    r = Reminders(watch=CsWatch())
    lines = r.next(rift(125))
    assert any("Cannon" in x for x in lines), lines
    r2 = Reminders(watch=CsWatch())
    lined = r2.next(rift(125, gold=1200))
    assert any("back" in x.lower() for x in lined), lined


def test_gank_when_jg_and_laner_cs_stall():
    w = CsWatch()
    r = Reminders(watch=w)
    pack = lambda m, j: [foe("Syndra", "MIDDLE", m, "Mid"), foe("Lee Sin", "JUNGLE", j, "Jg")]
    r.next(rift(180, extra=pack(40, 20)))
    r.next(rift(181, extra=pack(41, 21)))
    lines = r.next(rift(200, extra=pack(41, 21)))
    assert any("gank" in x.lower() or "sumiram" in x for x in lines), lines


def test_kill_says_reset_wave():
    r = Reminders(watch=CsWatch())
    start = [{"EventID": 0, "EventName": "GameStart", "EventTime": 0}]
    r.next(rift(199, ev=start))
    lines = r.next(
        rift(
            200,
            ev=start
            + [
                {
                    "EventID": 2,
                    "EventName": "ChampionKill",
                    "EventTime": 200,
                    "KillerName": "Você",
                    "VictimName": "Inimigo",
                    "Assisters": [],
                }
            ],
        )
    )
    assert any("reseta" in x.lower() for x in lines), lines


if __name__ == "__main__":
    for fn in (
        test_first_dragon_clock,
        test_dragon_respawn_after_kill,
        test_grubs_gone_after_three_hordes,
        test_baron_at_20,
        test_no_objectives_on_aram,
        test_dragon_30s_reminder_once,
        test_death_calls_tab,
        test_compact_uses_live_gold_not_theory,
        test_cannon_clock,
        test_cannon_reset_call,
        test_gank_when_jg_and_laner_cs_stall,
        test_kill_says_reset_wave,
    ):
        fn()
        print("ok", fn.__name__)
    print("all passed")
