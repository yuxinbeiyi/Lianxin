"""LSP 级代码智能 — 基于 jedi（跳转定义/引用）+ pyflakes（诊断）

仅支持 Python 文件，不依赖 LSP 服务器。
"""

from pathlib import Path
import jedi
import pyflakes.api
import pyflakes.reporter
import io


def goto_definition(file_path: str, line: int, symbol: str = "", column: int = 0) -> str:
    """跳转到类/函数/变量的定义位置，返回定义的文件、行号和上下文。"""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"文件不存在：{path}"
    if path.suffix != ".py":
        return "code_goto_def 目前仅支持 Python (.py) 文件"

    code = path.read_text(encoding="utf-8", errors="replace")

    script = jedi.Script(code=code, path=str(path))
    try:
        definitions = script.goto(line=line, column=column)

        if not definitions:
            return f"在 {path.name}:{line} 未找到可跳转的符号定义"

        results = []
        for d in definitions:
            if d.type == "module":
                continue
            loc = f"{d.module_path or path}:{d.line}"
            desc = d.description.strip()
            doc = d.docstring()
            doc_short = doc.split("\n")[0][:80] if doc else ""

            line_text = ""
            if d.line and d.module_path:
                try:
                    lines = Path(d.module_path).read_text(encoding="utf-8", errors="replace").splitlines()
                    if d.line <= len(lines):
                        line_text = lines[d.line - 1].strip()
                except Exception:
                    pass

            entry = f"{'='*50}\n定义：{desc}\n位置：{loc}"
            if doc_short:
                entry += f"\n文档：{doc_short}"
            if line_text:
                entry += f"\n代码：{line_text}"
            if d.type == "instance":
                entry += "\n类型：实例属性"
            elif d.type == "class":
                entry += "\n类型：类"
            elif d.type == "function":
                entry += "\n类型：函数/方法"
            elif d.type == "statement":
                entry += "\n类型：变量/语句"

            results.append(entry)

        return "\n\n".join(results)
    except Exception as e:
        return f"跳转定义失败：{e}"


def find_references(file_path: str, line: int, symbol: str = "", column: int = 0) -> str:
    """查找函数/类/变量在项目中的所有引用位置。"""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"文件不存在：{path}"
    if path.suffix != ".py":
        return "code_find_refs 目前仅支持 Python (.py) 文件"

    code = path.read_text(encoding="utf-8", errors="replace")

    script = jedi.Script(code=code, path=str(path))
    try:
        references = script.get_references(line=line, column=column)

        if not references:
            return f"在 {path.name}:{line} 未找到任何引用"

        results = [f"共 {len(references)} 处引用："]
        for i, ref in enumerate(references, 1):
            loc = f"{ref.module_path or path}:{ref.line}:{ref.column}"
            desc = ref.description.strip()[:60]

            line_text = ""
            if ref.line and ref.module_path:
                try:
                    lines = Path(ref.module_path).read_text(encoding="utf-8", errors="replace").splitlines()
                    if ref.line <= len(lines):
                        line_text = lines[ref.line - 1].strip()[:100]
                except Exception:
                    pass

            results.append(f"{i}. {loc}  {desc}")
            if line_text:
                results.append(f"   {line_text}")

        return "\n".join(results)
    except Exception as e:
        return f"查找引用失败：{e}"


def get_diagnostics(file_path: str) -> str:
    """检查 Python 文件的语法错误和代码问题。"""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return f"文件不存在：{path}"
    if path.suffix != ".py":
        return "code_diagnostics 目前仅支持 Python (.py) 文件"

    errors = []
    output = io.StringIO()
    reporter = pyflakes.reporter.Reporter(output, output)

    try:
        pyflakes.api.checkPath(str(path), reporter)
        report = output.getvalue().strip()
        if report:
            for line in report.split("\n"):
                line = line.strip()
                if line:
                    errors.append(line)
            return f"{path.name} 发现 {len(errors)} 个问题：\n" + "\n".join(f"  - {e}" for e in errors)
        else:
            return f"{path.name} — 未发现问题 ✅"
    except SyntaxError as e:
        return f"{path.name} 语法错误：{e}"
    except Exception as e:
        return f"诊断失败：{e}"
