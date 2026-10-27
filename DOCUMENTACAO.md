# 📖 MANUAL E DOCUMENTAÇÃO OFICIAL — MAESTRO BOT ENTERPRISE

> **Versão do Sistema:** `v2.7.0 Enterprise Release`  
> **Linguagem & Framework:** Python 3.14 • `python-telegram-bot` v22.8 • `APScheduler` • Telegram Bot API 8.0+  
> **Hospedagem Recomendada:** Discloud (100% Otimizado) • VPS Linux (Ubuntu/Debian) • VPS Windows  

---

## 📑 ÍNDICE
1. [Visão Geral & Arquitetura](#1-visão-geral--arquitetura)
2. [Como Acessar a Documentação Diretamente no Bot](#2-como-acessar-a-documentação-diretamente-no-bot)
3. [Múltiplos Grupos & Canais (Multi-Chat Engine)](#3-múltiplos-grupos--canais-multi-chat-engine)
4. [Formatação Nativa RICA & Botões em Grade](#4-formatação-nativa-rica--botões-em-grade)
5. [Mensagens Programadas & Agendador Autônomo](#5-mensagens-programadas--agendador-autônomo)
6. [Módulo de Transmissão & Envio como o Bot](#6-módulo-de-transmissão--envio-como-o-bot)
7. [Segurança, Anti-Bot & Blindagem do Grupo](#7-segurança-anti-bot--blindagem-do-grupo)
8. [Moderação Ágil, Punições & Auditoria](#8-moderação-ágil-punições--auditoria)
9. [Auto-Respostas (Regex) & Sistema de Notas (#Hashtags)](#9-auto-respostas-regex--sistema-de-notas-hashtags)
10. [Painel Visual de Controle (/config)](#10-painel-visual-de-controle-config)
11. [Backup, Restauração & Deploy na Discloud](#11-backup-restauração--deploy-na-discloud)
12. [Tabela Completa de Comandos](#12-tabela-completa-de-comandos)

---

## 1. VISÃO GERAL & ARQUITETURA

O **Maestro Bot** é uma solução corporativa completa de automação, moderação, segurança e transmissão de conteúdo para o Telegram. Desenvolvido sob arquitetura assíncrona orientada a eventos (`asyncio`), ele opera com isolamento de falhas, reconciliação de dados em memória e persistência contínua em formato JSON.

### Estrutura de Arquivos do Projeto:
- **`main.py`**: Ponto de entrada do sistema. Registra os roteadores de eventos, pipeline de mensagens, comandos e inicializa o agendador contínuo de segundo plano (`background_scheduler`).
- **`config.py`**: Gerenciador de configuração central (`config.json`), esquemas padrão, funções de manipulação de múltiplos grupos/canais e migração automática entre versões.
- **`modules/admin_commands.py`**: Implementa comandos de moderação (ban, mute, warn, limpar), gerenciamento de canais/grupos, backup, restauração, relógio e centrais de ajuda/sobre.
- **`modules/panel.py`**: Painel gráfico interativo (`/config`) com navegação multipáginas, edição guiada de boas-vindas, regras, mensagens programadas, horários e fusos.
- **`modules/recurring.py`**: Motor de mensagens repetidas e programadas com suporte a múltiplos destinos, disparo por relógio, por intervalo de minutos ou por contagem de mensagens.
- **`modules/antispam.py`**: Filtros de segurança contra links externos, convites de outros grupos/canais, excesso de mensagens por segundo (anti-flood) e lista negra de palavras.
- **`modules/antirepeat.py`**: Algoritmo inteligente que gera hashes criptográficos de textos e mídias para evitar repostagens repetidas em uma janela de horas configurável (ex: 2h, 6h, 24h).
- **`modules/captcha.py`**: Verificação anti-bot interativa com botões inline, restrição imediata de novos membros e expulsão automática por tempo limite.
- **`modules/locks.py`**: Tranca cirúrgica por tipos de mídia (`/lock audio`, `/lock sticker`, `/lock gif`, etc.).
- **`modules/nightmode.py`**: Modo noturno automatizado que silencia o grupo em horários definidos (ex: 23:00 às 07:00) com avisos de início e término.
- **`modules/notes.py`**: Sistema de notas rápidas por hashtags (`#aviso`, `#regras`, etc.) com suporte a arquivos, partituras, PDFs e botões.
- **`modules/auto_responder.py`**: Respostas automáticas inteligentes com suporte a palavras-chave simples e Expressões Regulares (Regex).
- **`modules/tutorial.py`**: Central de tutoriais interativos integrados com 11 lições passo a passo guiando todas as configurações do bot.
- **`modules/logger_channel.py`**: Registro e espelhamento em tempo real de todas as ações administrativas para um canal privado de auditoria.
- **`modules/utils.py`**: Conversores de formatação rica, analisadores de botões em grade, agendadores de deleção e cache de permissões.

---

## 2. COMO ACESSAR A DOCUMENTAÇÃO DIRETAMENTE NO BOT

Você não precisa abrir arquivos externos para ver o status, os comandos ou as instruções do bot. Tudo está integrado:

1. **Pelo Comando Direto:**
   - Digite `/sobre`, `/doc`, `/versao`, `/documentacao` ou `/manual` no chat privado ou no grupo. O bot responderá com o cartão oficial da versão v2.5 e botões rápidos.
2. **Pela Central de Ajuda:**
   - Digite `/ajuda` ou `/help` e clique no botão **`ℹ️ Versão & Sobre o Bot`**.
3. **Pelo Painel de Configurações:**
   - Digite `/config`, vá para a **Página 2 (Avançado)** e clique em **`ℹ️ Versão & Docs`**.
4. **Pela Central de Tutoriais:**
   - Digite `/tutorial` para acessar os 11 guias interativos divididos por assunto.

---

## 3. MÚLTIPLOS GRUPOS & CANAIS (MULTI-CHAT ENGINE)

O Maestro Bot v2.5 permite vincular **infinitos grupos e canais**, gerenciando tudo a partir de uma única central.

### 👥 Grupos:
- **Como Vincular:**
  - *Opção Automática:* Adicione o bot no grupo e dê cargo de Administrador. O bot detecta sua promoção e se auto-registra instantaneamente!
  - *Opção por Comando:* Envie `/setgrupo` dentro do grupo desejado.
- **Como Desvincular:**
  - Envie `/desvincular` dentro do grupo ou `/desvincular <ID_DO_GRUPO>`.

### 📢 Canais:
- **Como Vincular:**
  - *Opção Automática:* Adicione o bot como Administrador do seu canal com permissão de postar mensagens. O bot se vincula automaticamente!
  - *Opção por Comando:* No privado do bot, envie: `/setcanal @seucanal` ou `/setcanal -1001234567890`.
- **Como Desvincular:**
  - No privado do bot, envie: `/desvincularcanal @seucanal` ou `/desvincularcanal -1001234567890`.

### 📋 Consultando Chats Conectados:
- Envie `/grupos` ou `/canais` (ou `/chats`) para receber uma lista detalhada com os nomes, IDs, tipos e se são principais ou secundários.
- No painel `/config`, clique em **`🌐 Grupos & Canais`** para ver e gerenciar interativamente.

---

## 4. FORMATAÇÃO NATIVA RICA & BOTÕES EM GRADE

Todas as mensagens enviadas através do bot — sejam no `/falar`, `/canal`, `/transmitir`, nas **Boas-Vindas**, nas **Respostas Automáticas**, nas **Notas** ou nas **Mensagens Repetidas** — aceitam a formatação nativa completa do Telegram e botões em grade.

### 🎨 Formatações de Texto Aceitas:
- **Negrito:** `*texto*` ou formatação direta pelo menu do Telegram (`Ctrl + B`).
- **Itálico:** `_texto_` ou formatação direta pelo menu do Telegram (`Ctrl + I`).
- **Sublinhado:** Menu do Telegram (`Ctrl + U`).
- **Tachado (Riscado):** `~texto~` ou menu do Telegram (`Ctrl + Shift + X`).
- **Spoiler (Texto oculto):** `||texto oculto||` ou menu do Telegram (`Ctrl + Shift + P`).
- **Código Inline:** `` `código` ``
- **Bloco de Código:** ```` ```linguagem\ncódigo\n``` ````
- **Citações Normais:** `> Linha citada`
- **Citações Expansíveis (Artigos Recolhíveis):**
  - Comece a linha com `>>` para criar uma citação recolhível/expansível nativa do Telegram:
  ```text
  >> Este é o resumo recolhível
  >> Você pode colocar várias linhas aqui dentro
  >> E o membro clica para expandir e ler tudo!
  ```

### 🎲 Variações Dinâmicas (Spintax & Textos Alternados):
Evite respostas robóticas ou repetitivas variando saudações e frases automaticamente:
- **Variação de Palavras/Expressões (`{RANDOM:...}` ou `{VAR:...}`):**
  - O bot escolhe uma opção aleatória a cada disparo:
  ```text
  {RANDOM:Olá|Oi|Opa|A paz de Deus}, {name}! 🎷
  {RANDOM:Dá uma olhada|Enquanto o pessoal não responde, confira} em nossos canais oficiais!
  ```
- **Variações de Mensagens Completas (`---`):**
  - No Auto-Responder ou Boas-Vindas, separe mensagens inteiras por `---`. O bot sorteará uma mensagem diferente a cada resposta:
  ```text
  Olá {name}! Dá uma olhada no canal oficial nos botões abaixo:
  ---
  A paz, {name}! Você pode buscar na lupa do grupo ou acessar nosso acervo completo no canal:
  ```

### 🔘 Botões Interativos em Grade (Inline Keyboards):
Você pode criar botões interativos em qualquer mensagem utilizando colchetes `[Texto | link]`.
- **Botões na mesma linha (Lado a Lado):** Coloque os colchetes na mesma linha:
  ```text
  [🌐 Nosso Site | https://seusite.com] [📢 Canal Oficial | https://t.me/seucanal]
  ```
- **Botões em linhas separadas (Empilhados):** Pule uma linha entre os colchetes:
  ```text
  [🎵 Partituras Gratuitas | https://t.me/seucanal]
  [💬 Falar com Suporte | https://t.me/seusuporte]
  ```

---

## 5. MENSAGENS PROGRAMADAS & AGENDADOR AUTÔNOMO

O motor de mensagens recorrentes do bot roda sob um **Loop Autônomo de Segundo Plano** que verifica o relógio a cada 10 segundos, garantindo precisão ao minuto programado, sem atrasos ou engasgos de threads.

### 🎯 Tipos de Disparo:
1. **Por Intervalo Corrido de Minutos:**
   - Exemplo: Disparar a cada 30 minutos ininterruptamente.
2. **Por Horário Fixo do Dia (Relógio):**
   - Exemplo: Disparar todos os dias exatamente às `09:00`, `14:30`, `18:00` ou `21:00`.
3. **Por Contagem de Mensagens do Grupo (Gatilho de Movimento):**
   - Exemplo: Disparar a mensagem toda vez que os membros conversarem 50 mensagens no grupo. Evita poluir o chat se o grupo estiver parado!

### 🗺️ Seletor de Destino Dinâmico:
Cada mensagem programada pode ter seu próprio destino:
- `all`: Dispara simultaneamente para **TODOS** os grupos e canais vinculados.
- `all_groups`: Dispara para **TODOS os grupos** vinculados.
- `all_channels`: Dispara para **TODOS os canais** vinculados.
- `ID do Chat`: Dispara apenas para o grupo ou canal selecionado.

### 🛠️ Diagnóstico do Agendador em Tempo Real:
- Envie `/relogio` a qualquer momento para ver:
  - Hora exata do servidor e do bot (Fuso Horário configurado).
  - Status da Mensagem #1, próximo horário, destino e último disparo.
  - Confirmação do funcionamento do loop autônomo.

---

## 6. MÓDULO DE TRANSMISSÃO & ENVIO COMO O BOT

Permite que os administradores enviem avisos, partituras, imagens, vídeos e comunicados falando diretamente como o bot a partir do chat privado:

### 📢 Central Visual de Transmissão Guiada (`/comunicado` ou no Painel `/config`):
Novo assistente interativo em 4 passos intuitivos, permitindo criar transmissões com prévia idêntica antes do envio:
1. **Passo 1 — Escolha de Destino:**
   - Selecione com 1 toque: *Canal Principal*, *Todos os Grupos*, *Todos os Canais*, *Transmitir em TODOS* ou um grupo/canal específico.
2. **Passo 2 — Mensagem & Texto:**
   - Envie o texto com toda a riqueza de formatação do Telegram: Negrito (`Ctrl+B`), Itálico (`Ctrl+I`), Spoiler (`||texto||`), Artigo expansível (`>>`), links e Spintax (`{RANDOM:op1|op2}`).
   - *(Dica: Se já enviar Foto ou Vídeo com legenda nesta etapa, o assistente detecta tudo de uma vez).*
3. **Passo 3 — Mídia (Foto ou Vídeo):**
   - Envie uma **Foto** ou **Vídeo** diretamente no chat, ou clique em `[ ⏭️ Pular Mídia ]` para enviar apenas texto formatado.
4. **Passo 4 — Botões Interativos com Link:**
   - Envie botões no modelo `[Texto do Botão | https://link.com]`, lado a lado ou empilhados, ou clique em `[ ⏭️ Pular Botões ]`.
5. **Prévia Idêntica & Painel de Confirmação:**
   - O bot gera uma mensagem idêntica no seu chat privado para você ver exatamente como ficará para os membros!
   - Menu com controles completos:
     - `[ 🚀 ENVIAR AGORA ]`: Dispara imediatamente para todos os alvos selecionados com relatório final de sucesso/falhas.
     - `[ ⏰ AGENDAR ENVIO ]`: Programa a transmissão para um horário futuro (com atalhos rápidos: 15 min, 30 min, 1h, 2h, hoje às 18:00/21:00, amanhã às 09:00 ou digitando qualquer horário específico).
     - `[ 🌊 Distribuição: Suave (2s/chat) ▾ ]`: **Envio gradual e escalonado** que distribui as mensagens entre os canais/grupos sem mandar tudo na mesma fração de segundo! Evita travamentos de API e limites de flood do Telegram (`0s Instantâneo`, `2s Suave`, `5s Moderado`, `10s Espaçado` ou `30s Gradual`).
     - `[ 📌 Fixar no Topo: Sim/Não ]`: Alterna a fixação no topo com 1 clique antes de enviar.
     - `[ 🎯 Mudar Destino ]`: Troca os alvos sem perder o texto ou mídias.
     - `[ ✏️ Alterar Texto ]`: Reescreve o texto mantendo as demais opções.
     - `[ 🖼️/🎥 Alterar Mídia ]`: Troca ou remove a foto/vídeo.
     - `[ 🔘 Alterar Botões ]`: Ajusta os botões e links.
     - `[ ❌ Cancelar Transmissão ]`: Aborta a operação com segurança.

### 🗓️ Gerenciamento de Transmissões Agendadas (`/agendados` ou `/transmissoes`):
- Visualize a qualquer instante todas as transmissões que estão na fila para serem disparadas.
- Possibilidade de **`[ 🚀 Disparar Agora ]`** para antecipar o envio ou **`[ 🗑️ Cancelar ]`** para abortar o agendamento.
- O loop autônomo de segundo plano do bot dispara na hora exata, distribui suavemente com o delay configurado e envia o relatório com recibo no privado do administrador!

---

### ⚡ Comandos Rápidos Alternativos:
- **`/falar <texto>` ou `/say <texto>` (Com Seletor Interativo de Destino):**
  - **No privado do bot com Múltiplos Grupos/Canais:**
    Quando você envia `/falar <sua mensagem>` no privado, o Maestro Bot exibe imediatamente um **seletor interativo de botões** para você escolher com 1 toque para onde deseja enviar.
  - **Com Mídias & Partituras (PDF, Fotos, Áudios, Vídeos):**
    Envie uma foto, arquivo PDF de partitura, áudio ou vídeo no privado com a legenda `/falar <texto>` (ou responda a qualquer arquivo com `/falar`), e o Maestro exibirá os botões para você tocar e enviar para o grupo desejado.
- **`/canal <texto>` ou `/postar <texto>`:**
  - Posta imediatamente no **Canal vinculado principal**.
  - Suporta fotos e arquivos (basta responder a foto/arquivo com `/canal <legenda>`).
  - Use `/canal pin <texto>` para postar e **fixar automaticamente** no topo do canal!
- **`/transmitir <texto>` ou `/broadcast <texto>`:**
  - Transmite o comunicado para **todos os grupos e canais** vinculados simultaneamente.
- **`/anunciar <texto>`:**
  - Envia a mensagem no grupo e fixa no topo instantaneamente.

---

## 7. SEGURANÇA, ANTI-BOT & BLINDAGEM DO GRUPO

1. **🧩 Anti-Bot / CAPTCHA Musical:**
   - Quando ativado, todo novo usuário que entrar fica com permissões de fala, envio de mídia e links **completamente bloqueadas**.
   - O bot envia uma mensagem personalizada com o botão interativo `[ 🎵 Sou Humano ]`.
   - Se o usuário não clicar dentro do tempo limite (padrão: 120s), ele é automaticamente expulso para proteger o grupo contra invasões em massa.
2. **🛡️ Anti-Repetição Inteligente em Janela de Horas:**
   - Detecta membros que ficam repostando a mesma mensagem, foto ou link várias vezes seguidas.
   - Janela configurável via painel (5 min, 1h, 2h, 6h, 12h, 24h).
   - Ao detectar duplicação, apaga a mensagem e avisa o membro.
3. **🔗 Bloqueio de Links & Convites Externos:**
   - Bloqueia links de internet genéricos (`http://`, `https://`).
   - Bloqueia links e convites de outros grupos ou canais do Telegram (`t.me/...`).
   - Bloqueia mensagens encaminhadas de canais terceiros.
4. **🔒 Bloqueios de Mídia Granulares (`/lock`):**
   - Permite trancar tipos de arquivos específicos para membros comuns enquanto administradores continuam podendo postar normalmente:
   - `sticker`, `audio`, `voice`, `video`, `gif`, `doc`, `forward`, `contact`, `poll`.
   - Veja o status com `/locks`. Libere com `/unlock <tipo>`.
5. **🌙 Silêncio Noturno Programado (`/noturno`):**
   - Tranca o envio de mensagens de todos os membros nos horários de descanso (ex: 23:00 às 07:00).
   - Envia aviso automático de boa noite e bom dia no grupo quando ativado.
6. **📥 Auto-Aprovação de Solicitações (Join Requests para Canais & Grupos):**
   - Aprova imediatamente novos inscritos ou membros que pedem para entrar no **Canal** ou **Grupo** através de links com aprovação de administrador.
   - Envia mensagem acolhedora de boas-vindas no privado do usuário e gera log detalhado no canal de auditoria.
   - Ative/Desative a qualquer momento no menu `/config` (Pág. 2 ➔ `📥 Auto-Aprovar`).
7. **📊 Auditoria em Tempo Real de Inscrições & Desinscrições:**
   - Monitora quem se inscreve e quem cancela inscrição nos canais e grupos em tempo real (`ChatMemberHandler.CHAT_MEMBER`).
   - Registra com nome, username, ID e link direto no Canal de Logs (`/setlog`).

---

## 8. MODERAÇÃO ÁGIL, PUNIÇÕES & AUDITORIA

Comandos para serem usados em resposta à mensagem do infrator:

| Comando | Descrição | Sintaxe / Exemplos |
| :--- | :--- | :--- |
| `/ban` | Bane o membro do grupo | `/ban` (perm) • `/ban 1d Spam` • `/ban 2h` |
| `/kick` | Expulsa o membro (pode voltar pelo link) | `/kick Mensagem inadequada` |
| `/mute` | Silencia temporariamente | `/mute 30m Discussão` • `/mute 2h` • `/mute 1d` |
| `/unmute` | Devolve a permissão de fala | `/unmute` (em resposta) |
| `/warn` | Aplica advertência (3 warns = ban automático) | `/warn Não desrespeite as regras` |
| `/unwarn` | Remove 1 advertência do membro | `/unwarn` (em resposta) |
| `/warns` | Consulta advertências ativas | `/warns` |
| `/limpar` | Apaga mensagens em lote | `/limpar 10` • `/limpar 50` |
| `/pin` / `/unpin` | Fixa ou desfixa mensagens no topo | `/pin` (em resposta) |
| `/report` | Membros comuns alertam a moderação | `/report Conteúdo impróprio` (em resposta) |
| `/info` | Exibe ficha completa do membro | `/info` (em resposta ou próprio) |
| `/staff` | Lista o criador e todos os administradores | `/staff` |
| `/setlog` | Conecta o canal privado de auditoria | `/setlog -1001234567890` |

---

## 9. AUTO-RESPOSTAS (REGEX & DELAY) & SISTEMA DE NOTAS (#HASHTAGS)

### 🤖 Auto-Respostas Inteligentes:
- Responde automaticamente quando alguém menciona termos específicos no grupo ou pergunta por materiais.
- **Suporte a Expressões Regulares (Regex):** Detecta perguntas naturais em português (ex: *"alguém tem o arranjo instrumental da música mil Graus??"*, *"alguém ai tem método de trompete?"*).
- **⏳ Delay Inteligente (Tempo de Espera):** Permite configurar um tempo de espera (ex: 5s, 10s, 15s, 30s) para que o bot demore alguns segundos antes de responder. A resposta é agendada em segundo plano (`asyncio`) de forma 100% não bloqueante (o bot continua processando comandos e mensagens normalmente).
- **Citação Direta (Reply):** Responde citando diretamente a mensagem do membro que fez a pergunta, gerando um atendimento humanizado e contextualizado.
- **Salvar com Mídia:** Responda a uma imagem, áudio ou documento no grupo com `/filtro termo` para salvar aquele anexo como resposta automática!
- Liste os filtros com `/filtros` e remova com `/delfiltro <id>`. No menu `/config`, configure gatilhos, textos, botões em grade, fotos, cooldown anti-spam e tempo de espera (delay).

### 📌 Sistema de Notas Estilo Rose Bot:
- **Como Salvar:** `/save partituras Aqui estão os links das partituras...`
- **Com Mídia:** Responda a uma foto ou PDF com `/save ensaio` para arquivar a mídia.
- **Como Chamar:** Qualquer membro ou admin pode digitar `#ensaio` ou `/get ensaio` para o bot entregar o conteúdo na hora.
- Liste todas as notas do grupo com `/notas`.

---

## 10. PAINEL VISUAL DE CONTROLE (/config) — IDENTIDADE MAESTRO BOT

O comando `/config` (ou `/painel`) abre uma central gráfica e elegante com identidade visual exclusiva do **Maestro Bot**, pensada para máxima clareza em smartphones e computadores (sem textos truncados ou botões cortados):

- **🎼 Página 1 (Configurações Principais):**
  - **📜 Regras:** Visualização e alteração das diretrizes oficiais do grupo.
  - **🛡️ Anti-Spam:** Proteção integrada contra divulgação e flood.
  - **💬 Boas-Vindas:** Gerenciador multi-grupo com suporte a mensagens personalizadas por comunidade e prévia ao vivo.
  - **🌊 Anti-Flood:** Controle de taxa de mensagens por segundo com silenciamento automático.
  - **🤖 Regex:** Filtros inteligentes com respostas automáticas e cooldown.
  - **⏱️ Repetidas:** Postagens programadas autônomas (por relógio ou contagem de mensagens).
  - **🔗 Bloquear Links:** Trava imediata de links externos no chat.
  - **🔤 Palavras Proibidas:** Lista negra de termos proibidos com escolha de punição.
  - **🌐 Chats Vinculados:** Hub unificado para orquestrar todos os grupos e canais conectados.
  - **🗑️ Limpar Chat:** Atalho para purgar mensagens do histórico.
  - **🎛️ Avançado ▶:** Acesso à segunda página de automação.

- **🎼 Página 2 (Configurações Avançadas):**
  - **🌙 Modo Noturno:** Silêncio programado automático no chat durante a madrugada.
  - **🧩 CAPTCHA:** Verificação interativa contra robôs na entrada.
  - **📥 Auto-Aprovar:** Aprovação automática de pedidos de entrada com DM de boas-vindas.
  - **🛡️ Anti-Repetição:** Filtro criptográfico contra envio de mensagens ou mídias duplicadas.
  - **⏱️ Auto-Apagar Boas-Vindas ▾:** Submenu dedicado com seleção rápida ou digitação de tempo personalizado (1 min a 24 horas).
  - **🕒 Fuso Horário ▾:** Submenu dedicado para escolha regional (Brasília, Manaus, Belém, Lisboa, etc.) ou fuso IANA customizado.
  - **⏱️ Janela de Repetição:** Intervalo de memória para bloqueio de posts duplicados (1h, 2h, 4h, 6h, 12h, 24h).
  - **🚪 Limpar Entradas:** Exclusão automática de mensagens de serviço ("fulano entrou no grupo").
  - **🧹 Limpar Comandos:** Moderação invisível que apaga os comandos dos administradores e membros.
  - **📡 Canal de Logs:** Espelhamento de auditoria e segurança.
  - **📢 Travar Convites & ⏩ Travar Encaminhados:** Blindagem contra divulgações indiretas.
  - **ℹ️ Versão & Docs:** Manual e resumo do sistema.

### ⏱️ Submenu Dedicado: Auto-Apagar Boas-Vindas (1 min a 24 horas):
Em vez de alternâncias cegas no mesmo botão, agora ao tocar em **`⏱️ Auto-Apagar Boas-Vindas`** (ou no tempo dentro das boas-vindas de qualquer grupo), abre-se um submenu completo:
1. **Botões de Tempo Rápido:**
   - `[ 🚫 Nunca Apagar ]`
   - `[ ⚡ 1 minuto ]` • `[ ⏱️ 5 minutos ]`
   - `[ ⏱️ 10 minutos ]` • `[ ⏱️ 15 minutos ]`
   - `[ ⏱️ 30 minutos ]` • `[ 🕐 1 hora ]`
   - `[ 🕑 2 horas ]` • `[ 🕕 6 horas ]`
   - `[ 🕛 12 horas ]` • `[ 📅 24 horas ]`
2. **Tempo Personalizado:**
   - Clique em **`[ ✍️ Digitar Tempo Personalizado (1m a 24h) ]`**.
   - Envie no chat o tempo que desejar: `10m`, `30 min`, `1h`, `2 horas`, `45 min`, ou `nunca`.
   - O Maestro Bot valida os limites e aplica imediatamente com botão de retorno direto!

### 🕒 Submenu Dedicado: Fuso Horário Regional:
Ao tocar em **`🕒 Fuso Horário ▾`**, abre-se uma tela com o horário exato em tempo real e lista de regiões:
- `[ 🇧🇷 Brasília / SP (UTC-3) ]`
- `[ 🇧🇷 Manaus (UTC-4) ]`
- `[ 🇧🇷 Fortaleza / Nordeste (UTC-3) ]`
- `[ 🇧🇷 Belém / Norte (UTC-3) ]`
- `[ 🇧🇷 Cuiabá / MT (UTC-4) ]`
- `[ 🇧🇷 Acre / Rio Branco (UTC-5) ]`
- `[ 🇧🇷 Fernando de Noronha (UTC-2) ]`
- `[ 🇵🇹 Lisboa / Portugal (UTC+0/+1) ]`
- `[ 🌐 UTC Universal ]`
- **Digitar Fuso Customizado:** Permite digitar qualquer timezone IANA oficial (ex: `America/Recife`, `America/Bahia`, `America/Campo_Grande`).

### 🌐 Gerenciador de Grupos e Canais Vinculados:
Ao tocar em **`🌐 Chats`**, o Maestro exibe todos os chats conectados com selo de `⭐️ Principal`:
- Ao clicar em um chat, abre-se a ficha completa com: Nome, ID, Username, Data de vinculação, Status de Boas-Vindas e Modo Noturno.
- **Ações disponíveis em 1 clique:**
  - `[ ⭐️ Definir como Principal ]`: Altera o alvo padrão dos comandos rápidos `/falar` ou `/canal`.
  - `[ 💬 Configurar Boas-Vindas ]`: Abre diretamente a edição exclusiva daquele grupo.
  - `[ ⏱️ Auto-Apagar Msg ]`: Ajusta o tempo de autodestruição das mensagens daquele grupo.
  - `[ 🗑️ Desvincular Chat ]`: Remove a conexão com segurança.

### 🌟 Boas-Vindas Personalizadas por Grupo (Multi-Grupo):
No menu `/config` ➔ **💬 Boas-Vindas**, você pode definir uma mensagem exclusiva para cada comunidade:
1. Clique no botão **`[ 🌐 Escolher Outro Grupo ▾ ]`**.
2. O bot abrirá a lista de todos os seus grupos vinculados:
   - `⭐️ Padrão Geral` (usado por padrão caso o grupo não tenha customização própria).
   - `🟢 Nome do Grupo [Personalizada]` (já possui texto/foto própria).
   - `⚪ Nome do Grupo [Padrão]` (está herdando o padrão geral).
3. Selecione o grupo desejado. Você poderá:
   - Configurar texto com placeholders (`{name}`, `{mention}`, `{group}`, `{date}`, `{hour}`).
   - Definir foto exclusiva e botões inline específicos para aquele grupo.
   - Usar artigos expansíveis com `>> seu artigo aqui`.
   - Clicar em **`[ 🔄 Resetar para o Padrão Geral ]`** a qualquer momento para voltar ao padrão.

### 🧹 Auto-Limpeza de Comandos & Moderação Invisível:
Para manter seu grupo sempre profissional e livre de poluição visual, acesse `/config` ➔ **Página 2** ➔ **`🧹 Limpar Comandos`**:
- **Apagar Comandos de Administradores (`/falar`, `/ban`, etc.):**
  Quando ativado, os comandos executados pelos administradores no chat do grupo (como `/falar`, `/say`, `/ban`, `/mute`, `/kick`, `/warn`, `/pin`, etc.) são **apagados imediatamente** após o acionamento! O bot assume a ação sem deixar rastros do comando no chat.
- **Apagar Comandos de Membros Comuns:**
  Quando membros tentam comandos restritos, o gatilho é excluído instantaneamente para evitar tumultos.
- **Tempo de Auto-Exclusão dos Avisos do Bot:**
  Permite definir o tempo para que a mensagem de confirmação do bot (ex: *"Usuário banido com sucesso"*) se autodestrua:
  - Opções cicláveis: **5s • 10s • 15s • 30s • 1 min • Desativado (Permanente)**.

---

## 11. BACKUP, RESTAURAÇÃO & DEPLOY NA DISCLOUD

### 💾 Backup & Restauração Segura:
- **`/backup`**: Envia no privado do administrador o arquivo `config.json` atualizado com todas as regras, boas-vindas, mensagens recorrentes e chats vinculados.
- **`/restaurar`**: Responda ao arquivo `config.json` enviado com `/restaurar` para recarregar todas as configurações instantaneamente, sem precisar reiniciar o bot.

### ☁️ Como Atualizar ou Subir na Discloud:
> [!IMPORTANT]
> **REGRA DE OURO DA DISCLOUD:**  
> O arquivo `bot_discloud.zip` gerado para a hospedagem **NUNCA DEVE CONTER O ARQUIVO `config.json`**!  
> Dessa forma, quando você enviar o zip de uma nova versão ou reiniciar na Discloud, as suas configurações reais de grupos, mensagens e regras salvas no servidor **jamais serão apagadas ou substituídas**.

---

## 12. TABELA COMPLETA DE COMANDOS

| Comando | Nível | Onde Usar | Descrição |
| :--- | :--- | :--- | :--- |
| `/sobre` | Todos | Ambos | Exibe versão v2.5, módulos e documentação interativa |
| `/ajuda` | Todos | Ambos | Abre a Central de Ajuda categorizada com botões |
| `/tutorial` | Admin | Ambos | Abre o menu com os 11 tutoriais passo a passo |
| `/config` | Admin | Privado/Grupo | Abre o Painel Gráfico de Configuração |
| `/comunicado` | Admin | Privado | Assistente visual de transmissão passo a passo (Foto/Vídeo/Botões/Prévia) |
| `/agendados` | Admin | Privado | Consulta e gerencia a fila de transmissões agendadas pendentes |
| `/relogio` | Admin | Privado/Grupo | Diagnóstico da hora e do agendador contínuo |
| `/grupos` | Admin | Ambos | Lista todos os grupos e canais vinculados |
| `/setgrupo` | Admin | Grupo | Vincula o grupo atual |
| `/desvincular` | Admin | Ambos | Remove o vínculo do grupo |
| `/setcanal` | Admin | Privado | Vincula um canal (`@canal` ou `-100...`) |
| `/desvincularcanal` | Admin | Privado | Remove o vínculo do canal |
| `/canal` | Admin | Privado | Posta no canal com formatação total e botões |
| `/falar` | Admin | Privado | Transmite texto ou mídias para o grupo como o bot |
| `/transmitir` | Admin | Privado | Envia mensagem para todos os grupos e canais |
| `/anunciar` | Admin | Grupo | Envia comunicado oficial e fixa no topo |
| `/regras` | Todos | Grupo | Exibe as regras oficiais do grupo |
| `/ban` | Admin | Grupo | Bane o membro (suporta tempo: 10m, 2h, 1d) |
| `/kick` | Admin | Grupo | Expulsa o membro do grupo |
| `/mute` | Admin | Grupo | Silencia o membro temporariamente |
| `/unmute` | Admin | Grupo | Remove o silêncio do membro |
| `/warn` | Admin | Grupo | Adverte o membro (3 warns = ban automático) |
| `/unwarn` | Admin | Grupo | Remove advertência do membro |
| `/warns` | Todos | Grupo | Consulta advertências ativas |
| `/limpar` | Admin | Grupo | Apaga lote de mensagens |
| `/pin` | Admin | Grupo | Fixa mensagem no topo |
| `/unpin` | Admin | Grupo | Desfixa mensagem do topo |
| `/lock` | Admin | Grupo | Tranca envio de tipo de mídia específico |
| `/unlock` | Admin | Grupo | Destranca envio de tipo de mídia |
| `/locks` | Admin | Grupo | Exibe tabela de bloqueios de mídia ativos |
| `/noturno` | Admin | Grupo | Ativa ou desativa o silêncio noturno |
| `/save` | Admin | Grupo | Salva uma nota rápida (#hashtag) |
| `/notas` | Todos | Grupo | Lista todas as notas salvas no grupo |
| `/get` | Todos | Grupo | Exibe uma nota salva |
| `/clear` | Admin | Grupo | Apaga uma nota salva |
| `/filtro` | Admin | Grupo | Adiciona resposta automática rápida |
| `/filtros` | Admin | Grupo | Lista respostas automáticas e Regex |
| `/delfiltro` | Admin | Grupo | Remove resposta automática |
| `/report` | Todos | Grupo | Denuncia mensagem à equipe de moderação |
| `/info` | Todos | Grupo | Consulta ficha cadastral do usuário |
| `/staff` | Todos | Grupo | Lista equipe de administração |
| `/chatinfo` | Admin | Grupo | Exibe dados do chat e ID numérico |
| `/backup` | Admin | Privado | Faz download do arquivo de configuração |
| `/restaurar` | Admin | Privado | Restaura configurações a partir de arquivo JSON |

---

*Documentação oficial compilada para o **Maestro Bot v2.5 Enterprise**.*
