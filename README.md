# LZ Collection — Moda Masculina

Aplicação completa para vitrine masculina, **sem dependências de pacotes Python ou npm**. Front-end HTML/CSS/JavaScript responsivo e backend Python 3 com SQLite. Não inclui gateway de pagamentos: o carrinho monta mensagem para WhatsApp.

## Incluído

- Visual preto, dourado e off-white com monograma da marca.
- Oito categorias: Calçados, Camisas, Calças, Bermudas, Shorts, Regatas, Dry Fit e UV.
- Produtos, fotos e variantes por cor, tamanho e estoque.
- Campo de pesquisa no cabeçalho com sugestões e pesquisa por nome, características e termos aproximados.
- Filtros e ordenação; destaque dos produtos.
- Carrinho persistente no navegador, revalidação de estoque e finalização no WhatsApp **+55 79 99893-2703**.
- Instagram flutuante em todas as páginas públicas: https://www.instagram.com/lz.collection__/
- Painel em `/admin/login`, com autenticação de administrador, upload de imagens, produtos, estoques, categorias, banner e contatos.
- Sessões HTTP-only, scrypt para senha, limitação de tentativas de login, token CSRF, validações e restrições de acesso na API.

## Começar no Windows

1. Instale **Python 3.10+** se ainda não tiver.
2. Abra a pasta `LZ-Collection` no Terminal / PowerShell.
3. Crie sua conta de proprietário:

   `python server.py create-admin`

   Informe seu próprio e-mail e **crie uma senha nova e forte (mínimo 12 caracteres)**. Não utilize a senha compartilhada anteriormente em conversas.

4. Execute `iniciar_windows.bat`, ou digite:

   `python server.py`

5. Abra **http://localhost:8000** para ver a vitrine e **http://localhost:8000/admin/login** para o painel.
6. Faça login, cadastre as fotografias reais, os preços, tamanhos e unidades. **Produtos novos começam como rascunho**; marque “Publicar na vitrine” quando estiverem prontos.

### macOS / Linux

`python3 server.py create-admin`

`./iniciar_linux_mac.sh`

## Publicação na internet

Este pacote é executável localmente. Para ficar online 24h, contrate uma hospedagem de Python ou Docker com **armazenamento persistente** e domínio; configure HTTPS com proxy reverso e ajuste `LZ_SECURE_COOKIES=1`.

O SQLite em `data/` e as fotografias em `media/` **não podem ficar em armazenamento efêmero**. Em Docker Compose, volumes persistentes já estão declarados.

Em servidores com mais de uma réplica/instância, SQLite local deixa de ser adequado. Nesse caso migre banco e imagens para serviços compartilhados (PostgreSQL + storage compatível) antes de escalar.

Configure o proxy para encaminhar `Host` corretamente, habilite HTTPS e faça backups de **ambos** `data/` e `media/` regularmente. Não exponha diretórios `data/` e `media/` diretamente pelo seu servidor web (a aplicação só expõe `/media/<arquivo>`).

### Docker Compose

`docker compose up --build -d`

`docker compose exec lzcollection python server.py create-admin`

Após configurar HTTPS em domínio público: `LZ_SECURE_COOKIES=1 docker compose up -d`.

## Segurança e operação

- Apenas o proprietário cadastrado no CLI pode fazer login; não há registro público.
- Sessão expira em sete dias. O cookie de sessão é HTTP-only e SameSite=Lax.
- Autorização é verificada na API, independentemente de o visitante saber a rota `/admin`.
- O checkout **não dá baixa em estoque**: a venda precisa ser confirmada fora do site. Atualize o estoque manualmente após cada venda.
- Link do WhatsApp inicia a conversa **sem enviar automaticamente** a mensagem. O cliente confirma o envio.
- O sistema **não envia e-mails de recuperação** e não oferece 2FA. Se esquecer a senha, será necessário procedimento manual no servidor. Para hospedagem pública de alto tráfego recomenda-se incorporar autenticação gerenciada.
- Recomenda-se adicionar compressão/otimização automática de imagens, monitoramento, backup programado e proteção de rede/CDN antes de uma operação com grande tráfego.
- A página de privacidade é um texto inicial e **precisa ser revisada/complementada pelo proprietário** antes da publicação.
- O design não inclui fotografias reais dos produtos, porque elas não foram fornecidas. O catálogo inicia vazio, sem mercadorias fictícias. Insira as fotos pelo painel.

## Estrutura

```
server.py               API, autenticação, upload e SQLite
frontend/index.html     ponto de entrada
frontend/app.js         vitrine, busca, carrinho e administração
frontend/styles.css     estilos responsivos
frontend/assets/        monograma e identidade
media/                  fotos enviadas pelo proprietário
data/                   banco SQLite persistente
Dockerfile              build do container
compose.yaml            volumes persistentes
```

## Limitações conscientes da versão 1

- A navegação por busca completa carrega uma lista pública de até 500 produtos; se ultrapassar esse volume, implementar paginação server-side na página de resultados.
- As imagens enviadas são validadas pelo cabeçalho do arquivo, sem redimensionamento automático; fotos devem estar otimizadas para não tornar o site pesado.
- Alterações de categoria por nome mantêm o slug original (URLs não quebram); categorias novas podem ser cadastradas pela administração.
- Produtos arquivados são representados por `published=0`; exclusão definitiva está disponível no painel, com confirmação.
- Não há registro de conversões ou pedidos porque o WhatsApp não confirma uma venda ao site.

**Resultado:** uma primeira versão real e funcional, pronta para rodar e receber o catálogo — ainda não publicada em domínio nem pré-carregada com estoque real.
