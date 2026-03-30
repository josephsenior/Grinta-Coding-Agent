"""Build a combined Tree-sitter language shared library.

App primarily uses `tree-sitter-language-pack` (prebuilt grammars) and does
not require vendored grammar repos. This script exists for advanced scenarios
where you want to build a custom combined library from Tree-sitter grammar
sources.

Historically, grammars lived under `backend/third_party` as git submodules.
This script now accepts an explicit grammar directory and keeps the old default
only for stable script invocation.
"""

import argparse
import logging
import os
import sys
from pathlib import Path


def _default_out_file(out_base: Path) -> str:
    platform = os.environ.get("APP_PLATFORM") or sys.platform

    if platform.startswith("win"):
        return f"{str(out_base)}.dll"
    if platform == "darwin":
        return f"{str(out_base)}.dylib"
    return f"{str(out_base)}.so"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grammar-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "grammars",
        help="Directory containing grammar repos (default: backend/grammars)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (without extension). Default: <grammar-dir>/my-langs",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=["tree-sitter-python"],
        help="Grammar repo folder name to include (repeatable)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    try:
        from tree_sitter import Language
    except Exception:
        logger.error(
            "py-tree-sitter not available; install with: pip install tree_sitter"
        )
        return 2

    base = args.grammar_dir
    out_base = args.out if args.out is not None else (base / "my-langs")
    out_file = _default_out_file(out_base)

    grammars: list[str] = []
    for name in args.lang:
        p = base / name
        if p.exists():
            grammars.append(str(p))
        else:
            logger.warning("Grammar dir not found: %s", p)

    if not grammars:
        logger.error(
            "No grammar sources found. Either install tree-sitter-language-pack "
            "(preferred), or provide grammar repos via --grammar-dir/--lang."
        )
        return 1

    logger.info("Building language lib -> %s", out_file)
    Language.build_library(out_file, grammars)  # type: ignore[attr-defined]
    logger.info("Built: %s", out_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
