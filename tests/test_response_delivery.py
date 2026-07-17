import unittest

from gui.character_widget import CharacterWidget


class _AnimationStub:
    def __init__(self, *, avatar_mode="animated", playing_arms_cross=False):
        self._avatar_mode = avatar_mode
        self._playing_arms_cross = playing_arms_cross


class AnimationCallbackContractTests(unittest.TestCase):
    def test_static_avatar_arms_cross_completes_callback(self):
        stub = _AnimationStub(avatar_mode="static")
        calls = []

        CharacterWidget.play_arms_cross(stub, lambda: calls.append("done"))

        self.assertEqual(["done"], calls)

    def test_already_playing_arms_cross_completes_callback(self):
        stub = _AnimationStub(playing_arms_cross=True)
        calls = []

        CharacterWidget.play_arms_cross(stub, lambda: calls.append("done"))

        self.assertEqual(["done"], calls)

    def test_stop_thinking_during_arms_cross_completes_callback(self):
        stub = _AnimationStub(playing_arms_cross=True)
        calls = []

        CharacterWidget.stop_thinking(stub, lambda: calls.append("done"))

        self.assertEqual(["done"], calls)


if __name__ == "__main__":
    unittest.main()
