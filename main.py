"""Scientific calculator using FastHTML and Datastar."""

import math
import operator
import ast

from fasthtml.common import (
    FastHTML, serve, Title, Meta, Script, Style,
    Div, Span, Button, H1,
)
from starlette.staticfiles import StaticFiles
from datastar_py.fasthtml import (
    DatastarResponse,
    ServerSentEventGenerator as SSE,
    read_signals,
)
from datastar_py import attribute_generator as ds

# ---------------------------------------------------------------------------
# Datastar JS path (bundled locally so the app works without internet access)
# ---------------------------------------------------------------------------
DS_JS = "/static/datastar.js"

# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

_SAFE_NAMES: dict = {
    # trigonometric
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    # hyperbolic
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    # exponential / logarithmic
    "exp": math.exp,
    "log": math.log10,
    "log2": math.log2,
    "ln": math.log,
    "sqrt": math.sqrt,
    # rounding
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    # power
    "pow": math.pow,
    # constants
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
    # disable all builtins
    "__builtins__": {},
}

_ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.keyword,
    # operators
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)


def _check_ast(node: ast.AST) -> None:
    """Raise ValueError if the AST contains unsafe node types."""
    if not isinstance(node, _ALLOWED_NODE_TYPES):
        raise ValueError(f"Unsafe operation: {type(node).__name__}")
    for child in ast.iter_child_nodes(node):
        _check_ast(child)


def safe_eval(expression: str) -> str:
    """Safely evaluate a mathematical expression and return the result as string."""
    expression = expression.strip()
    if not expression:
        return ""
    # Replace common display symbols with Python equivalents
    expression = (
        expression
        .replace("×", "*")
        .replace("÷", "/")
        .replace("π", "pi")
        .replace("^", "**")
    )
    try:
        tree = ast.parse(expression, mode="eval")
        _check_ast(tree.body)
        result = eval(  # noqa: S307 -- we validated the AST above
            compile(tree, "<string>", "eval"),
            {"__builtins__": {}},
            _SAFE_NAMES,
        )
        # Format result: drop trailing zeros for floats
        if isinstance(result, float):
            if result == int(result) and not math.isinf(result):
                return str(int(result))
            return f"{result:.10g}"
        return str(result)
    except ZeroDivisionError:
        return "Error: Division by zero"
    except (ValueError, TypeError, OverflowError) as exc:
        return f"Error: {exc}"
    except Exception:
        return "Error"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg: #1a1a2e;
    --panel: #16213e;
    --btn: #0f3460;
    --btn-hover: #1a4a7a;
    --btn-op: #e94560;
    --btn-op-hover: #ff6b8a;
    --btn-sci: #533483;
    --btn-sci-hover: #7046b0;
    --btn-eq: #00b4d8;
    --btn-eq-hover: #0096c7;
    --btn-clear: #ef233c;
    --btn-clear-hover: #d90429;
    --text: #e0e0e0;
    --display-bg: #0d1b2a;
    --display-expr: #90e0ef;
    --display-result: #ffffff;
    --radius: 8px;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.calculator {
    background: var(--panel);
    border-radius: 16px;
    padding: 20px;
    width: 360px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
}

h1 {
    text-align: center;
    font-size: 1rem;
    color: #90e0ef;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 16px;
    opacity: 0.7;
}

/* Display */
.display {
    background: var(--display-bg);
    border-radius: var(--radius);
    padding: 12px 16px;
    margin-bottom: 16px;
    min-height: 80px;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    align-items: flex-end;
    word-break: break-all;
}

.display-expr {
    font-size: 0.9rem;
    color: var(--display-expr);
    min-height: 1.2em;
    opacity: 0.8;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.display-result {
    font-size: 1.8rem;
    font-weight: 600;
    color: var(--display-result);
    min-height: 1.5em;
}

/* Button grid */
.btn-grid {
    display: grid;
    gap: 8px;
}

.sci-row {
    grid-template-columns: repeat(6, 1fr);
}

.main-grid {
    grid-template-columns: repeat(4, 1fr);
}

/* Buttons */
button {
    background: var(--btn);
    color: var(--text);
    border: none;
    border-radius: var(--radius);
    padding: 14px 8px;
    font-size: 0.95rem;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    user-select: none;
    -webkit-user-select: none;
}

button:hover {
    background: var(--btn-hover);
}

button:active {
    transform: scale(0.95);
}

.btn-op {
    background: var(--btn-op);
}
.btn-op:hover { background: var(--btn-op-hover); }

.btn-sci {
    background: var(--btn-sci);
    font-size: 0.75rem;
}
.btn-sci:hover { background: var(--btn-sci-hover); }

.btn-eq {
    background: var(--btn-eq);
    color: #fff;
    font-weight: 700;
    font-size: 1.2rem;
}
.btn-eq:hover { background: var(--btn-eq-hover); }

.btn-clear {
    background: var(--btn-clear);
    font-weight: 700;
}
.btn-clear:hover { background: var(--btn-clear-hover); }

.btn-del {
    background: #6c2a2a;
}
.btn-del:hover { background: #8b3a3a; }

.span2 { grid-column: span 2; }
""".strip()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastHTML(
    hdrs=(
        Meta(charset="UTF-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1.0"),
        Script(src=DS_JS, type="module"),
        Style(CSS),
    ),
    # Disable defaults we don't need
    default_hdrs=False,
)
rt = app.route
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Helper: build a calculator button
# ---------------------------------------------------------------------------

def calc_btn(label: str, action: str, cls: str = "") -> Button:
    """Return a FastHTML Button with a Datastar on-click attribute."""
    klass = f"btn {cls}".strip()
    return Button(label, cls=klass, **dict(ds.on("click", action)))


# ---------------------------------------------------------------------------
# Calculator UI
# ---------------------------------------------------------------------------

def calculator_ui() -> Div:
    signals_attr = dict(ds.signals({"expression": "", "result": "0"}))

    # -- Display --
    display = Div(
        Span(cls="display-expr", **dict(ds.text("$expression || '0'"))),
        Span(cls="display-result", **dict(ds.text("$result"))),
        cls="display",
    )

    # -- Scientific function row --
    sci_row = Div(
        calc_btn("sin", "$expression += 'sin('", "btn-sci"),
        calc_btn("cos", "$expression += 'cos('", "btn-sci"),
        calc_btn("tan", "$expression += 'tan('", "btn-sci"),
        calc_btn("log", "$expression += 'log('", "btn-sci"),
        calc_btn("ln",  "$expression += 'ln('",  "btn-sci"),
        calc_btn("√",   "$expression += 'sqrt('","btn-sci"),
        cls="btn-grid sci-row",
    )

    # -- Main button grid --
    main_grid = Div(
        # Row 1
        calc_btn("AC",  "$expression = ''; $result = '0'",    "btn-clear"),
        calc_btn("(",   "$expression += '('"),
        calc_btn(")",   "$expression += ')'"),
        calc_btn("÷",   "$expression += '÷'",                 "btn-op"),
        # Row 2
        calc_btn("7",   "$expression += '7'"),
        calc_btn("8",   "$expression += '8'"),
        calc_btn("9",   "$expression += '9'"),
        calc_btn("×",   "$expression += '×'",                 "btn-op"),
        # Row 3
        calc_btn("4",   "$expression += '4'"),
        calc_btn("5",   "$expression += '5'"),
        calc_btn("6",   "$expression += '6'"),
        calc_btn("−",   "$expression += '-'",                 "btn-op"),
        # Row 4
        calc_btn("1",   "$expression += '1'"),
        calc_btn("2",   "$expression += '2'"),
        calc_btn("3",   "$expression += '3'"),
        calc_btn("+",   "$expression += '+'",                 "btn-op"),
        # Row 5
        calc_btn("π",   "$expression += 'π'"),
        calc_btn("0",   "$expression += '0'"),
        calc_btn(".",   "$expression += '.'"),
        calc_btn("=",   "@post('/calculate')",                "btn-eq"),
        # Row 6
        calc_btn("e",   "$expression += 'e'"),
        calc_btn("^",   "$expression += '^'"),
        calc_btn("%",   "$expression += '%'"),
        calc_btn("⌫",  "$expression = $expression.slice(0, -1)", "btn-del"),
        cls="btn-grid main-grid",
    )

    return Div(
        H1("Scientific Calculator"),
        display,
        sci_row,
        Div(style="height:8px"),
        main_grid,
        cls="calculator",
        **signals_attr,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@rt("/")
def index():
    return (
        Title("Scientific Calculator"),
        calculator_ui(),
    )


@rt("/calculate", methods=["POST"])
async def calculate(req):
    signals = await read_signals(req)
    expression = (signals or {}).get("expression", "")
    result = safe_eval(expression)
    return DatastarResponse([
        SSE.patch_signals({"result": result}),
    ])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    serve(port=5000)
