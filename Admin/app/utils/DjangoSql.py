import logging
import re
from django.db import connection

from app.utils.SafeLog import safe_json_dumps, truncate_text


logger = logging.getLogger(__name__)
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$", re.ASCII)


def _quote_identifier(identifier):
    value = str(identifier or "")
    if not SQL_IDENTIFIER_RE.fullmatch(value):
        raise ValueError("Invalid SQL identifier")
    return connection.ops.quote_name(value)


class DjangoSql:

    def select(self, sql, params=None):
        """
        执行查询语句
        :param sql: SQL 语句（支持参数化查询，使用 %s 占位符）
        :param params: 参数列表或元组
        :return: 查询结果列表
        """
        data = []
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params or [])
                raw_data = cursor.fetchall()
                col_names = [desc[0] for desc in cursor.description]

                for row in raw_data:
                    d = {}
                    for index, value in enumerate(row):
                        d[col_names[index]] = value
                    data.append(d)
        except Exception:
            logger.exception(
                "DjangoSql.select() error sql=%s params=%s",
                truncate_text(str(sql), max_len=512),
                safe_json_dumps(params, max_len=512),
            )

        return data

    def insert(self, tb_name, d):
        """
        插入数据（使用参数化查询防止 SQL 注入）
        :param tb_name: 表名
        :param d: 字典数据
        :return: 是否成功
        """
        if not d:
            return False

        try:
            table_name = _quote_identifier(tb_name)
            columns = [_quote_identifier(name) for name in d.keys()]
        except ValueError:
            logger.warning("DjangoSql.insert() rejected unsafe identifier")
            return False
        placeholders = ["%s"] * len(columns)
        values = list(d.values())

        sql = "INSERT INTO %s(%s) VALUES(%s)" % (  # NOSONAR - identifiers are allowlisted and quoted above.
            table_name, ",".join(columns), ",".join(placeholders))

        return self.execute(sql, values)  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query

    def execute(self, sql, params=None):
        """
        执行 SQL 语句（支持参数化查询）
        :param sql: SQL 语句（使用 %s 占位符）
        :param params: 参数列表或元组
        :return: 是否成功
        """
        ret = False
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params or [])
            ret = True
        except Exception:
            logger.exception(
                "DjangoSql.execute() error sql=%s params=%s",
                truncate_text(str(sql), max_len=512),
                safe_json_dumps(params, max_len=512),
            )

        return ret
