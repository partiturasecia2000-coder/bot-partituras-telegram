# Versão 5 — restauração, histórico único e prévia completa

Base: `bot_discloud_transmissoes_painel_v4.zip`. As versões anteriores foram preservadas. Não houve deploy, envio real ou restauração de dados da hospedagem.

## Entregas

**Restauração pelo painel.** Sistema → Backup → Restaurar backup recebe um ZIP no privado do administrador. O arquivo é validado antes de aparecer a confirmação: conteúdo permitido, limites de tamanho, JSON, estrutura e integridade dos bancos SQLite. Arquivos de aplicação, `.env`, caminhos externos, nomes duplicados, links e estruturas incompatíveis são recusados.

A prévia mostra arquivos, quantidade de partituras, exclusões, chats e programações. A confirmação é vinculada ao administrador, conversa e mensagem, expira em cinco minutos e só pode ser usada uma vez. A permissão é conferida novamente na confirmação.

Antes da substituição, o bot pausa o agendador e tarefas de importação/respostas atrasadas e cria um ZIP do estado atual em `backups/`. A troca tem diário de reversão. Uma falha durante a aplicação tenta recompor o estado anterior; se houver interrupção do processo, a recuperação é executada ao importar a configuração, antes de inicializar o banco do acervo. Se a reversão não puder terminar, o bot bloqueia novas operações até reiniciar/recuperar. Gravações antigas de configuração são rejeitadas após uma restauração.

O token e o ambiente atuais não são substituídos. IDs administrativos explícitos atuais são mantidos e o responsável pela restauração permanece autorizado; IDs vindos do arquivo não são ativados. Os destinos atuais dos backups e logs também são preservados. Recorrências, transmissões antigas, YouTube, exclusões restauradas e backups automáticos ficam pausados ou marcados para revisão, evitando executar tarefas antigas involuntariamente. A tela informa essa política antes da confirmação.

O comando `/restaurar` antigo passa pela mesma validação e prévia, incluindo arquivos JSON/DB de versões anteriores. `/backup` agora gera o ZIP completo e só permite download por administrador no privado, em vez de publicar configurações no grupo. Foi corrigida a liberação irrestrita de usuários privados na verificação administrativa dessa classe de comandos.

**Histórico único.** `/falar`, `/anunciar` e `/canal`, com seus aliases, usam o mesmo motor do `/comunicado`: resultados por destino, confirmação das partes, falhas categorizadas e repetição apenas dos destinos elegíveis. Foram mantidos seleção por ID/número/username, grupos/canais, tópicos, fixação, botões e cópia de postagem. O motor passou a aceitar também documento/PDF, áudio e voz, além de texto, foto e vídeo. Comandos em legendas são tratados antes da importação de documentos do acervo.

**Prévia completa obrigatória.** Os comandos e o assistente, em envio imediato ou agendado, criam uma prévia que não dispara a postagem. Ela reúne conteúdo legível, tipo de mídia, todos os destinos, horário, distribuição, botões, tópico e fixação. Textos e destinos longos são paginados. “Ver conteúdo no privado” mostra a postagem formatada somente ao autor; não publica a amostra no grupo de destino. Apenas “Confirmar envio/agendamento” libera o registro para o agendador. Prévia expirada, conteúdo alterado, perda de acesso, mensagem de confirmação diferente e clique repetido não iniciam novo envio. Um horário vencido durante a prévia exige preparar outro agendamento.

## Verificação

- **135 testes automatizados aprovados**, incluindo 77 testes da versão anterior e 58 novos cenários de restauração/comandos.
- Validação de ZIP/JSON/SQLite, rejeição de caminhos e arquivos indevidos, confirmação, autorização, cópia anterior, reversão de troca parcial, recuperação no início do processo e recusa de gravações antigas.
- Mídias, tópicos, cópia de post, fixação, histórico comum, prévia obrigatória, clique duplicado, destinos removidos, horários vencidos e amostra privada de comandos feitos no grupo.
- Roteamento das legendas conferido com objetos reais do SDK, sem chamadas externas.
- Checagem anterior de 52 funções de menus/importações/persistência/SQLite/durações, compilação e verificação de referências globais dos módulos alterados aprovadas.
- Pacote final conferido quanto a integridade, presença dos arquivos e preservação de deploy, mídias, dependências e valores originais de configuração/token.

Testes locais em Windows, Python 3.14.3, com as dependências fixadas existentes e chamadas de rede simuladas. A validação conectada ao Telegram e ao Discloud continua pendente.

## Uso e limites

Atualize o ZIP completo e preserve `.env`, `config.json`, `.config_backup.json`, `acervo_partituras.db`, `agendamentos.db` e a pasta `backups/` da hospedagem. Se existir um diário de restauração interrompida, preserve também `.restore_journal.json` e `.restore-transactions/` até concluir a recuperação.

Os comandos de postagem agora pedem confirmação em vez de enviar imediatamente. A prévia expira em 30 minutos; a restauração tem limite de upload de 20 MB e conteúdo descompactado de 128 MB. É necessário espaço livre para a cópia anterior e a reversão. As cópias anteriores ficam no servidor e são oferecidas ao responsável para download no privado por uma hora.

Restaurar um backup não desfaz mensagens já entregues no Telegram. Tarefas antigas são mantidas para conferência, e exclusões restauradas não são reativadas em lote nesta versão; novas exclusões continuam funcionando. Backups automáticos, YouTube e recorrências podem ser reativados pelos controles já existentes após revisão. Envios sem confirmação continuam fora das novas tentativas, pois não há garantia de entrega exatamente uma vez entre uma resposta de rede e a gravação local. Mantenha uma única instância por token/conjunto de dados.
