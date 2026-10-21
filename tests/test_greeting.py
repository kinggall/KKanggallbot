"""Greeting keyword behavior and Iris self-message loop prevention."""

import unittest
from unittest.mock import patch

import bot


class GreetingTests(unittest.TestCase):
    def test_profanity_keywords_reply_inside_longer_messages(self):
        cases = {
            "진짜 시발 뭐야": "욕하지 마세요",
            "씨발": "욕하지 마세요",
            "애미라고 쓰지 마": "바르고 고운 말 써요~",
            "좆같네": "바르고 고운 말 써요~",
        }
        for message, expected in cases.items():
            with self.subTest(message=message), patch.object(bot.requests, "post") as post:
                response = bot.app.test_client().post(
                    "/webhook",
                    json={"msg": message, "json": {"chat_id": "greeting-room"}},
                )

            self.assertEqual(response.status_code, 200)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs["json"]["data"], expected)

    def test_profanity_replies_do_not_trigger_again(self):
        for message in ("욕하지 마세요", "바르고 고운 말 써요~"):
            with self.subTest(message=message), patch.object(bot.requests, "post") as post:
                response = bot.app.test_client().post(
                    "/webhook",
                    json={
                        "msg": message,
                        "room": "Iris",
                        "sender": "Iris",
                        "json": {"chat_id": "greeting-room"},
                    },
                )

            self.assertEqual(response.status_code, 200)
            post.assert_not_called()

    def test_good_morning_keyword_replies_once_to_original_chat(self):
        with patch.object(bot.requests, "post") as post:
            response = bot.app.test_client().post(
                "/webhook",
                json={
                    "msg": "여러분 굿모닝입니다",
                    "room": None,
                    "json": {"chat_id": "greeting-room"},
                },
            )

        self.assertEqual(response.status_code, 200)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"type": "text", "room": "greeting-room", "data": "굿모닝~"},
        )

    def test_iris_echo_of_reply_does_not_trigger_again(self):
        with patch.object(bot.requests, "post") as post:
            response = bot.app.test_client().post(
                "/webhook",
                json={
                    "msg": "굿모닝~",
                    "room": "Iris",
                    "sender": "Iris",
                    "json": {"chat_id": "greeting-room"},
                },
            )

        self.assertEqual(response.status_code, 200)
        post.assert_not_called()

    def test_korean_good_morning_with_or_without_space(self):
        for message in ("좋은 아침", "다들 좋은아침이에요"):
            with self.subTest(message=message), patch.object(bot.requests, "post") as post:
                response = bot.app.test_client().post(
                    "/webhook",
                    json={"msg": message, "json": {"chat_id": "greeting-room"}},
                )

            self.assertEqual(response.status_code, 200)
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs["json"]["data"], "좋은 아침입니다!")

    def test_korean_good_morning_reply_does_not_trigger_again(self):
        with patch.object(bot.requests, "post") as post:
            response = bot.app.test_client().post(
                "/webhook",
                json={
                    "msg": "좋은 아침입니다!",
                    "room": "Iris",
                    "sender": "Iris",
                    "json": {"chat_id": "greeting-room"},
                },
            )

        self.assertEqual(response.status_code, 200)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
