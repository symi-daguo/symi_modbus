# Symi Modbus 集成

这个集成为 Home Assistant 提供 Modbus 控制功能，专为 Symi Modbus 设备设计。它支持通过 TCP 和串口（RTU）连接 Modbus 设备，同时保持高效的轮询机制。

## 特点

- 支持 TCP 和串口（RTU）连接
- 每个从站自动创建 32 个开关实体（线圈地址 0-31）
- 高效轮询机制（每秒轮询一次所有从站）
- 简化的配置流程（只需选择连接类型和从站地址）
- 自动生成设备名称和实体ID
- 多语言支持（英文和中文）

## 安装

### 方法 1: HACS (推荐)

1. 打开 [HACS](https://hacs.xyz/)
2. 点击集成
3. 点击右上角的三个点
4. 选择"自定义存储库"
5. 添加 URL `https://github.com/symi-daguo/symi_modbus` 并选择类别为"集成"
6. 点击"添加"
7. 搜索"Symi Modbus"并安装

### 方法 2: 手动安装

1. 下载此存储库的最新版本
2. 解压缩文件
3. 复制 `symi_modbus` 文件夹到 Home Assistant 配置目录下的 `custom_components` 文件夹中
4. 重启 Home Assistant

## 配置

### 通过 Home Assistant UI (推荐)

1. 转到配置 > 集成
2. 点击"添加集成"
3. 搜索 "Symi Modbus"
4. 选择连接类型（TCP 或串口）
5. 填写必要的连接信息（主机/端口 或 串口设备）
6. 选择从站地址（默认为 0x0A/10）
7. 完成配置

每个从站会自动创建 32 个开关实体，对应线圈地址 0-31。实体名称格式为：`{从站地址十六进制}switch{线圈地址}`，例如 `0Aswitch00`, `0Aswitch01` 等。

### 添加多个从站

如果需要控制多个从站，只需重复上述过程，为每个从站选择不同的地址（例如 0x0A, 0x0B, 0x0C 等）。

### YAML 配置 (可选)

```yaml
# 串口连接示例 (RTU)
symi_modbus:
  - type: serial
    port: /dev/ttyUSB0
    slave: 10  # 0x0A
    baudrate: 9600
    bytesize: 8
    parity: N
    stopbits: 1
    method: rtu
    scan_interval: 1

# TCP连接示例
symi_modbus:
  - type: tcp
    host: 192.168.1.100
    port: 502
    slave: 10  # 0x0A
    scan_interval: 1
```

## 使用

### 服务

此集成提供以下服务：

- `symi_modbus.write_coil` - 写入线圈值
- `symi_modbus.write_register` - 写入寄存器值

#### 写入线圈示例:
```yaml
service: symi_modbus.write_coil
data:
  hub: modbus_tcp_10
  slave: 10
  address: 0
  state: true
```

#### 写入寄存器示例:
```yaml
service: symi_modbus.write_register
data:
  hub: modbus_serial_10
  slave: 10
  address: 0
  value: 100
```

## 故障排除

如果遇到连接问题：

1. 检查设备是否在线并可访问
2. 验证连接参数（主机/端口 或 串口设备）
3. 确认从站地址是否正确
4. 查看 Home Assistant 日志以获取更多信息

## 许可证

MIT 