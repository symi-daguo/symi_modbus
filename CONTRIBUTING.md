# 贡献指南

感谢您对 Symi Modbus 集成的兴趣！以下是参与这个项目的指南。

> Contributions from outside China are welcome as well. Please write in English in the issues
> and the pull requests, or in Chinese, both are fine.

## 提交 Issue

如果您发现了问题或有功能建议，请通过 GitHub Issues 提交，包括以下内容：

- 对问题或功能的清晰描述
- 问题的复现步骤（如适用）
- 您的 Home Assistant 版本
- 您使用的硬件配置（串口参数、从站地址、连接方式）

## 提交代码

1. Fork 这个仓库
2. 创建您的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 将您的更改推送到分支 (`git push origin feature/amazing-feature`)
5. 打开一个 Pull Request

## 代码风格

- 使用 [Black](https://github.com/psf/black) 进行代码格式化
- 遵循 [Home Assistant 编码规范](https://developers.home-assistant.io/docs/development_guidelines)
- 在适当的地方添加文档字符串和注释

## 运行测试

提交前请确保全部测试通过：

```bash
docker run --rm -v "$PWD:/work" -w /work homeassistant/home-assistant:stable \
  sh -c "pip install pytest-asyncio -q && python -m pytest tests/ -q --asyncio-mode=auto"
```

新增功能请同时补充测试，尤其是帧编解码与断线重连相关的逻辑。

## 品牌资源

品牌图片位于 `custom_components/symi_modbus/brand/`，源图在 `assets/icon_source.png`。
修改源图后运行 `python scripts/generate_brand.py` 重新生成全部尺寸，不要手工编辑生成结果。

## 许可证

通过提交代码，您同意您的贡献将在与项目相同的许可证（MIT）下发布。
