# MINIC — compilador em Python

Compilador da linguagem educacional MINIC (ver `docs/especificacao-completa-minic.pdf`),
organizado conforme a seção 14 da especificação.

## Uso

```bash
python3 minic.py programa.c              # análise léxica, sintática e semântica
python3 minic.py --ir programa.c         # imprime a IR de três endereços (-O0)
python3 minic.py --ir -O1 programa.c     # IR otimizada
python3 src/ir/interpretador.py p.ir     # executa uma IR
```

Códigos de saída (seção 11.1): 0 sucesso, 1 uso inválido, 2 erro léxico,
3 erro sintático, 4 erro semântico.

## Testes

```bash
make teste-semantico     # 20 casos da etapa semântica (compara byte a byte)
make teste-ir            # 30 casos da etapa de IR, critérios do README da suíte
make teste-ir-O1         # os mesmos casos com otimização
make teste-dirigidos     # casos de segurança das otimizações: -O0, -O1 e gcc
make teste-diferencial   # -O0, -O1 e gcc em programas aleatórios (N=200)
```

`tests/test_ir_python.sh` é o script fornecido para a etapa de IR. Ele compara
byte a byte com gabaritos que contêm texto descritivo, por isso não serve para
avaliar a IR; `tests/verificar_ir.py` aplica os critérios descritos no README
da suíte (ver `docs/arquitetura.md`).

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `src/lexer/` | `scanner.py` — tokens com linha e coluna |
| `src/parser/` | `parser.py` — parser descendente recursivo |
| `src/ast/` | `arvore.py` — nós da árvore sintática |
| `src/semantic/` | `semantic.py` — escopos, tipos e diagnósticos SEMxxx |
| `src/ir/` | `ir.py` (gerador de IR) e `interpretador.py` (execução da IR) |
| `src/optimizer/` | `otimizador.py` — passagens do modo -O1 |
| `src/codegen/` | geração de código (próxima etapa) |
| `tests/` | suítes de teste, verificador e teste diferencial |
| `examples/` | programas de exemplo |
| `docs/` | especificação, gramática e decisões de arquitetura |

Requisitos: Python 3.8+; `gcc` apenas para o teste diferencial.
