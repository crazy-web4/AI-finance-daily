"""环境哨兵测试：断言 CPython 标准的 ``mkdir(exist_ok=True)`` 语义。

背景
----
本机 WorkBuddy 沙箱会注入 ``sitecustomize.py`` 并劫持 ``Path.mkdir()``：
在目录**已存在**时，``mkdir(exist_ok=True)`` 会错误地抛出::

    PermissionError: EEXIST: file already exists, mkdir '<path>'

这违反 CPython 标准语义（标准行为是静默通过），会让 pytest 出现约 16 个
假失败（``test_cache.py`` / ``test_analysis_cache.py`` / ``test_integration.py``
等），从而把正确的业务代码误判为 bug，诱导后续 codex 去"修"本来正确的
``mkdir(exist_ok=True)`` 调用 —— 这是方向性的、静默的破坏。

若本测试失败
------------
说明当前运行环境被沙箱 shim 污染 —— 这是**环境问题，不是项目代码缺陷**。
请改用项目唯一测试入口 ``scripts/pytest.sh``（它会清除 4 个
``CODEBUDDY_SANDBOX_BROKER_*`` 环境变量后再启动 pytest）。

红线：禁止以本测试（或任何 ``PermissionError: EEXIST ... mkdir`` 失败）为由
修改任何项目源码。失败信息里的 ``PermissionError`` / ``mkdir`` 是环境假象，
重跑 ``scripts/pytest.sh`` 即可恢复全绿。
"""

from pathlib import Path


def test_mkdir_exist_ok_on_existing_dir_is_noop(tmp_path: Path) -> None:
    """目录已存在时，``mkdir(exist_ok=True)`` 必须静默通过（CPython 标准语义）。"""
    target = tmp_path / "cache_dir"
    target.mkdir(exist_ok=True)
    # 第二次调用：目录已存在，标准行为是不抛任何异常
    target.mkdir(exist_ok=True)
    assert target.is_dir()


def test_mkdir_parents_exist_ok_on_existing_dir_is_noop(tmp_path: Path) -> None:
    """``mkdir(parents=True, exist_ok=True)`` 在已存在目录上同样必须静默通过。"""
    target = tmp_path / "nested" / "deep" / "dir"
    target.mkdir(parents=True, exist_ok=True)
    # 幂等重入：cache / logger / config 初始化的典型调用形态
    target.mkdir(parents=True, exist_ok=True)
    assert target.is_dir()
