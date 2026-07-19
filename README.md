# EDA Studio

基于 [Senza](https://github.com/oh-my-harness/Senza) 的开源 EDA 自动化芯片设计流程示例。

## 快速开始

```bash
./scripts/install-senza-dev.sh
pip install -e .
docker run -d --name eda-tools -v $(pwd)/designs:/work/designs \
  -e PDK=sky130A hpretl/iic-osic-tools:latest --skip sleep infinity
cp config.example.yaml config.yaml
python -m eda_studio run uart
```
