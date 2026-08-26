# Política de packs e da camada de API

Este projeto separa idioma estático e tradução dinâmica. Um pack não precisa ser
recriado para cada idioma apenas para traduzir diálogos; a camada opcional da API
faz isso onde os hooks possuem acesso seguro.

## Responsabilidade de cada camada

O pack ativo é responsável por:

- menus, botões, abas, configurações e tela inicial;
- mapas, localizações e nameplates;
- nomes de NPCs, monstros, itens, equipamentos, skills, spells e quests;
- qualquer texto estático que não passe por um hook com limite conhecido.

A camada da API pode traduzir:

- diálogos e história;
- walkthrough e objetivo narrativo;
- descrição de quest;
- resumo de história e trivia capturados pelo hook de texto de rede.

Diálogos com caixa de escolha são enviados como um bloco atômico. A tradução só
é aceita quando os controles permanecem idênticos e cada seletor mantém a mesma
quantidade e ordem de opções; se a validação falhar, todo o bloco permanece no
idioma do pack. Nenhum marcador novo deve ser inventado para “reconstruir” uma
caixa de escolha.

Títulos de quests, recompensas, itens e outros nomes pesquisáveis não devem ser
enviados para a API. A grafia inglesa continua compatível com as wikis em inglês
e japonês.

## Prioridade

1. O pack fornece o texto inicial.
2. Uma correção humana do idioma-alvo vence o cache automático correspondente.
3. Com `API translation overlay` ligado, somente campos de prosa suportados
   recebem tradução adicional.
4. Se a API falhar, o texto fornecido pelo pack permanece visível.
5. A conversão para caracteres aceitos pelo jogo ocorre apenas antes da escrita
   no buffer; o banco mantém Unicode completo.

A opção é desativada por padrão. Quando desligada, o comportamento legado envia
somente texto japonês para a API. Quando ligada, a origem é detectada
automaticamente.

## Continuidade dos provedores gratuitos

O launcher oferece, apenas para `Google Translate Mobile (free)`, o fallback
opcional `Use Yandex during Google Free cooldowns`. Ele não faz rotação normal
de provedores: somente um `HTTP 429` confirmado abre o cooldown e permite que
as novas falas sejam enviadas ao Yandex. Ao terminar o prazo, a próxima
tradução tenta o Google novamente. Falhas de parsing, timeout ou resposta
suspeita não acionam essa troca.

O fallback é desativado por padrão porque envia ao Yandex o texto recebido
durante o bloqueio do Google. Resultados válidos continuam usando o cache do
idioma-alvo; resultados vazios ou suspeitos não são persistidos.

## Atualização do pack inglês

Ao atualizar o pack base:

1. baixar o CLPK somente da release oficial;
2. verificar a integridade e manter um backup da versão anterior;
3. ativar apenas packs que não forneçam o mesmo arquivo de saída;
4. testar menus, mapas, inventário, equipamentos, skills, quests e lojas;
5. testar separadamente diálogo, walkthrough, descrição de quest e resumo de
   história com a camada da API ligada e desligada;
6. confirmar que nomes canônicos continuam em inglês nos dois modos;
7. confirmar que uma falha ou indisponibilidade da API devolve o texto do pack,
   sem caixa vazia;
8. registrar versão do jogo, versão do pack, idioma-alvo, provedor e screenshots.

## Guia para agentes de IA

Ao pedir manutenção a um agente, forneça este documento e exija que ele:

1. classifique cada texto como `pack-estatico`, `canonico` ou `prosa-api`;
2. nunca traduza nomes canônicos sem decisão humana explícita;
3. preserve tags e placeholders na mesma ordem;
4. trate diálogos com escolhas como blocos atômicos e preserve exatamente seus
   controles, quantidade e ordem de opções;
5. não escreva além de limites de buffer conhecidos;
6. armazene Unicode e aplique ASCII/romanização somente na fronteira do jogo;
7. não crie arquivos de tradução específicos por idioma fora de um CLPK
   explicitamente solicitado;
8. não inclua chaves, contas, banco local, logs, packs baixados ou builds;
9. execute Ruff, todos os testes Python, os testes do launcher e a build Release;
10. informe claramente campos ainda não alcançados por hooks.

## Matriz mínima de teste visual

- tela inicial e seleção de personagem;
- menu principal, itens, status, equipamento e configurações;
- mapa local e título da localização;
- loja: saudação, comprar/vender e lista de itens;
- diálogo comum e cutscene;
- walkthrough e objetivo de quest;
- descrição, título e recompensas de quest;
- story so far e registros;
- nameplates de NPC e monstro;
- falha simulada da API.

O resultado esperado com o pack inglês e a camada ligada é: cobertura estática e
nomes canônicos em inglês, prosa interceptada no idioma-alvo e nenhum texto vazio.
