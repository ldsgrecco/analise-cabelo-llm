# Analise de Cabelo com LLM â€” entrega final

Projeto academico individual de Luis Daniel Silla Grecco, Bacharelado em Inteligencia Artificial.

## Demonstracao
- Laboratorio web: https://ldsgreccoia.com.br/analise-cabelo-llm-lab/
- Versao inicial preservada: https://ldsgreccoia.com.br/analise-cabelo-llm/

## Objetivo e publico
Interpretar pedidos feitos por texto ou voz e analisar **comprimento** e/ou **textura aparente** do cabelo a partir de fotografia. Publico: estudantes, professores e pessoas que desejam observar essas caracteristicas. Nao e diagnostico capilar.

## Funcionalidades
- Modo 1: fotografia anexada manualmente, com entrada de texto ou voz no navegador.
- Modo 2: galeria de exemplos e comandos por voz.
- Intencoes: comprimento (curto, medio, longo, extralongo) e textura (lisa, ondulada, cacheada, crespa).
- Pedido generico como "analise esse cabelo" deve solicitar os dois atributos.
- Falta de fotografia: solicitar uma foto antes da analise; pedidos fora do escopo devem ser recusados com educacao.
- Prova de conceito com Qwen via Groq e Gemini; fallback quando o provedor principal falha. O painel de demonstracao utiliza falhas simuladas e chamadas reais ao modelo de reserva, que podem sofrer limites 429 ou indisponibilidade 503.

## Arquitetura
Frontend HTML/CSS/JavaScript -> backend Python FastAPI -> API Groq/Qwen ou API Gemini -> resultado estruturado exibido na interface. Nao requer banco de dados para o fluxo principal.

## Estrutura
- `frontend/`: interface web.
- `backend/main.py`: API e interpretacao das intencoes.
- `backend/requirements.txt`: dependencias Python.
- `tests/`: testes do backend.
- `docs/`: documentacao academica historica.

## Execucao local
1. Instalar Python 3.12 ou compativel e as dependencias com `python -m pip install -r backend/requirements.txt`.
2. Criar `backend/.env` **local**, usando os nomes de variaveis esperados pelo codigo. Nao versionar esse arquivo. Chaves privadas devem ficar exclusivamente no ambiente de execucao.
3. Iniciar backend: na pasta `backend`, executar `python -m uvicorn main:app --host 127.0.0.1 --port 8011`.
4. Iniciar frontend: na pasta `frontend`, executar `python -m http.server 5511` e abrir `http://127.0.0.1:5511/`.
5. O frontend deve apontar para a URL da API conforme configuracao da versao; em hospedagem, usar roteamento do Nginx.

## Limites e observacoes
O servico de reconhecimento de voz do navegador depende de permissao do microfone e suporte do navegador; pode falhar por razoes externas. APIs de terceiros tambem podem ficar indisponiveis. A aplicacao deve informar falhas sem inventar classificacoes. Os testes de fallback simulam somente a primeira falha; o provedor reserva e acionado de verdade.

## Seguranca
Nenhum `.env`, token, credencial, foto privada ou arquivo gerado por instaladores deve ser publicado. A demonstracao no servidor precisa ter controles de autorizacao e cotas; configuracoes temporarias sem senha da apresentacao nao fazem parte desta entrega.
