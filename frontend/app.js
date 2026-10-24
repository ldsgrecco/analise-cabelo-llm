
const form = document.querySelector("#chat-form");
const input = document.querySelector("#message");
const fileInput = document.querySelector("#image");
const fileButton = document.querySelector("#attach-photo");
const fileName = document.querySelector("#file-name");
const messages = document.querySelector("#messages");
const send = document.querySelector("#send");
const voiceButton = document.querySelector("#voice-button");

let sessionId = crypto.randomUUID();

function addBubble(text, type = "assistant") {
  const item = document.createElement("article");
  item.className = `bubble ${type}`;
  item.textContent = text;
  messages.appendChild(item);
  item.scrollIntoView({ behavior: "smooth", block: "end" });
}

function addImageBubble(file) {
  const item = document.createElement("article");
  item.className = "bubble user image-bubble";

  const image = document.createElement("img");
  image.src = URL.createObjectURL(file);
  image.alt = "Foto enviada para análise";

  item.appendChild(image);
  messages.appendChild(item);
  item.scrollIntoView({ behavior: "smooth", block: "end" });
}

function setDefaultInputState() {
  input.placeholder = "Ex.: q tamanho ta meu cabelo e ele é ondulado ou liso?";
}

input.focus();

// ==================================================
// RECONHECIMENTO DE VOZ
// ==================================================

const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;

if (!SpeechRecognition) {
  voiceButton.disabled = true;
  voiceButton.textContent = "🎤 Indisponível";
} else {
  const recognition = new SpeechRecognition();

  recognition.lang = "pt-BR";
  recognition.continuous = false;
  recognition.interimResults = false;

  let listening = false;
  let textoAntesDoDitado = "";

  recognition.onstart = () => {
    listening = true;
    textoAntesDoDitado = input.value.trim();
    voiceButton.textContent = "⏹ Parar";
  };

  recognition.onresult = (event) => {
    const text = Array.from(event.results)
      .map((result) => result[0].transcript)
      .join(" ")
      .trim();

    if (text) {
      input.value = [textoAntesDoDitado, text]
        .filter(Boolean)
        .join(" ");

      input.focus();
    }
  };

  recognition.onerror = (event) => {
    if (event.error === "not-allowed") {
      alert("Permita o acesso ao microfone no navegador.");
    }
  };

  recognition.onend = () => {
    listening = false;
    voiceButton.textContent = "🎤 Falar";
  };

  voiceButton.addEventListener("click", () => {
    if (listening) {
      recognition.stop();
    } else {
      recognition.start();
    }
  });
}

// ==================================================
// ANEXAR FOTOGRAFIA
// ==================================================

fileButton.addEventListener("click", () => {
  fileInput.click();
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];

  if (file) {
    fileName.textContent = file.name;
    send.focus();
  } else {
    fileName.textContent = "Nenhuma foto selecionada";
  }
});

// ==================================================
// ENVIO DE MENSAGEM PELO TECLADO
// ==================================================

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

// ==================================================
// ENVIO DA MENSAGEM E ANALISE PELA API
// ==================================================

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = input.value.trim();
  const image = fileInput.files[0];
  let nextFocus = "input";

  if (!text && !image) {
    input.focus();
    return;
  }

  if (text) {
    addBubble(text, "user");
  }

  if (image) {
    addImageBubble(image);
  }

  const data = new FormData();

  data.append("message", text);
  data.append("session_id", sessionId);

  if (image) {
    data.append("image", image);
  }

  input.value = "";
  fileInput.value = "";
  fileName.textContent = "Nenhuma foto selecionada";

  if (image) {
    input.placeholder = "Analisando a fotografia...";
    input.disabled = true;
    fileButton.disabled = true;
  }

  send.disabled = true;
  send.textContent = "Enviando...";

  try {
    const response = await fetch("/analise-cabelo-api/api/chat", {
      method: "POST",
      body: data
    });

    const raw = await response.text();
    let result;

    try {
      result = JSON.parse(raw);
    } catch {
      throw new Error("Resposta inválida do servidor.");
    }

    if (!response.ok) {
      throw new Error(
        result.detail || "Não foi possível concluir a análise."
      );
    }

    if (result.session_id) {
      sessionId = result.session_id;
    }

    addBubble(result.message, "assistant");

    if (result.follow_up) {
      addBubble(result.follow_up, "assistant");
    }

    if (result.status === "aguardando_foto") {
      input.placeholder = "Agora, anexe uma foto para continuar.";
      nextFocus = "file";
    } else {
      setDefaultInputState();
    }
  } catch (error) {
    addBubble(
      error.message ||
        "Não foi possível concluir a análise. Tente novamente.",
      "error"
    );

    setDefaultInputState();
  } finally {
    input.disabled = false;
    fileButton.disabled = false;
    send.disabled = false;
    send.textContent = "Enviar";

    setTimeout(() => {
      if (nextFocus === "file") {
        fileButton.focus();
      } else {
        input.focus();
      }
    }, 50);
  }
});
