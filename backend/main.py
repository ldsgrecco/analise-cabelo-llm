import base64
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
import httpx

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL = "gemini-3.1-flash-lite"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "qwen/qwen3.8-27b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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
offered_intents = {}
new_photo_offers = set()
# Resultado acumulado das caracteristicas confirmadas para a foto atual de cada sessao.
completed_analyses = {}

VALID_INTENTS = {"comprimento", "textura"}
VALID_LENGTHS = {"curto", "médio", "longo", "extralongo"}
VALID_TEXTURES = {"lisa", "ondulada", "cacheada", "crespa"}

OUT_OF_SCOPE_MESSAGE = (
    "Minha função é identificar apenas o comprimento e a textura aparente do cabelo, "
    "a partir de uma fotografia. Não consigo responder a perguntas sobre outros "
    "assuntos. Se desejar, envie uma foto e me diga qual dessas características "
    "gostaria de analisar."
)
INCOMPLETE_REQUEST_MESSAGE = (
    "Claro! Posso identificar o comprimento, a textura aparente ou ambos. "
    "Qual dessas características você gostaria de analisar? Depois, é só enviar "
    "uma fotografia em que seu cabelo esteja visível."
)


def contains_term(text: str, terms: list[str]) -> bool:
    return any(re.search(r"\b" + re.escape(term) + r"\b", text) for term in terms)


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

    if contains_term(text, both_terms):
        return ["comprimento", "textura"]

    intents = []

    if contains_term(text, length_terms):
        intents.append("comprimento")

    if contains_term(text, texture_terms):
        intents.append("textura")

    return intents


def is_generic_request(message: str) -> bool:
    text = re.sub(r"[^\w\s]", "", normalize(message)).strip()
    text = re.sub(r"(?:\s+(?:por favor|por gentileza|para mim|pra mim))+$", "", text).strip()
    return bool(re.fullmatch(
        r"(?:(?:eu )?(?:quero|gostaria de) saber (?:mais )?(?:sobre )?"
        r"(?:o )?(?:meu )?cabelo|"
        r"(?:analise|analisar|avalie|avaliar) (?:o )?(?:meu )?cabelo|"
        r"como (?:e|esta|ta) (?:(?:o )?meu cabelo|ele)|"
        r"o que (?:da para ver|e possivel analisar))",
        text,
    ))


def resolve_negated_intents(message: str) -> dict | None:
    """Trata negações explícitas sem transformar palavra negada em intenção.

    Evita concluir 'comprimento' a partir de 'não quero comprimento'.
    Uma negação sem escolha positiva pede esclarecimento.
    """
    text = normalize(message)
    length = r"(?:comprimento|conprimento|comprimeto|tamanho|tamaho|tamano)"
    texture = r"(?:textura|testura|textrua|tipo)"
    negation = r"\b(?:nao\s+(?:quero|desejo|preciso|gostaria\s+de)(?:\s+saber)?(?:\s+(?:o|a|do|da))?|sem)\s+"
    neg_length = bool(re.search(negation + length + r"\b", text))
    neg_texture = bool(re.search(negation + texture + r"\b", text))
    if not (neg_length or neg_texture):
        return None

    positive_text = re.sub(negation + r"(?:" + length + "|" + texture + r")\b", " ", text)
    # Opcionalmente distingue a intenção afirmada depois de uma vírgula/contraste.
    positive = fallback_intents(positive_text)
    positive = [item for item in positive
                if not ((item == "comprimento" and neg_length) or
                        (item == "textura" and neg_texture))]
    if not positive:
        return {"status": "incompleto", "intents": []}
    return {"status": "analise", "intents": positive}


def fallback_request(message: str) -> dict:
    """Interpretação local conservadora para indisponibilidade da Gemini."""
    text = normalize(message)
    negated = resolve_negated_intents(message)
    if negated is not None:
        return negated
    if re.fullmatch(r"(?:(?:quero|gostaria de|pode|por favor)\s+)*(?:analise|analisa|analisar|avalie|avaliar|qual e|quero saber)\s+(?:(?:o|a)\s+)?tipo\s+(?:do\s+)?(?:meu\s+)?cabelo", text):
        return {"status": "incompleto", "intents": []}
    intents = fallback_intents(message)
    # Aceite somente o vocabulário das perguntas curtas suportadas.
    # 'Tamanho do Sol', por exemplo, não é uma análise capilar.
    short_request_words = set(
        "eu quero gostaria de saber qual o a os as e ou meu ele esta ta tem "
        "q que um uma por favor pode me dizer diz identificar analisar analise analisa avalie avaliar verificar verifique aparente "
        "cabelo comprimento conprimento comprimeto tamanho tamaho tamano curto "
        "medio longo extralongo textura testura textrua tipo liso liza lizo "
        "ondulado onduldo cacheado cachedo caxeado crespo encaracolado enrolado "
        "cachos tudo ambos duas dois 2 analises sobre se do da dos das "
        "foto fotografia imagem outra nova uma enviar mandar trocar mudar "
        "em na nesta nessa agora novamente para mim pra gentileza conseguir consegue "
        "nao sem mesma dessa desta anterior "
        "poderia favor por verificar me ajude me ajuda meu cabelo".split()
    )
    words = set(re.findall(r"\w+", text))
    unsupported = contains_term(text, [
        "cor", "coloracao", "volume", "queda", "tratamento", "diagnostico",
        "olho", "olhos", "pele", "barba", "unha", "unhas",
    ])
    if intents and words <= short_request_words and not unsupported:
        return {"status": "analise", "intents": intents}
    if is_generic_request(message) or not text or (asks_for_new_photo(message) and not unsupported):
        return {"status": "incompleto", "intents": []}
    return {"status": "fora_escopo", "intents": []}


def classify_request(message: str) -> dict:
    fallback = fallback_request(message)
    # REGRA_HAIR_INTENTS_LOCAL_20261123
    texto = normalize(message)
    palavras = set(re.findall(r"\w+", texto))
    bloqueadas = {"cor", "coloracao", "volume", "queda", "tratamento", "diagnostico", "olho", "olhos", "pele", "barba", "unhas", "sol"}
    menciona_cabelo = bool(palavras & {"cabelo", "fios", "madeixas"})
    termos_comprimento = {"comprimento", "tamanho", "curto", "medio", "longo", "extralongo"}
    termos_textura = {"textura", "liso", "ondulado", "cacheado", "crespo"}
    if menciona_cabelo and not (palavras & bloqueadas):
        generico = re.sub(r"[^\w\s]", "", texto).strip()
        generico = re.sub(r"(?:\s+(?:por favor|por gentileza|para mim|pra mim))+$", "", generico).strip()
        if re.fullmatch(r"(?:analise|analisa|analisar|avalie|avaliar)\s+(?:(?:esse|este|esta|o|a|meu|minha)\s+)?cabelo", generico):
            return {"status": "analise", "intents": ["comprimento", "textura"]}
        if palavras & (termos_comprimento | termos_textura):
            reconhecidas = fallback_intents(message)
            if reconhecidas and resolve_negated_intents(message) is None:
                return {"status": "analise", "intents": reconhecidas}


    # Negação explícita deve prevalecer sobre sugestões do modelo.
    negated = resolve_negated_intents(message)
    if negated is not None:
        return negated

    # Pedidos genéricos conhecidos sempre exigem uma escolha explícita.
    if is_generic_request(message) or re.fullmatch(r"(?:analise|analisa|quero saber|qual e)\s+(?:o\s+)?tipo\s+(?:do\s+)?(?:meu\s+)?cabelo", normalize(message)):
        return {"status": "incompleto", "intents": []}

    if not client:
        return fallback

    prompt = f"""
Você interpreta mensagens de um chat acadêmico de análise de cabelo.

A pessoa pode querer descobrir:
- "comprimento"
- "textura"
- ambos

Entenda linguagem informal, perguntas curtas e erros de grafia. Não presuma que
perguntas sobre outros assuntos se referem a cabelo. Apenas comprimento e textura
aparente do cabelo estão no escopo; cor, volume, tratamentos e outros assuntos não.
Pedidos genéricos sobre cabelo não autorizam analisar ambas as características.
Use "analise" para uma escolha explícita, "incompleto" quando falta escolher a
característica, ou "fora_escopo" para pedidos fora dessas duas análises.
Se houver também um pedido fora do escopo, use "fora_escopo".
Não responda ao usuário; devolva SOMENTE JSON válido com status e intents.

Exemplos:
"q tamaho ta meu cabelo?" -> {{"status":"analise","intents":["comprimento"]}}
"ele é caxeado ou lizo?" -> {{"status":"analise","intents":["textura"]}}
"como ele é?" -> {{"status":"incompleto","intents":[]}}
"Quero saber sobre meu cabelo" -> {{"status":"incompleto","intents":[]}}
"quero saber de tudo" -> {{"status":"analise","intents":["comprimento","textura"]}}
"qual a cor do meu olho?" -> {{"status":"fora_escopo","intents":[]}}
"qual o tamanho do Sol?" -> {{"status":"fora_escopo","intents":[]}}
"qual a cor do meu cabelo?" -> {{"status":"fora_escopo","intents":[]}}
"quero enviar outra foto" -> {{"status":"incompleto","intents":[]}}

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
        if not isinstance(data, dict):
            return fallback

        status = data.get("status")
        if status in ("incompleto", "fora_escopo"):
            # Uma recusa válida da LLM não pode ser sobrescrita por palavras-chave.
            return {"status": status, "intents": []}

        intents = data.get("intents", [])

        if status != "analise" or not isinstance(intents, list):
            return fallback

        valid = []
        for intent in intents:
            if isinstance(intent, str) and intent in VALID_INTENTS and intent not in valid:
                valid.append(intent)

        return {"status": "analise", "intents": valid} if valid else fallback

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

    # “Não quero outra foto, quero a textura na mesma” não é troca.
    if re.search(r"\b(?:nao|sem)\b.{0,55}\b(?:outra|nova|trocar|mudar)\s+(?:foto|imagem)\b", text):
        return False
    if re.search(r"\b(?:na mesma|dessa mesma|desta mesma|na fotografia anterior)\b", text):
        return False
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


def analyze_image_gemini(image_bytes: bytes, mime_type: str, intents: list[str]) -> dict:
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
        if length == "medio":
            length = "médio"
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


def analyze_image_groq(image_bytes: bytes, mime_type: str, intents: list[str]) -> dict:
    """Executa Qwen via Groq, em nuvem, somente para análise visual."""
    if not GROQ_API_KEY:
        raise ValueError("Chave Groq não configurada")
    if not image_bytes or len(image_bytes) > 15 * 1024 * 1024:
        raise ValueError("Fotografia vazia ou maior que o limite de segurança")
    if mime_type not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("Formato de imagem não suportado no experimento")

    requested = ", ".join(intents)
    prompt = (
        "Analise APENAS o cabelo visível na fotografia. "
        "Classifique somente as características solicitadas: "
        f"{requested}. "
        "Comprimento permitido: curto, médio, longo, extralongo. "
        "Textura permitida: lisa, ondulada, cacheada, crespa. "
        "Se não for possível verificar, use null. "
        "Não faça diagnóstico, nem infira comprimento real dos fios esticados. "
        "Responda APENAS um objeto JSON com as chaves "
        "comprimento e textura, usando null nas características não solicitadas."
    )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": GROQ_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime_type};base64,{encoded}"
                }},
            ],
        }],
        "temperature": 0,
        "max_completion_tokens": 256,
        "reasoning_effort": "none",
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    response = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json=payload,
        timeout=25.0,
    )
    response.raise_for_status()
    body = response.json()
    text = body["choices"][0]["message"].get("content") or ""
    data = parse_json(text)
    if not isinstance(data, dict):
        raise ValueError("A Groq não retornou um objeto JSON")
    length = normalize(str(data.get("comprimento") or ""))
    if length == "medio":
        length = "médio"
    texture = feminine_texture(str(data.get("textura") or ""))
    if length not in VALID_LENGTHS:
        length = None
    if texture not in VALID_TEXTURES:
        texture = None
    result = {"comprimento": length, "textura": texture}
    if any(not result.get(intent) for intent in intents):
        raise ValueError("Qwen não identificou todas as características pedidas")
    return result


def analyze_image(image_bytes: bytes, mime_type: str, intents: list[str]) -> dict:
    """Groq/Qwen primeiro; Gemini se houver falha ou resultado inválido.

    A intenção continua interpretada pela Gemini ou pelas regras locais
    existentes, para preservar a conversa e a transcrição por voz.
    """
    try:
        result = analyze_image_groq(image_bytes, mime_type, intents)
        result["ia_utilizada"] = "Qwen 3.8 27B (Groq)"
        return result
    except Exception as error:
        # Não registrar mensagem da exceção: pode conter detalhes do serviço.
        print(f"[LLM experimental] Falha no Qwen ({type(error).__name__}); tentando Gemini.")
        result = analyze_image_gemini(image_bytes, mime_type, intents)
        result["ia_utilizada"] = "Gemini 3.1 Flash-Lite (fallback)"
        return result


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
    """Oferece apenas a característica que ainda nao foi analisada."""
    remaining = {"comprimento", "textura"} - set(intents)
    if not remaining:
        return "Gostaria de analisar outra fotografia?"
    if remaining == {"textura"}:
        return "Se quiser, também posso identificar a textura aparente nesta mesma foto ou analisar outra fotografia."
    return "Se quiser, também posso identificar o comprimento aparente nesta mesma foto ou analisar outra fotografia."


def completed_summary(results: dict) -> str:
    """Resumo exibido uma unica vez quando as duas caracteristicas estiverem disponiveis."""
    return (
        "Concluí a análise desta fotografia: "
        f"comprimento {results['comprimento']} e textura {results['textura']}. "
        "Gostaria de analisar outra fotografia?"
    )


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

    if image is None and closing_text in closing_messages:
        pending_requests.pop(session_id, None)
        last_intents.pop(session_id, None)
        offered_intents.pop(session_id, None)
        new_photo_offers.discard(session_id)
        completed_analyses.pop(session_id, None)
        session_images.pop(session_id, None)

        return {
            "session_id": session_id,
            "message": "Obrigado por utilizar a análise de cabelo! Até a próxima. Quando quiser continuar, é só enviar uma nova mensagem ou outra foto.",
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
        "quero sim",
    }

    # Confirmação acompanhada de nova imagem: aproveitar a oferta apenas
    # nesta requisição, sem deixá-la ativa após uma possível falha.
    previous_offer = list(offered_intents.get(session_id, []))
    previous_new_photo_offer = session_id in new_photo_offers
    if image is not None:
        image_bytes = await image.read()

        if not image_bytes:
            raise HTTPException(status_code=400, detail="Envie uma imagem válida.")

        session_images[session_id] = (
            image_bytes,
            image.content_type or "image/jpeg",
        )
        completed_analyses.pop(session_id, None)
        # Uma nova imagem invalida ofertas relacionadas à fotografia antiga.
        # A intenção pendente continua válida mesmo se a API falhar.
        offered_intents.pop(session_id, None)
        new_photo_offers.discard(session_id)

    new_photo = asks_for_new_photo(message)
    if new_photo:
        offered_intents.pop(session_id, None)
        new_photo_offers.discard(session_id)
        # A imagem anexada nesta mensagem já é a nova fotografia.
        if image is None:
            session_images.pop(session_id, None)
            completed_analyses.pop(session_id, None)

    intents = []

    if closing_text in affirmative_messages:
        # A confirmação aceita a característica oferecida, não repete a última.
        intents = (
            (previous_offer if image is not None else offered_intents.get(session_id, []))
            or pending_requests.get(session_id, [])
        )
        if not intents and (previous_new_photo_offer if image is not None else session_id in new_photo_offers):
            # A última oferta após analisar ambos foi uma nova fotografia.
            # Nova fotografia com as duas características; não herdar estado anterior.
            intents = ["comprimento", "textura"]
            pending_requests[session_id] = intents
            new_photo_offers.discard(session_id)
            if image is None:
                session_images.pop(session_id, None)
                completed_analyses.pop(session_id, None)
                return {
                    "session_id": session_id,
                    "message": "Ótimo! Envie outra foto quando quiser fazer uma nova análise.",
                    "status": "aguardando_foto",
                }
        if not intents:
            pending_requests[session_id] = []
            return {
                "session_id": session_id,
                "message": INCOMPLETE_REQUEST_MESSAGE,
                "status": "aguardando_intencao",
            }

    elif message:
        request = classify_request(message)
        offered_intents.pop(session_id, None)
        new_photo_offers.discard(session_id)
        if request["status"] == "fora_escopo":
            return {
                "session_id": session_id,
                "message": OUT_OF_SCOPE_MESSAGE,
                "status": "fora_escopo",
            }

        intents = request["intents"]
        if new_photo and not intents:
            intents = pending_requests.get(session_id, last_intents.get(session_id, []))
        if not intents:
            # Uma escolha pendente vazia impede que a próxima foto reutilize
            # automaticamente a característica de uma análise anterior.
            pending_requests[session_id] = []
            return {
                "session_id": session_id,
                "message": INCOMPLETE_REQUEST_MESSAGE,
                "status": "aguardando_intencao",
            }

    elif session_id in pending_requests:
        intents = pending_requests[session_id]
    elif session_id in last_intents and image is not None:
        intents = last_intents[session_id]

    if intents:
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

    # Registrar somente resultados realmente identificados com sucesso.
    accumulated = completed_analyses.setdefault(session_id, {})
    for intent in intents:
        if result.get(intent):
            accumulated[intent] = result[intent]

    remaining = [
        intent for intent in ("comprimento", "textura")
        if intent not in accumulated
    ]
    offered_intents[session_id] = remaining

    if not remaining:
        offered_intents.pop(session_id, None)
        new_photo_offers.add(session_id)
        # Não repetir o resultado recém-exibido; acrescentar o resumo da fotografia.
        follow_up = completed_summary(accumulated)
    else:
        new_photo_offers.discard(session_id)
        follow_up = follow_up_message(list(accumulated)) if accumulated else (
            "Não foi possível concluir a análise com segurança. "
            "Você pode tentar outra fotografia."
        )

    return {
        "session_id": session_id,
        "message": result_message(result, intents),
        "follow_up": follow_up,
        "status": "concluido",
        "resultado": result,
    }
