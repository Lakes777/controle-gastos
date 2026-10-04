"""Contas de usuário da versão online: cadastro com convite, login e sessões.

Segurança, em resumo:
- a senha é guardada com argon2id (lento de propósito, com "sal" próprio): nem quem
  ler o banco descobre a senha;
- a sessão é um número aleatório no cookie; no banco fica só o hash dele;
- depois de 5 senhas erradas em 15 minutos, o e-mail fica bloqueado por um tempo;
- "e-mail não existe" e "senha errada" dão a mesma resposta (e levam o mesmo
  tempo), para ninguém descobrir quem tem conta;
- o cadastro exige um código de convite, guardado numa variável de ambiente;
- chaves de acesso (para programas do próprio usuário, como um bot) seguem a
  regra das sessões: aleatórias, mostradas uma vez só, e no banco fica só o hash.
"""

import hashlib
import secrets
import uuid
from datetime import timedelta

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

VALIDADE_SESSAO = timedelta(days=30)
MAXIMO_TENTATIVAS = 5
JANELA_TENTATIVAS = timedelta(minutes=15)
# "sw_" (de Spendwise) na frente: fica fácil reconhecer uma chave colada no lugar errado.
PREFIXO_CHAVE = "sw_"
LIMITE_CHAVES = 5


class CadastroFechado(Exception):
    """O servidor não tem código de convite: ninguém consegue se cadastrar."""


class ConviteInvalido(Exception):
    pass


class EmailJaCadastrado(Exception):
    pass


class LoginBloqueado(Exception):
    """Senhas erradas demais em pouco tempo."""


class LimiteDeChaves(Exception):
    """A conta já tem o máximo de chaves de acesso."""


def normalizar_email(email: str) -> str:
    return email.strip().lower()


def hash_do_token(token: str) -> str:
    # SHA-256 basta aqui: o token já é aleatório e longo (não dá para adivinhar),
    # diferente de uma senha, que precisa do argon2.
    return hashlib.sha256(token.encode()).hexdigest()


class Autenticacao:
    def __init__(self, codigo_convite: str | None, hasher: PasswordHasher | None = None) -> None:
        self.codigo_convite = codigo_convite or None
        self.hasher = hasher or PasswordHasher()  # argon2id com os parâmetros recomendados
        # Hash de mentira, usado quando o e-mail não existe: assim o login demora o
        # mesmo tempo, e ninguém descobre quem tem conta pelo tempo de resposta.
        self._hash_falso = self.hasher.hash(secrets.token_hex(16))

    @property
    def cadastro_aberto(self) -> bool:
        return self.codigo_convite is not None

    # ---------- Cadastro e login ----------

    def cadastrar(self, conexao: psycopg.Connection, email: str, senha: str, convite: str) -> str:
        """Cria a conta e devolve o id dela."""
        if not self.cadastro_aberto:
            raise CadastroFechado
        # compare_digest compara sempre no mesmo tempo (não entrega o código aos poucos).
        if not secrets.compare_digest(convite.encode(), self.codigo_convite.encode()):
            raise ConviteInvalido
        # "u_" na frente: o id de um usuário nunca tem o formato do cookie da demonstração.
        conta = f"u_{uuid.uuid4().hex}"
        try:
            with conexao.transaction():
                conexao.execute(
                    "INSERT INTO contas (id, tipo, email, senha_hash) VALUES (%s, 'usuario', %s, %s)",
                    (conta, normalizar_email(email), self.hasher.hash(senha)),
                )
        except psycopg.errors.UniqueViolation:
            raise EmailJaCadastrado
        return conta

    def entrar(self, conexao: psycopg.Connection, email: str, senha: str) -> str | None:
        """Devolve o id da conta se a senha estiver certa; senão, None."""
        email = normalizar_email(email)
        erros_recentes = conexao.execute(
            "SELECT count(*) AS n FROM tentativas_login WHERE email = %s AND momento > now() - %s",
            (email, JANELA_TENTATIVAS),
        ).fetchone()["n"]
        if erros_recentes >= MAXIMO_TENTATIVAS:
            raise LoginBloqueado

        linha = conexao.execute(
            "SELECT id, senha_hash FROM contas WHERE lower(email) = %s AND tipo = 'usuario'",
            (email,),
        ).fetchone()
        try:
            self.hasher.verify(linha["senha_hash"] if linha else self._hash_falso, senha)
            certa = linha is not None
        except VerificationError:
            certa = False

        if not certa:
            with conexao.transaction():
                conexao.execute("INSERT INTO tentativas_login (email) VALUES (%s)", (email,))
                # Aproveita para limpar as tentativas antigas (de qualquer e-mail).
                conexao.execute(
                    "DELETE FROM tentativas_login WHERE momento < now() - %s", (JANELA_TENTATIVAS,)
                )
            return None

        with conexao.transaction():
            conexao.execute("DELETE FROM tentativas_login WHERE email = %s", (email,))
            # Se os parâmetros do argon2 mudarem um dia, a senha é regravada no login.
            if self.hasher.check_needs_rehash(linha["senha_hash"]):
                conexao.execute(
                    "UPDATE contas SET senha_hash = %s WHERE id = %s",
                    (self.hasher.hash(senha), linha["id"]),
                )
        return linha["id"]

    def conferir_senha(self, conexao: psycopg.Connection, conta: str, senha: str) -> bool:
        linha = conexao.execute(
            "SELECT senha_hash FROM contas WHERE id = %s AND tipo = 'usuario'", (conta,)
        ).fetchone()
        try:
            return linha is not None and self.hasher.verify(linha["senha_hash"], senha)
        except VerificationError:
            return False

    # ---------- Sessões ----------

    def criar_sessao(self, conexao: psycopg.Connection, conta: str) -> str:
        """Devolve o token que vai no cookie (no banco fica só o hash dele)."""
        token = secrets.token_urlsafe(32)
        with conexao.transaction():
            conexao.execute(
                "INSERT INTO sessoes (token_hash, conta, expira_em) VALUES (%s, %s, now() + %s)",
                (hash_do_token(token), conta, VALIDADE_SESSAO),
            )
            conexao.execute("DELETE FROM sessoes WHERE expira_em < now()")
        return token

    def conta_da_sessao(self, conexao: psycopg.Connection, token: str) -> dict | None:
        """A conta (id e e-mail) dona da sessão, ou None se ela não existe ou venceu."""
        return conexao.execute(
            "SELECT contas.id, contas.email FROM sessoes JOIN contas ON contas.id = sessoes.conta "
            "WHERE sessoes.token_hash = %s AND sessoes.expira_em > now() AND contas.tipo = 'usuario'",
            (hash_do_token(token),),
        ).fetchone()

    def sair(self, conexao: psycopg.Connection, token: str) -> None:
        with conexao.transaction():
            conexao.execute("DELETE FROM sessoes WHERE token_hash = %s", (hash_do_token(token),))

    # ---------- Chaves de acesso ----------

    def criar_chave(self, conexao: psycopg.Connection, conta: str, nome: str) -> tuple[dict, str]:
        """Cria a chave e devolve (dados dela, token). O token só existe aqui: no banco fica o hash."""
        token = PREFIXO_CHAVE + secrets.token_urlsafe(32)
        with conexao.transaction():
            # Trava a linha da conta: dois pedidos juntos não passam do limite.
            conexao.execute("SELECT id FROM contas WHERE id = %s FOR UPDATE", (conta,))
            quantas = conexao.execute(
                "SELECT count(*) AS n FROM chaves WHERE conta = %s", (conta,)
            ).fetchone()["n"]
            if quantas >= LIMITE_CHAVES:
                raise LimiteDeChaves
            chave = conexao.execute(
                "INSERT INTO chaves (conta, nome, token_hash) VALUES (%s, %s, %s) "
                "RETURNING id, nome, criada_em, usada_em",
                (conta, nome, hash_do_token(token)),
            ).fetchone()
        return chave, token

    def listar_chaves(self, conexao: psycopg.Connection, conta: str) -> list[dict]:
        return conexao.execute(
            "SELECT id, nome, criada_em, usada_em FROM chaves WHERE conta = %s ORDER BY id",
            (conta,),
        ).fetchall()

    def apagar_chave(self, conexao: psycopg.Connection, conta: str, chave_id: int) -> bool:
        with conexao.transaction():
            cursor = conexao.execute(
                "DELETE FROM chaves WHERE id = %s AND conta = %s", (chave_id, conta)
            )
        return cursor.rowcount > 0

    def conta_da_chave(self, conexao: psycopg.Connection, token: str) -> dict | None:
        """A conta (id e e-mail) dona da chave, ou None se ela não existe (ou foi apagada).

        Aproveita a consulta para anotar quando a chave foi usada pela última vez.
        """
        with conexao.transaction():
            return conexao.execute(
                "UPDATE chaves SET usada_em = now() FROM contas "
                "WHERE chaves.token_hash = %s AND contas.id = chaves.conta AND contas.tipo = 'usuario' "
                "RETURNING contas.id, contas.email",
                (hash_do_token(token),),
            ).fetchone()

    def excluir_conta(self, conexao: psycopg.Connection, conta: str) -> None:
        """Apaga a conta e tudo dela (gastos, orçamentos, recorrentes, sessões e chaves, em cascata)."""
        with conexao.transaction():
            conexao.execute("DELETE FROM contas WHERE id = %s AND tipo = 'usuario'", (conta,))
