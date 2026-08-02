# Contributing to GIFManager

感谢你愿意为 GIFManager 贡献代码！请先阅读并遵守以下约定。

## 开发环境

- Python 3.10+（建议 3.12+），依赖见 `requirements.txt`
- 安装：`pip install -r requirements.txt`
- 运行：`python main.py`
- 测试：`python -m unittest tests.test_columns tests.test_layout -v`

## 代码风格

所有代码必须遵守项目内 `gifmanager-code-style` 规范（PEP8 + 双语注释）：

- 行宽 ≤ 100，4 空格缩进，PEP8 基础格式
- 三引号 docstring 仅限文件头（英文行 + 中文行）；代码内部一律 `#` 双语注释
- 修改后必须通过 `py_compile` 与全部回归测试

## 分支命名

- 功能分支：`feature/<short-description>`（如 `feature/export-support`）
- 修复分支：`fix/<short-description>`（如 `fix/all-group-sync`）

## Commit 规范

- 使用 Conventional Commits 格式：
  - `feat: 添加导出功能` / `fix: 修复“All”分组不同步`
  - `refactor:`、`docs:`、`test:`、`style:`、`perf:` 等同理
- 提交信息应说明"为什么"，而非机械重复代码
- 每个 commit 保持独立可编译、可测试

## Pull Request 流程

1. 从最新 `main` 切出分支，改动尽量聚焦单一主题
2. 提交前运行：`py_compile` 相关文件 + `python -m unittest tests.test_columns tests.test_layout -v` 全绿
3. 新增功能附带对应测试（`tests/` 下）
4. 翻译改动需同步更新 `language/zh_CN.json` 与 `language/en_US.json`
5. 描述改动内容、测试结果、截图（如涉及 UI）

## 版本与许可

- 项目采用 [MIT License](LICENSE)，提交代码即视为同意在该许可下发布
