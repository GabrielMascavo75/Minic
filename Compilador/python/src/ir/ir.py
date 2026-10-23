
# Geração de representação intermediária (IR) de três endereços do MINIC.

# Recebe a árvore JÁ VALIDADA pela análise semântica (com no.tipo e
# no.simbolo preenchidos) e produz uma lista de linhas de IR.

# Conjunto de instruções:

#     x = y                      cópia (ASSIGN)
#     x = y op z                 + - * / % < > <= >= == != and or
#     x = not y                  NOT
#     x = neg y                  NEG (menos unário)
#     x = itof y                 conversão int -> float
#     x = ctoi y                 conversão char -> int
#     x = load v[i]              LOAD de elemento de vetor
#     store v[i], y              STORE em elemento de vetor
#     param y                    PARAM
#     x = call f, n              CALL com resultado
#     call f, n                  CALL sem resultado (void ou valor descartado)
#     return / return y          RETURN
#     print y / read x           saída e entrada
#     goto L                     JUMP
#     ifFalse x goto L           JUMP_IF_FALSE
#     ifTrue x goto L            JUMP_IF_TRUE
#     L:                         LABEL
#     global x / global v[n]     declaração de variável global

# Decisões de implementação (não fixadas pela especificação):
#   - Temporários (t1, t2, ...) e rótulos recomeçam em cada função.
#   - Índices de vetor são em unidades de elemento: o endereço é i * 1.
#   - && e || têm curto-circuito, como em C. Quando o operando da direita
#     pode ser avaliado sempre sem efeito observável (sem chamadas, sem
#     acesso a vetor e sem divisão por algo que possa ser zero), a IR usa a
#     operação direta (and/or), como no gabarito P08 — o resultado é o mesmo.
#     Caso contrário, gera saltos:
#         t1 = <esquerda>
#         ifFalse t1 goto L_sc        (para ||: ifTrue t1 goto L_sc)
#         t1 = <direita>
#       L_sc:
#   - Argumentos são todos avaliados, da esquerda para a direita, antes
#     dos "param": assim chamadas aninhadas não misturam seus parâmetros.
#   - Variáveis com o mesmo nome em escopos diferentes recebem nomes
#     distintos (x, x#2, ...), pois a IR não tem blocos.
#   - Inicializadores de globais vão para a função especial "#init",
#     executada antes de main.


import re

from src.ast.arvore import (
    Programa, Funcao, DeclVar, ListaDecl, Bloco, If, While, For,
    Return, Break, Continue, Print, Read, ExprStmt, Atribuicao, Binaria,
    Unaria, Chamada, Indice, Identificador, Literal,
)
from src.semantic.semantic import INT, FLOAT, CHAR, VOID, laco_infinito, valor_constante

# Palavras da IR que não podem ser usadas como nome de variável, para que
# a IR continue sem ambiguidade (ex.: uma variável chamada "call").
RESERVADAS_IR = {
    "func", "endfunc", "global", "param", "call", "return", "print", "read",
    "goto", "ifFalse", "load", "store", "not", "neg", "itof", "ctoi",
    "and", "or", "true", "false",
}

OPERADORES_IR = {"&&": "and", "||": "or"}

ESCALA_ELEMENTO = 1   # índices em unidades de elemento


def eh_temporario(nome):
    return re.fullmatch(r"t\d+", nome) is not None


def avaliacao_segura(no):
    """A expressão pode ser avaliada mesmo quando o programa não a avaliaria?
    (sem efeitos observáveis e sem possibilidade de erro em execução)"""
    if isinstance(no, (Literal, Identificador)):
        return True
    if isinstance(no, Unaria):
        return avaliacao_segura(no.operando)
    if isinstance(no, Binaria):
        if no.operador in ("/", "%"):
            divisor = valor_constante(no.direita)
            if divisor is None or divisor == 0:
                return False
        return avaliacao_segura(no.esquerda) and avaliacao_segura(no.direita)
    return False   # chamadas, acessos a vetor e atribuições


def sempre_retorna(no):
    """Todo caminho pelo comando termina em return? (sem diagnósticos)"""
    if isinstance(no, Return):
        return True
    if isinstance(no, Bloco):
        return any(sempre_retorna(c) for c in no.comandos)
    if isinstance(no, If):
        return (no.senao is not None
                and sempre_retorna(no.entao) and sempre_retorna(no.senao))
    if isinstance(no, (While, For)):
        return laco_infinito(no)
    return False


class GeradorIR:

    def __init__(self):
        self.linhas = []
        self.nomes = {}          # id(Simbolo) -> nome na IR
        self.usados_global = set()

        # Estado da função em geração
        self.usados = set()
        self.n_temp = 0
        self.n_construcao = 0
        self.lacos = []          # pilha de (rótulo do break, rótulo do continue)

    # Utilidades

    def emitir(self, instrucao):
        self.linhas.append("  " + instrucao)

    def emitir_rotulo(self, rotulo):
        self.linhas.append(f"{rotulo}:")

    def novo_temp(self):
        self.n_temp += 1
        return f"t{self.n_temp}"

    def novos_rotulos(self, *bases):
        """Rótulos de uma construção: L_else, L_end (1ª), L_else2, ... """
        self.n_construcao += 1
        sufixo = "" if self.n_construcao == 1 else str(self.n_construcao)
        return [f"L_{base}{sufixo}" for base in bases]

    def nomear(self, simbolo, usados):
        """Escolhe o nome do símbolo na IR, evitando colisões."""
        base = simbolo.nome
        nome = base
        k = 1
        while nome in usados or nome in RESERVADAS_IR or eh_temporario(nome):
            k += 1
            nome = f"{base}#{k}"
        usados.add(nome)
        self.nomes[id(simbolo)] = nome
        return nome

    def nome(self, simbolo):
        return self.nomes[id(simbolo)]

    def converter(self, operando, de, para):
        """Insere as conversões implícitas anotadas pela semântica."""
        if para == FLOAT and de == CHAR:
            operando = self.converter(operando, CHAR, INT)
            de = INT
        if para == FLOAT and de == INT:
            t = self.novo_temp()
            self.emitir(f"{t} = itof {operando}")
            return t
        if para == INT and de == CHAR:
            t = self.novo_temp()
            self.emitir(f"{t} = ctoi {operando}")
            return t
        return operando

    def endereco(self, indice):
        """Calcula o deslocamento de um elemento: indice * escala."""
        i = self.expr(indice)
        i = self.converter(i, indice.tipo, INT)
        t = self.novo_temp()
        self.emitir(f"{t} = {i} * {ESCALA_ELEMENTO}")
        return t
    
    # Programa e funções

    def gerar(self, programa):
        globais = []
        funcoes = []
        for decl in programa.declaracoes:
            if isinstance(decl, Funcao):
                funcoes.append(decl)
            elif isinstance(decl, ListaDecl):
                globais.extend(decl.declaracoes)
            else:
                globais.append(decl)

        # Globais: declaração e, se houver, inicialização em "#init".
        for decl in globais:
            nome = self.nomear(decl.simbolo, self.usados_global)
            tamanho = decl.simbolo.tamanho
            if decl.simbolo.tipo.vetor:
                self.linhas.append(f"global {nome}[{tamanho}]")
            else:
                self.linhas.append(f"global {nome}")

        inicializadas = [d for d in globais if d.inicializador is not None]
        if inicializadas:
            self.iniciar_funcao()
            self.linhas.append("func #init")
            for decl in inicializadas:
                self.declaracao(decl)
            self.emitir("return")
            self.linhas.append("endfunc")

        for funcao in funcoes:
            self.funcao(funcao)

        return self.linhas

    def iniciar_funcao(self):
        self.usados = set(self.usados_global)
        self.n_temp = 0
        self.n_construcao = 0
        self.lacos = []

    def funcao(self, no):
        self.iniciar_funcao()
        self.tipo_retorno = no.simbolo.tipo

        params = [self.nomear(p.simbolo, self.usados) for p in no.parametros]
        if params:
            self.linhas.append(f"func {no.nome}({', '.join(params)})")
        else:
            self.linhas.append(f"func {no.nome}")

        for comando in no.corpo.comandos:
            self.comando(comando)

        # Função void que pode chegar ao fim: return implícito.
        # (Funções não void sempre retornam: a semântica garante — SEM011.)
        if no.simbolo.tipo == VOID and not sempre_retorna(no.corpo):
            self.emitir("return")

        self.linhas.append("endfunc")

    # Comandos

    def comando(self, no):
        getattr(self, "cmd_" + type(no).__name__)(no)

    def declaracao(self, no):
        if no.simbolo.tipo.vetor:
            return   # vetores locais não geram instrução (como no gabarito)
        if no.inicializador is not None:
            valor = self.expr(no.inicializador)
            valor = self.converter(valor, no.inicializador.tipo, no.simbolo.tipo)
            self.emitir(f"{self.nome(no.simbolo)} = {valor}")

    def cmd_DeclVar(self, no):
        self.nomear(no.simbolo, self.usados)
        self.declaracao(no)

    def cmd_ListaDecl(self, no):
        for decl in no.declaracoes:
            self.cmd_DeclVar(decl)

    def cmd_Bloco(self, no):
        for comando in no.comandos:
            self.comando(comando)

    def cmd_ExprStmt(self, no):
        if no.expressao is None:
            return
        if isinstance(no.expressao, Chamada):
            self.chamada(no.expressao, descartar=True)
        else:
            self.expr(no.expressao)

    def cmd_If(self, no):
        if no.senao is None:
            (fim,) = self.novos_rotulos("end_if")
            cond = self.expr(no.condicao)
            self.emitir(f"ifFalse {cond} goto {fim}")
            self.comando(no.entao)
            self.emitir_rotulo(fim)
        else:
            senao, fim = self.novos_rotulos("else", "end")
            cond = self.expr(no.condicao)
            self.emitir(f"ifFalse {cond} goto {senao}")
            self.comando(no.entao)
            self.emitir(f"goto {fim}")
            self.emitir_rotulo(senao)
            self.comando(no.senao)
            self.emitir_rotulo(fim)

    def cmd_While(self, no):
        teste, fim = self.novos_rotulos("test", "end")
        self.emitir_rotulo(teste)
        cond = self.expr(no.condicao)
        self.emitir(f"ifFalse {cond} goto {fim}")
        self.lacos.append((fim, teste))     # continue volta ao teste
        self.comando(no.corpo)
        self.lacos.pop()
        self.emitir(f"goto {teste}")
        self.emitir_rotulo(fim)

    def cmd_For(self, no):
        # for (init; cond; passo) corpo  ==  init; while (cond) { corpo; passo }
        teste, fim, passo = self.novos_rotulos("test", "end", "step")
        if no.inicio is not None:
            self.expr_comando(no.inicio)
        self.emitir_rotulo(teste)
        if no.condicao is not None:
            cond = self.expr(no.condicao)
            self.emitir(f"ifFalse {cond} goto {fim}")

        self.lacos.append((fim, passo))     # continue vai para o passo
        inicio_corpo = len(self.linhas)
        self.comando(no.corpo)
        self.lacos.pop()

        # O rótulo do passo só é emitido se algum continue o usa.
        if any(l.strip() == f"goto {passo}" for l in self.linhas[inicio_corpo:]):
            self.emitir_rotulo(passo)
        if no.passo is not None:
            self.expr_comando(no.passo)
        self.emitir(f"goto {teste}")
        self.emitir_rotulo(fim)

    def expr_comando(self, no):
        """Expressão usada como comando (init e passo do for)."""
        if isinstance(no, Chamada):
            self.chamada(no, descartar=True)
        else:
            self.expr(no)

    def cmd_Break(self, no):
        self.emitir(f"goto {self.lacos[-1][0]}")

    def cmd_Continue(self, no):
        self.emitir(f"goto {self.lacos[-1][1]}")

    def cmd_Return(self, no):
        if no.expressao is None:
            self.emitir("return")
            return
        valor = self.expr(no.expressao)
        # O tipo esperado é o de retorno da função que contém o return;
        # como a semântica já validou, basta converter quando necessário.
        valor = self.converter(valor, no.expressao.tipo, self.tipo_retorno)
        self.emitir(f"return {valor}")

    def cmd_Print(self, no):
        self.emitir(f"print {self.expr(no.argumento)}")

    def cmd_Read(self, no):
        alvo = no.alvo
        if isinstance(alvo, Identificador):
            self.emitir(f"read {self.nome(alvo.simbolo)}")
        else:
            desloc = self.endereco(alvo.indice)
            t = self.novo_temp()
            self.emitir(f"read {t}")
            self.emitir(f"store {self.nome(alvo.vetor.simbolo)}[{desloc}], {t}")

    # Expressões: devolvem o operando (nome, temporário ou literal)

    def expr(self, no):
        return getattr(self, "expr_" + type(no).__name__)(no)

    def expr_Literal(self, no):
        return no.lexema

    def expr_Identificador(self, no):
        return self.nome(no.simbolo)

    def expr_Atribuicao(self, no):
        if isinstance(no.alvo, Identificador):
            valor = self.expr(no.valor)
            valor = self.converter(valor, no.valor.tipo, no.alvo.tipo)
            destino = self.nome(no.alvo.simbolo)
            self.emitir(f"{destino} = {valor}")
            return destino

        # Elemento de vetor: endereço, depois valor, depois store.
        desloc = self.endereco(no.alvo.indice)
        valor = self.expr(no.valor)
        valor = self.converter(valor, no.valor.tipo, no.alvo.tipo)
        self.emitir(f"store {self.nome(no.alvo.vetor.simbolo)}[{desloc}], {valor}")
        return valor

    def expr_Unaria(self, no):
        operando = self.expr(no.operando)
        t_operando = no.operando.tipo
        if no.operador == "!":
            t = self.novo_temp()
            self.emitir(f"{t} = not {operando}")
            return t
        operando = self.converter(operando, t_operando,
                                  FLOAT if t_operando == FLOAT else INT)
        t = self.novo_temp()
        self.emitir(f"{t} = neg {operando}")
        return t

    def expr_Binaria(self, no):
        op = no.operador
        if op in ("&&", "||") and not avaliacao_segura(no.direita):
            return self.curto_circuito(no)
        esq = self.expr(no.esquerda)
        dir_ = self.expr(no.direita)
        te, td = no.esquerda.tipo, no.direita.tipo

        if op in ("+", "-", "*", "/", "%", "<", ">", "<=", ">=", "==", "!="):
            # Tipo comum dos operandos: float se algum for float; int se
            # algum for int (char promovido); char só se ambos forem char.
            if FLOAT in (te, td):
                comum = FLOAT
            elif INT in (te, td) or op in ("+", "-", "*", "/", "%"):
                comum = INT
            else:
                comum = te
            esq = self.converter(esq, te, comum)
            dir_ = self.converter(dir_, td, comum)

        t = self.novo_temp()
        self.emitir(f"{t} = {esq} {OPERADORES_IR.get(op, op)} {dir_}")
        return t

    def curto_circuito(self, no):
        """&& / || com saltos: a direita só é avaliada se for necessária."""
        (fim,) = self.novos_rotulos("sc")
        esq = self.expr(no.esquerda)
        t = self.novo_temp()
        self.emitir(f"{t} = {esq}")
        salto = "ifFalse" if no.operador == "&&" else "ifTrue"
        self.emitir(f"{salto} {t} goto {fim}")
        self.emitir(f"{t} = {self.expr(no.direita)}")
        self.emitir_rotulo(fim)
        return t

    def expr_Chamada(self, no):
        return self.chamada(no, descartar=False)

    def chamada(self, no, descartar):
        simbolo = no.simbolo
        argumentos = []
        for arg, t_param in zip(no.argumentos, simbolo.parametros):
            valor = self.expr(arg)
            argumentos.append(self.converter(valor, arg.tipo, t_param))
        for valor in argumentos:
            self.emitir(f"param {valor}")

        n = len(argumentos)
        if descartar or simbolo.tipo == VOID:
            self.emitir(f"call {no.funcao.nome}, {n}")
            return None
        t = self.novo_temp()
        self.emitir(f"{t} = call {no.funcao.nome}, {n}")
        return t

    def expr_Indice(self, no):
        desloc = self.endereco(no.indice)
        t = self.novo_temp()
        self.emitir(f"{t} = load {self.nome(no.vetor.simbolo)}[{desloc}]")
        return t


def gerar_ir(programa):
    """Ponto de entrada: devolve a lista de linhas de IR do programa."""
    return GeradorIR().gerar(programa)
