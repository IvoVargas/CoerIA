# Ajuda contextual em português — v0.3.111

Release preparada para publicação e deploy a pedido do utilizador.
O procedimento de deploy repete a suite na VPS antes de reiniciar o serviço.
Substitui o comportamento da v0.3.110: o ícone já não abre diretamente
uma página externa. Os registos da versão anterior permanecem históricos.

## Comportamento

- Pop-up com «O que significa», «O que preencher», «Exemplo ilustrativo»
  e «Fonte / Saber mais».
- Conteúdo editorial em português de Portugal, sem geração por IA.
- Fonte original facultativa, em nova aba, com proteção de referência e janela.
- Orientações distintas para nível/verbo SOLO/Bloom, tarefa/evidência,
  prática/acompanhamento e relações RA/TA/AE. Campos operacionais continuam
  sem ícones.
- Um diálogo nativo do navegador, partilhado pelas tabelas de consulta,
  edição e revisão. Conteúdo inserido como texto, nunca HTML vindo da sessão.
- Fecho por botão, Escape ou clique fora; foco devolvido ao acionador.
  Não guarda nem altera rascunhos, propostas ou versões.

## Verificação local

- Suite completa: **365 testes e 7 subtestes passaram**, incluindo compilação
  LaTeX/PDF. Após o ajuste editorial da ajuda das AE na grelha, os 14 testes
  específicos da ajuda voltaram a passar.

- Testes do catálogo, fontes, exclusões, taxonomias, recursos por instância,
  cabeçalhos, preservação do estado e propostas pendentes.
- Navegador: abertura em consulta e edição; diferenças entre «Nível» e
  «Verbo»; abertura por Enter e Espaço; Escape fecha e repõe o foco.
- Texto introduzido num rascunho permaneceu intacto depois de abrir e fechar
  a ajuda; a URL da página não mudou.
- A referência QNQ abriu a DGERT numa nova aba a partir do pop-up; foram
  confirmados os atributos de segurança e de privacidade da ligação.
- Pop-up inspecionado visualmente, com largura limitada, centrado e com
  deslocamento vertical para ecrãs pequenos.

As fontes são as do catálogo da v0.3.110. Os exemplos são editoriais e
ilustrativos, não citações dos autores. O DOI dos modos de IA mantém a limitação
de acesso automatizado ao OSF documentada anteriormente.
