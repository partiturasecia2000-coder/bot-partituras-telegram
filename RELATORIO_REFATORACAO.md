# Versão 6 — menu mais legível

Base: `bot_discloud_backup_previa_v5.zip`. O pacote anterior permaneceu intacto. A alteração foi feita em uma cópia; não houve deploy nem mensagens reais no Telegram.

## Alterações

- Painel inicial com categorias em linhas inteiras e atalhos diretos para nova postagem e histórico. Rótulos mais curtos reduzem o corte de texto no celular.
- Estados escritos como **Ativado/Desativado**, sem depender apenas de pontos coloridos. Os botões indicam a ação que será aplicada, como “Ativar antispam”.
- Cabeçalhos, resumos e espaçamento revisados em limpeza, segurança, boas-vindas, mensagens, sistema, backups, acervo, permissões, modo noturno, registros e horário. Foram removidas divisórias decorativas extensas e afirmações de funcionamento que não eram verificadas.
- Contagem de recorrências e respostas diferencia itens ativos do total cadastrado.
- Navegação padronizada com **Voltar**, **Início** e fechamento claro do painel. A ajuda informa corretamente prévia, confirmação e restauração, em vez de prometer ações instantâneas.
- Personalização de boas-vindas com botões largos e estados claros; lista de grupos agora paginada.
- Teclado do `/menu` com oito atalhos curtos: painel, partituras, postagem, histórico, canais, grupos, pessoas/links e ajuda.
- Corrigido o encaminhamento dos botões fixos: cada atalho abre a área correspondente, em vez de cair no recebimento de uma postagem. Os seis textos do teclado anterior continuam aceitos. Permissões são verificadas antes de abrir as áreas administrativas.
- Atalhos de canais e grupos abrem listas separadas; a paginação mantém o filtro selecionado.
- Descrições curtas no menu de comandos do Telegram e acesso visível aos recursos existentes de histórico, tarefas, backup e restauração.

## Prévia visual

`PREVIA_MENU_V6.html` é uma demonstração local com 17 telas, comparação com o painel anterior e alternância claro/escuro. Usa dados fictícios, não conecta ao Telegram e não executa as ações do bot. As telas e botões foram gerados pelas funções do menu novo.

A aparência exata, a fonte e o tamanho do texto seguem o aplicativo Telegram e as preferências de cada pessoa. A repaginação melhora o conteúdo, a largura dos botões e a organização; a prévia HTML é ilustrativa, não uma captura do Telegram.

## Validação

- **149 testes automatizados aprovados**: 135 anteriores e 14 de apresentação/navegação.
- Verificados: rotas originais das categorias, estados por escrito, configurações intactas ao renderizar, contadores corretos, nomes com caracteres especiais, limites dos rótulos, acesso a todos os grupos de boas-vindas, filtros da paginação e atalhos novos/antigos.
- Testado também o bloqueio de atalhos para usuário sem autorização.
- Checagem de 52 funções de menus/importações/persistência/SQLite/durações aprovada.
- Compilação e referências globais verificadas. JavaScript da prévia validado e as 17 telas exercitadas em um ambiente de DOM simulado, sem rede.
- Integridade e conteúdo do ZIP final conferidos. Arquivos de deploy, configuração, dependências, tokens e mídias preservados.

Testes locais/offline em Windows e Python 3.14.3. Não houve teste visual no aplicativo Telegram real. As confirmações, prévias de envio, controle de acesso, histórico, restauração e agendador continuam com as regras da versão 5.

## Aplicar

Atualize com o ZIP completo e reinicie o bot. Preserve os arquivos de dados da hospedagem e as pastas de backup/recuperação já existentes. Depois abra `/painel` e use `/menu` para atualizar os botões fixos na conversa. Os botões antigos continuam funcionando enquanto o teclado não for renovado.
