import importlib

try:
    m = importlib.import_module('fastmcp.server.server')
    print('FASTMCP', getattr(m, '__file__', None))
    # try importing the mcp.types from this runtime
    try:
        import mcp.types as mt

        print('MCP_TYPES', getattr(mt, '__file__', None))
    except Exception as e:
        print('ERR_MCP_TYPES', repr(e))
except Exception as e:
    print('ERR_FASTMCP', repr(e))
