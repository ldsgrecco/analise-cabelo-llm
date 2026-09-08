import json
import os
import re
import unicodedata
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = "gemini-3.5-flash"

app = FastAPI(title="API - Análise de Cabelo com LLM")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ldsgreccoia.com.br"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = genai.Client(api_key=API_KEY) if API_KEY else None

pending_requests = {}
session_images = {}
last_intents = {}

VALID_INTENTS = {"comprimento", "textura"}
VALID_LENGTHS = {"curto", "médio", "longo", "extralongo"}
VALID_TEXTURES = {"lisa", "ondulada", "cacheada", "crespa"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)

    return json.loads(cleaned)


def fallback_intents(message: str) -> list[str]:
    text = normalize(message)

    both_terms = [
        "tudo",
        "ambos",
        "as duas",
        "os dois",
        "os 2",
        "as 2",
        "2 analises",
        "duas analises",
        "comprimento e textura",
        "tamanho e textura",
        "tamanho e tipo",
        "como e",
        "como ele e",
        "me diz como ele e",
        "o que da para ver",
        "o que e possivel analisar",
        "quero saber de tudo",
    ]

    length_terms = [
        "comprimento",
        "conprimento",
        "comprimeto",
        "tamanho",
        "tamaho",
        "tamano",
        "curto",
        "medio",
        "longo",
        "extralongo",
    ]

    texture_terms = [
        "textura",
        "testura",
        "textrua",
        "tipo",
        "liso",
        "liza",
        "lizo",
        "ondulado",
        "onduldo",
        "cacheado",
        "cachedo",
        "caxeado",
        "crespo",
        "encaracolado",
        "enrolado",
        "cachos",
    ]

    if any(term in text for term in both_terms):
        return ["comprimento", "textura"]

    intents = []

    if any(term in text for term in length_terms):
        intents.append("comprimento")

    if any(term in text for term in texture_terms):
        intents.append("textura")

    return intents


def classify_intents(message: str) -> list[str]:
    fallback = fallback_intents(message)

    if not client:
        return fallback

    prompt = f"""
Você interpreta mensagens de um chat acadêmico de análise de cabelo.

A pessoa pode querer descobrir:
- "comprimento"
- "textura"
- ambos

Considere que o assunto permanente da conversa é cabelo. Entenda linguagem informal,
perguntas curtas e erros de grafia. Não responda ao usuário; devolva SOMENTE JSON válido.

Exemplos:
"q tamaho ta meu cabelo?" -> {{"intents":["comprimento"]}}
"ele é caxeado ou lizo?" -> {{"intents":["textura"]}}
"como ele é?" -> {{"intents":["comprimento","textura"]}}
"quero saber de tudo" -> {{"intents":["comprimento","textura"]}}
"qual a cor do meu olho?" -> {{"intents":[]}}

Mensagem: {message!r}
"""

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )

        data = parse_json(response.text or "")
        intents = data.get("intents", [])

        if not isinstance(intents, list):
            return fallback

        valid = []
        for intent in intents:
            if intent in VALID_INTENTS and intent not in valid:
                valid.append(intent)

        return valid or fallback

    except Exception:
        return fallback


def asks_for_new_photo(message: str) -> bool:
    text = normalize(message)

    phrases = [
        "outra foto",
        "nova foto",
        "outra imagem",
        "nova imagem",
        "mandar outra",
        "enviar outra",
        "trocar foto",
        "mudar foto",
    ]

    return any(phrase in text for phrase in phrases)


def feminine_texture(texture: str) -> str:
    mapping = {
        "liso": "lisa",
        "lisa": "lisa",
        "ondulado": "ondulada",
        "ondulada": "ondulada",
        "cacheado": "cacheada",
        "cacheada": "cacheada",
        "crespo": "crespa",
        "crespa": "crespa",
    }

    return mapping.get(normalize(texture), "indefinida")


def analyze_image(image_bytes: bytes, mime_type: str, intents: list[str]) -> dict:
    if not client:
        raise HTTPException(
            status_code=503,
            detail="O serviço de IA não está configurado no momento.",
        )

    requested = ", ".join(intents)

    prompt = f"""
Você é um assistente acadêmico de análise visual de cabelo.

Analise exclusivamente estes aspectos aparentes na fotografia:
- comprimento: curto, médio, longo ou extralongo
- textura: lisa, ondulada, cacheada ou crespa

A pessoa solicitou: {requested}.

Responda SOMENTE JSON válido, sem markdown, no formato:
{{
  "comprimento": "curto|médio|longo|extralongo|null",
  "textura": "lisa|ondulada|cacheada|crespa|null"
}}

Preencha apenas o que foi solicitado. Se não houver segurança visual suficiente,
use null. Não faça diagnóstico capilar, não invente características e não cite
informações fora da fotografia.
"""

    try:
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type or "image/jpeg",
        )

        response = client.models.generate_content(
            model=MODEL,
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )

        data = parse_json(response.text or "")

        length = normalize(str(data.get("comprimento") or ""))
        texture = feminine_texture(str(data.get("textura") or ""))

        if length not in VALID_LENGTHS:
            length = None

        if texture not in VALID_TEXTURES:
            texture = None

        return {
            "comprimento": length,
            "textura": texture,
        }

    except Exception as error:
        error_text = str(error)

        if "429" in error_text:
            raise HTTPException(
                status_code=429,
                detail="O serviço de IA atingiu temporariamente o limite de uso. Aguarde alguns minutos e tente novamente.",
            )

        if "503" in error_text or "UNAVAILABLE" in error_text:
            raise HTTPException(
                status_code=503,
                detail="O serviço de IA está temporariamente indisponível por alta demanda. Tente novamente em alguns minutos.",
            )

        raise HTTPException(
            status_code=503,
            detail="Não foi possível concluir a análise agora. Tente novamente.",
        )


def result_message(result: dict, intents: list[str]) -> str:
    length = result.get("comprimento")
    texture = result.get("textura")

    if intents == ["comprimento"]:
        if length:
            return f"Pela fotografia, seu cabelo aparenta ter comprimento {length}."
        return "Não foi possível identificar o comprimento com segurança nesta fotografia."

    if intents == ["textura"]:
        if texture:
            return f"Pela fotografia, seu cabelo aparenta ter textura {texture}."
        return "Não foi possível identificar a textura com segurança nesta fotografia."

    if length and texture:
        return f"Pela fotografia, seu cabelo aparenta ter comprimento {length} e textura {texture}."

    if length:
        return f"Pela fotografia, seu cabelo aparenta ter comprimento {length}. Não foi possível identificar a textura com segurança."

    if texture:
        return f"Pela fotografia, seu cabelo aparenta ter textura {texture}. Não foi possível identificar o comprimento com segurança."

    return "Não foi possível identificar o comprimento nem a textura com segurança nesta fotografia."


def follow_up_message(intents: list[str]) -> str:
    if set(intents) == {"comprimento", "textura"}:
        return "Quer continuar? Você pode enviar outra foto para uma nova análise."

    if intents == ["comprimento"]:
        return "Se quiser, também posso identificar a textura aparente nesta mesma foto ou analisar outra fotografia."

    return "Se quiser, também posso identificar o comprimento aparente nesta mesma foto ou analisar outra fotografia."


def waiting_photo_message(intents: list[str]) -> str:
    if set(intents) == {"comprimento", "textura"}:
        return "Certo. Vou analisar o comprimento e a textura aparente do seu cabelo. Envie uma foto em que o cabelo esteja visível."

    if intents == ["comprimento"]:
        return "Certo. Vou analisar o comprimento do seu cabelo. Envie uma foto em que o cabelo esteja visível."

    return "Certo. Vou analisar a textura aparente do seu cabelo. Envie uma foto em que o cabelo esteja visível."


@app.get("/")
def root():
    return {"message": "API de Análise de Cabelo com LLM"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_configurado": bool(API_KEY),
    }


@app.post("/analisar")
async def analisar(image: UploadFile = File(...)):
    image_bytes = await image.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Envie uma imagem válida.")

    intents = ["comprimento", "textura"]
    result = analyze_image(image_bytes, image.content_type or "image/jpeg", intents)

    return {
        "message": result_message(result, intents),
        "resultado": result,
    }


@app.post("/api/chat")
async def chat(
    message: str = Form(""),
    session_id: str = Form(""),
    image: UploadFile | None = File(None),
):
    message = message.strip()
    session_id = session_id.strip() or str(uuid4())
    normalized_message = normalize(message)
    closing_text = re.sub(r"[^\w\s]", "", normalized_message).strip()

    closing_messages = {
        "nao",
        "nao obrigado",
        "nao obrigada",
        "nao agradeco",
        "nao valeu",
        "nao preciso de mais",
        "nao quero mais",
        "era isso",
        "isso e tudo",
    }

    if closing_text in closing_messages:
        pending_requests.pop(session_id, None)
        session_images.pop(session_id, None)
        last_intents.pop(session_id, None)

        return {
            "session_id": session_id,
            "message": "Por nada! Quando quiser analisar outra foto, estarei por aqui.",
            "status": "encerrado",
        }

    affirmative_messages = {
        "quero",
        "sim",
        "claro",
        "vamos",
        "continuar",
        "quero continuar",
        "sim quero",
    }

    if (
        image is None
        and closing_text in affirmative_messages
        and session_id in last_intents
    ):
        pending_requests[session_id] = last_intents[session_id]
        session_images.pop(session_id, None)

        return {
            "session_id": session_id,
            "message": "Ótimo! Envie outra foto quando quiser fazer uma nova análise.",
            "status": "aguardando_foto",
        }

    if image is not None:
        image_bytes = await image.read()

        if not image_bytes:
            raise HTTPException(status_code=400, detail="Envie uma imagem válida.")

        session_images[session_id] = (
            image_bytes,
            image.content_type or "image/jpeg",
        )

    if asks_for_new_photo(message):
        previous_intents = last_intents.get(session_id)

        if previous_intents:
            pending_requests[session_id] = previous_intents
            session_images.pop(session_id, None)

            return {
                "session_id": session_id,
                "message": "Claro. Envie a nova foto e farei novamente a análise solicitada.",
                "status": "aguardando_foto",
            }

        return {
            "session_id": session_id,
            "message": "Claro. Envie a nova foto e escreva o que deseja descobrir: comprimento, textura aparente ou ambos.",
            "status": "aguardando_intencao",
        }

    intents = []

    if message:
        intents = classify_intents(message)

        if not intents:
            return {
                "session_id": session_id,
                "message": "Posso identificar o comprimento, a textura aparente ou ambos. Escreva o que deseja descobrir e envie uma foto em que o cabelo esteja visível.",
                "status": "aguardando_intencao",
            }

        pending_requests[session_id] = intents

    elif session_id in pending_requests:
        intents = pending_requests[session_id]

    if not intents and session_id in pending_requests:
        intents = pending_requests[session_id]

    if not intents and session_id in last_intents and image is not None:
        intents = last_intents[session_id]
        pending_requests[session_id] = intents

    stored_image = session_images.get(session_id)

    if not stored_image:
        if intents:
            return {
                "session_id": session_id,
                "message": waiting_photo_message(intents),
                "status": "aguardando_foto",
            }

        return {
            "session_id": session_id,
            "message": "Olá! O que você gostaria de descobrir sobre seu cabelo? Posso identificar o comprimento aparente, a textura aparente ou os dois. Envie uma foto quando estiver pronto.",
            "status": "aguardando_intencao",
        }

    if not intents:
        return {
            "session_id": session_id,
            "message": "Recebi a foto. Agora escreva se deseja identificar o comprimento, a textura aparente ou ambos.",
            "status": "aguardando_intencao",
        }

    image_bytes, mime_type = stored_image
    result = analyze_image(image_bytes, mime_type, intents)

    pending_requests.pop(session_id, None)
    last_intents[session_id] = intents

    return {
        "session_id": session_id,
        "message": result_message(result, intents),
        "follow_up": follow_up_message(intents),
        "status": "concluido",
        "resultado": result,
    }
