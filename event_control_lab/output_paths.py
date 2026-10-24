"""Read-only checks shared by installed commands and the source launcher."""

from pathlib import Path


def check_new_output(destination):
    output = Path(destination)
    if output.exists() or output.is_symlink():
        raise ValueError(
            "输出路径已存在，这次没有开始计算；请换一个新目录，旧结果会保留。 / "
            "output directory already exists; choose a new --out path"
        )
    for parent in output.parents:
        if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
            raise NotADirectoryError(
                f"上级路径 {parent} 不是文件夹，这次没有开始计算。请换一个保存位置。 / "
                f"Output parent {parent} is not a directory; choose another --out path."
            )
