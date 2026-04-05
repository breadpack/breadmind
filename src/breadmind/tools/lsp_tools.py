"""LSP tools registered as agent-callable tools."""
from breadmind.tools.registry import tool


@tool("Go to definition of a symbol at a given position in a file", read_only=True)
async def lsp_goto_definition(file_path: str, line: int, character: int) -> str:
    from breadmind.tools.lsp_client import LSPClient
    client = LSPClient()
    locations = await client.goto_definition(file_path, line, character)
    if not locations:
        return "No definition found."
    parts = []
    for loc in locations:
        parts.append(f"{loc.file_path}:{loc.line + 1}:{loc.character}")
        if loc.preview:
            parts.append(f"  {loc.preview}")
    return "\n".join(parts)


@tool("Find all references to a symbol", read_only=True)
async def lsp_find_references(file_path: str, line: int, character: int) -> str:
    from breadmind.tools.lsp_client import LSPClient
    client = LSPClient()
    locations = await client.find_references(file_path, line, character)
    if not locations:
        return "No references found."
    parts = [f"Found {len(locations)} references:"]
    for loc in locations:
        parts.append(f"  {loc.file_path}:{loc.line + 1} — {loc.preview}")
    return "\n".join(parts)


@tool("Get all symbols (classes, functions) in a file", read_only=True)
async def lsp_document_symbols(file_path: str) -> str:
    from breadmind.tools.lsp_client import LSPClient
    client = LSPClient()
    symbols = await client.document_symbols(file_path)
    if not symbols:
        return "No symbols found."
    parts = [f"Symbols in {file_path}:"]
    for sym in symbols:
        parts.append(f"  [{sym.kind}] {sym.name} — line {sym.location.line + 1}")
    return "\n".join(parts)
