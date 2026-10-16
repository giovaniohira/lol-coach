# LoL Coach

Coach por áudio no ouvido, usando o **estado real da partida** (não só teoria de matchup).

Não é endossado pela Riot Games.

## O que ele faz

Enquanto você joga, lê o Live Client Data (`https://127.0.0.1:2999`) — ouro, itens, CS, KDA, eventos, relógio. Com isso ele:

- manda **TAB** e **minimapa** em intervalos
- avisa dragão / grubs / arauto / barão **60s e 30s antes**, com o timer calculado dos kills da *sua* partida
- avisa **gank**: jungle/matchup parou de farmar (CS travou) — a API não vê o rio
- avisa **reset de wave**: cannon, crash+back com ouro, e depois que você mata
- fala na morte, first blood, objetivo, ace, inibidor
- lembra de back quando o ouro atual dá item

Segura **F8** (ou aperta Enter no terminal) e pergunta, por exemplo *“devo comprar essa troca?”*. Ele captura a **tela** (loja, minimapa, luta) + o JSON do jogo e responde em 1–2 frases por áudio.

A API do client não vê fog of war. Screenshot entra só na pergunta, no que **você** já está vendo.

## Setup

1. Python 3.12
2. Chave DeepSeek (visão + texto). Microfone usa o STT gratuito do Google.
3. Voz `pt-BR-AntonioNeural` via Edge TTS (internet)

```powershell
cd lol-coach
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Coloca a chave em `.env`. Se o F8 não pega com o LoL em foco, rode o terminal **como administrador** (o League come tecla). Enter no terminal sempre funciona.

## Uso

```powershell
python coach.py
```

Entra na partida. Quando o client abrir a porta 2999, ele fala que está no jogo.

Ouvir os timers sem LoL (relógio acelerado):

```powershell
python coach.py --demo
```

Checar a lógica:

```powershell
python test_game.py
```

## ToS

Só lê a API oficial do client e a sua tela. Não injeta no jogo, não aperta tecla por você, não rastreia flash/ult inimiga.
