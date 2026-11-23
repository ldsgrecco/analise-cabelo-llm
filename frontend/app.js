
function initPanel(root, { galleryEnabled = false, autoSendVoice = false, wakeFeature = false } = {}) {
const form = root.querySelector(".chat-form");
const input = root.querySelector(".message-input");
const fileInput = root.querySelector(".image-input");
const fileButton = root.querySelector(".attach-photo");
const fileName = root.querySelector(".file-name");
const messages = root.querySelector(".messages");
const send = root.querySelector(".send-button");
const voiceButton = root.querySelector(".voice-button");

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

// Galeria aprovada: arquivos reais fixos e numerados para a demonstração.
// A foto é escolhida pelo usuário e anexada só ao clicar em Enviar.
const sampleImages = [1, 2, 3].map((number) => ({
  number, src: `assets/fotos-exemplo/Foto_${number}.png`
}));
let chosenSample = null;
let chosenSampleFile = null;

function selectSamplePhoto(number) {
  const sample = sampleImages.find((item) => item.number === number);
  if (!galleryEnabled || !sample) return false;
  chosenSample = sample;
  chosenSampleFile = null;
  fileInput.value = "";
  fileName.textContent = `Foto ${number} selecionada (exemplo acadêmico)`;
  if (galleryElement) {
    galleryElement.querySelectorAll("button[data-photo]").forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.photo === String(number) ? "true" : "false");

    });
  }
  return true;
}

// A galeria é inserida no próprio navegador: não altera HTML/CSS da produção.
let galleryElement = null;
if (galleryEnabled) {
  galleryElement = document.querySelector("#gallery-sidebar");
  const labels = [
    {name:"Foto 1", description:"Cabelo longo e cacheado"},
    {name:"Foto 2", description:"Cabelo médio e ondulado"},
    {name:"Foto 3", description:"Cabelo curto e liso"}
  ];
  sampleImages.forEach((sample, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.photo = String(sample.number);
    button.setAttribute("aria-pressed", "false");
    button.className = "sidebar-photo";
    const img = document.createElement("img");
    img.src = sample.src;
    img.alt = `Foto ${sample.number}: cabelo visto de costas`;
    const caption = document.createElement("span");
    caption.className = "sidebar-caption";
    caption.textContent = labels[index].name;
    const small = document.createElement("small");
    small.textContent = labels[index].description;
    caption.appendChild(small);
    button.appendChild(img);
    button.appendChild(caption);
    button.addEventListener("click", () => {
      // Selecionar uma foto corresponde ao modo galeria, mesmo se o modo manual estiver ativo.
      document.querySelector('#tab-galeria').click();
      selectSamplePhoto(sample.number);
    });
    galleryElement.appendChild(button);
  });
}

function removeDiacritics(text) {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

// Comando de seleção integrado à fala, sem acesso a pastas privadas do PC.
function parseGalleryCommand(text) {
  const normalized = removeDiacritics(text);
  const photoPattern = /\bfoto\s+(?:(?:numero|n|n\.)\s*)?(1|2|3|um|uma|dois|duas|tres)\b/i;
  const match = normalized.match(photoPattern);
  if (!match) return text.trim();
  const numbers = {um:1,uma:1,dois:2,duas:2,tres:3};
  const number = numbers[match[1]] || Number(match[1]);
  if (galleryEnabled) selectSamplePhoto(number);
  // Para que o backend receba apenas uma intenção capilar válida,
  // retiramos a referência à galeria sem descartar o conteúdo do pedido.
  const remaining = normalized.replace(photoPattern, ' ').replace(/\s+/g,' ').trim();
  const length = /\b(comprimento|tamanho)\b/.test(remaining);
  const texture = /\b(textura|tipo|liso|ondulado|cacheado|crespo)\b/.test(remaining);
  if (length && texture) return 'Analise o comprimento e a textura do cabelo desta foto';
  if (length) return 'Analise o comprimento do cabelo desta foto';
  if (texture) return 'Analise a textura do cabelo desta foto';
  // Somente número da foto: usuário pode então pedir a característica.
  if (/\b(cor|olho|aeroporto|volume|tratamento|queda)\b/.test(remaining)) return text;
  return 'Analise o comprimento e a textura do cabelo desta foto';
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

// A detecção depende dos eventos de fala fornecidos pelo navegador.
// O reconhecimento pode encerrar uma sessão antes do prazo; nesse caso,
// reabrimos a escuta até completar a pausa ou até o usuário parar.
const SILENCE_MS = 2000;

// Balão discreto exibido somente enquanto o microfone está ativo.
// Criado no JavaScript para não alterar o HTML nem o CSS existentes.
const voiceHint = document.createElement("div");
voiceHint.setAttribute("role", "status");
voiceHint.setAttribute("aria-live", "polite");
voiceHint.textContent =
  autoSendVoice
    ? "🎤 Ouvindo você...\nA mensagem será enviada após a pausa ou ao dizer ‘câmbio’."
    : "🎤 Ouvindo você...\nAguarde a transcrição e depois clique em Enviar.";
Object.assign(voiceHint.style, {
  display: "none",
  position: "absolute",
  left: "0",
  bottom: "calc(100% + 10px)",
  zIndex: "20",
  boxSizing: "border-box",
  maxWidth: "min(340px, calc(100vw - 48px))",
  width: "max-content",
  padding: "11px 14px",
  borderLeft: "4px solid #c69a42",
  borderRadius: "12px",
  background: "#142f56",
  color: "#ffffff",
  boxShadow: "0 5px 18px rgba(0, 0, 0, 0.18)",
  fontSize: "13px",
  lineHeight: "1.45",
  whiteSpace: "pre-line",
  pointerEvents: "none"
});
const voiceHintContainer = voiceButton.parentElement;
if (voiceHintContainer) {
  if (!voiceHintContainer.style.position || voiceHintContainer.style.position === "static") {
    voiceHintContainer.style.position = "relative";
  }
  voiceHintContainer.appendChild(voiceHint);
}

function showVoiceHint(show) {
  if (voiceHintContainer) voiceHint.style.display = show ? "block" : "none";
}

if (!SpeechRecognition) {
  voiceButton.disabled = true;
  voiceButton.textContent = "🎤 Indisponível";
} else {
  // Ativação experimental por palavra-chave: exige clique inicial para consentimento.
  // Ao desativar, o reconhecimento para. Sem gravação ou envio em segundo plano.
  const wakeButton = document.createElement("button");
  wakeButton.type = "button";
  wakeButton.textContent = "📻 Ativar Gepeto";
  wakeButton.setAttribute("aria-pressed", "false");
  wakeButton.className = "wake-button";
  if (!wakeFeature) wakeButton.hidden = true;
  if (wakeFeature) voiceButton.parentElement?.appendChild(wakeButton);

  const recognition = new SpeechRecognition();
  recognition.lang = "pt-BR";
  recognition.continuous = true;
  recognition.interimResults = true;

  let wantsListening = false;
  let wakeEnabled = false;
  let awaitingWake = false;
  let dictationStarted = false;
  let stoppedByCommand = false;
  let recognitionRunning = false;
  let textoAntesDoDitado = "";
  let textoSessaoAnterior = "";
  let textoSessaoAtual = "";
  let silenceTimer = null;
  let restartTimer = null;
  let startFailures = 0;

  function cancelSilenceTimer() {
    if (silenceTimer !== null) clearTimeout(silenceTimer);
    silenceTimer = null;
  }

  function updateTranscript() {
    const dictated = [textoSessaoAnterior, textoSessaoAtual]
      .filter(Boolean).join(" ").trim();
    input.value = [textoAntesDoDitado, dictated]
      .filter(Boolean).join(" ");
  }

  function finishDictation({ autoSend = false } = {}) {
    // Envia somente se houve fala reconhecida nesta rodada; não reenvia texto antigo.
    const hasNewSpeech = Boolean([textoSessaoAnterior, textoSessaoAtual].filter(Boolean).join(" ").trim());
    showVoiceHint(false);
    wantsListening = false;
    cancelSilenceTimer();
    if (restartTimer !== null) clearTimeout(restartTimer);
    restartTimer = null;
    voiceButton.textContent = "🎤 Falar";
    if (recognitionRunning) recognition.stop();
    if (wakeEnabled && wakeFeature) {
      awaitingWake = true;
      voiceButton.textContent = "🎤 Falar";
      scheduleWakeRestart();
    }
    // Envio automático apenas por silêncio ou comando "câmbio".
    // A validação de escopo permanece a cargo do backend.
    if (autoSend && autoSendVoice && hasNewSpeech && !send.disabled && !input.disabled) {
      form.requestSubmit();
    }
  }

  function scheduleWakeRestart(delay = 250) {
    if (!wakeEnabled || wantsListening || recognitionRunning || restartTimer !== null) return;
    restartTimer = setTimeout(() => {
      restartTimer = null;
      if (wakeEnabled && !wantsListening) startRecognition();
    }, delay);
  }

  function scheduleSilenceStop() {
    if (!wantsListening) return;
    cancelSilenceTimer();
    silenceTimer = setTimeout(() => {
      silenceTimer = null;
      if (wantsListening) finishDictation({ autoSend: true });
    }, SILENCE_MS);
  }

  function startRecognition() {
    if ((!wantsListening && !wakeEnabled) || recognitionRunning) return;
    try {
      recognition.start();
    } catch (error) {
      // O Chrome pode ainda estar encerrando a sessão anterior.
      // Nesse caso, não abandone o modo Gepeto: tente novamente.
      if (error?.name === "InvalidStateError" && startFailures < 3) {
        startFailures++;
        if (wakeEnabled && !wantsListening) scheduleWakeRestart(700);
        else if (wantsListening && restartTimer === null) {
          restartTimer = setTimeout(() => { restartTimer = null; startRecognition(); }, 700);
        }
      } else {
        if (wantsListening) finishDictation();
        if (wakeEnabled) {
          wakeEnabled = false;
          awaitingWake = false;
          wakeButton.textContent = "📻 Ativar Gepeto";
          wakeButton.setAttribute("aria-pressed", "false");
        }
      }
    }
  }

  recognition.onstart = () => {
    startFailures = 0;
    recognitionRunning = true;
    if (wantsListening) voiceButton.textContent = "⏹ Parar";
  };

  recognition.onspeechstart = () => {
    if (wantsListening) cancelSilenceTimer();
  };

  recognition.onspeechend = () => {
    // Só começa a contar depois que a pessoa já falou alguma coisa.
    if (wantsListening && (textoSessaoAnterior || textoSessaoAtual)) scheduleSilenceStop();
  };

  recognition.onresult = (event) => {
    const raw = Array.from(event.results)
      .map((result) => result[0].transcript).join(" ").trim();
    const isFinal = Array.from(event.results).every((result) => result.isFinal);
    if (!raw) return;

    if (wakeEnabled && awaitingWake) {
      // Uma única chamada falada, com variantes de transcrição comuns.
      // Excluímos GPT/GPTO para evitar ativar enquanto se fala sobre IA.
      const wakeMatch = removeDiacritics(raw).trim().match(
        /^(?:(?:oi|ei)[,!?.:;]?\s+)?(?:gepeto|geppetto|repeto)(?=$|[\s,!?.:;])/
      );
      if (!wakeMatch) return;
      awaitingWake = false;
      wantsListening = true;
      dictationStarted = true;
      textoAntesDoDitado = input.value.trim();
      textoSessaoAnterior = "";
      showVoiceHint(true);
      voiceButton.textContent = "⏹ Parar";
      // Pode haver uma pergunta inteira após a palavra Gepeto na mesma fala.
    }
    if (!wantsListening) return;
    let spoken = raw.trim().replace(
      /^(?:(?:oi|ei)[,!?.:;]?\s+)?(?:gepeto|geppetto|repeto)(?=$|[\s,!?.:;])[\s,:.!?-]*/i,
      ""
    );
    const command = /(?:^|[\s,.!?;])c[aâ]mbio[\s,.!?;]*$/i.test(spoken);
    if (command) spoken = spoken.replace(/(?:^|[\s,.!?;])c[aâ]mbio[\s,.!?;]*$/i, "").trim();
    // Se "câmbio" chegou sozinho em uma nova sessão, não apaga a frase anterior.
    if (spoken) textoSessaoAtual = galleryEnabled ? parseGalleryCommand(spoken) : spoken;
    updateTranscript();
    if (command && isFinal) {
      stoppedByCommand = true;
      finishDictation({ autoSend: true });
    } else if (textoSessaoAtual) {
      scheduleSilenceStop();
    }
  };

  recognition.onerror = (event) => {
    if (["not-allowed", "service-not-allowed", "audio-capture", "network"].includes(event.error)) {
      wakeEnabled = false;
      awaitingWake = false;
      wakeButton.textContent = "📻 Ativar Gepeto";
      wakeButton.setAttribute("aria-pressed", "false");
    }
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      finishDictation();
      alert("Permita o acesso ao microfone no navegador.");
    } else if (event.error === "audio-capture") {
      finishDictation();
      alert("Não foi possível acessar o microfone.");
    } else if (event.error === "network") {
      finishDictation();
      alert("O reconhecimento de voz está indisponível. Você pode digitar a mensagem.");
    }
    // 'no-speech' pode acontecer quando fazemos uma pausa: onend tentará
    // reiniciar a sessão, sem apagar o texto já reconhecido.
  };

  recognition.onend = () => {
    recognitionRunning = false;
    if (!wantsListening) {
      voiceButton.textContent = "🎤 Falar";
      if (wakeEnabled) scheduleWakeRestart();
      return;
    }
    // A API do navegador pode encerrar uma sessão antes dos 2 s.
    // Salva a transcrição e tenta continuar sem perder o texto anterior.
    if (textoSessaoAtual) {
      textoSessaoAnterior = [textoSessaoAnterior, textoSessaoAtual]
        .filter(Boolean).join(" ");
      textoSessaoAtual = "";
      updateTranscript();
    }
    if (restartTimer !== null) clearTimeout(restartTimer);
    restartTimer = setTimeout(() => {
      restartTimer = null;
      startRecognition();
    }, 150);
  };

  if (wakeFeature) wakeButton.addEventListener("click", () => {
    wakeEnabled = !wakeEnabled;
    wakeButton.textContent = wakeEnabled ? "📻 Desativar Gepeto" : "📻 Ativar Gepeto";
    wakeButton.setAttribute("aria-pressed", String(wakeEnabled));
    if (wakeEnabled) {
      awaitingWake = true;
      showVoiceHint(false);
      // O áudio fica disponível ao reconhecimento do navegador, mas só
      // transcrevemos mensagens depois de detectar a palavra "Gepeto".
      startRecognition();
    } else {
      awaitingWake = false;
      if (wantsListening) finishDictation();
      if (restartTimer !== null) clearTimeout(restartTimer);
      restartTimer = null;
      if (recognitionRunning) recognition.stop();
    }
  });

  voiceButton.addEventListener("click", () => {
    if (wantsListening) {
      finishDictation();
      return;
    }
    awaitingWake = false;
    wantsListening = true;
    showVoiceHint(true);
    textoAntesDoDitado = input.value.trim();
    textoSessaoAnterior = "";
    textoSessaoAtual = "";
    cancelSilenceTimer();
    startRecognition();
  });
  root.stopListening = () => {
    wakeEnabled = false;
    awaitingWake = false;
    wantsListening = false;
    showVoiceHint(false);
    cancelSilenceTimer();
    if (restartTimer !== null) clearTimeout(restartTimer);
    restartTimer = null;
    if (recognitionRunning) { try { recognition.abort(); } catch (_) {} }
    wakeButton.textContent = "📻 Ativar Gepeto";
    wakeButton.setAttribute("aria-pressed", "false");
    voiceButton.textContent = "🎤 Falar";
  };
}

// ==================================================
// ANEXAR FOTOGRAFIA
// ==================================================

fileButton.addEventListener("click", () => {
  chosenSample = null;
  chosenSampleFile = null;
  fileInput.click();
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];

  if (file) {
    chosenSample = null;
    chosenSampleFile = null;
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
  let image = fileInput.files[0];
  if (!image && chosenSample) {
    // Arquivo estático fornecido pela própria página, não pelo sistema de arquivos.
    try {
      if (!chosenSampleFile) {
        const imageResponse = await fetch(chosenSample.src);
        if (!imageResponse.ok) throw new Error("Não foi possível carregar a foto de exemplo.");
        const blob = await imageResponse.blob();
        chosenSampleFile = new File([blob], `Foto_${chosenSample.number}.png`, { type: "image/png" });
      }
      image = chosenSampleFile;
    } catch (error) {
      addBubble(error.message || "Erro ao carregar a foto de exemplo.", "error");
      return;
    }
  }
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
  chosenSample = null;
  chosenSampleFile = null;
  // Mantenha a foto marcada na barra lateral para indicar o contexto atual.

  if (image) {
    input.placeholder = "Analisando a fotografia...";
    input.disabled = true;
    fileButton.disabled = true;
  }

  send.disabled = true;
  send.textContent = "Enviando...";
  voiceButton.disabled = true;
  const busy = document.createElement("article");
  busy.className = "bubble assistant processing";
  busy.setAttribute("role", "status");
  busy.textContent = image ? "⏳ Analisando fotografia com a IA..." : "⏳ Processando seu pedido...";
  messages.appendChild(busy);
  messages.scrollTop = messages.scrollHeight;

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

    busy.remove();
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
    busy.remove();
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
    voiceButton.disabled = !SpeechRecognition;
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

}

const manualPanel = document.querySelector("#panel-manual");
const galleryPanel = document.querySelector("#panel-galeria");
initPanel(manualPanel, {galleryEnabled:false,autoSendVoice:false,wakeFeature:false});
initPanel(galleryPanel, {galleryEnabled:true,autoSendVoice:true,wakeFeature:true});
const tabs = document.querySelectorAll(".mode-tab");
tabs.forEach((tab) => tab.addEventListener("click", () => {
  const isGallery = tab.dataset.mode === "galeria";
  const oldPanel = isGallery ? manualPanel : galleryPanel;
  if (typeof oldPanel.stopListening === 'function') oldPanel.stopListening();
  manualPanel.hidden = isGallery;
  galleryPanel.hidden = !isGallery;
  tabs.forEach((button) => {
    const active = button === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}));
