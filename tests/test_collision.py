import unittest

import pyforge as game
from pyforge.collision import contains_point, rects_overlap
from pyforge.engine import Game


class RectOverlapTests(unittest.TestCase):
    def test_overlapping_rectangles_collide(self):
        self.assertTrue(rects_overlap(0, 0, 10, 10, 5, 5, 10, 10))

    def test_separate_rectangles_do_not_collide(self):
        self.assertFalse(rects_overlap(0, 0, 10, 10, 20, 20, 5, 5))

    def test_touching_edges_do_not_collide(self):
        self.assertFalse(rects_overlap(0, 0, 10, 10, 10, 0, 10, 10))
        self.assertFalse(rects_overlap(0, 0, 10, 10, 0, 10, 10, 10))

    def test_one_inside_the_other_collides(self):
        self.assertTrue(rects_overlap(0, 0, 100, 100, 40, 40, 5, 5))

    def test_zero_size_never_collides(self):
        self.assertFalse(rects_overlap(0, 0, 0, 10, 0, 0, 10, 10))

    def test_negative_size_extends_left_and_up(self):
        self.assertTrue(rects_overlap(10, 10, -10, -10, 2, 2, 3, 3))
        self.assertFalse(rects_overlap(10, 10, -10, -10, 12, 12, 3, 3))

    def test_contains_point(self):
        g = Game()
        with g.activate():
            s = game.Sprite(10, 10, 20, 20)
        self.assertTrue(contains_point(s, 10, 10))
        self.assertTrue(contains_point(s, 29.9, 29.9))
        self.assertFalse(contains_point(s, 30, 30))
        self.assertFalse(contains_point(s, 9, 15))


class SpriteCollisionTests(unittest.TestCase):
    def setUp(self):
        self.g = Game()
        with self.g.activate():
            self.a = game.Sprite(0, 0, 10, 10)
            self.b = game.Sprite(5, 5, 10, 10)
            self.c = game.Sprite(50, 50, 10, 10)

    def test_game_collides(self):
        self.assertTrue(game.collides(self.a, self.b))
        self.assertFalse(game.collides(self.a, self.c))

    def test_sprite_method(self):
        self.assertTrue(self.a.collides(self.b))
        self.assertFalse(self.b.collides(self.c))

    def test_collisions_lists_only_hits_and_never_self(self):
        hits = game.collisions(self.a, [self.a, self.b, self.c])
        self.assertEqual(hits, [self.b])

    def test_moving_changes_result(self):
        self.assertFalse(self.a.collides(self.c))
        self.a.move(45, 45)
        self.assertTrue(self.a.collides(self.c))


class CollisionCallbackTests(unittest.TestCase):
    def test_callback_fires_once_per_contact(self):
        g = Game()
        hits = []
        with g.activate():
            hero = game.Sprite(0, 0, 10, 10)
            coin = game.Sprite(100, 0, 10, 10)
            game.on_collision(hero, coin, lambda a, b: hits.append((a, b)))
        g.run(None)
        g.tick(0.016)
        self.assertEqual(hits, [])
        hero.x = 100
        g.tick(0.016)
        g.tick(0.016)  # still touching: no second call
        self.assertEqual(hits, [(hero, coin)])
        hero.x = 0
        g.tick(0.016)
        hero.x = 100
        g.tick(0.016)  # touching again: a new contact
        self.assertEqual(len(hits), 2)

    def test_callback_sees_sprites_added_to_list_later(self):
        g = Game()
        hits = []
        coins = []
        with g.activate():
            hero = game.Sprite(0, 0, 10, 10)
            game.on_collision(hero, coins, lambda a, b: hits.append(b))
            late = game.Sprite(5, 5, 10, 10)
        coins.append(late)
        g.tick(0.016)
        self.assertEqual(hits, [late])

    def test_removed_sprites_are_ignored(self):
        g = Game()
        hits = []
        with g.activate():
            hero = game.Sprite(0, 0, 10, 10)
            coin = game.Sprite(0, 0, 10, 10)
            game.on_collision(hero, coin, lambda a, b: hits.append(b))
        coin.remove()
        g.tick(0.016)
        self.assertEqual(hits, [])

    def test_bad_arguments_raise(self):
        g = Game()
        with g.activate():
            hero = game.Sprite(0, 0, 10, 10)
            with self.assertRaises(game.GameError):
                game.on_collision(hero, 5, lambda a, b: None)
            with self.assertRaises(game.GameError):
                game.on_collision(hero, hero, "not callable")


if __name__ == "__main__":
    unittest.main()
