"""Testes HTTP locais: o cliente Gemini é substituído e a rede externa é bloqueada."""

import json
import os
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

# Não lê .env nem cria um cliente real, mesmo se existir uma chave na máquina.
with patch("dotenv.load_dotenv"), patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
    from backend import main


OUT_OF_SCOPE = (
    "Minha função é identificar apenas o comprimento e a textura aparente do cabelo, "
    "a partir de uma fotografia. Não consigo responder a perguntas sobre outros "
    "assuntos. Se desejar, envie uma foto e me diga qual dessas características "
    "gostaria de analisar."
)
INCOMPLETE = (
    "Claro! Posso identificar o comprimento, a textura aparente ou ambos. "
    "Qual dessas características você gostaria de analisar? Depois, é só enviar "
    "uma fotografia em que seu cabelo esteja visível."
)
PHOTO = b"foto-simulada-1"
NEW_PHOTO = b"foto-simulada-2"


class ChatTests(unittest.TestCase):
    def setUp(self):
        for state in (main.session_images, main.pending_requests, main.last_intents, main.offered_intents):
            state.clear()
        main.new_photo_offers.clear()
        self.addCleanup(self.clear_state)
        original_connect = socket.socket.connect

        def local_connect(sock, address):
            # O event loop do Windows usa um socket de loopback internamente.
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return original_connect(sock, address)
            raise AssertionError("Rede externa proibida nos testes")

        self.enterContext(patch("socket.socket.connect", new=local_connect))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("Rede externa proibida nos testes")))
        self.intent_reply = {"status": "analise", "intents": ["comprimento"]}
        self.image_reply = {"comprimento": "longo", "textura": "cacheada"}
        self.classification_error = None
        self.image_error = None
        self.images = []
        self.classifications = []
        self.gemini = Mock()
        self.gemini.models.generate_content.side_effect = self.generate
        self.enterContext(patch.object(main, "client", self.gemini))
        self.http = self.enterContext(TestClient(main.app))

    def clear_state(self):
        for state in (main.session_images, main.pending_requests, main.last_intents, main.offered_intents):
            state.clear()
        main.new_photo_offers.clear()

    def generate(self, *, model, contents, config):
        self.assertEqual(model, main.MODEL)
        self.assertEqual(config.response_mime_type, "application/json")
        if isinstance(contents, str):
            self.classifications.append(contents)
            if self.classification_error:
                raise self.classification_error
            reply = self.intent_reply
        else:
            prompt, part = contents
            self.images.append((part.inline_data.data, part.inline_data.mime_type, prompt))
            if self.image_error:
                raise self.image_error
            reply = self.image_reply
        return SimpleNamespace(text=reply if isinstance(reply, str) else json.dumps(reply))

    def send(self, message="", photo=None, session="session-a", expected_code=200):
        files = {"image": ("cabelo.png", photo, "image/png")} if photo is not None else None
        response = self.http.post(
            "/api/chat", data={"message": message, "session_id": session}, files=files,
        )
        self.assertEqual(response.status_code, expected_code, response.text)
        return response.json()

    def analyze(self, intents=None, session="session-a", photo=PHOTO):
        intents = intents or ["comprimento"]
        self.intent_reply = {"status": "analise", "intents": intents}
        response = self.send(" e ".join(intents), photo, session)
        self.assertEqual(response["status"], "concluido")
        return response

    def test_short_confirmations_analyze_complement_in_same_photo(self):
        for first, complement in (("comprimento", "textura"), ("textura", "comprimento")):
            for affirmative in ("quero", "sim", "quero sim", "claro", "SIM!", "Quero, sim."):
                with self.subTest(first=first, affirmative=affirmative):
                    self.clear_state()
                    self.analyze([first])
                    calls_before = len(self.classifications)
                    response = self.send(affirmative)
                    self.assertEqual(response["status"], "concluido")
                    self.assertIn(f"A pessoa solicitou: {complement}.", self.images[-1][2])
                    self.assertEqual(self.images[-1][:2], (PHOTO, "image/png"))
                    self.assertEqual(main.session_images["session-a"][0], PHOTO)
                    self.assertEqual(len(self.classifications), calls_before)

    def test_explicit_complement_reuses_photo(self):
        self.analyze()
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        self.assertEqual(self.send("E a textura?")["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)
        self.assertIn("A pessoa solicitou: textura.", self.images[-1][2])

    def test_confirmation_without_offer_does_not_invent_choice(self):
        for text in ("sim", "quero", "quero sim", "claro"):
            with self.subTest(text=text):
                response = self.send(text)
                self.assertEqual(response["message"], INCOMPLETE)
        self.assertEqual(self.images, [])
        self.gemini.models.generate_content.assert_not_called()

    def test_confirmation_after_both_requests_new_photo_and_reanalyzes(self):
        self.analyze(["comprimento", "textura"])
        response = self.send("sim")
        self.assertEqual(response["status"], "aguardando_foto")
        self.assertNotIn("session-a", main.session_images)
        self.assertEqual(len(self.images), 1)
        self.assertEqual(self.send(photo=NEW_PHOTO)["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)
        self.assertIn("comprimento, textura", self.images[-1][2])

    def test_confirmation_while_waiting_does_not_lose_requested_intent(self):
        self.assertEqual(self.send("comprimento")["status"], "aguardando_foto")
        self.assertEqual(self.send("quero sim")["status"], "aguardando_foto")
        self.assertEqual(self.send(photo=PHOTO)["status"], "concluido")
        self.assertIn("A pessoa solicitou: comprimento.", self.images[-1][2])

    def test_photo_only_after_request(self):
        self.send("comprimento")
        response = self.send(photo=PHOTO)
        self.assertEqual(response["status"], "concluido")
        self.assertEqual(len(self.classifications), 1)

    def test_photo_first_waits_for_choice(self):
        self.assertEqual(self.send(photo=PHOTO)["status"], "aguardando_intencao")
        self.assertEqual(self.images, [])
        self.assertEqual(self.send("comprimento")["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)

    def test_request_new_photo_discards_old_and_retains_intent(self):
        self.analyze()
        self.intent_reply = {"status": "incompleto", "intents": []}
        response = self.send("quero enviar outra foto")
        self.assertEqual(response["status"], "aguardando_foto")
        self.assertNotIn("session-a", main.session_images)
        self.assertEqual(self.send("sim")["status"], "aguardando_foto")
        self.assertEqual(len(self.images), 1)
        self.assertEqual(self.send(photo=NEW_PHOTO)["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)

    def test_request_new_photo_before_any_analysis_discards_old(self):
        self.send(photo=PHOTO)
        self.intent_reply = {"status": "incompleto", "intents": []}
        self.assertEqual(self.send("nova imagem")["status"], "aguardando_intencao")
        self.assertNotIn("session-a", main.session_images)

    def test_new_photo_attached_to_replacement_message_is_used(self):
        self.analyze()
        self.intent_reply = {"status": "incompleto", "intents": []}
        self.assertEqual(self.send("outra foto", NEW_PHOTO)["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)
        self.assertEqual(main.session_images["session-a"][0], NEW_PHOTO)

    def test_photo_only_replaces_previous_image(self):
        self.analyze()
        self.assertEqual(self.send(photo=NEW_PHOTO)["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)

    def test_confirmation_with_new_photo_uses_new_photo(self):
        self.analyze()
        self.assertEqual(self.send("quero sim", NEW_PHOTO)["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)
        self.assertIn("A pessoa solicitou: textura.", self.images[-1][2])

    def test_new_photo_with_explicit_choice_overrides_previous_choice(self):
        self.analyze()
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        self.send("quero a textura em outra foto")
        self.send(photo=NEW_PHOTO)
        self.assertIn("A pessoa solicitou: textura.", self.images[-1][2])
        self.assertEqual(self.images[-1][0], NEW_PHOTO)

    def test_out_of_scope_returns_exact_approved_message(self):
        self.intent_reply = {"status": "fora_escopo", "intents": []}
        for message in ("Qual a capital da França?", "Qual o tamanho do Sol?", "Qual a cor do meu cabelo?", "Como é o clima?"):
            with self.subTest(message=message):
                response = self.send(message, PHOTO)
                self.assertEqual(response["status"], "fora_escopo")
                self.assertEqual(response["message"], OUT_OF_SCOPE)
        self.assertEqual(self.images, [])

    def test_model_scope_decision_is_not_overridden_by_keyword_fallback(self):
        self.intent_reply = {"status": "fora_escopo", "intents": ["comprimento"]}
        response = self.send("Qual o comprimento do rio?", PHOTO)
        self.assertEqual(response["message"], OUT_OF_SCOPE)
        self.assertEqual(self.images, [])

    def test_generic_request_never_assumes_both_even_with_photo(self):
        self.intent_reply = {"status": "analise", "intents": ["comprimento", "textura"]}
        for text in ("Quero saber sobre meu cabelo", "Como é meu cabelo?", "Analise meu cabelo"):
            for photo in (None, PHOTO):
                with self.subTest(text=text, photo=photo):
                    response = self.send(text, photo)
                    self.assertEqual(response["status"], "aguardando_intencao")
                    self.assertEqual(response["message"], INCOMPLETE)
        self.gemini.models.generate_content.assert_not_called()

    def test_model_can_recognize_other_incomplete_phrasings(self):
        self.intent_reply = {"status": "incompleto", "intents": []}
        response = self.send("Me ajuda a entender meu cabelo?", PHOTO)
        self.assertEqual(response["message"], INCOMPLETE)
        self.assertEqual(len(self.classifications), 1)
        self.assertEqual(self.images, [])

    def test_generic_request_then_choice_reuses_photo(self):
        self.send("Quero saber sobre meu cabelo", PHOTO)
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        self.assertEqual(self.send("textura")["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)

    def test_generic_request_clears_old_offer_and_requires_new_choice(self):
        self.analyze()
        self.send("Quero saber sobre meu cabelo")
        self.assertEqual(self.send("sim")["status"], "aguardando_intencao")
        self.assertEqual(self.send(photo=NEW_PHOTO)["status"], "aguardando_intencao")
        self.assertEqual(len(self.images), 1)

    def test_off_topic_detour_keeps_photo_but_clears_stale_offer(self):
        self.analyze()
        self.intent_reply = {"status": "fora_escopo", "intents": []}
        self.send("Quanto é 2 + 2?")
        self.assertEqual(self.send("sim")["status"], "aguardando_intencao")
        self.assertEqual(main.session_images["session-a"][0], PHOTO)
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        self.assertEqual(self.send("textura")["status"], "concluido")

    def test_sessions_do_not_share_photo_or_offer(self):
        self.analyze()
        self.assertEqual(self.send("sim", session="session-b")["status"], "aguardando_intencao")
        self.assertEqual(self.send("comprimento", session="session-b")["status"], "aguardando_foto")
        self.assertNotIn("session-b", main.session_images)
        self.assertEqual(self.send("sim")["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)

    def test_empty_upload_does_not_overwrite_photo(self):
        self.analyze()
        self.send("outra foto", b"", expected_code=400)
        self.assertEqual(main.session_images["session-a"][0], PHOTO)

    def test_declining_clears_offer_but_retains_photo_for_explicit_request(self):
        self.analyze()
        self.assertEqual(self.send("Não, obrigado!")["status"], "encerrado")
        self.assertEqual(self.send("sim")["status"], "aguardando_intencao")
        self.assertEqual(main.session_images["session-a"][0], PHOTO)
        self.assertEqual(self.send("comprimento")["status"], "concluido")

    def test_session_id_is_generated(self):
        response = self.send("comprimento", session="")
        self.assertTrue(response["session_id"])
        self.assertEqual(response["status"], "aguardando_foto")

    def test_missing_gemini_configuration_does_not_fabricate_result(self):
        with patch.object(main, "client", None):
            response = self.send("comprimento", PHOTO, expected_code=503)
        self.assertIn("não está configurado", response["detail"])

    def test_image_service_errors_and_retry_keep_photo_and_intent(self):
        for error, code in (("429 quota", 429), ("503 UNAVAILABLE", 503), ("unknown", 503)):
            with self.subTest(error=error):
                self.clear_state()
                self.image_error = RuntimeError(error)
                self.send("comprimento", PHOTO, expected_code=code)
                self.assertEqual(main.session_images["session-a"][0], PHOTO)
                self.image_error = None
                self.assertEqual(self.send("sim")["status"], "concluido")

    def test_unreadable_image_result_does_not_invent_features(self):
        self.image_reply = {"comprimento": None, "textura": None}
        response = self.analyze(["comprimento", "textura"])
        self.assertIn("Não foi possível identificar", response["message"])

    def test_medium_length_remains_valid(self):
        self.image_reply = {"comprimento": "médio", "textura": None}
        self.assertEqual(self.analyze()["resultado"]["comprimento"], "médio")

    def test_old_offer_does_not_override_pending_after_failed_new_image(self):
        self.analyze(["comprimento"])
        self.image_error = RuntimeError("503 UNAVAILABLE")
        self.send(photo=NEW_PHOTO, expected_code=503)
        self.image_error = None
        response = self.send("sim")
        self.assertEqual(response["status"], "concluido")
        self.assertIn("A pessoa solicitou: comprimento.", self.images[-1][2])
        self.assertEqual(self.images[-1][0], NEW_PHOTO)

    def test_negated_new_photo_keeps_original_and_uses_explicit_choice(self):
        self.analyze(["comprimento"])
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        response = self.send("Não quero outra foto, quero a textura na mesma")
        self.assertEqual(response["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)
        self.assertIn("A pessoa solicitou: textura.", self.images[-1][2])

    def test_local_fallback_recognizes_polite_hair_requests(self):
        with patch.object(main, "client", None):
            self.assertEqual(self.send("Quero saber sobre meu cabelo, por favor")["message"], INCOMPLETE)
            self.assertEqual(
                self.send("Pode identificar o comprimento do meu cabelo para mim?")["status"],
                "aguardando_foto",
            )

    def test_confirmation_after_both_not_confused_by_off_topic_detour(self):
        self.analyze(["comprimento", "textura"])
        self.intent_reply = {"status": "fora_escopo", "intents": []}
        self.send("Qual o endereço do aeroporto?")
        self.assertEqual(self.send("sim")["message"], INCOMPLETE)
        self.assertEqual(main.session_images["session-a"][0], PHOTO)

    def test_fallback_understands_negation_of_new_photo(self):
        self.analyze(["comprimento"])
        with patch.object(main, "client", None):
            request = main.classify_request("Não quero outra foto, quero a textura na mesma")
            self.assertEqual(request, {"status": "analise", "intents": ["textura"]})
        self.intent_reply = {"status": "analise", "intents": ["textura"]}
        self.assertEqual(self.send("Não quero outra foto, quero a textura na mesma")["status"], "concluido")
        self.assertEqual(self.images[-1][0], PHOTO)

    def test_new_photo_with_confirmation_after_both_analyzes_directly(self):
        self.analyze(["comprimento", "textura"])
        response = self.send("sim", NEW_PHOTO)
        self.assertEqual(response["status"], "concluido")
        self.assertEqual(self.images[-1][0], NEW_PHOTO)
        self.assertIn("comprimento, textura", self.images[-1][2])

    def test_original_analisar_endpoint(self):
        response = self.http.post("/analisar", files={"image": ("cabelo.png", PHOTO, "image/png")})
        self.assertEqual(response.status_code, 200)
        self.assertIn("longo e textura cacheada", response.json()["message"])
        self.assertEqual(self.images[-1][0], PHOTO)

    def test_health_and_root(self):
        self.assertEqual(self.http.get("/").status_code, 200)
        self.assertEqual(self.http.get("/health").json()["status"], "ok")

    def test_classifier_falls_back_on_service_error_or_malformed_response(self):
        for reply in ("não é JSON", [], {"status": "analise", "intents": "textura"}, {"status": "analise", "intents": [{}]}):
            with self.subTest(reply=reply):
                self.intent_reply = reply
                self.assertEqual(main.classify_request("q tamaho ta meu cabelo?")["intents"], ["comprimento"])
        self.classification_error = RuntimeError("503 UNAVAILABLE")
        self.assertEqual(main.classify_request("ele é caxeado ou lizo?")["intents"], ["textura"])

    def test_negation_selects_only_affirmed_feature_without_gemini(self):
        with patch.object(main, "client", None):
            cases = (
                ("Não quero saber o comprimento. Quero saber apenas a textura do meu cabelo.", "textura"),
                ("Não quero textura, quero só comprimento", "comprimento"),
                ("Não quero comprimento, só textura", "textura"),
            )
            for text, expected in cases:
                with self.subTest(text=text):
                    self.clear_state()
                    answer = self.send(text)
                    self.assertEqual(answer["status"], "aguardando_foto")
                    self.assertEqual(main.pending_requests["session-a"], [expected])
            self.clear_state()
            answer = self.send("Não quero saber o comprimento")
            self.assertEqual(answer["status"], "aguardando_intencao")
            self.assertEqual(answer["message"], INCOMPLETE)

    def test_negation_is_not_overridden_by_gemini(self):
        self.intent_reply = {"status": "analise", "intents": ["comprimento", "textura"]}
        answer = self.send("Não quero comprimento, apenas textura")
        self.assertEqual(answer["status"], "aguardando_foto")
        self.assertEqual(main.pending_requests["session-a"], ["textura"])

    def test_fallback_does_not_confuse_unrelated_topics_with_hair(self):
        with patch.object(main, "client", None):
            for text in ("Qual o comprimento do rio?", "Qual o tamanho do Sol?", "Como é o clima?", "Qual a cor do meu cabelo?", "Qual meu tipo sanguíneo?"):
                with self.subTest(text=text):
                    self.assertEqual(self.send(text)["message"], OUT_OF_SCOPE)

    def test_fallback_preserves_original_informal_requests(self):
        with patch.object(main, "client", None):
            for text, intents in (
                ("q tamaho ta meu cabelo?", ["comprimento"]),
                ("Quero saber o comprimento do meu cabelo", ["comprimento"]),
                ("ele é caxeado ou lizo?", ["textura"]),
                ("quero os 2", ["comprimento", "textura"]),
                ("quero a textura em outra foto", ["textura"]),
            ):
                with self.subTest(text=text):
                    self.assertEqual(main.classify_request(text), {"status": "analise", "intents": intents})


if __name__ == "__main__":
    unittest.main()

# Teste de regressão adicional da linguagem informal de uma demonstração.
class TipoCabeloGenericTests(unittest.TestCase):
    def test_tipo_do_meu_cabelo_pede_esclarecimento(self):
        import backend.main as main
        for text in ("analise o tipo do meu cabelo", "quero saber o tipo do meu cabelo"):
            with self.subTest(text=text):
                self.assertEqual(main.fallback_request(text), {"status": "incompleto", "intents": []})
