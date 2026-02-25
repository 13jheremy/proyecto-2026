# src/modulos/usuarios/pagination.py
from rest_framework.pagination import PageNumberPagination


class UsuarioPagination(PageNumberPagination):
    page_size = 10  # por defecto
    page_size_query_param = "page_size"  # permite ?page_size=20
    max_page_size = 100  # opcional: límite máximo


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100
