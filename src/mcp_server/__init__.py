"""
MCP Server for Data Service
============================
Model Context Protocol (MCP) server that provides access to market data.
"""

from .data_mcp_server import (
    DataServiceWrapper,
    get_data_wrapper,
    main
)

__all__ = ['DataServiceWrapper', 'get_data_wrapper', 'main']
