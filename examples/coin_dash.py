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
