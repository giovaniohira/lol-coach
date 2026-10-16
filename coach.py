"""Coach de LoL por áudio: estado vivo do client + screenshot quando você pergunta."""

from __future__ import annotations

import base64
import json
import os
import socket
import sys
import threading
import time

from dotenv import load_dotenv
from openai import OpenAI

import game
import voice

SYSTEM = """Você é um coach de League of Legends falando no ouvido do jogador NO MEIO da partida.
Responda em português do Brasil, 1 a 2 frases curtas, call de Discord — não aula.
Use o ESTADO DO JOGO (JSON) e a SCREENSHOT. O estado é a verdade de ouro/itens/eventos/níveis; a tela mostra o que ele está olhando (loja, minimapa, luta).
Se a pergunta for comprar item, troca ou build, olhe ouro + inventário + loja na screenshot. Diga sim/não e o porquê em uma frase, no contexto DESTE jogo (objetivo próximo, se está ganhando a lane, se precisa de defesa).
Se perguntar de gank/voltar: use "sumidos" (CS parou) e a screenshot do minimapa. Sem posição no mapa a API não vê o rio — não invente.
Se perguntar de wave/reset/back: use proxima_cannon, ouro e se acabou de matar.
Não recorra a matchup teórico se o JSON já mostra o jogo real (placar, itens, relógio de objetivo).
Se a tela mostra luta, priorize a luta. Se mostra loja, priorize a compra.
Nunca invente cooldown de ultimates inimigas. Nunca dê wallhack. Pode mandar TAB, minimapa, wave, visão, back.
"""


def ask(client: OpenAI, model: str, question: str, state: dict, jpeg: bytes | None) -> str:
    parts: list[dict] = [
        {
            "type": "text",
            "text": f"Estado atual:\n{json.dumps(state, ensure_ascii=False)}\n\nPergunta do jogador: {question}",
        }
    ]
    if jpeg:
        b64 = base64.b64encode(jpeg).decode()
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
            }
        )
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": parts}],
            max_tokens=180,
            temperature=0.2,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception:
        if jpeg:
            return ask(client, model, question, state, None)
        raise
    msg = r.choices[0].message
    text = (msg.content or "").strip()
    if not text:
        text = (getattr(msg, "reasoning_content", None) or "").strip()
    return text


def handle_question(client: OpenAI, model: str, data: dict, speaker: voice.Speaker, audio) -> None:
    q = voice.transcribe(audio)
    if not q:
        speaker.say("Não ouvi.")
        return
    print(f"você: {q}")
    jpeg = None
    try:
        jpeg = voice.screenshot_jpeg()
    except Exception as e:
        print(f"screenshot falhou: {e}")
    try:
        ans = ask(client, model, q, game.compact(data), jpeg)
    except Exception as e:
        ans = f"Falhou o coach: {e}"
    speaker.say(ans)


def _listen_hotkey(flag: list[bool]) -> None:
    try:
        import keyboard

        keyboard.add_hotkey(os.environ.get("COACH_HOTKEY", "f8"), lambda: flag.__setitem__(0, True))
        keyboard.wait()
    except Exception as e:
        print(f"hotkey indisponível ({e}). Use Enter no terminal pra perguntar.")


def _stdin_flag(flag: list[bool]) -> None:
    if not sys.stdin.isatty():
        return
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            return
        if not line:
            return
        flag[0] = True


def wait_ingame(speaker: voice.Speaker) -> dict:
    print("Esperando a partida (Live Client em https://127.0.0.1:2999)...")
    announced = False
    while True:
        data = game.poll()
        if data:
            if not announced:
                me = game.me_row(data) or {}
                champ = me.get("championName") or "você"
                speaker.say(f"Estou no jogo. {champ}. Segura F8 e pergunta. Enter também vale.")
                announced = True
            return data
        time.sleep(1.5)


def make_client() -> tuple[OpenAI, str]:
    load_dotenv()
    ds = os.environ.get("DEEPSEEK_API_KEY")
    if ds:
        return (
            OpenAI(api_key=ds, base_url=os.environ.get("COACH_BASE_URL", "https://api.deepseek.com")),
            os.environ.get("COACH_MODEL", "deepseek-flash"),
        )
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("Coloca DEEPSEEK_API_KEY no .env (copia o .env.example).")
    return OpenAI(), os.environ.get("COACH_MODEL", "gpt-4o-mini")


def _only_one() -> None:
    # ponytail: porta local como mutex. dois coaches = "não ouvi" em dobro
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 17999))
        sock.listen(1)
    except OSError:
        sys.exit("Já tem um coach rodando. Fecha o outro e tenta de novo.")
    global _lock_sock
    _lock_sock = sock


_lock_sock = None


def loop(demo: bool) -> None:
    _only_one()
    client, model = make_client()
    speaker = voice.Speaker()
    rem = game.Reminders(
        tab_every=float(os.environ.get("TAB_EVERY", "45")),
        map_every=float(os.environ.get("MAP_EVERY", "28")),
    )
    want = [False]
    threading.Thread(target=_listen_hotkey, args=(want,), daemon=True).start()
    threading.Thread(target=_stdin_flag, args=(want,), daemon=True).start()

    t0 = time.time()
    data = None
    if demo:
        speaker.say("Modo demo. Relógio acelerado. F8 ainda pergunta.")
    else:
        data = wait_ingame(speaker)

    last_auto = 0.0
    while True:
        if demo:
            # ponytail: 1s de jogo a cada 50ms, só pra ouvir os timers sem entrar na rift
            fake_t = (time.time() - t0) * 20
            data = _demo_data(fake_t)
        else:
            data = game.poll() or data
            if data is None:
                time.sleep(1)
                continue

        if want[0] and data:
            want[0] = False
            voice.beep()
            audio = voice.record_while_held()
            if audio.size < voice.FS * 0.35:
                print("fala (6s)...")
                audio = voice.record_seconds(6)
            voice.beep()
            handle_question(client, model, data, speaker, audio)

        if data:
            lines = rem.next(data)
            if lines:
                urgent = any(
                    k in lines[0]
                    for k in ("sumiu", "gank", "Jungler", "Matou", "Morto", "Cannon", "Janela")
                )
                if urgent or time.time() - last_auto > 7:
                    speaker.say(lines[0], drop_if_busy=not urgent)
                    last_auto = time.time()
                    for extra in lines[1:]:
                        print(f"(adiado) {extra}")

        time.sleep(0.25 if demo else 1.0)


def _enemy(champ: str, lane: str, name: str, t: float, cs: int, dead: bool = False) -> dict:
    return {
        "championName": champ,
        "summonerName": name,
        "team": "CHAOS",
        "position": lane,
        "isDead": dead,
        "respawnTimer": 12 if dead else 0,
        "level": max(1, int(t / 95) + 1),
        "items": [{"displayName": "Needlessly Large Rod"}],
        "scores": {"kills": 0, "deaths": 1, "assists": 0, "creepScore": cs},
        "summonerSpells": {
            "summonerSpellOne": {"displayName": "Flash"},
            "summonerSpellTwo": {"displayName": "Teleport"},
        },
    }


def _demo_data(t: float) -> dict:
    mid_cs = int(t / 9) if t < 165 else int(165 / 9)
    jg_cs = int(t / 6) if t < 155 else int(155 / 6)
    return {
        "activePlayer": {
            "currentGold": 400 + t * 2,
            "level": max(1, int(t / 90) + 1),
            "summonerName": "Você",
            "championStats": {"currentHealth": 800, "maxHealth": 1400},
            "abilities": {"R": {"displayName": "Ult", "abilityLevel": 1 if t > 360 else 0}},
            "fullRunes": {"keystone": {"displayName": "Electrocute"}},
        },
        "allPlayers": [
            {
                "championName": "Ahri",
                "summonerName": "Você",
                "team": "ORDER",
                "position": "MIDDLE",
                "isDead": False,
                "respawnTimer": 0,
                "level": max(1, int(t / 90) + 1),
                "items": [{"displayName": "Lost Chapter"}],
                "scores": {"kills": 1, "deaths": 0, "assists": 2, "creepScore": int(t / 8)},
                "summonerSpells": {
                    "summonerSpellOne": {"displayName": "Flash"},
                    "summonerSpellTwo": {"displayName": "Ignite"},
                },
            },
            _enemy("Syndra", "MIDDLE", "Inimigo", t, mid_cs, dead=t > 280 and int(t) % 80 < 8),
            _enemy("Lee Sin", "JUNGLE", "JG", t, jg_cs),
        ],
        "events": {
            "Events": [{"EventID": 0, "EventName": "GameStart", "EventTime": 0.0}]
            + ([{"EventID": 1, "EventName": "MinionsSpawning", "EventTime": 90}] if t >= 90 else [])
        },
        "gameData": {"gameMode": "CLASSIC", "gameTime": t, "mapName": "Map11", "mapNumber": 11},
    }


if __name__ == "__main__":
    loop(demo="--demo" in sys.argv)
