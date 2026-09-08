# Análise de Cabelo com LLM

Protótipo acadêmico que recebe mensagens em linguagem natural e fotografias para identificar características aparentes do cabelo. O sistema usa a API Gemini para interpretar o pedido e analisar visualmente a imagem.

Demonstração publicada:
https://ldsgreccoia.com.br/analise-cabelo-llm/

Repositório GitHub:
https://github.com/ldsgrecco/analise-cabelo-llm

## Objetivo da atividade

Este protótipo foi desenvolvido para:

- receber uma mensagem em linguagem natural;
- identificar a intenção do usuário;
- extrair as informações necessárias;
- consultar um serviço externo quando necessário;
- solicitar informações adicionais quando a mensagem estiver incompleta;
- gerar uma resposta final sem inventar dados.

## Intenção escolhida

**Analisar características aparentes do cabelo a partir de uma fotografia.**

A intenção permite identificar:

- comprimento aparente: curto, médio, longo ou extralongo;
- textura aparente: lisa, ondulada, cacheada ou crespa;
- ambos os aspectos.

Comprimento e textura são informações extraídas dentro da mesma intenção principal.

## Relação com a proposta inicial

Na proposta inicial, eu pretendia incorporar a LLM ao projeto Espelho Virtual para analisar comprimento, textura, volume e sinais visuais de coloração.

Durante o desenvolvimento, percebi que seria mais adequado manter esta atividade como um protótipo acadêmico separado, sem alterar o funcionamento do Espelho Virtual. Por isso, concentrei esta implementação no comprimento e na textura aparentes. Volume e sinais de coloração permanecem como possibilidades para uma etapa futura.

## Arquitetura

O projeto possui duas partes:

- `frontend/`: interface web em HTML, CSS e JavaScript;
- `backend/`: API em Python com FastAPI.

Fluxo da aplicação:

1. A pessoa escreve uma pergunta em linguagem natural.
2. A API Gemini interpreta se ela deseja descobrir o comprimento, a textura ou ambos.
3. Caso não haja fotografia, o sistema solicita que ela seja anexada.
4. Com a mensagem e a fotografia, a API Gemini analisa a imagem.
5. A aplicação gera uma resposta baseada somente nas classificações retornadas.
6. Se a imagem não permitir identificar algum aspecto com segurança, a aplicação informa essa limitação.

## Tecnologias utilizadas

- Python 3.12
- FastAPI
- Google Gemini API
- HTML, CSS e JavaScript
- Nginx no ambiente publicado

## Prompt utilizado

### Interpretação da mensagem

```text
Você interpreta pedidos em português sobre características aparentes do cabelo.

Identifique o que a pessoa deseja descobrir:
- comprimento;
- textura;
- ambos.

Considere perguntas curtas, linguagem informal, abreviações e erros de escrita.
Exemplos:
- "q tamanho ta meu cabelo?" = comprimento
- "ele é caxeado ou lizo?" = textura
- "como ele é?" = ambos
- "quero saber de tudo" = ambos

Responda somente em JSON com a chave "intencao".
Use apenas: "comprimento", "textura" ou "ambos".
```

### Análise da fotografia

```text
Analise somente características visualmente aparentes do cabelo na fotografia.

Classifique o comprimento como: curto, médio, longo ou extralongo.
Classifique a textura como: lisa, ondulada, cacheada ou crespa.

Se algum aspecto não puder ser identificado com segurança, retorne null.
Não faça diagnóstico capilar, não invente informações e responda somente em JSON.
```

## Estrutura de arquivos

```text
analise-cabelo-llm/
├── backend/
│   ├── .env.example
│   ├── main.py
│   └── requirements.txt
├── frontend/
│   ├── app.js
│   ├── index.html
│   └── style.css
├── docs/
├── .gitignore
└── README.md
```

## Como executar localmente

### 1. Criar o ambiente virtual

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Instalar as dependências

```bash
pip install -r requirements.txt
```

### 3. Configurar a chave da API

Copie o arquivo `.env.example` para `.env` e informe sua chave da API Gemini:

```bash
cp .env.example .env
nano .env
```

O arquivo `.env` deve conter:

```text
GEMINI_API_KEY=sua_chave_da_api_gemini_aqui
```

A chave não deve ser enviada ao repositório.

### 4. Iniciar a API

```bash
uvicorn main:app --host 0.0.0.0 --port 8001
```

A API ficará disponível em `http://127.0.0.1:8001`.

## Testes realizados

| Tipo de teste | Mensagem enviada | Comportamento esperado | Resultado |
|---|---|---|---|
| Mensagem completa | `como ele é?` com fotografia | Identificar comprimento e textura aparentes | Identificou comprimento médio e textura cacheada. |
| Informação faltando | `quero saber o tamanho` sem fotografia | Solicitar o envio de uma fotografia | Solicitou uma fotografia e não inventou uma classificação. |
| Linguagem informal | `q tamaho ta meu cabelo?` | Interpretar como pedido de comprimento e solicitar foto | Interpretou a mensagem informal e identificou comprimento médio e textura cacheada. |

Os testes também foram registrados por meio de capturas de tela e estão organizados no relatório entregue na pasta `docs/`.

## Dificuldades encontradas

- A API Gemini possui limites de uso no plano gratuito e pode retornar indisponibilidade temporária.
- Fotografias com pouca iluminação, cabelo oculto ou enquadramento insuficiente podem impedir uma classificação segura.
- Foi necessário tratar mensagens informais e com erros de escrita para tornar a interação mais natural.

## Possíveis melhorias

- Criar uma API própria de visão computacional, reduzindo a dependência de serviços externos.
- Registrar histórico de análises em banco de dados.
- Permitir que a pessoa avalie a resposta recebida.
- Ampliar os testes com diferentes tipos de fotografia e variações de linguagem.

## Relatório da entrega

O relatório completo, com a demonstração visual dos testes, está disponível em:
[Relatorio_de_Testes_Analise_de_Cabelo_LLM.docx](docs/Relatorio_de_Testes_Analise_de_Cabelo_LLM.docx)

## Limitação ética

As classificações são visuais e destinadas exclusivamente a fins acadêmicos. Elas não substituem avaliação profissional de cabeleireiro ou dermatologista.
