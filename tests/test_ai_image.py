import base64
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from PIL import Image
import requests

from ai_image import detect_provider, generate_image, list_models, normalize_base_url


def response(payload=None, content=b""):
    value = mock.Mock(content=content)
    value.json.return_value = payload
    return value


class ImageApiTests(unittest.TestCase):
    def test_openai_models_custom_base_and_auth(self):
        session = mock.Mock()
        session.get.return_value = response({"data": [
            {"id": "text-model"}, {"id": "gpt-image-test"}, {"id": "gpt-image-test"}]})
        provider, models = list_models("https://proxy.example/api/openai/", " secret ", session=session)
        self.assertEqual(provider, "OpenAI")
        self.assertEqual(models, ["gpt-image-test", "text-model"])
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], "https://proxy.example/api/openai/models")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_gemini_pagination_and_method_filter(self):
        session = mock.Mock()
        session.get.side_effect = [
            response({"models": [{"name": "models/gemini-image", "supportedGenerationMethods": ["generateContent"]},
                                 {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}],
                      "nextPageToken": "next+token"}),
            response({"models": [{"name": "models/gemini-text"}]})]
        provider, models = list_models("https://generativelanguage.googleapis.com", "key", session=session)
        self.assertEqual(provider, "Gemini")
        self.assertEqual(models, ["gemini-image", "gemini-text"])
        self.assertIn("pageToken=next%2Btoken", session.get.call_args.args[0])
        self.assertEqual(session.get.call_args.kwargs["headers"]["x-goog-api-key"], "key")

    def test_openai_base64_generation(self):
        session = mock.Mock()
        session.post.return_value = response({"data": [{"b64_json": base64.b64encode(b"image").decode()}]})
        provider, data = generate_image("https://proxy.example/v1", "key", "image-test", "a house", session=session)
        self.assertEqual((provider, data), ("OpenAI", b"image"))
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://proxy.example/v1/images/generations")
        self.assertEqual(kwargs["json"]["model"], "image-test")
        self.assertEqual(kwargs["json"]["n"], 1)

    def test_openai_url_download_does_not_forward_key(self):
        session = mock.Mock()
        session.post.return_value = response({"data": [{"url": "https://cdn.example/result.png"}]})
        session.get.return_value = response(content=b"png")
        self.assertEqual(generate_image("", "key", "image-test", "house", session=session)[1], b"png")
        self.assertNotIn("headers", session.get.call_args.kwargs)

    def test_gemini_generation_inline_image(self):
        session = mock.Mock()
        session.post.return_value = response({"candidates": [{"content": {"parts": [
            {"text": "result"}, {"inlineData": {"mimeType": "image/png",
                                               "data": base64.b64encode(b"gemini").decode()}}]}}]})
        result = generate_image("https://proxy.example/v1beta", "key", "models/gemini-image", "house",
                                "Gemini", session=session)
        self.assertEqual(result, ("Gemini", b"gemini"))
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://proxy.example/v1beta/models/gemini-image:generateContent")
        self.assertEqual(kwargs["json"]["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])

    def test_empty_models_and_text_only_generation_raise(self):
        session = mock.Mock()
        session.get.return_value = response({"data": []})
        with self.assertRaisesRegex(RuntimeError, "模型"):
            list_models("", "key", session=session)
        session.post.return_value = response({"candidates": []})
        with self.assertRaisesRegex(RuntimeError, "图像"):
            generate_image("", "key", "model", "house", "Gemini", session=session)

    def test_validation_and_explicit_provider(self):
        self.assertEqual(detect_provider("https://gemini.example", "OpenAI"), "OpenAI")
        self.assertEqual(detect_provider("https://gemini.example"), "OpenAI")
        self.assertEqual(detect_provider("https://generativelanguage.googleapis.com/v1beta"), "Gemini")
        self.assertEqual(normalize_base_url("", "Gemini"),
                         "https://generativelanguage.googleapis.com/v1beta")
        for url in ("file:///secret", "https://", "https://x.example?key=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_base_url(url, "OpenAI")
        with self.assertRaises(ValueError):
            generate_image("", "", "model", "prompt")


class LocalImageServerTests(unittest.TestCase):
    def test_both_protocols_over_real_http(self):
        calls = []
        image_buffer = io.BytesIO()
        Image.new("RGB", (16, 16), "white").save(image_buffer, format="PNG")
        encoded = base64.b64encode(image_buffer.getvalue()).decode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send_json(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                calls.append((self.path, dict(self.headers), None))
                if self.path == "/v1/models":
                    self.send_json({"data": [{"id": "image-test"}]})
                else:
                    self.send_json({"models": [{"name": "models/gemini-image",
                                                 "supportedGenerationMethods": ["generateContent"]}]})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, dict(self.headers), payload))
                if self.path == "/v1/images/generations":
                    self.send_json({"data": [{"b64_json": encoded}]})
                else:
                    self.send_json({"candidates": [{"content": {"parts": [
                        {"inlineData": {"mimeType": "image/png", "data": encoded}}]}}]})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        root = "http://127.0.0.1:{}".format(server.server_port)
        session = requests.Session()
        session.trust_env = False
        try:
            for protocol, version, model in (("OpenAI", "v1", "image-test"),
                                             ("Gemini", "v1beta", "gemini-image")):
                base = root + "/" + version
                self.assertEqual(list_models(base, "local-test", protocol, session=session)[1], [model])
                _, result = generate_image(base, "local-test", model, "house", protocol, session=session)
                with Image.open(io.BytesIO(result)) as image:
                    self.assertEqual(image.size, (16, 16))
            self.assertEqual(calls[1][0], "/v1/images/generations")
            self.assertEqual(calls[1][1]["Authorization"], "Bearer local-test")
            self.assertEqual(calls[3][0], "/v1beta/models/gemini-image:generateContent")
            self.assertEqual(calls[3][1]["x-goog-api-key"], "local-test")
        finally:
            session.close()
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())
