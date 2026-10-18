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
