import re
import json
import sys


# Sequências de escape válidas
ESCAPE = r"\\(?:n|t|\\|'|\")"


TOKEN_SPEC = [

    # =========================
    # Palavras reservadas
    # =========================

    ("INT", r"\bint\b"),
    ("FLOAT", r"\bfloat\b"),
    ("BOOL", r"\bbool\b"),
    ("CHAR", r"\bchar\b"),
    ("VOID", r"\bvoid\b"),
    ("IF", r"\bif\b"),
    ("ELSE", r"\belse\b"),
    ("WHILE", r"\bwhile\b"),
    ("FOR", r"\bfor\b"),
    ("RETURN", r"\breturn\b"),
    ("BREAK", r"\bbreak\b"),
    ("CONTINUE", r"\bcontinue\b"),
    ("TRUE", r"\btrue\b"),
    ("FALSE", r"\bfalse\b"),
    ("PRINT", r"\bprint\b"),
    ("READ", r"\bread\b"),


    # =========================
    # Comentários inválidos
    # =========================

    # Comentários válidos PRIMEIRO
    ("COMMENT", r"//[^\n]*"),
    ("BLOCK_COMMENT", r"/\*[\s\S]*?\*/"),

    # Comentário que começa mas não termina
    ("UNTERMINATED_BLOCK_COMMENT", r"/\*[\s\S]*$"),


    # =========================
    # Strings e caracteres
    # =========================

    # Casos válidos
    ("STRING_LIT", rf'"(?:[^"\\]|{ESCAPE})*"'),
    ("CHAR_LIT", rf"'(?:[^'\\]|{ESCAPE})'"),

    # Casos inválidos
    ("UNTERMINATED_STRING", r'"[^"\n)]*'),
    ("UNTERMINATED_CHAR", r"'[^\n]*"),


    # =========================
    # Identificadores e números
    # =========================

    ("IDENT", r"[a-zA-Z_][a-zA-Z0-9_]*"),

    ("FLOAT_LIT", r"[0-9]+\.[0-9]+"),

    ("INT_LIT", r"[0-9]+"),


    # =========================
    # Operadores
    # =========================

    ("EQ", r"=="),
    ("NE", r"!="),
    ("LE", r"<="),
    ("GE", r">="),
    ("AND", r"&&"),
    ("OR", r"\|\|"),

    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("STAR", r"\*"),
    ("SLASH", r"/"),
    ("PERCENT", r"%"),

    ("LT", r"<"),
    ("GT", r">"),
    ("NOT", r"!"),
    ("ASSIGN", r"="),


    # =========================
    # Delimitadores
    # =========================

    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),

    ("LBRACE", r"\{"),
    ("RBRACE", r"\}"),

    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),

    ("SEMICOLON", r";"),
    ("COMMA", r","),

    # Ponto
    ("DOT", r"\."),


    # =========================
    # Espaços e quebras de linha
    # =========================

    ("WHITESPACE", r"\s+"),
]


# Junta todos os padrões em uma única expressão regular
tok_regex = "|".join(
    f"(?P<{name}>{pattern})"
    for name, pattern in TOKEN_SPEC
)

get_token = re.compile(tok_regex).match


def get_attribute(tipo, valor):

    if tipo == "IDENT":
        return valor

    if tipo == "INT_LIT":
        return int(valor)

    if tipo == "FLOAT_LIT":
        return float(valor)

    if tipo == "STRING_LIT":
        return valor[1:-1]

    if tipo == "CHAR_LIT":
        return valor[1:-1]

    return None


def lexer(codigo):

    pos = 0
    linha = 1
    coluna = 1

    # Guarda se ocorreu algum erro durante a análise
    teve_erro = False


    while pos < len(codigo):

        match = get_token(codigo, pos)


        # =========================
        # Símbolo desconhecido
        # =========================

        if not match:

            erro = {
                "error": "UNKNOWN_SYMBOL",
                "lexeme": codigo[pos],
                "line": linha,
                "column": coluna
            }

            print(json.dumps(erro, ensure_ascii=False))

            teve_erro = True

            # Avança um caractere para evitar loop infinito
            if codigo[pos] == "\n":
                linha += 1
                coluna = 1
            else:
                coluna += 1

            pos += 1

            # Continua analisando o restante do código
            continue


        tipo = match.lastgroup
        valor = match.group()

        linha_inicio = linha
        coluna_inicio = coluna

        pos = match.end()


        # =========================
        # Atualiza linha e coluna
        # =========================

        linhas = valor.split("\n")

        if len(linhas) > 1:

            linha += len(linhas) - 1
            coluna = len(linhas[-1]) + 1

        else:

            coluna += len(valor)


        # =========================
        # Erro: string não terminada
        # =========================

        if tipo == "UNTERMINATED_STRING":

            erro = {
                "error": "UNTERMINATED_STRING",
                "lexeme": valor,
                "line": linha_inicio,
                "column": coluna_inicio
            }

            print(json.dumps(erro, ensure_ascii=False))

            teve_erro = True

            continue


        # =========================
        # Erro: caractere não terminado
        # =========================

        if tipo == "UNTERMINATED_CHAR":

            erro = {
                "error": "UNTERMINATED_CHAR",
                "lexeme": valor,
                "line": linha_inicio,
                "column": coluna_inicio
            }

            print(json.dumps(erro, ensure_ascii=False))

            teve_erro = True

            continue


        # =========================
        # Erro: comentário não terminado
        # =========================

        if tipo == "UNTERMINATED_BLOCK_COMMENT":

            erro = {
                "error": "UNTERMINATED_BLOCK_COMMENT",
                "lexeme": valor,
                "line": linha_inicio,
                "column": coluna_inicio
            }

            print(json.dumps(erro, ensure_ascii=False))

            teve_erro = True

            continue


        # =========================
        # Ignora espaços e comentários
        # =========================

        if tipo in (
            "WHITESPACE",
            "COMMENT",
            "BLOCK_COMMENT"
        ):

            continue


        # =========================
        # Token válido
        # =========================

        attribute = get_attribute(tipo, valor)

        token = {
            "token": tipo,
            "lexeme": valor,
            "attribute": attribute,
            "line": linha_inicio,
            "column": coluna_inicio
        }

        print(json.dumps(token, ensure_ascii=False))


    # =========================
    # EOF
    # =========================

    token = {
        "token": "EOF",
        "lexeme": "",
        "attribute": None,
        "line": linha,
        "column": coluna
    }

    print(json.dumps(token, ensure_ascii=False))


    # Se ocorreu algum erro, retorna 2.
    # Caso contrário, retorna 0.
    if teve_erro:
        return 2

    return 0


def ler_arquivo(nome_arquivo):

    try:

        with open(
            nome_arquivo,
            "r",
            encoding="utf-8"
        ) as arquivo:

            return arquivo.read()

    except FileNotFoundError:

        raise FileNotFoundError(
            f"Arquivo não encontrado: {nome_arquivo}"
        )


def main():

    if len(sys.argv) != 2:

        print("Uso: python scanner.py <arquivo.c>")

        return 1


    nome_arquivo = sys.argv[1]


    try:

        codigo = ler_arquivo(nome_arquivo)

        return lexer(codigo)


    except FileNotFoundError as erro:

        print(erro)

        return 1


if __name__ == "__main__":

    sys.exit(main())
