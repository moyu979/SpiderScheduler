from pathlib import Path
import shutil


def init_files() -> None:
    """初始化根目录下的 `docker` 文件夹结构。

    要求：
    - 以项目内的 `src/assets` 为模板。
    - 在项目根目录创建/对齐 `docker` 目录结构。
    - 仅补齐缺失的目录与文件，不覆盖已存在的文件。
    """

    # 模板目录相对本文件（src/initer/ -> src/assets）
    assets_dir: Path = Path(__file__).resolve().parent.parent / "assets"
    docker_dir: Path = Path("docker")

    if not assets_dir.exists() or not assets_dir.is_dir():
        # 如果模板目录不存在，直接返回（不做额外行为）
        return None

    # 确保 docker 目录存在
    docker_dir.mkdir(parents=True, exist_ok=True)

    # 遍历 assets，补齐 docker 中缺失的目录和文件
    for source_path in assets_dir.rglob("*"):
        relative_path = source_path.relative_to(assets_dir)
        target_path = docker_dir / relative_path

        if source_path.is_dir():
            # 目录：确保存在
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            # 文件：仅在缺失时拷贝
            if not target_path.exists():
                # 目标上级目录若缺失，确保创建
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

if __name__ == "__main__":
    init_files()


