# 贡献指南

感谢您对 Symi Modbus 集成的兴趣！以下是参与这个项目的指南。

## 提交 Issue

如果您发现了问题或有功能建议，请通过 GitHub Issues 提交，包括以下内容：

- 对问题或功能的清晰描述
- 问题的复现步骤（如适用）
- 您的 Home Assistant 版本
- 您使用的硬件配置

## 提交代码

1. Fork 这个仓库
2. 创建您的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 将您的更改推送到分支 (`git push origin feature/amazing-feature`)
5. 打开一个 Pull Request

## 代码风格

请确保您的代码遵循以下规范：

- 使用 [Black](https://github.com/psf/black) 进行代码格式化
- 遵循 [Home Assistant 编码规范](https://developers.home-assistant.io/docs/development_guidelines)
- 在适当的地方添加文档字符串和注释

## 测试您的代码

在提交前，请确保您的代码：

- 没有引入新的 pylint 警告或错误
- 与 Home Assistant 最新版本兼容
- 正确处理错误情况

## 许可证

通过提交代码，您同意您的贡献将在与项目相同的许可证（MIT）下发布。 