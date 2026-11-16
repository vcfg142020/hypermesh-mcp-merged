# 迁移和配置入口

迁移到新电脑后，一般按这个顺序：

1. 双击 `安装离线依赖.bat`
2. 如果只用 HM 后台划分，双击 `配置hmbatch路径.bat`
3. 如果要用 `HM+ANSA同时划分`，双击 `配置HM+ANSA同时划分环境.bat`
4. 回到 `01_后台划分_双击入口`，双击 `启动后台划分面板.vbs`

`配置HM+ANSA同时划分环境.bat` 会同时完成：

- 查找并保存 HyperMesh `hmbatch.exe`
- 查找并保存 `ansa_mesh_tool` 工具目录
- 调用 ANSA 工具自己的配置，保存 ANSA 安装位置

这两个 bat 虽然放在本文件夹里，但会自动回到上一级项目根目录查找：

- `requirements.txt`
- `wheels`
- `hypermesh_batch_path.txt`
- `ansa_auto_mesh_dir.txt`

所以核心代码和依赖文件不要移动。
