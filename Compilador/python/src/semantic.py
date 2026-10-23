
# Analisador semântico do MINIC.

# Percorre a AST produzida pelo parser (arvore.py), verificando nomes,
# escopos, tipos e regras contextuais (seções 5, 6 e 7 da especificação).
# Os diagnósticos seguem o catálogo SEMxxx do GABARITO.md da suíte de testes.

# Os erros são acumulados (vários por execução); cada expressão recebe seu
# tipo inferido em `no.tipo`, e identificadores/chamadas recebem `no.simbolo`.


from arvore import (
    Programa, Funcao, DeclVar, ListaDecl, Bloco, If, While, For,
    Return, Break, Continue, Print, Read, ExprStmt, Atribuicao, Binaria,
    Unaria, Chamada, Indice, Identificador, Literal,
)



# Catálogo de códigos

SEM001 = "SEM001"  # identificador não declarado
SEM002 = "SEM002"  # declaração duplicada
SEM003 = "SEM003"  # incompatibilidade de atribuição/conversão
SEM004 = "SEM004"  # operando de tipo inválido para o operador
SEM005 = "SEM005"  # condição não booleana
SEM006 = "SEM006"  # índice (ou tamanho) de vetor inválido
SEM007 = "SEM007"  # aridade incorreta
SEM008 = "SEM008"  # tipo de argumento incompatível
SEM009 = "SEM009"  # retorno incompatível
SEM010 = "SEM010"  # break/continue fora de laço
SEM011 = "SEM011"  # possível queda de função não void
SEM012 = "SEM012"  # chamada void usada como valor
SEM013 = "SEM013"  # destino não atribuível
SEM014 = "SEM014"  # uso inválido de símbolo ou tipo
SEM015 = "SEM015"  # divisão por zero constante


# Representação de tipos

class Tipo:
    """Tipo base (int, float, bool, char, void, string, erro) + flag de vetor."""

    def __init__(self, base, vetor=False):
        self.base = base
        self.vetor = vetor

    def __eq__(self, outro):
        return (isinstance(outro, Tipo)
                and self.base == outro.base and self.vetor == outro.vetor)

    def __hash__(self):
        return hash((self.base, self.vetor))

    def __str__(self):
        return self.base + ("[]" if self.vetor else "")


INT = Tipo("int")
FLOAT = Tipo("float")
BOOL = Tipo("bool")
CHAR = Tipo("char")
VOID = Tipo("void")
STRING = Tipo("string")
# Tipo "coringa" usado após um erro, para não gerar erros em cascata.
ERRO = Tipo("erro")

TIPO_LITERAL = {"int": INT, "real": FLOAT, "bool": BOOL,
                "char": CHAR, "string": STRING}

DESCRICAO_LITERAL = {"int": "o literal inteiro", "real": "o literal real",
                     "bool": "o literal booleano", "char": "o literal caractere",
                     "string": "a cadeia"}

# Conversões implícitas permitidas (destino, origem) — seção 5.
# char -> float é a composição char -> int -> float.
CONVERSOES_IMPLICITAS = {("float", "int"), ("int", "char"), ("float", "char")}


def eh_erro(*tipos):
    return any(t == ERRO for t in tipos)


def eh_numerico(t):
    return not t.vetor and t.base in ("int", "float", "char")


def eh_inteiro(t):
    return not t.vetor and t.base in ("int", "char")


def compativel(destino, origem):
    """Um valor do tipo `origem` pode ser usado onde se espera `destino`?"""
    if eh_erro(destino, origem):
        return True
    if destino.vetor or origem.vetor:
        return destino == origem
    if destino.base == origem.base:
        return destino.base not in ("void", "string")
    return (destino.base, origem.base) in CONVERSOES_IMPLICITAS


def plural(n, singular, plural_):
    return f"{n} {singular if n == 1 else plural_}"


# Tabela de símbolos (seção 6)

class Simbolo:
    def __init__(self, nome, categoria, tipo, nivel, linha, coluna,
                 parametros=None, tamanho=None):
        self.nome = nome
        self.categoria = categoria    # VARIÁVEL, PARÂMETRO, VETOR, FUNÇÃO
        self.tipo = tipo              # para FUNÇÃO, é o tipo de retorno
        self.nivel = nivel            # nível léxico (0 = global)
        self.linha = linha
        self.coluna = coluna
        self.parametros = parametros or []   # lista de Tipo (funções)
        self.tamanho = tamanho        # tamanho constante do vetor, se conhecido
        self.inicializado = False
        self.usado = False


class TabelaSimbolos:
    """Pilha de escopos; cada escopo é um dicionário nome -> Simbolo."""

    def __init__(self):
        self.escopos = [{}]   # escopo global

    @property
    def nivel(self):
        return len(self.escopos) - 1

    def abrir_escopo(self):
        self.escopos.append({})

    def fechar_escopo(self):
        self.escopos.pop()

    def inserir(self, nome, simbolo):
        self.escopos[-1][nome] = simbolo

    def buscar_no_escopo_atual(self, nome):
        return self.escopos[-1].get(nome)

    def buscar(self, nome):
        # Do escopo mais interno para o mais externo: sombreamento léxico.
        for escopo in reversed(self.escopos):
            if nome in escopo:
                return escopo[nome]
        return None


# Diagnósticos

class Diagnostico:
    def __init__(self, codigo, linha, coluna, mensagem):
        self.codigo = codigo
        self.linha = linha
        self.coluna = coluna
        self.mensagem = mensagem

    def __str__(self):
        return (f"{self.codigo} — linha {self.linha}, "
                f"coluna {self.coluna}: {self.mensagem}")


# Analisador

class semantic:

    def __init__(self, fonte=None):
        # O texto-fonte é usado para citar expressões nas mensagens.
        self.fonte = fonte
        self.inicio_linhas = [0]
        if fonte is not None:
            self.inicio_linhas += [i + 1 for i, c in enumerate(fonte) if c == "\n"]

        self.tabela = TabelaSimbolos()
        self.erros = []
        self.funcao_atual = None   # Simbolo da função sendo analisada
        self.nivel_laco = 0        # > 0 quando dentro de while/for


    def erro(self, codigo, no, mensagem):
        self.erros.append(Diagnostico(codigo, no.linha, no.coluna, mensagem))

    def texto(self, no):
        """Trecho do código-fonte que originou a expressão."""
        if self.fonte is None or no.fim_linha is None:
            return str(no)
        inicio = self.inicio_linhas[no.linha - 1] + no.coluna - 1
        fim = self.inicio_linhas[no.fim_linha - 1] + no.fim_coluna - 1
        return self.fonte[inicio:fim]

    def analisar(self, programa):
        self.visitar(programa)
        # "Em ordem de origem". sort() é estável: empates mantêm a ordem
        # em que foram detectados.
        self.erros.sort(key=lambda e: (e.linha, e.coluna))
        return self.erros

    def visitar(self, no):
        return getattr(self, "visitar_" + type(no).__name__)(no)


    # Declarações, nomes e escopos

    def visitar_Programa(self, no):
        for decl in no.declaracoes:
            if isinstance(decl, (Funcao, DeclVar, ListaDecl)):
                self.visitar(decl)
            else:
                self.erro(SEM014, decl, "Comando fora de função.")

        # A ausência de main não é erro (a suíte usa "principal"), mas,
        # se main existir, sua assinatura é verificada.
        main = self.tabela.buscar("main")
        if main is not None and main.categoria == "FUNÇÃO":
            if main.tipo != INT:
                self.erro(SEM014, main, "A função “main” deve retornar int.")
            if main.parametros:
                self.erro(SEM014, main, "A função “main” não deve ter parâmetros.")

    def declarar(self, simbolo):
        """Insere no escopo atual, rejeitando duplicidade (SEM002)."""
        anterior = self.tabela.buscar_no_escopo_atual(simbolo.nome)
        if anterior is not None:
            if anterior.categoria == "FUNÇÃO":
                descricao = f"função de retorno {anterior.tipo}"
            else:
                descricao = f"tipo {anterior.tipo}"
            self.erro(SEM002, simbolo,
                      f"“{simbolo.nome}” já declarado neste escopo; "
                      f"declaração anterior na linha {anterior.linha}, "
                      f"coluna {anterior.coluna} ({descricao}).")
            return False
        self.tabela.inserir(simbolo.nome, simbolo)
        return True

    def visitar_ListaDecl(self, no):
        for decl in no.declaracoes:
            self.visitar(decl)

    def visitar_DeclVar(self, no):
        if no.tipo_base == "void":
            self.erro(SEM014, no, f"Variável “{no.nome}” não pode ter tipo void.")
            tipo = ERRO
        else:
            tipo = Tipo(no.tipo_base, vetor=no.tamanho is not None)

        tamanho = None
        if no.tamanho is not None:
            t_tamanho = self.expr(no.tamanho, "como tamanho de vetor")
            if not eh_erro(t_tamanho) and not eh_inteiro(t_tamanho):
                self.erro(SEM006, no.tamanho,
                          f"Tamanho do vetor “{no.nome}” deve ser int; recebeu "
                          f"{t_tamanho} (expressão “{self.texto(no.tamanho)}”).")
            tamanho = valor_constante(no.tamanho)
            if isinstance(tamanho, int) and tamanho <= 0:
                self.erro(SEM006, no.tamanho,
                          f"Tamanho do vetor “{no.nome}” deve ser positivo; "
                          f"recebeu {tamanho}.")

        # O inicializador é analisado ANTES de inserir o nome:
        # em "int x = x;" o x da direita não é o que está sendo declarado.
        if no.inicializador is not None:
            t_init = self.expr(no.inicializador, "como inicializador")
            if tipo.vetor:
                self.erro(SEM003, no.inicializador,
                          f"Vetor “{no.nome}” não pode receber inicializador.")
            elif not compativel(tipo, t_init):
                self.erro(SEM003, no.inicializador,
                          f"Não é possível atribuir {t_init} a {tipo} sem "
                          f"conversão permitida (destino “{no.nome}”; "
                          f"expressão “{self.texto(no.inicializador)}”).")

        categoria = "VETOR" if tipo.vetor else "VARIÁVEL"
        simbolo = Simbolo(no.nome, categoria, tipo, self.tabela.nivel,
                          no.linha, no.coluna, tamanho=tamanho)
        simbolo.inicializado = no.inicializador is not None
        no.simbolo = simbolo
        self.declarar(simbolo)

    def visitar_Funcao(self, no):
        tipos_params = [Tipo(p.tipo_base, p.eh_vetor) for p in no.parametros]
        # O símbolo fica na posição do NOME (usada no SEM002);
        # o nó Funcao fica na posição do tipo de retorno (usada no SEM011).
        simbolo = Simbolo(no.nome, "FUNÇÃO", Tipo(no.tipo_retorno),
                          self.tabela.nivel, no.linha_nome, no.coluna_nome,
                          parametros=tipos_params)
        no.simbolo = simbolo

        # A função entra na tabela antes do corpo: permite recursão.
        self.declarar(simbolo)

        self.funcao_atual = simbolo
        self.tabela.abrir_escopo()

        for param, tipo in zip(no.parametros, tipos_params):
            if param.tipo_base == "void":
                self.erro(SEM014, param,
                          f"Parâmetro “{param.nome}” não pode ter tipo void.")
                tipo = ERRO
            s = Simbolo(param.nome, "PARÂMETRO", tipo, self.tabela.nivel,
                        param.linha, param.coluna)
            s.inicializado = True
            param.simbolo = s
            self.declarar(s)

        # Parâmetros e corpo compartilham o mesmo escopo (como em C):
        # "int f(int a) { int a; }" é declaração duplicada.
        for comando in no.corpo.comandos:
            self.visitar(comando)

        if simbolo.tipo != VOID:
            motivo = self.motivo_queda(no.corpo)
            if motivo is not None:
                if motivo is CAI:
                    motivo = "o fim do corpo é alcançado sem executar return"
                self.erro(SEM011, no,
                          f"A função “{no.nome}” pode terminar sem retornar "
                          f"{simbolo.tipo}; {motivo}.")

        self.tabela.fechar_escopo()
        self.funcao_atual = None

    # Comandos e regras contextuais

    def visitar_Bloco(self, no):
        # Todo bloco interno cria um escopo próprio (sombreamento).
        self.tabela.abrir_escopo()
        for comando in no.comandos:
            self.visitar(comando)
        self.tabela.fechar_escopo()

    def condicao(self, expr, comando):
        tipo = self.expr(expr, "como condição")
        if not eh_erro(tipo) and tipo != BOOL:
            self.erro(SEM005, expr,
                      f"Condição de {comando} deve ter tipo bool; recebeu "
                      f"{tipo} (expressão “{self.texto(expr)}”).")

    def visitar_If(self, no):
        self.condicao(no.condicao, "if")
        self.visitar(no.entao)
        if no.senao is not None:
            self.visitar(no.senao)

    def visitar_While(self, no):
        self.condicao(no.condicao, "while")
        self.nivel_laco += 1
        self.visitar(no.corpo)
        self.nivel_laco -= 1

    def visitar_For(self, no):
        if no.inicio is not None:
            self.expr(no.inicio, contexto=None)
        if no.condicao is not None:
            self.condicao(no.condicao, "for")
        if no.passo is not None:
            self.expr(no.passo, contexto=None)
        self.nivel_laco += 1
        self.visitar(no.corpo)
        self.nivel_laco -= 1

    def visitar_Break(self, no):
        if self.nivel_laco == 0:
            self.erro(SEM010, no, "Comando “break” fora de laço.")

    def visitar_Continue(self, no):
        if self.nivel_laco == 0:
            self.erro(SEM010, no, "Comando “continue” fora de laço.")

    def visitar_Return(self, no):
        esperado = self.funcao_atual.tipo
        nome = self.funcao_atual.nome

        if no.expressao is None:
            if esperado != VOID:
                self.erro(SEM009, no,
                          f"Retorno sem valor na função “{nome}”, que deve "
                          f"retornar {esperado}.")
            return

        if esperado == VOID:
            self.expr(no.expressao, contexto=None)
            self.erro(SEM009, no.expressao,
                      f"A função “{nome}” é void e não pode retornar valor "
                      f"(expressão “{self.texto(no.expressao)}”).")
            return

        tipo = self.expr(no.expressao, "como valor de retorno")
        if not compativel(esperado, tipo):
            self.erro(SEM009, no.expressao,
                      f"Retorno {tipo} incompatível com o tipo {esperado} da "
                      f"função “{nome}”; conversão implícita de {tipo} para "
                      f"{esperado} não permitida.")

    def visitar_Print(self, no):
        arg = no.argumento
        if isinstance(arg, Literal) and arg.tipo_literal == "string":
            arg.tipo = STRING   # cadeia só é aceita aqui
            return
        tipo = self.expr(arg, "como argumento de print")
        if not eh_erro(tipo) and tipo.vetor:
            self.erro(SEM014, arg,
                      f"print não aceita um vetor inteiro "
                      f"(expressão “{self.texto(arg)}”).")

    def visitar_Read(self, no):
        self.destino(no.alvo, "leitura")

    def visitar_ExprStmt(self, no):
        if no.expressao is not None:
            # contexto=None: chamada void permitida, o valor é descartado.
            self.expr(no.expressao, contexto=None)


    # Cobertura de retornos

    def motivo_queda(self, no):
        """None se todo caminho por `no` executa return; senão, o motivo.

        Devolve a constante CAI quando o comando simplesmente não retorna,
        sem um motivo mais específico (ex.: uma atribuição).
        """
        if isinstance(no, Return):
            return None

        if isinstance(no, Bloco):
            motivos = [self.motivo_queda(c) for c in no.comandos]
            if any(m is None for m in motivos):
                return None
            # Explica pelo último comando que tem um motivo específico.
            for m in reversed(motivos):
                if m is not CAI:
                    return m
            return CAI

        if isinstance(no, If):
            cond = self.texto(no.condicao)
            m_entao = self.motivo_queda(no.entao)
            if m_entao is CAI:
                return f"o ramo em que “{cond}” é verdadeiro alcança o fim do corpo"
            if m_entao is not None:
                return m_entao
            if no.senao is None:
                return f"o ramo em que “{cond}” é falso alcança o fim do corpo"
            m_senao = self.motivo_queda(no.senao)
            if m_senao is CAI:
                return f"o ramo em que “{cond}” é falso alcança o fim do corpo"
            return m_senao

        if isinstance(no, (While, For)):
            if laco_infinito(no):
                return None   # só sai por return: não alcança o fim
            nome = "while" if isinstance(no, While) else "for"
            return (f"o laço {nome} pode terminar sem executar return "
                    f"e alcançar o fim do corpo")

        return CAI
    

    # Expressões e tipos

    def expr(self, no, contexto="como valor"):
        """Analisa uma expressão, anota no.tipo e devolve o tipo.

        `contexto` descreve onde o valor é usado (para o SEM012).
        contexto=None significa posição de comando: void é permitido.
        """
        tipo = getattr(self, "expr_" + type(no).__name__)(no)

        if tipo == VOID and contexto is not None:
            nome = (no.funcao.nome if isinstance(no, Chamada)
                    and isinstance(no.funcao, Identificador) else self.texto(no))
            self.erro(SEM012, no,
                      f"Função “{nome}” não produz valor (retorno void) e "
                      f"não pode ser usada {contexto}.")
            tipo = ERRO

        no.tipo = tipo
        return tipo

    def expr_Literal(self, no):
        if no.tipo_literal == "string":
            self.erro(SEM014, no,
                      f"Cadeia “{no.lexema[1:-1]}” só é permitida como "
                      f"argumento de print.")
            return ERRO
        return TIPO_LITERAL[no.tipo_literal]

    def expr_Identificador(self, no):
        simbolo = self.tabela.buscar(no.nome)
        if simbolo is None:
            self.erro(SEM001, no,
                      f"Identificador “{no.nome}” não declarado neste escopo.")
            return ERRO

        no.simbolo = simbolo
        if simbolo.categoria == "FUNÇÃO":
            self.erro(SEM014, no,
                      f"“{no.nome}” é uma função e não pode ser usada sem chamada.")
            return ERRO

        simbolo.usado = True
        return simbolo.tipo

    def destino(self, alvo, operacao):
        """Valida o lado esquerdo de atribuição ou o alvo de read (SEM013)."""
        prefixo = f"Destino de {operacao} não é atribuível"

        if isinstance(alvo, Identificador):
            simbolo = self.tabela.buscar(alvo.nome)
            if simbolo is None:
                self.erro(SEM001, alvo,
                          f"Identificador “{alvo.nome}” não declarado neste escopo.")
                return ERRO
            alvo.simbolo = simbolo
            if simbolo.categoria == "FUNÇÃO":
                self.erro(SEM013, alvo,
                          f"{prefixo}; “{alvo.nome}” designa uma função, não "
                          f"uma variável ou elemento de vetor.")
                return ERRO
            if simbolo.tipo.vetor:
                self.erro(SEM013, alvo,
                          f"{prefixo}; “{alvo.nome}” designa um vetor inteiro, "
                          f"não uma variável ou elemento de vetor.")
                return ERRO
            simbolo.inicializado = True
            alvo.tipo = simbolo.tipo
            return simbolo.tipo

        if isinstance(alvo, Indice):
            return self.expr(alvo)

        # Qualquer outra expressão: analisa (para achar erros internos) e
        # rejeita como destino.
        self.expr(alvo, contexto=None)
        if isinstance(alvo, Literal):
            descricao = DESCRICAO_LITERAL[alvo.tipo_literal]
        elif isinstance(alvo, Chamada):
            descricao = "a chamada"
        else:
            descricao = "a expressão"
        self.erro(SEM013, alvo,
                  f"{prefixo}; {descricao} “{self.texto(alvo)}” não designa "
                  f"uma variável ou elemento de vetor.")
        return ERRO

    def expr_Atribuicao(self, no):
        t_valor = self.expr(no.valor, "como expressão de atribuição")
        t_alvo = self.destino(no.alvo, "atribuição")

        if eh_erro(t_alvo, t_valor):
            return ERRO
        if not compativel(t_alvo, t_valor):
            self.erro(SEM003, no.valor,
                      f"Não é possível atribuir {t_valor} a {t_alvo} sem "
                      f"conversão permitida (destino “{self.texto(no.alvo)}”; "
                      f"expressão “{self.texto(no.valor)}”).")
            return ERRO
        return t_alvo

    def expr_Unaria(self, no):
        tipo = self.expr(no.operando, "como operando")
        if eh_erro(tipo):
            return ERRO

        if no.operador == "!":
            if tipo != BOOL:
                self.erro(SEM004, no,
                          f"Operador “!” exige operando bool; recebeu {tipo} "
                          f"(expressão “{self.texto(no)}”).")
                return ERRO
            return BOOL

        # "-" unário
        if not eh_numerico(tipo):
            self.erro(SEM004, no,
                      f"Operador “-” exige operando numérico; recebeu {tipo} "
                      f"(expressão “{self.texto(no)}”).")
            return ERRO
        return FLOAT if tipo == FLOAT else INT

    def expr_Binaria(self, no):
        op = no.operador
        te = self.expr(no.esquerda, "como operando")
        td = self.expr(no.direita, "como operando")
        if eh_erro(te, td):
            return ERRO

        def rejeitar(exigencia):
            self.erro(SEM004, no,
                      f"Operador “{op}” {exigencia}; recebeu {te} e {td} "
                      f"(expressão “{self.texto(no)}”).")
            return ERRO

        if op in ("&&", "||"):
            if te != BOOL or td != BOOL:
                return rejeitar("exige operandos bool")
            return BOOL

        if op in ("==", "!="):
            if eh_numerico(te) and eh_numerico(td):
                return BOOL
            if te == td and not te.vetor:
                return BOOL
            return rejeitar("exige operandos de tipos comparáveis")

        if op in ("<", ">", "<=", ">="):
            if not (eh_numerico(te) and eh_numerico(td)):
                return rejeitar("exige operandos numéricos")
            return BOOL

        if op == "%":
            if not (eh_inteiro(te) and eh_inteiro(td)):
                return rejeitar("exige operandos inteiros")
            self.checar_divisor(no)
            return INT

        # + - * /
        if not (eh_numerico(te) and eh_numerico(td)):
            return rejeitar("exige operandos numéricos")
        if op == "/":
            self.checar_divisor(no)
        return FLOAT if FLOAT in (te, td) else INT

    def checar_divisor(self, no):
        if valor_constante(no.direita) == 0:
            self.erro(SEM015, no.direita,
                      f"Divisão por zero constante "
                      f"(expressão “{self.texto(no)}”).")

    def expr_Chamada(self, no):
        def analisar_argumentos():
            return [self.expr(a, "como argumento") for a in no.argumentos]

        if not isinstance(no.funcao, Identificador):
            self.erro(SEM014, no,
                      f"Apenas funções nomeadas podem ser chamadas "
                      f"(expressão “{self.texto(no)}”).")
            analisar_argumentos()
            return ERRO

        nome = no.funcao.nome
        simbolo = self.tabela.buscar(nome)
        if simbolo is None:
            self.erro(SEM001, no.funcao,
                      f"Identificador “{nome}” não declarado neste escopo.")
            analisar_argumentos()
            return ERRO
        if simbolo.categoria != "FUNÇÃO":
            self.erro(SEM014, no.funcao,
                      f"“{nome}” não é uma função e não pode ser chamado.")
            analisar_argumentos()
            return ERRO

        no.funcao.simbolo = simbolo
        no.simbolo = simbolo
        simbolo.usado = True

        tipos_args = analisar_argumentos()
        esperados = simbolo.parametros

        if len(tipos_args) != len(esperados):
            self.erro(SEM007, no,
                      f"“{nome}” espera "
                      f"{plural(len(esperados), 'argumento', 'argumentos')}, "
                      f"mas recebeu {len(tipos_args)}.")
        else:
            for i, (arg, t_arg, t_param) in enumerate(
                    zip(no.argumentos, tipos_args, esperados), 1):
                if not compativel(t_param, t_arg):
                    self.erro(SEM008, arg,
                              f"Argumento {i} de “{nome}”: esperado {t_param}, "
                              f"recebido {t_arg} (expressão “{self.texto(arg)}”).")

        return simbolo.tipo

    def expr_Indice(self, no):
        t_vetor = self.expr(no.vetor, "como operando")
        t_indice = self.expr(no.indice, "como índice")
        nome_vetor = self.texto(no.vetor)

        if not eh_erro(t_indice) and not eh_inteiro(t_indice):
            self.erro(SEM006, no.indice,
                      f"Índice do vetor “{nome_vetor}” deve ser int; recebeu "
                      f"{t_indice} (expressão “{self.texto(no.indice)}”).")

        if eh_erro(t_vetor):
            return ERRO
        if not t_vetor.vetor:
            self.erro(SEM014, no.vetor,
                      f"“{nome_vetor}” não é um vetor e não pode ser indexado "
                      f"(tipo {t_vetor}).")
            return ERRO

        # Limites: verificáveis em compilação quando índice e tamanho
        # são constantes.
        simbolo = no.vetor.simbolo if isinstance(no.vetor, Identificador) else None
        indice = valor_constante(no.indice)
        if (simbolo is not None and isinstance(simbolo.tamanho, int)
                and isinstance(indice, int)
                and not 0 <= indice < simbolo.tamanho):
            self.erro(SEM006, no.indice,
                      f"Índice {indice} fora dos limites do vetor "
                      f"“{nome_vetor}” (tamanho {simbolo.tamanho}).")

        return Tipo(t_vetor.base)


# Funções auxiliares (análise estática)

# Marcador: "este comando não retorna", sem motivo específico.
CAI = object()


def valor_constante(no):
    """Avalia expressões numéricas constantes; devolve None se não for."""
    if isinstance(no, Literal) and no.tipo_literal in ("int", "real"):
        return no.valor
    if isinstance(no, Unaria) and no.operador == "-":
        v = valor_constante(no.operando)
        return None if v is None else -v
    if isinstance(no, Binaria) and no.operador in ("+", "-", "*"):
        e, d = valor_constante(no.esquerda), valor_constante(no.direita)
        if e is None or d is None:
            return None
        return {"+": e + d, "-": e - d, "*": e * d}[no.operador]
    return None


def contem_break(no):
    """Há um break que sai DESTE laço? (ignora laços aninhados)"""
    if isinstance(no, Break):
        return True
    if isinstance(no, Bloco):
        return any(contem_break(c) for c in no.comandos)
    if isinstance(no, If):
        return contem_break(no.entao) or (
            no.senao is not None and contem_break(no.senao))
    return False


def laco_infinito(no):
    """while(true) ou for(;;) sem break: o fim do laço é inalcançável."""
    cond = no.condicao
    sempre = cond is None or (isinstance(cond, Literal)
                              and cond.tipo_literal == "bool"
                              and cond.lexema == "true")
    return sempre and not contem_break(no.corpo)
