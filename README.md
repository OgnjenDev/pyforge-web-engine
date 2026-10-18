# PyForge

**PyForge is a tiny game engine that lets you write browser games in plain Python.**

You write your game logic in Python. PyForge runs it on a small built-in web server and draws it in any web browser using an HTML5 canvas. You never touch JavaScript, HTML or CSS.

- **Python standard library only.** No Flask, no Pygame, no Node.js.
- **Every browser tab is its own game.** Each player gets an independent session with their own sprites, variables and input.
- **Works on desktop and Termux (Android).** Phones and tablets on the same Wi-Fi can play too, with on-screen touch controls.

> **Status: version 0.1, early.** It is a small, working foundation, not a finished engine. Read [Current limitations](#current-limitations), especially the security note, before you put a game on a network you do not control.

---

## Installation

PyForge needs **Python 3.9 or newer**.

PyForge is **not on PyPI yet** (see [Publishing](#publishing)), so for now install it from this folder:

```bash
cd PyForge
pip install .
```

Check that it worked:

```bash
pyforge --version
```

If your system says `pyforge: command not found`, run it as `python -m pyforge` instead (everything below works with either), or see [Troubleshooting](#troubleshooting).

### Termux (Android)

```bash
pkg update
pkg install python
cd PyForge
pip install .
```

Termux has no extra requirements. Optionally run `termux-wake-lock` so Android does not suspend Termux while you play.

---

## Your first game

This tutorial builds a small game, **Coin Dash**: move the blue square, collect the yellow coins, avoid the red square. The finished file is in `examples/coin_dash.py`.

### Step 1: a square you can move

Create a folder for your game, and a file called `game.py` in it:

```python
import pyforge as game

game.init(800, 600)
game.set_background("#202020")

player = game.Sprite(
    100, 100, 40, 40,
    color="#00aaff"
)

def update():
    if game.key("right"):
        player.x += 5

    if game.key("left"):
        player.x -= 5

    if game.key("up"):
        player.y -= 5

    if game.key("down"):
        player.y += 5

game.run(update)
```

Start it:

```bash
pyforge run game.py
```

Open the address it prints (`http://127.0.0.1:8000/`) in your browser and use the arrow keys. This exact program is `examples/basic_game.py`.

What is happening:

- `game.init(800, 600)` sets the canvas size in pixels.
- `game.Sprite(x, y, width, height, color=...)` creates a rectangle. `x` and `y` are its top-left corner. `y` grows **downwards**.
- `update()` is called for every frame. Whatever you change on a sprite shows up in the browser.
- `game.run(update)` hands `update` to the engine. Put it last.

Edit `game.py` and press **Restart** in the browser: the file is read again, so you do not need to restart the server.

### Step 2: the whole game

Replace `game.py` with this. It uses time-based movement (`update(dt)`), collision callbacks, text labels and restart. The numbered notes follow the code.

```python
import random

import pyforge as game

WIDTH, HEIGHT = 800, 600
SPEED = 300  # pixels per second

game.init(WIDTH, HEIGHT, title="Coin Dash")
game.set_background("#1b1b2f")

player = game.Sprite(380, 280, 40, 40, color="#00aaff")
enemy = game.Sprite(100, 100, 50, 50, color="#ff3355")
coin = game.Sprite(0, 0, 24, 24, color="#ffd400")
score_label = game.Label(12, 10, "Score: 0", size=24)
message = game.Label(40, 280, "", size=32, color="#ffffff", visible=False)

score = 0
game_over = False
enemy_dx, enemy_dy = 180, 140


def move_coin():
    coin.x = random.randint(0, WIDTH - coin.width)
    coin.y = random.randint(50, HEIGHT - coin.height)


def collect(hero, item):
    global score
    score += 1
    score_label.text = f"Score: {score}"
    move_coin()


def hit(hero, bad_guy):
    global game_over
    game_over = True
    message.text = f"Game over! Score {score}. Press SPACE to play again"
    message.visible = True


move_coin()
game.on_collision(player, coin, collect)
game.on_collision(player, enemy, hit)


def update(dt):
    global enemy_dx, enemy_dy

    if game_over:
        if game.key_pressed("space"):
            game.restart()
        return

    if game.key("left") or game.key("a"):
        player.x -= SPEED * dt
    if game.key("right") or game.key("d"):
        player.x += SPEED * dt
    if game.key("up") or game.key("w"):
        player.y -= SPEED * dt
    if game.key("down") or game.key("s"):
        player.y += SPEED * dt
    player.x = max(0, min(WIDTH - player.width, player.x))
    player.y = max(0, min(HEIGHT - player.height, player.y))

    enemy.x += enemy_dx * dt
    enemy.y += enemy_dy * dt
    if enemy.x < 0 or enemy.right > WIDTH:
        enemy_dx = -enemy_dx
    if enemy.y < 0 or enemy.bottom > HEIGHT:
        enemy_dy = -enemy_dy


game.run(update)
```

1. **`update(dt)`**: if your update function accepts one argument, PyForge passes the seconds since the last frame. `SPEED * dt` gives the same speed on any frame rate.
2. **`game.on_collision(player, coin, collect)`** calls `collect(player, coin)` once each time the two start touching.
3. **`game.Label`** is a line of text. Change its `.text` whenever you like.
4. **`game.restart()`** runs your whole file again for a fresh game.
5. **Variables live in your game file.** Each player gets their own copy of `score`, `player` and the rest.

Open the game in two browser tabs: each tab is a separate game.

---

## API reference

Everything below is used as `game.<name>` after `import pyforge as game`.

### Game

| Function | What it does |
|---|---|
| `game.init(width=800, height=600, title="PyForge game", fps=None, touch_controls="auto")` | Canvas size in pixels (1 to 4096), page title, updates per second (1 to 240, default 60), and on-screen touch controls: `"auto"` shows them on touch devices, `True` always, `False` never. |
| `game.set_background(color)` | Background colour, e.g. `"#202020"` or `"navy"`. |
| `game.run(update=None, fps=None)` | Registers your update function and starts the game. `update` may take no arguments or one (`dt`, seconds since the last frame). `fps` sets the update rate. `game.run()` with no function shows a static scene. |
| `game.stop()` | Stops the game loop. The browser keeps the last frame and offers a Restart button. |
| `game.restart()` | Starts the game over by re-reading and re-running your game file. |
| `game.frame()` | Frames completed so far. The first `update()` call sees `0`. |
| `game.dt()` | Seconds since the previous frame. |

### Sprites

`game.Sprite(x, y, width, height, color="#ffffff", visible=True)` is a coloured rectangle.

| Attribute / method | What it does |
|---|---|
| `sprite.x`, `sprite.y` | Top-left corner. Assign or use `+=`. |
| `sprite.width`, `sprite.height` | Size in pixels. |
| `sprite.color` | Any CSS colour string. |
| `sprite.visible` | `False` hides it (it still exists and still collides). |
| `sprite.left`, `.right`, `.top`, `.bottom` | Edges (read-only). |
| `sprite.center` | `(x, y)` of the middle (read-only). |
| `sprite.move(dx, dy)` | Moves by an amount. |
| `sprite.collides(other)` | `True` if it overlaps `other`. |
| `sprite.contains(x, y)` | `True` if the point is inside, handy for mouse clicks. |
| `sprite.remove()` | Removes it for good. Safe to call twice. |

`game.Label(x, y, text="", color="#ffffff", size=20, visible=True)` is a line of text with attributes `x`, `y`, `text`, `color`, `size`, `visible` and a `remove()` method. Draw order is creation order: later sprites and labels are drawn on top.

Sprites and labels must be created inside your game file (at the top level or inside your functions). Values must be numbers; if you set `sprite.x = "left"`, the browser shows a clear error message.

### Input

Key names are lowercase: `"left"`, `"right"`, `"up"`, `"down"`, `"space"`, `"enter"`, `"escape"`, `"shift"`, `"ctrl"`, `"alt"`, `"tab"`, letters `"a"` to `"z"` and digits `"0"` to `"9"`. Letter keys follow the physical key position (like WASD), so they work on any keyboard layout.

| Function | What it does |
|---|---|
| `game.key(name)` | `True` while the key is held. |
| `game.key_pressed(name)` | `True` only on the frame the key went down. Quick taps are never missed. |
| `game.key_released(name)` | `True` only on the frame the key came up. |
| `game.mouse()` | Mouse (or finger) position as `(x, y)` in **game pixels**, even if the canvas is scaled to fit the screen. |
| `game.mouse_down(button="left")` | `True` while `"left"`, `"middle"` or `"right"` is held. |
| `game.mouse_pressed(button="left")` | `True` only on the frame the button went down. |

On touch devices a tap or drag on the canvas counts as the left mouse button, and an on-screen d-pad plus a SPACE button send the arrow keys and `"space"`.

### Collisions

Two rectangles collide when they overlap. Rectangles that only touch along an edge do not.

| Function | What it does |
|---|---|
| `game.collides(a, b)` | `True` if the two sprites overlap. |
| `game.collisions(sprite, others)` | List of the sprites in `others` that overlap `sprite` (never includes `sprite` itself). |
| `game.on_collision(sprite, others, callback)` | Calls `callback(sprite, other)` once each time `sprite` starts touching `other`. `others` is one sprite or a list; a list is re-read every frame, so sprites you add later are included. Callbacks run after `update()`. |

### Errors

If your game raises an error, the game stops, the browser shows the error with the lines from your file, and the server keeps running for everyone else. Fix the file and press **Restart**. The full traceback is also printed in the terminal.

---

## Running a game

```bash
pyforge run game.py                 # http://127.0.0.1:8000/
pyforge run game.py --port 9000     # another port
pyforge run --help                  # all options
```

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | Address to listen on. `0.0.0.0` means "every network interface". |
| `--port` | `8000` | Port to listen on. `0` picks any free port (it is printed). |
| `--session-timeout` | `60` | Seconds without contact before a player's game is closed. |
| `--cleanup-interval` | `5` | How often (seconds) to look for timed-out games. |
| `--max-sessions` | `50` | Most players at once. Extra players get "server is full". |
| `--verbose` | off | Log every HTTP request. |

You can also start a game file directly with `python game.py`; it runs a server with the default host and port. Use `pyforge run` when you want options.

**Stopping the server:** press **Ctrl+C** in its terminal, or from another terminal run `pyforge stop --port 8000`. (`pyforge stop` only works for servers started by you on the same machine.) Stopping closes every player's game. The game itself can end with `game.stop()`.

### Letting other devices on your network connect

1. Put the devices on the **same Wi-Fi / network** as the computer (or Termux phone) running the game.
2. Start the server so it listens on every interface:

   ```bash
   pyforge run game.py --host 0.0.0.0
   ```

3. PyForge prints a `Network:` address such as `http://192.168.1.23:8000/`. Open that address on the other device. If no address is printed, find the host device's IP in its Wi-Fi settings (in Termux, `pkg install net-tools` and run `ifconfig`) and use `http://<that-ip>:8000/`.
4. Every device gets its own separate game.

Anyone who can reach that address can play. Only do this on a network you trust.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `pyforge: command not found` | Use `python -m pyforge run game.py`. Or add pip's scripts folder to your `PATH` (on Termux and Linux it is usually `~/.local/bin`). |
| `port 8000 is already in use` | Another program (or an old PyForge) is using it. Use `--port 8001`, or `pyforge stop --port 8000`. |
| Page loads but stays black | Your file never reached `game.run(update)`, or an error is shown over the canvas. Read the message and the terminal output. |
| Red "Game error" box | Read the lines from your file in the message. Fix the file, then press **Restart**. |
| "Session ended" or "Session expired" | The server was restarted, or the page was inactive longer than `--session-timeout`. Press **Start a new session**. |
| Phone or other computer cannot connect | Did you use `--host 0.0.0.0`? Same Wi-Fi? Guest or public Wi-Fi often blocks devices from talking to each other ("client isolation"). A computer firewall may need to allow the port. |
| Keys do nothing | Click the game once so the page has focus. Key names are lowercase (`"space"`, not `"Space"`). |
| Keys stay "stuck" after switching windows | PyForge releases all keys when the page loses focus; if it still happens, press and release the key once. |
| Page hangs after opening many tabs | Browsers allow about 6 connections to one address and each game tab keeps one open. Close some tabs. |
| `ModuleNotFoundError` for your own helper file | Put it in the same folder as your game file. See the limitation about shared state below. |

---

## Current limitations

- **Not a sandbox. Do not run games you do not trust, and do not host strangers' code.** `pyforge run` executes your game file as ordinary Python with your user's permissions. Browsers never send code to the server and all game logic runs on the server (so players cannot cheat by editing the page), but the server has **no authentication, encryption, process isolation or resource limits** beyond a session cap, a sprite cap and request validation. Never put it on the public internet as-is. A public hosting service would need per-game process isolation, resource limits, authentication and HTTPS in front; that is future work.
- **A game that loops forever hangs only its own session**, but Python cannot kill that thread, so the process may need to be stopped with Ctrl+C.
- **State shared by imported helper modules is shared between players.** Keep your game's variables and sprites in your game file (or in objects you create from it). Do not create sprites at import time in other files.
- **Rectangles and text only.** No images, animation, sound, tilemaps, physics, camera, scenes, gamepad or multiplayer yet. These are planned and the code is organised so they can be added.
- **Latency matters.** Input goes browser, server, browser on every frame. That is fine on a local network, and noticeable on slow connections.
- One thread per player and Python's GIL mean it is built for tens of players, not thousands.
- When nobody is watching a game (tab closed or phone asleep) the game pauses, and it is closed after `--session-timeout`.
- Tested on Python 3.11 and 3.13 on Linux. Termux/Android and other operating systems should work (standard library only) but have not been tested by the author.

---

## Publishing

PyForge is set up as an installable package (`pyproject.toml`, the `pyforge` command, `src/` layout), but it has **not been published**, and the availability of the name `pyforge` on PyPI has **not been checked**. Before publishing, check https://pypi.org/project/pyforge/ and pick another distribution name in `pyproject.toml` if it is taken (the `pyforge` command and the `pyforge` import name can stay the same). Then build and upload:

```bash
pip install build twine
python -m build
twine upload dist/*
```

---

## Project layout

```
PyForge/
├── pyproject.toml
├── src/pyforge/
│   ├── __init__.py      public API (game.init, game.key, ...)
│   ├── engine.py        Game state, update loop, collision callbacks
│   ├── sprites.py       Sprite and Label
│   ├── input.py         keyboard / mouse state
│   ├── collision.py     rectangle collision maths
│   ├── sessions.py      one game + thread per player, timeouts, state diffs
│   ├── server.py        stdlib HTTP server, Server-Sent Events
│   ├── cli.py           the `pyforge` command
│   └── web/             browser client (index.html, client.js)
├── examples/            basic_game.py, coin_dash.py
└── tests/
```

How it works: the browser opens a session (`POST /api/session`), then listens to a Server-Sent Events stream of game changes (only what changed since the last message is sent) and sends key and mouse events back. Each session runs your game on its own thread and publishes read-only snapshots of it, so no two players, and no HTTP thread, ever touch the same game data.

## Contributing

1. Fork or copy the repository and install it in editable mode: `pip install -e .`
2. Run the tests (no extra packages needed): `python -m unittest discover -s tests`
3. Keep the core on the standard library only, keep functions small and readable, add type hints where they help.
4. Every function in the README API reference must exist and be tested; `tests/test_docs.py` checks this.
5. New features should come with tests. Good first contributions are on the roadmap: image and animated sprites, sound, tilemaps, simple physics, camera, scenes, gamepad support, multiplayer sessions, game export, plugins.
6. Open a pull request that says what changed and why.

PyForge is released under the MIT License (see `LICENSE`).
