
# Driver do compilador MINIC.
#
# Uso: python3 minic.py [--ir] [-O0 | -O1] <arquivo.c>
#
#   (sem opções)  análise léxica, sintática e semântica; imprime o resumo
#                 da análise (formato dos gabaritos da etapa semântica)
#   --ir          gera e imprime a representação intermediária
#   -O0 / -O1     desativa / ativa as otimizações (padrão: -O0)
#
# Códigos de saída (seção 11.1): 0 sucesso, 1 uso inválido,
# 2 erro léxico, 3 erro sintático, 4 erro semântico.

import os
import sys

from src.parser.parser import analisar_sintaxe, ErroLexico, ErroSintatico
from src.semantic.semantic import semantic, plural
from src.ir.ir import gerar_ir
from src.optimizer.otimizador import otimizar

# Os gabaritos da etapa semântica usam CRLF entre linhas e não têm quebra
# no final do arquivo; o diff do script de testes compara byte a byte.
SEPARADOR = "\r\n"

USO = "Uso: python3 minic.py [--ir] [-O0 | -O1] <arquivo.c>"


def emitir(linhas):
    # Escreve bytes UTF-8 diretamente: evita que o Python traduza "\n"
    # (no Windows) ou use outra codificação conforme o locale.
    sys.stdout.buffer.write(SEPARADOR.join(linhas).encode("utf-8"))
    sys.stdout.flush()


def emitir_ir(linhas):
    # A IR segue o formato dos gabaritos da etapa de IR: uma instrução por
    # linha, separadas por "\n", com quebra de linha no final.
    sys.stdout.buffer.write(("\n".join(linhas) + "\n").encode("utf-8"))
    sys.stdout.flush()


def ler_opcoes(argumentos):
    """Devolve (mostrar_ir, nivel_otimizacao, arquivo) ou None se inválido."""
    mostrar_ir = False
    nivel = 0
    arquivos = []
    for arg in argumentos:
        if arg == "--ir":
            mostrar_ir = True
        elif arg in ("-O0", "-O1"):
            nivel = int(arg[2])
        elif arg.startswith("-"):
            return None
        else:
            arquivos.append(arg)
    if len(arquivos) != 1:
        return None
    return mostrar_ir, nivel, arquivos[0]


def main():
    opcoes = ler_opcoes(sys.argv[1:])
    if opcoes is None:
        print(USO, file=sys.stderr)
        return 1
    mostrar_ir, nivel, nome_arquivo = opcoes

    if not os.path.isfile(nome_arquivo):
        print(f"Arquivo não encontrado: {nome_arquivo}", file=sys.stderr)
        return 1

    try:
        # estrito=False: "3 = n" chega à análise semântica (SEM013).
        ast = analisar_sintaxe(nome_arquivo, estrito=False)
    except ErroLexico as e:
        emitir([f"Erro léxico: {e}"])
        return 2
    except ErroSintatico as e:
        emitir([f"Erro sintático: {e}"])
        return 3

    # Mesma leitura do scanner (texto UTF-8), para as colunas baterem.
    with open(nome_arquivo, encoding="utf-8") as arquivo:
        fonte = arquivo.read()

    erros = semantic(fonte).analisar(ast)

    # Programa com erro semântico nunca chega à geração de IR.
    if erros or not mostrar_ir:
        linhas = [str(e) for e in erros]
        situacao = "programa aceito" if not erros else "programa rejeitado"
        linhas.append(f"Análise semântica concluída: "
                      f"{plural(len(erros), 'erro', 'erros')}; {situacao}.")
        emitir(linhas)
        return 0 if not erros else 4

    linhas = gerar_ir(ast)
    if nivel == 1:
        linhas = otimizar(linhas)
    emitir_ir(linhas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
